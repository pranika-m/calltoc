"""Appointment availability, booking, and rescheduling in plain Python."""

from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import Appointment, Lead

logger = logging.getLogger(__name__)

BUSINESS_HOURS_START = 9
BUSINESS_HOURS_END = 17  # Last 1-hour slot starts at 17:00


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 or 'YYYY-MM-DD HH:MM' string into a UTC-aware datetime."""
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid date/time format: {value}") from exc

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(minute=0 if dt.minute == 0 else dt.minute, second=0, microsecond=0)


def parse_date(date_str: str) -> date:
    """Parse a 'YYYY-MM-DD' string into a date."""
    try:
        return date.fromisoformat(date_str.strip()[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid date format (expected YYYY-MM-DD): {date_str}") from exc


def check_availability(db: Session, tenant_id: int, date_str: str) -> list[str]:
    """Return available hourly ISO-8601 UTC slots for a tenant on the given date."""
    target_date = parse_date(date_str)
    day_start = datetime.combine(target_date, time(BUSINESS_HOURS_START, 0), tzinfo=timezone.utc)
    day_end = datetime.combine(target_date, time(BUSINESS_HOURS_END, 59, 59), tzinfo=timezone.utc)

    booked_rows = list(
        db.scalars(
            select(Appointment.starts_at).where(
                Appointment.tenant_id == tenant_id,
                Appointment.status.in_(("booked", "rescheduled")),
                Appointment.starts_at >= day_start,
                Appointment.starts_at <= day_end,
            )
        )
    )
    booked_hours = {
        (dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).hour
        for dt in booked_rows
    }

    free_slots: list[str] = []
    for hour in range(BUSINESS_HOURS_START, BUSINESS_HOURS_END + 1):
        if hour not in booked_hours:
            slot_dt = datetime.combine(target_date, time(hour, 0), tzinfo=timezone.utc)
            free_slots.append(slot_dt.isoformat().replace("+00:00", "Z"))
    return free_slots


def book_appointment(
    db: Session,
    tenant_id: int,
    lead_id: int,
    starts_at_str: str,
) -> dict[str, Any]:
    """Validate and book an appointment; return alternatives if the slot is taken."""
    starts_at = parse_datetime(starts_at_str)
    if starts_at <= datetime.now(timezone.utc) - timedelta(minutes=5):
        return {"booked": False, "error": "Requested time is in the past."}

    if not (BUSINESS_HOURS_START <= starts_at.hour <= BUSINESS_HOURS_END):
        alternatives = check_availability(db, tenant_id, starts_at.date().isoformat())
        return {
            "booked": False,
            "error": "Requested time is outside business hours (09:00-18:00 UTC).",
            "alternatives": alternatives[:3],
        }

    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    if lead is None:
        return {"booked": False, "error": "Lead not found for this tenant."}

    appointment = Appointment(
        tenant_id=tenant_id,
        lead_id=lead_id,
        starts_at=starts_at,
        status="booked",
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        alternatives = check_availability(db, tenant_id, starts_at.date().isoformat())
        return {
            "booked": False,
            "error": "That time slot is already booked.",
            "alternatives": alternatives[:3],
        }

    db.refresh(appointment)
    logger.info("Booked appointment id=%d for tenant_id=%d lead_id=%d", appointment.id, tenant_id, lead_id)
    return {
        "booked": True,
        "appointment": {
            "id": appointment.id,
            "tenant_id": appointment.tenant_id,
            "lead_id": appointment.lead_id,
            "starts_at": starts_at.isoformat().replace("+00:00", "Z"),
            "status": appointment.status,
        },
    }


def reschedule_appointment(
    db: Session,
    tenant_id: int,
    lead_id: int,
    new_starts_at_str: str,
) -> dict[str, Any]:
    """Move a lead's latest active appointment to a new slot without creating duplicates."""
    new_starts_at = parse_datetime(new_starts_at_str)
    if new_starts_at <= datetime.now(timezone.utc) - timedelta(minutes=5):
        return {"rescheduled": False, "error": "Requested time is in the past."}

    if not (BUSINESS_HOURS_START <= new_starts_at.hour <= BUSINESS_HOURS_END):
        alternatives = check_availability(db, tenant_id, new_starts_at.date().isoformat())
        return {
            "rescheduled": False,
            "error": "Requested time is outside business hours (09:00-18:00 UTC).",
            "alternatives": alternatives[:3],
        }

    existing = db.scalar(
        select(Appointment)
        .where(
            Appointment.tenant_id == tenant_id,
            Appointment.lead_id == lead_id,
            Appointment.status.in_(("booked", "rescheduled")),
        )
        .order_by(Appointment.id.desc())
    )
    if existing is None:
        return book_appointment(db, tenant_id, lead_id, new_starts_at_str)

    existing.starts_at = new_starts_at
    existing.status = "rescheduled"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        alternatives = check_availability(db, tenant_id, new_starts_at.date().isoformat())
        return {
            "rescheduled": False,
            "error": "That new time slot is already booked.",
            "alternatives": alternatives[:3],
        }

    db.refresh(existing)
    return {
        "rescheduled": True,
        "appointment": {
            "id": existing.id,
            "tenant_id": existing.tenant_id,
            "lead_id": existing.lead_id,
            "starts_at": new_starts_at.isoformat().replace("+00:00", "Z"),
            "status": existing.status,
        },
    }
