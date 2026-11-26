"""Unit tests for pure-Python appointment booking and conflict handling."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.booking import book_appointment, check_availability, reschedule_appointment
from backend.database import Appointment, Base, Lead, Tenant


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    tenant = Tenant(name="ApexCRM", agent_config={})
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    lead = Lead(tenant_id=tenant.id, name="Asha")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return db, tenant, lead


def test_book_and_reject_duplicate_slot():
    db, tenant, lead = _make_db()
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    slot = f"{tomorrow}T15:00:00Z"

    first = book_appointment(db, tenant.id, lead.id, slot)
    assert first["booked"] is True

    duplicate = book_appointment(db, tenant.id, lead.id, slot)
    assert duplicate["booked"] is False
    assert "already booked" in duplicate["error"].lower()
    assert len(duplicate["alternatives"]) > 0

    free = check_availability(db, tenant.id, tomorrow)
    assert slot not in free
    db.close()


def test_reschedule_without_duplicate():
    db, tenant, lead = _make_db()
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    slot1 = f"{tomorrow}T10:00:00Z"
    slot2 = f"{tomorrow}T14:00:00Z"

    assert book_appointment(db, tenant.id, lead.id, slot1)["booked"] is True
    res = reschedule_appointment(db, tenant.id, lead.id, slot2)
    assert res["rescheduled"] is True
    assert res["appointment"]["starts_at"] == slot2

    rows = list(db.scalars(select(Appointment).where(Appointment.tenant_id == tenant.id)))
    assert len(rows) == 1
    assert rows[0].status == "rescheduled"
    db.close()
