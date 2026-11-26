"""FastAPI application with Phase 2 REST endpoints, validation, and error handling."""

import asyncio
import base64
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from websockets.exceptions import ConnectionClosed

from backend.agent import AgentError, answer_kb_question, generate_call_summary, run_agent_turn
from backend.config import settings
from backend.crm import finalize_call_summary, get_analytics, lead_to_dict, upsert_lead
from backend.database import Appointment, Call, CallSummary, Lead, Message, SessionLocal, Tenant, get_db, init_db, seed_tenants
from backend.rag import KB_DIR, ingest_knowledge_base, search_knowledge_base
from backend.seed import seed_demo_data
from backend.telephony import (
    TelephonyError,
    build_stream_twiml,
    initiate_outbound_call,
    mask_phone,
    verify_twilio_signature,
)
from backend.voice import VoiceError, connect_deepgram, stream_elevenlabs_tts

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize tables and seed sample tenants on startup."""
    init_db()
    with SessionLocal() as db:
        seed_tenants(db)
        if settings.seed_demo_data:
            seed_demo_data(db, tenant_id=1)
    logger.info("Application startup complete")
    yield


app = FastAPI(
    title="Autonomous AI Sales Voice Agent",
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_payload(code: str, message: str, details: Any = None) -> dict:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return payload


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(f"http_{exc.status_code}", str(exc.detail)),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_payload("validation_error", "Invalid request payload", exc.errors()),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_payload("internal_error", "An unexpected error occurred"),
    )


# --- Pydantic Schemas ---


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    agent_config: dict[str, Any]
    created_at: datetime


class LeadCreate(BaseModel):
    tenant_id: int = Field(..., ge=1)
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    company: str | None = Field(default=None, max_length=160)
    industry: str | None = Field(default=None, max_length=120)
    requirement: str | None = None
    budget: str | None = Field(default=None, max_length=80)
    timeline: str | None = Field(default=None, max_length=80)
    decision_maker: bool | None = None
    interest: str | None = Field(default=None, max_length=40)


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str | None
    phone: str | None
    company: str | None
    industry: str | None
    requirement: str | None
    budget: str | None
    timeline: str | None
    decision_maker: bool | None
    interest: str | None
    score: int
    category: str
    created_at: datetime


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    lead_id: int | None
    status: str
    language: str
    started_at: datetime
    ended_at: datetime | None
    duration: int | None
    sentiment: str | None
    summary: str | None


class AppointmentCreate(BaseModel):
    tenant_id: int = Field(..., ge=1)
    lead_id: int = Field(..., ge=1)
    starts_at: datetime
    status: str = Field(default="booked", pattern="^(booked|completed|rescheduled|cancelled)$")


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    lead_id: int
    starts_at: datetime
    status: str
    created_at: datetime


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    tenant_id: int = Field(default=1, ge=1)
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)
    call_id: int | None = Field(default=None, ge=1)
    lead_id: int | None = Field(default=None, ge=1)


class ChatResponse(BaseModel):
    reply: str
    history: list[ChatMessage]
    call_id: int
    lead_id: int
    lead_data: dict[str, Any]
    score: int
    category: str
    sources: list[str] = Field(default_factory=list)
    appointment: dict[str, Any] | None = None
    end_call: bool = False


class RagSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=10)


class RagDocumentUpdate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1)


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    company: str | None = Field(default=None, max_length=160)
    industry: str | None = Field(default=None, max_length=120)
    requirement: str | None = None
    budget: str | None = Field(default=None, max_length=80)
    timeline: str | None = Field(default=None, max_length=80)
    decision_maker: bool | None = None
    interest: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, pattern="^(hot|warm|cold)$")


class AppointmentUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(booked|completed|rescheduled|cancelled)$")
    starts_at: datetime | None = None


class TenantConfigUpdate(BaseModel):
    agent_config: dict[str, Any]


# --- Helpers ---


def _require_tenant(db: Session, tenant_id: int) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


def _create_jwt(sub: str, role: str, tenant_id: int) -> str:
    """Create a minimal HS256 JWT using the Python standard library."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload_bytes = json.dumps(
        {"sub": sub, "role": role, "tenant_id": tenant_id, "exp": int(time.time()) + 86400},
        separators=(",", ":"),
    ).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    signing_input = f"{header}.{payload}".encode()
    sig = base64.urlsafe_b64encode(
        hmac.new(settings.auth_secret.encode(), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"


def _verify_jwt(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Verify Bearer JWT when AUTH_REQUIRED=true; returns demo admin context in local dev."""
    if not settings.auth_required:
        return {"sub": "demo-admin", "role": "admin"}
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    signing_input = f"{parts[0]}.{parts[1]}".encode()
    expected = base64.urlsafe_b64encode(
        hmac.new(settings.auth_secret.encode(), signing_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    if not hmac.compare_digest(expected, parts[2]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(padded))
    if claims.get("exp", 0) < time.time():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return claims


# --- Routes ---


class TokenRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    role: Literal["admin", "sales_rep"] = "sales_rep"
    tenant_id: int = Field(default=1, ge=1)


@app.post("/auth/token")
def issue_token(payload: TokenRequest) -> dict[str, str]:
    """Issue a signed HS256 JWT for dashboard authentication."""
    return {"access_token": _create_jwt(payload.username, payload.role, payload.tenant_id), "token_type": "bearer"}


@app.get("/health")
def health_check(db: Session = Depends(get_db)) -> dict[str, str]:
    """Verify API and database connectivity."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.error("Database health check failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return {"status": "ok", "database": "connected"}


@app.get("/tenants", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db)) -> list[Tenant]:
    """List available tenants."""
    return list(db.scalars(select(Tenant).order_by(Tenant.id)))


@app.patch("/tenants/{tenant_id}", response_model=TenantOut)
def update_tenant_config(
    tenant_id: int,
    payload: TenantConfigUpdate,
    db: Session = Depends(get_db),
) -> Tenant:
    """Update a tenant's agent configuration settings."""
    tenant = _require_tenant(db, tenant_id)
    merged = dict(tenant.agent_config or {})
    merged.update(payload.agent_config)
    tenant.agent_config = merged
    db.commit()
    db.refresh(tenant)
    return tenant


@app.get("/leads")
def list_leads(
    tenant_id: int = Query(..., ge=1),
    category: str | None = Query(default=None, pattern="^(hot|warm|cold)$"),
    sentiment: str | None = Query(default=None),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List leads scoped to a tenant, enriched with latest call sentiment and next action."""
    _require_tenant(db, tenant_id)
    stmt = select(Lead).where(Lead.tenant_id == tenant_id)
    if category is not None:
        stmt = stmt.where(Lead.category == category)
    leads = list(db.scalars(stmt.order_by(Lead.id.desc())))

    result: list[dict[str, Any]] = []
    search_q = (search or "").strip().lower()
    sent_q = (sentiment or "").strip().lower()

    # Two bulk queries instead of two queries per lead.
    lead_ids = [lead.id for lead in leads]
    calls = db.scalars(
        select(Call).where(Call.tenant_id == tenant_id, Call.lead_id.in_(lead_ids)).order_by(Call.id)
    )
    last_call_by_lead = {call.lead_id: call for call in calls}  # newest call wins
    summaries = db.scalars(
        select(CallSummary).where(CallSummary.call_id.in_([c.id for c in last_call_by_lead.values()]))
    )
    summary_by_call = {summary.call_id: summary for summary in summaries}

    for lead in leads:
        last_call = last_call_by_lead.get(lead.id)
        summary = summary_by_call.get(last_call.id) if last_call else None
        lead_sentiment = last_call.sentiment if last_call and last_call.sentiment else "neutral"
        if sent_q and lead_sentiment.lower() != sent_q:
            continue
        if search_q:
            haystack = " ".join(
                str(v or "") for v in (lead.name, lead.company, lead.requirement, lead.industry)
            ).lower()
            if search_q not in haystack:
                continue

        item = LeadOut.model_validate(lead).model_dump()
        item["sentiment"] = lead_sentiment
        item["last_call"] = last_call.started_at if last_call else None
        item["next_action"] = summary.next_action if summary else None
        result.append(item)
    return result


@app.get("/leads/{lead_id}")
def get_lead_detail(
    lead_id: int,
    tenant_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return lead profile, call timeline, transcripts, and appointments."""
    _require_tenant(db, tenant_id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    calls = list(db.scalars(select(Call).where(Call.tenant_id == tenant_id, Call.lead_id == lead.id).order_by(Call.id.desc())))
    appointments = list(
        db.scalars(
            select(Appointment)
            .where(Appointment.tenant_id == tenant_id, Appointment.lead_id == lead.id)
            .order_by(Appointment.starts_at.desc())
        )
    )
    call_details = []
    for c in calls:
        msgs = list(db.scalars(select(Message).where(Message.call_id == c.id).order_by(Message.id)))
        summary = db.scalar(select(CallSummary).where(CallSummary.call_id == c.id))
        call_details.append(
            {
                "call": CallOut.model_validate(c).model_dump(),
                "messages": [{"id": m.id, "role": m.role, "text": m.text, "created_at": m.created_at} for m in msgs],
                "next_action": summary.next_action if summary else None,
            }
        )
    return {
        "lead": LeadOut.model_validate(lead).model_dump(),
        "calls": call_details,
        "appointments": [AppointmentOut.model_validate(a).model_dump() for a in appointments],
    }


@app.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead_endpoint(
    lead_id: int,
    payload: LeadUpdate,
    tenant_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> Lead:
    """Update lead fields or Kanban category for a tenant."""
    _require_tenant(db, tenant_id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(lead, k, v)
    db.commit()
    db.refresh(lead)
    return lead


@app.delete("/leads/{lead_id}")
def delete_lead(
    lead_id: int,
    tenant_id: int = Query(..., ge=1),
    claims: dict[str, Any] = Depends(_verify_jwt),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete a tenant-scoped lead and its associated records (data retention control)."""
    if claims.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    _require_tenant(db, tenant_id)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    db.delete(lead)
    db.commit()
    return {"status": "deleted"}


@app.post("/leads", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(payload: LeadCreate, db: Session = Depends(get_db)) -> Lead:
    """Create a new lead for a tenant."""
    _require_tenant(db, payload.tenant_id)
    lead = Lead(**payload.model_dump())
    db.add(lead)
    db.commit()
    db.refresh(lead)
    logger.info("Created lead id=%d for tenant_id=%d", lead.id, lead.tenant_id)
    return lead


@app.get("/calls")
def list_calls(
    tenant_id: int = Query(..., ge=1),
    lead_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List calls scoped to a tenant, enriched with lead name and score."""
    _require_tenant(db, tenant_id)
    stmt = select(Call).where(Call.tenant_id == tenant_id)
    if lead_id is not None:
        stmt = stmt.where(Call.lead_id == lead_id)
    calls = list(db.scalars(stmt.order_by(Call.id.desc())))
    items: list[dict[str, Any]] = []
    for c in calls:
        lead = db.scalar(select(Lead).where(Lead.id == c.lead_id, Lead.tenant_id == tenant_id)) if c.lead_id else None
        row = CallOut.model_validate(c).model_dump()
        row["lead_name"] = lead.name if lead else None
        row["lead_score"] = lead.score if lead else 0
        row["lead_category"] = lead.category if lead else "cold"
        items.append(row)
    return items


@app.get("/calls/{call_id}")
def get_call_detail(
    call_id: int,
    tenant_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return a single call with its messages and structured summary."""
    _require_tenant(db, tenant_id)
    call = db.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    msgs = list(db.scalars(select(Message).where(Message.call_id == call.id).order_by(Message.id)))
    summary = db.scalar(select(CallSummary).where(CallSummary.call_id == call.id))
    lead = db.scalar(select(Lead).where(Lead.id == call.lead_id, Lead.tenant_id == tenant_id)) if call.lead_id else None
    insights = dict(summary.insights or {}) if summary else {}
    return {
        "call": CallOut.model_validate(call).model_dump(),
        "lead": LeadOut.model_validate(lead).model_dump() if lead else None,
        "messages": [{"id": m.id, "role": m.role, "text": m.text, "created_at": m.created_at} for m in msgs],
        "tool_actions": insights.get("tool_actions", []),
        "summary": (
            {
                "requirement": summary.requirement,
                "objection": summary.objection,
                "next_action": summary.next_action,
                "insights": insights,
            }
            if summary
            else None
        ),
    }


@app.post("/calls/{call_id}/end")
def end_call_endpoint(
    call_id: int,
    tenant_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """End a call and generate its structured summary, sentiment, and lead updates."""
    _require_tenant(db, tenant_id)
    call = db.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    msgs = list(db.scalars(select(Message).where(Message.call_id == call.id).order_by(Message.id)))
    history = [{"role": m.role, "content": m.text} for m in msgs]
    lead = db.scalar(select(Lead).where(Lead.id == call.lead_id, Lead.tenant_id == tenant_id)) if call.lead_id else None
    summary_data = generate_call_summary(history, lead_to_dict(lead) if lead else {})
    summary_row = finalize_call_summary(db, tenant_id, call.id, summary_data)
    db.refresh(call)
    return {
        "call": CallOut.model_validate(call).model_dump(),
        "summary": summary_row.insights,
    }


@app.delete("/calls/{call_id}")
def delete_call(
    call_id: int,
    tenant_id: int = Query(..., ge=1),
    claims: dict[str, Any] = Depends(_verify_jwt),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete a tenant-scoped call, its messages, and summary."""
    if claims.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    _require_tenant(db, tenant_id)
    call = db.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    db.delete(call)
    db.commit()
    return {"status": "deleted"}


@app.get("/analytics")
def analytics(
    tenant_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return tenant-scoped CRM and call analytics."""
    _require_tenant(db, tenant_id)
    return get_analytics(db, tenant_id)


@app.get("/appointments")
def list_appointments(
    tenant_id: int = Query(..., ge=1),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List appointments scoped to a tenant with lead contact info."""
    _require_tenant(db, tenant_id)
    stmt = select(Appointment).where(Appointment.tenant_id == tenant_id)
    if status_filter:
        stmt = stmt.where(Appointment.status == status_filter)
    appts = list(db.scalars(stmt.order_by(Appointment.starts_at.asc())))
    items: list[dict[str, Any]] = []
    for a in appts:
        lead = db.scalar(select(Lead).where(Lead.id == a.lead_id, Lead.tenant_id == tenant_id))
        row = AppointmentOut.model_validate(a).model_dump()
        row["lead_name"] = lead.name if lead else None
        row["lead_company"] = lead.company if lead else None
        items.append(row)
    return items


@app.patch("/appointments/{appointment_id}", response_model=AppointmentOut)
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    tenant_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> Appointment:
    """Update an appointment's status or reschedule its time."""
    _require_tenant(db, tenant_id)
    appt = db.scalar(
        select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == tenant_id)
    )
    if appt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    if payload.starts_at is not None:
        appt.starts_at = payload.starts_at
        if payload.status is None:
            appt.status = "rescheduled"
    if payload.status is not None:
        appt.status = payload.status

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This time slot is already booked for the tenant",
        ) from exc
    db.refresh(appt)
    return appt


@app.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def create_appointment(payload: AppointmentCreate, db: Session = Depends(get_db)) -> Appointment:
    """Book an appointment for a tenant and lead, preventing double bookings."""
    _require_tenant(db, payload.tenant_id)
    lead = db.scalar(
        select(Lead).where(Lead.id == payload.lead_id, Lead.tenant_id == payload.tenant_id)
    )
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found for this tenant",
        )

    appointment = Appointment(**payload.model_dump())
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This time slot is already booked for the tenant",
        ) from exc

    db.refresh(appointment)
    logger.info(
        "Booked appointment id=%d for tenant_id=%d lead_id=%d",
        appointment.id,
        appointment.tenant_id,
        appointment.lead_id,
    )
    return appointment


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """Run a single text sales agent turn with memory, lead extraction, and scoring."""
    tenant = _require_tenant(db, payload.tenant_id)

    call: Call | None = None
    if payload.call_id is not None:
        call = db.scalar(select(Call).where(Call.id == payload.call_id, Call.tenant_id == payload.tenant_id))
        if call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    lead: Lead | None = None
    target_lead_id = payload.lead_id or (call.lead_id if call else None)
    if target_lead_id is not None:
        lead = db.scalar(select(Lead).where(Lead.id == target_lead_id, Lead.tenant_id == payload.tenant_id))
        if lead is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    if lead is None:
        lead = upsert_lead(db, payload.tenant_id, {})

    if call is None:
        call = Call(tenant_id=payload.tenant_id, lead_id=lead.id, status="active")
        db.add(call)
        db.commit()
        db.refresh(call)

    existing_lead_data = lead_to_dict(lead)
    if payload.history:
        messages = [msg.model_dump() for msg in payload.history]
    else:
        prior = list(db.scalars(select(Message).where(Message.call_id == call.id).order_by(Message.id)))
        messages = [{"role": m.role, "content": m.text} for m in prior]
    messages.append({"role": "user", "content": payload.message})

    try:
        turn_result = run_agent_turn(
            messages,
            tenant_name=tenant.name,
            agent_config=tenant.agent_config,
            lead_data=existing_lead_data,
            db=db,
            tenant_id=payload.tenant_id,
            lead_id=lead.id,
        )
    except AgentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    reply = turn_result["reply"]
    db.add_all(
        [
            Message(call_id=call.id, role="user", text=payload.message),
            Message(call_id=call.id, role="assistant", text=reply),
        ]
    )
    db.commit()
    db.refresh(lead)

    updated_history = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
    updated_history.append(ChatMessage(role="assistant", content=reply))

    return ChatResponse(
        reply=reply,
        history=updated_history,
        call_id=call.id,
        lead_id=lead.id,
        lead_data=lead_to_dict(lead),
        score=lead.score,
        category=lead.category,
        sources=turn_result["sources"],
        appointment=turn_result["appointment"],
        end_call=turn_result["end_call"],
    )


@app.get("/rag/documents")
def list_rag_documents() -> list[dict[str, str]]:
    """List all markdown documents in knowledge_base/."""
    KB_DIR.mkdir(parents=True, exist_ok=True)
    docs = []
    for md_file in sorted(KB_DIR.glob("*.md")):
        docs.append({"filename": md_file.name, "content": md_file.read_text(encoding="utf-8")})
    return docs


@app.post("/rag/documents")
def save_rag_document(payload: RagDocumentUpdate) -> dict[str, Any]:
    """Create or update a markdown document inside knowledge_base/ and re-index."""
    safe_name = payload.filename.strip().replace("\\", "/").split("/")[-1]
    if not safe_name.endswith(".md"):
        safe_name = f"{safe_name}.md"
    if not safe_name or safe_name.startswith("."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")

    KB_DIR.mkdir(parents=True, exist_ok=True)
    target = (KB_DIR / safe_name).resolve()
    if target.parent != KB_DIR.resolve():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")
    target.write_text(payload.content, encoding="utf-8")
    chunks = ingest_knowledge_base()
    return {"filename": safe_name, "chunks_indexed": chunks}


@app.post("/rag/reindex")
def reindex_rag() -> dict[str, int]:
    """Re-index markdown files from knowledge_base/ into ChromaDB."""
    chunks = ingest_knowledge_base()
    return {"chunks_indexed": chunks}


@app.post("/rag/search")
def rag_search(payload: RagSearchRequest) -> dict[str, Any]:
    """Search the company knowledge base and return matching chunks."""
    return search_knowledge_base(payload.query, top_k=payload.top_k)


@app.post("/rag/ask")
def rag_ask(payload: RagSearchRequest) -> dict[str, Any]:
    """Retrieve matching chunks and generate a grounded test answer."""
    return answer_kb_question(payload.query)


async def _send_json_safe(ws: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        pass


def _process_voice_turn_sync(
    tenant_id: int,
    tenant_name: str,
    agent_config: dict[str, Any],
    call_id: int,
    lead_id: int,
    utterance: str,
    history: list[dict[str, str]],
    language: str | None = None,
) -> tuple[str, dict[str, Any], int, str, list[str], dict[str, Any] | None, bool, list[dict[str, Any]]]:
    """Run LLM reply with tools, message persistence, and lead extraction/scoring."""
    with SessionLocal() as db:
        lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
        existing_lead_data = lead_to_dict(lead) if lead else {}
        turn_messages = [*history, {"role": "user", "content": utterance}]

        turn_result = run_agent_turn(
            turn_messages,
            tenant_name=tenant_name,
            agent_config=agent_config,
            lead_data=existing_lead_data,
            db=db,
            tenant_id=tenant_id,
            lead_id=lead_id,
            language=language,
        )
        reply = turn_result["reply"]

        db.add_all(
            [
                Message(call_id=call_id, role="user", text=utterance),
                Message(call_id=call_id, role="assistant", text=reply),
            ]
        )
        db.commit()

        db.refresh(lead)
        return (
            reply,
            lead_to_dict(lead),
            lead.score,
            lead.category,
            turn_result["sources"],
            turn_result["appointment"],
            turn_result["end_call"],
            turn_result["tool_actions"],
        )


# How long after the last transcript a pending final still counts as end of turn.
IDLE_FLUSH_SECONDS = 1.2


@app.websocket("/ws/call")
async def voice_call_ws(websocket: WebSocket, tenant_id: int = Query(default=1, ge=1)) -> None:
    """Real-time browser voice WebSocket: mic audio -> Deepgram -> LLM -> ElevenLabs."""
    await websocket.accept()

    with SessionLocal() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None:
            await _send_json_safe(websocket, {"type": "error", "message": "Tenant not found"})
            await websocket.close(code=1008)
            return
        tenant_name = tenant.name
        agent_config = dict(tenant.agent_config or {})
        lead = upsert_lead(db, tenant_id, {})
        call = Call(tenant_id=tenant_id, lead_id=lead.id, status="listening", language=agent_config.get("language", "en"))
        db.add(call)
        db.commit()
        db.refresh(call)
        call_id, lead_id = call.id, lead.id
        started_at = call.started_at

    deepgram_ws = None
    state = "listening"
    history: list[dict[str, str]] = []
    tool_actions_log: list[dict[str, Any]] = []
    turn_counter = 0
    tts_cancel_event = asyncio.Event()
    active_turn_task: asyncio.Task | None = None
    stop_event = asyncio.Event()
    last_utterance = ""
    last_utterance_ts = 0.0

    async def set_state(new_state: str) -> None:
        nonlocal state
        state = new_state
        await _send_json_safe(websocket, {"type": "state", "state": new_state})

    async def cancel_speaking() -> None:
        tts_cancel_event.set()
        if active_turn_task and not active_turn_task.done():
            active_turn_task.cancel()
            try:
                await active_turn_task
            except asyncio.CancelledError:
                pass
        await _send_json_safe(websocket, {"type": "stop_audio"})
        if not stop_event.is_set():
            await set_state("listening")

    async def speak_text(text_to_speak: str) -> None:
        nonlocal turn_counter
        turn_counter += 1
        current_turn = turn_counter
        tts_cancel_event.clear()
        await set_state("speaking")
        try:
            for attempt in (1, 2):
                started = False
                try:
                    async for chunk in stream_elevenlabs_tts(text_to_speak, cancel_event=tts_cancel_event):
                        if tts_cancel_event.is_set() or stop_event.is_set():
                            break
                        started = True
                        encoded = base64.b64encode(chunk).decode("ascii")
                        await _send_json_safe(
                            websocket,
                            {"type": "audio_chunk", "data": encoded, "turn_id": current_turn},
                        )
                    if not tts_cancel_event.is_set() and not stop_event.is_set():
                        await _send_json_safe(websocket, {"type": "audio_end", "turn_id": current_turn})
                    break
                except VoiceError as exc:
                    # Retry only when nothing has played, so a sentence never restarts mid-way.
                    if started or attempt == 2:
                        await _send_json_safe(websocket, {"type": "error", "message": str(exc)})
                        break
                    logger.warning("TTS failed before audio started; retrying once")
                    await asyncio.sleep(0.3)
        finally:
            if not stop_event.is_set() and state == "speaking":
                await set_state("listening")

    async def handle_utterance(utterance: str) -> None:
        try:
            await set_state("processing")
            reply, lead_data, score, category, sources, appointment, should_end, actions = await asyncio.to_thread(
                _process_voice_turn_sync,
                tenant_id,
                tenant_name,
                agent_config,
                call_id,
                lead_id,
                utterance,
                history,
            )
            history.append({"role": "user", "content": utterance})
            history.append({"role": "assistant", "content": reply})
            tool_actions_log.extend(actions)

            await _send_json_safe(
                websocket,
                {"type": "transcript", "role": "assistant", "text": reply, "is_final": True},
            )
            await _send_json_safe(
                websocket,
                {"type": "lead_update", "lead_data": lead_data, "score": score, "category": category},
            )
            if sources:
                await _send_json_safe(websocket, {"type": "knowledge_used", "sources": sources})
            if appointment:
                await _send_json_safe(websocket, {"type": "appointment_booked", "appointment": appointment})

            await speak_text(reply)
            if should_end:
                stop_event.set()
        except asyncio.CancelledError:
            raise
        except AgentError as exc:
            await _send_json_safe(websocket, {"type": "error", "message": str(exc)})
            await set_state("listening")
        except Exception as exc:
            logger.exception("Voice turn failed: %s", type(exc).__name__)
            await _send_json_safe(websocket, {"type": "error", "message": "Unable to process voice turn."})
            await set_state("listening")

    try:
        deepgram_ws = await connect_deepgram(language=agent_config.get("language", "en"))
        await _send_json_safe(
            websocket,
            {"type": "call_started", "call_id": call_id, "lead_id": lead_id, "state": "listening"},
        )

        greeting = agent_config.get("greeting") or f"Hi, thanks for calling {tenant_name}! How can I help you today?"
        history.append({"role": "assistant", "content": greeting})
        with SessionLocal() as db:
            db.add(Message(call_id=call_id, role="assistant", text=greeting))
            db.commit()
        await _send_json_safe(
            websocket,
            {"type": "transcript", "role": "assistant", "text": greeting, "is_final": True},
        )
        active_turn_task = asyncio.create_task(speak_text(greeting))

        async def browser_to_deepgram() -> None:
            while not stop_event.is_set():
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    stop_event.set()
                    break
                if msg.get("bytes") is not None:
                    if deepgram_ws is not None:
                        try:
                            await deepgram_ws.send(msg["bytes"])
                        except ConnectionClosed:
                            return  # STT session is over; its reader logs the close and ends the call
                elif msg.get("text"):
                    try:
                        data = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                    action = data.get("type")
                    if action == "interrupt":
                        await cancel_speaking()
                    elif action == "end_call":
                        stop_event.set()
                        break

        async def deepgram_to_agent() -> None:
            nonlocal active_turn_task, last_utterance, last_utterance_ts
            final_parts: list[str] = []
            last_result_ts = 0.0

            def dispatch_utterance() -> None:
                nonlocal active_turn_task, last_utterance, last_utterance_ts
                utterance = " ".join(final_parts).strip()
                final_parts.clear()
                now = time.monotonic()
                norm = utterance.lower()
                if not norm or (norm == last_utterance and now - last_utterance_ts <= 2.0):
                    return
                last_utterance, last_utterance_ts = norm, now
                if active_turn_task and not active_turn_task.done():
                    active_turn_task.cancel()
                active_turn_task = asyncio.create_task(handle_utterance(utterance))

            async def flush_stale_final() -> None:
                # When the mic goes quiet, Deepgram sends a final result without
                # speech_final and never sends UtteranceEnd; a stale final still ends the turn.
                while not stop_event.is_set():
                    await asyncio.sleep(0.25)
                    if final_parts and time.monotonic() - last_result_ts > IDLE_FLUSH_SECONDS:
                        dispatch_utterance()

            flush_task = asyncio.create_task(flush_stale_final())
            try:
                async for raw in deepgram_ws:
                    if stop_event.is_set():
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    evt_type = event.get("type")
                    if evt_type == "SpeechStarted" and state == "speaking":
                        await cancel_speaking()
                        continue

                    if evt_type == "Results":
                        alts = event.get("channel", {}).get("alternatives", [])
                        transcript = (alts[0].get("transcript", "") if alts else "").strip()
                        if not transcript:
                            continue

                        if state == "speaking":
                            await cancel_speaking()

                        last_result_ts = time.monotonic()
                        is_final = bool(event.get("is_final"))
                        await _send_json_safe(
                            websocket,
                            {"type": "transcript", "role": "user", "text": transcript, "is_final": is_final},
                        )
                        if is_final:
                            final_parts.append(transcript)
                        if bool(event.get("speech_final")) and final_parts:
                            dispatch_utterance()

                    elif evt_type == "UtteranceEnd" and final_parts:
                        dispatch_utterance()
            except ConnectionClosed:
                logger.info("STT stream ended for call_id=%d", call_id)
            finally:
                flush_task.cancel()

        call_tasks = {
            asyncio.create_task(browser_to_deepgram()),
            asyncio.create_task(deepgram_to_agent()),
        }
        done, pending = await asyncio.wait(call_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()

    except WebSocketDisconnect:
        logger.info("Voice WebSocket disconnected for call_id=%d", call_id)
    except VoiceError as exc:
        await _send_json_safe(websocket, {"type": "error", "message": str(exc)})
    except Exception as exc:
        logger.exception("Voice WebSocket error for call_id=%d: %s", call_id, type(exc).__name__)
        await _send_json_safe(websocket, {"type": "error", "message": "Voice connection error"})
    finally:
        stop_event.set()
        tts_cancel_event.set()
        if active_turn_task and not active_turn_task.done():
            # Give a reply that is already being generated a moment to reach the client;
            # wait_for cancels the turn itself if it outlives the timeout.
            with suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(active_turn_task, timeout=3.0)
        if deepgram_ws is not None:
            try:
                await deepgram_ws.send(json.dumps({"type": "CloseStream"}))
                await deepgram_ws.close()
            except Exception:
                pass
        ended_at = datetime.now(timezone.utc)
        # SQLite hands back started_at without tzinfo; normalise before subtracting.
        started = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
        duration_sec = max(0, int((ended_at - started).total_seconds()))

        def _finalize() -> None:
            with SessionLocal() as db:
                db_call = db.scalar(select(Call).where(Call.id == call_id))
                if db_call is not None:
                    db_call.ended_at = ended_at
                    db_call.duration = duration_sec
                    db.commit()
                db_lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
                summary_data = generate_call_summary(history, lead_to_dict(db_lead) if db_lead else {})
                summary_data["tool_actions"] = tool_actions_log
                finalize_call_summary(db, tenant_id, call_id, summary_data)

        await asyncio.to_thread(_finalize)
        await _send_json_safe(websocket, {"type": "state", "state": "ended"})
        logger.info("Ended voice call_id=%d duration=%ds", call_id, duration_sec)


class OutboundCallRequest(BaseModel):
    to: str = Field(..., min_length=6, max_length=32)
    tenant_id: int = Field(default=1, ge=1)
    language: str = Field(default="en", pattern="^(en|hi)$")


@app.post("/twilio/voice")
async def twilio_voice_webhook(
    request: Request,
    tenant_id: int = Query(default=1, ge=1),
    language: str = Query(default="en", pattern="^(en|hi)$"),
) -> Response:
    """Inbound/outbound Twilio TwiML webhook returning a Media Streams <Connect><Stream>."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    sig = request.headers.get("X-Twilio-Signature")
    if not verify_twilio_signature(str(request.url), form, sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")

    ws_base = settings.public_base_url.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
    twiml = build_stream_twiml(f"{ws_base}/ws/twilio", tenant_id=tenant_id, language=language)
    return Response(content=twiml, media_type="application/xml")


@app.post("/twilio/status")
async def twilio_status_webhook(request: Request) -> dict[str, str]:
    """Twilio call status callback with signature verification."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    sig = request.headers.get("X-Twilio-Signature")
    if not verify_twilio_signature(str(request.url), form, sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")

    call_status = form.get("CallStatus", "unknown")
    logger.info("Twilio status callback status=%s from=%s", call_status, mask_phone(form.get("From")))
    return {"status": "received"}


@app.post("/twilio/outbound")
async def twilio_outbound_call(payload: OutboundCallRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Initiate an outbound phone call via Twilio bridged to the AI sales agent."""
    _require_tenant(db, payload.tenant_id)
    try:
        return await initiate_outbound_call(payload.to, payload.tenant_id, payload.language)
    except TelephonyError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@app.websocket("/ws/twilio")
async def twilio_media_stream_ws(websocket: WebSocket) -> None:
    """Bridge Twilio Media Streams (mulaw 8kHz) to Deepgram, the sales agent, and ElevenLabs."""
    await websocket.accept()
    stream_sid = ""
    tenant_id = 1
    language = settings.default_language
    call_id: int | None = None
    lead_id: int | None = None
    started_at = datetime.now(timezone.utc)
    tenant_name = "ApexCRM"
    agent_config: dict[str, Any] = {}
    history: list[dict[str, str]] = []
    tool_actions_log: list[dict[str, Any]] = []

    deepgram_ws = None
    tts_cancel_event = asyncio.Event()
    active_turn_task: asyncio.Task | None = None
    stop_event = asyncio.Event()
    state = "listening"
    last_utterance = ""
    last_utterance_ts = 0.0

    async def speak_to_twilio(text_to_speak: str) -> None:
        nonlocal state
        if not stream_sid:
            return
        tts_cancel_event.clear()
        state = "speaking"
        try:
            async for chunk in stream_elevenlabs_tts(
                text_to_speak, cancel_event=tts_cancel_event, output_format="ulaw_8000"
            ):
                if tts_cancel_event.is_set() or stop_event.is_set():
                    break
                payload_b64 = base64.b64encode(chunk).decode("ascii")
                await _send_json_safe(
                    websocket,
                    {"event": "media", "streamSid": stream_sid, "media": {"payload": payload_b64}},
                )
        except VoiceError as exc:
            logger.warning("Twilio TTS error: %s", exc)
        finally:
            if not stop_event.is_set():
                state = "listening"

    async def handle_twilio_utterance(utterance: str) -> None:
        if call_id is None or lead_id is None:
            return
        state_local = "processing"
        try:
            reply, _ld, _sc, _cat, _src, _appt, should_end, actions = await asyncio.to_thread(
                _process_voice_turn_sync,
                tenant_id,
                tenant_name,
                agent_config,
                call_id,
                lead_id,
                utterance,
                history,
                language,
            )
            history.append({"role": "user", "content": utterance})
            history.append({"role": "assistant", "content": reply})
            tool_actions_log.extend(actions)
            await speak_to_twilio(reply)
            if should_end:
                stop_event.set()
        except Exception as exc:
            logger.warning("Twilio turn error (%s): %s", state_local, type(exc).__name__)

    try:
        while not stop_event.is_set():
            raw = await websocket.receive_text()
            event = json.loads(raw)
            evt = event.get("event")

            if evt == "start":
                start_info = event.get("start", {})
                stream_sid = start_info.get("streamSid", "")
                custom = start_info.get("customParameters", {})
                tenant_id = int(custom.get("tenant_id", 1))
                language = custom.get("language", settings.default_language)

                with SessionLocal() as db:
                    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
                    if tenant is not None:
                        tenant_name = tenant.name
                        agent_config = dict(tenant.agent_config or {})
                    lead = upsert_lead(db, tenant_id, {})
                    call = Call(tenant_id=tenant_id, lead_id=lead.id, status="listening", language=language)
                    db.add(call)
                    db.commit()
                    db.refresh(call)
                    call_id, lead_id, started_at = call.id, lead.id, call.started_at

                deepgram_ws = await connect_deepgram(language=language, encoding="mulaw", sample_rate=8000)

                async def dg_loop() -> None:
                    nonlocal active_turn_task, last_utterance, last_utterance_ts
                    final_parts: list[str] = []
                    async for dg_raw in deepgram_ws:
                        if stop_event.is_set():
                            break
                        dg_evt = json.loads(dg_raw)
                        if dg_evt.get("type") == "SpeechStarted" and state == "speaking":
                            tts_cancel_event.set()
                            await _send_json_safe(websocket, {"event": "clear", "streamSid": stream_sid})
                        elif dg_evt.get("type") == "Results":
                            alts = dg_evt.get("channel", {}).get("alternatives", [])
                            txt = (alts[0].get("transcript", "") if alts else "").strip()
                            if not txt:
                                continue
                            if dg_evt.get("is_final"):
                                final_parts.append(txt)
                            if dg_evt.get("speech_final") and final_parts:
                                utt = " ".join(final_parts).strip()
                                final_parts.clear()
                                now = time.monotonic()
                                norm = utt.lower()
                                if norm and (norm != last_utterance or now - last_utterance_ts > 2.0):
                                    last_utterance, last_utterance_ts = norm, now
                                    if active_turn_task and not active_turn_task.done():
                                        active_turn_task.cancel()
                                    active_turn_task = asyncio.create_task(handle_twilio_utterance(utt))
                        elif dg_evt.get("type") == "UtteranceEnd" and final_parts:
                            utt = " ".join(final_parts).strip()
                            final_parts.clear()
                            now = time.monotonic()
                            norm = utt.lower()
                            if norm and (norm != last_utterance or now - last_utterance_ts > 2.0):
                                last_utterance, last_utterance_ts = norm, now
                                if active_turn_task and not active_turn_task.done():
                                    active_turn_task.cancel()
                                active_turn_task = asyncio.create_task(handle_twilio_utterance(utt))

                asyncio.create_task(dg_loop())
                greeting = (
                    "नमस्ते! बताइए आज मैं आपकी क्या मदद कर सकती हूँ?"
                    if language.startswith("hi")
                    else agent_config.get("greeting", f"Hi, thanks for calling {tenant_name}!")
                )
                history.append({"role": "assistant", "content": greeting})
                active_turn_task = asyncio.create_task(speak_to_twilio(greeting))

            elif evt == "media" and deepgram_ws is not None:
                audio_b64 = event.get("media", {}).get("payload", "")
                if audio_b64:
                    await deepgram_ws.send(base64.b64decode(audio_b64))

            elif evt == "stop":
                stop_event.set()
                break
    except WebSocketDisconnect:
        logger.info("Twilio Media Stream disconnected")
    finally:
        stop_event.set()
        tts_cancel_event.set()
        if deepgram_ws is not None:
            try:
                await deepgram_ws.send(json.dumps({"type": "CloseStream"}))
                await deepgram_ws.close()
            except Exception:
                pass
        if call_id is not None and lead_id is not None:
            ended_at = datetime.now(timezone.utc)
            started = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
            duration_sec = max(0, int((ended_at - started).total_seconds()))

            def _finalize_twilio() -> None:
                with SessionLocal() as db:
                    db_call = db.scalar(select(Call).where(Call.id == call_id))
                    if db_call is not None:
                        db_call.ended_at = ended_at
                        db_call.duration = duration_sec
                        db.commit()
                    db_lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
                    summary_data = generate_call_summary(history, lead_to_dict(db_lead) if db_lead else {})
                    summary_data["tool_actions"] = tool_actions_log
                    finalize_call_summary(db, tenant_id, call_id, summary_data)

            await asyncio.to_thread(_finalize_twilio)
