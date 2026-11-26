"""Integration tests for API route handlers, tenant isolation, appointments, chat, and analytics."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.agent as agent_mod
import backend.main as main_mod
from backend.database import Base, seed_tenants


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    seed_tenants(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_health_tenants_and_isolation(db):
    assert main_mod.health_check(db=db)["status"] == "ok"
    tenants = main_mod.list_tenants(db=db)
    assert len(tenants) == 2

    lead = main_mod.create_lead(
        main_mod.LeadCreate(tenant_id=1, name="Ravi", budget="$800/mo"),
        db=db,
    )
    t1_leads = main_mod.list_leads(tenant_id=1, category=None, sentiment=None, search=None, db=db)
    t2_leads = main_mod.list_leads(tenant_id=2, category=None, sentiment=None, search=None, db=db)
    assert any(l["id"] == lead.id for l in t1_leads)
    assert all(l["id"] != lead.id for l in t2_leads)


def test_appointment_duplicate_rejected(db):
    lead = main_mod.create_lead(main_mod.LeadCreate(tenant_id=1, name="Asha"), db=db)
    slot = datetime.now(timezone.utc) + timedelta(days=1)
    payload = main_mod.AppointmentCreate(tenant_id=1, lead_id=lead.id, starts_at=slot)

    created = main_mod.create_appointment(payload, db=db)
    assert created.status == "booked"

    with pytest.raises(HTTPException) as exc:
        main_mod.create_appointment(payload, db=db)
    assert exc.value.status_code == 409


def test_chat_end_call_and_analytics(db):
    tool_call = MagicMock(id="call_lead_1")
    tool_call.function.name = "update_lead"
    tool_call.function.arguments = json.dumps({"name": "Meera", "requirement": "Sales CRM", "interest": "high"})
    tool_msg = MagicMock(content=None, tool_calls=[tool_call])
    reply_msg = MagicMock(content="Nice to meet you! What is your timeline?", tool_calls=None)
    summary_msg = MagicMock(
        content=json.dumps(
            {
                "customer": "Meera",
                "requirement": "Sales CRM",
                "budget": "$1000/mo",
                "timeline": "2 weeks",
                "sentiment": "positive",
                "interest": "high",
                "objection": "None",
                "next_action": "Book demo",
                "summary": "Meera wants Sales CRM.",
            }
        )
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=tool_msg)]),
        MagicMock(choices=[MagicMock(message=reply_msg)]),
        MagicMock(choices=[MagicMock(message=summary_msg)]),
    ]

    with patch.object(agent_mod, "_get_client", return_value=mock_client):
        chat_res = main_mod.chat(
            main_mod.ChatRequest(tenant_id=1, message="Hi, I am Meera looking for Sales CRM."),
            db=db,
        )
        assert chat_res.call_id >= 1
        assert chat_res.lead_data["name"] == "Meera"

        end_res = main_mod.end_call_endpoint(call_id=chat_res.call_id, tenant_id=1, db=db)
        assert end_res["call"]["sentiment"] == "positive"

    stats = main_mod.analytics(tenant_id=1, db=db)
    assert stats["total_calls"] == 1
    assert stats["lead_counts"]["hot"] == 1
