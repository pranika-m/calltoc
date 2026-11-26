"""CRM business logic: pure-Python lead scoring, classification, summaries, and analytics."""

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import Appointment, Call, CallSummary, Lead

LEAD_FIELDS = (
    "name",
    "phone",
    "company",
    "industry",
    "requirement",
    "budget",
    "timeline",
    "decision_maker",
    "interest",
)


def _is_within_30_days(timeline: Any) -> bool:
    """Return True when the timeline indicates a purchase within 30 days."""
    if not timeline or not isinstance(timeline, str):
        return False
    text = timeline.strip().lower()
    quick_phrases = (
        "immediate",
        "asap",
        "right away",
        "this week",
        "next week",
        "this month",
        "within 30",
        "30 days",
    )
    if any(phrase in text for phrase in quick_phrases):
        return True

    day_match = re.search(r"(\d+)\s*day", text)
    if day_match and int(day_match.group(1)) <= 30:
        return True

    week_match = re.search(r"(\d+)\s*week", text)
    if week_match and int(week_match.group(1)) <= 4:
        return True

    month_match = re.search(r"(\d+)\s*month", text)
    if month_match and int(month_match.group(1)) <= 1:
        return True

    return False


def calculate_lead_score(lead_data: dict[str, Any]) -> int:
    """Compute a 0-100 lead score from extracted lead fields."""
    score = 0
    if lead_data.get("requirement"):
        score += 20
    if lead_data.get("budget"):
        score += 20
    if _is_within_30_days(lead_data.get("timeline")):
        score += 25
    if lead_data.get("decision_maker") is True:
        score += 20
    if str(lead_data.get("interest", "")).strip().lower() == "high":
        score += 15
    return min(score, 100)


def classify_lead(score: int) -> str:
    """Classify a numeric lead score into hot, warm, or cold."""
    if score >= settings.lead_hot_threshold:
        return "hot"
    if score >= settings.lead_warm_threshold:
        return "warm"
    return "cold"


def merge_lead_data(existing: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    """Merge non-empty newly extracted fields into existing lead_data."""
    merged = dict(existing)
    for field in LEAD_FIELDS:
        value = extracted.get(field)
        if value is not None and value != "":
            merged[field] = value
    return merged


def lead_to_dict(lead: Lead) -> dict[str, Any]:
    """Convert a Lead ORM row into a plain lead_data dictionary."""
    return {field: getattr(lead, field) for field in LEAD_FIELDS if getattr(lead, field) is not None}


def upsert_lead(
    db: Session,
    tenant_id: int,
    lead_data: dict[str, Any],
    lead_id: int | None = None,
) -> Lead:
    """Create or update a tenant-scoped lead with recalculated score and category."""
    lead: Lead | None = None
    if lead_id is not None:
        lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))

    if lead is None:
        lead = Lead(tenant_id=tenant_id)
        db.add(lead)

    for field in LEAD_FIELDS:
        if field in lead_data and lead_data[field] is not None:
            setattr(lead, field, lead_data[field])

    current_data = lead_to_dict(lead)
    lead.score = calculate_lead_score(current_data)
    lead.category = classify_lead(lead.score)

    db.commit()
    db.refresh(lead)
    return lead


def finalize_call_summary(
    db: Session,
    tenant_id: int,
    call_id: int,
    summary_data: dict[str, Any],
) -> CallSummary:
    """Persist structured call summary and update call and lead records."""
    call = db.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    if call is None:
        raise ValueError("Call not found for tenant")

    now = datetime.now(timezone.utc)
    call.status = "ended"
    if call.ended_at is None:
        call.ended_at = now
    if call.duration is None and call.started_at is not None:
        started = call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=timezone.utc)
        call.duration = max(0, int((call.ended_at - started).total_seconds()))
    call.sentiment = summary_data.get("sentiment", "neutral")
    call.summary = summary_data.get("summary", "")

    if call.lead_id is not None:
        lead = db.scalar(select(Lead).where(Lead.id == call.lead_id, Lead.tenant_id == tenant_id))
        if lead is not None:
            existing = lead_to_dict(lead)
            updates = {
                k: summary_data.get(k)
                for k in ("requirement", "budget", "timeline", "interest")
                if summary_data.get(k)
            }
            if summary_data.get("customer") and summary_data["customer"] != "Unknown" and not existing.get("name"):
                updates["name"] = summary_data["customer"]
            merged = merge_lead_data(existing, updates)
            upsert_lead(db, tenant_id, merged, lead_id=lead.id)

    summary_row = db.scalar(select(CallSummary).where(CallSummary.call_id == call_id))
    if summary_row is None:
        summary_row = CallSummary(call_id=call_id)
        db.add(summary_row)

    summary_row.requirement = summary_data.get("requirement") or None
    summary_row.objection = summary_data.get("objection") or None
    summary_row.next_action = summary_data.get("next_action") or None
    summary_row.insights = summary_data

    db.commit()
    db.refresh(summary_row)
    return summary_row


def get_analytics(db: Session, tenant_id: int) -> dict[str, Any]:
    """Compute tenant-scoped CRM and call analytics."""
    calls = list(db.scalars(select(Call).where(Call.tenant_id == tenant_id)))
    leads = list(db.scalars(select(Lead).where(Lead.tenant_id == tenant_id)))
    appointments = list(
        db.scalars(
            select(Appointment).where(
                Appointment.tenant_id == tenant_id,
                Appointment.status.in_(("booked", "rescheduled", "completed")),
            )
        )
    )
    call_ids = [c.id for c in calls]
    summaries = (
        list(db.scalars(select(CallSummary).where(CallSummary.call_id.in_(call_ids))))
        if call_ids
        else []
    )

    lead_counts = {"hot": 0, "warm": 0, "cold": 0}
    for lead in leads:
        cat = lead.category if lead.category in lead_counts else "cold"
        lead_counts[cat] += 1

    qualified_conversations = sum(1 for lead in leads if lead.score >= settings.lead_warm_threshold)
    total_calls = len(calls)
    appointments_booked = len(appointments)
    booking_rate = round((appointments_booked / total_calls) * 100, 1) if total_calls else 0.0

    req_counter: Counter[str] = Counter()
    obj_counter: Counter[str] = Counter()
    for s in summaries:
        if s.requirement:
            req_counter[s.requirement] += 1
        if s.objection:
            obj_counter[s.objection] += 1

    sentiment_counter: Counter[str] = Counter()
    day_counter: Counter[str] = Counter()
    for c in calls:
        sentiment_counter[c.sentiment or "neutral"] += 1
        if c.started_at:
            day_counter[c.started_at.date().isoformat()] += 1

    return {
        "total_calls": total_calls,
        "qualified_conversations": qualified_conversations,
        "lead_counts": lead_counts,
        "appointments_booked": appointments_booked,
        "booking_rate": booking_rate,
        "top_requirements": [{"label": k, "count": v} for k, v in req_counter.most_common(5)],
        "top_objections": [{"label": k, "count": v} for k, v in obj_counter.most_common(5)],
        "sentiment_breakdown": [{"sentiment": k, "count": v} for k, v in sentiment_counter.items()],
        "calls_per_day": [{"date": d, "count": day_counter[d]} for d in sorted(day_counter)],
    }
