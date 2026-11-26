"""Database engine, session management, ORM models, and tenant seeding."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.config import settings

logger = logging.getLogger(__name__)


def _create_db_engine():
    connect_args: dict[str, object] = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        _ensure_sqlite_folder()
    elif settings.database_url.startswith("postgresql"):
        connect_args["connect_timeout"] = 5
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def _ensure_sqlite_folder() -> None:
    """Create the folder that holds the local SQLite file when it is missing."""
    db_path = settings.database_url.replace("sqlite:///", "", 1)
    folder = Path(db_path).parent
    if folder and not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)


engine = _create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    agent_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[str | None] = mapped_column(String(80), nullable=True)
    timeline: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decision_maker: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    interest: Mapped[str | None] = mapped_column(String(40), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="cold", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "starts_at", name="uq_appointments_tenant_starts_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="booked", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CallSummary(Base):
    __tablename__ = "call_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), unique=True, nullable=False)
    requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    objection: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    insights: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all database tables if they do not exist."""
    Base.metadata.create_all(bind=engine)


def seed_tenants(db: Session) -> None:
    """Insert two sample tenants when the tenants table is empty."""
    existing = db.scalar(select(Tenant.id).limit(1))
    if existing is not None:
        return

    sample_tenants = [
        Tenant(
            name="ApexCRM",
            agent_config={
                "agent_name": "Aria",
                "greeting": "Hi, thanks for calling ApexCRM! May I know your name?",
                "language": "en",
                "business_hours": "09:00-18:00",
            },
        ),
        Tenant(
            name="NovaCloud",
            agent_config={
                "agent_name": "Noah",
                "greeting": "Hello, welcome to NovaCloud. How can I help your team today?",
                "language": "en",
                "business_hours": "09:00-18:00",
            },
        ),
    ]
    db.add_all(sample_tenants)
    db.commit()
    logger.info("Seeded %d sample tenants", len(sample_tenants))
