"""Realistic demo records so a fresh install opens onto a populated CRM."""

from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.crm import classify_lead, calculate_lead_score
from backend.database import Appointment, Call, CallSummary, Lead, Message

logger = logging.getLogger(__name__)

DEMO_LEADS = [
    {
        "name": "Rahul Sharma",
        "phone": "+919812345670",
        "company": "Sharma Realty",
        "industry": "Real Estate",
        "requirement": "Automate follow-ups for 15 property agents and track site visits",
        "budget": "Rs 50,000 / year",
        "timeline": "within 30 days",
        "decision_maker": True,
        "interest": "high",
        "sentiment": "positive",
        "objection": "Needs WhatsApp integration confirmed",
        "next_action": "Demo booked - show follow-up automation",
    },
    {
        "name": "Meera Iyer",
        "phone": "+919812345671",
        "company": "Nova Edutech",
        "industry": "Education",
        "requirement": "Admission enquiry pipeline with counsellor assignment",
        "budget": "Rs 80,000 / year",
        "timeline": "next week",
        "decision_maker": True,
        "interest": "high",
        "sentiment": "interested",
        "objection": "Wants data migration support",
        "next_action": "Send migration plan and pricing sheet",
    },
    {
        "name": "Arjun Nair",
        "phone": "+919812345672",
        "company": "Nair Insurance",
        "industry": "Insurance",
        "requirement": "Policy renewal reminders and call logging",
        "budget": "",
        "timeline": "in 3 months",
        "decision_maker": False,
        "interest": "medium",
        "sentiment": "neutral",
        "objection": "Budget not approved yet",
        "next_action": "Follow up after budget review",
    },
    {
        "name": "Priya Deshmukh",
        "phone": "+919812345673",
        "company": "Deshmukh Motors",
        "industry": "Automobile",
        "requirement": "Showroom lead tracking for test drive bookings",
        "budget": "",
        "timeline": "",
        "decision_maker": None,
        "interest": "low",
        "sentiment": "hesitant",
        "objection": "Happy with spreadsheets for now",
        "next_action": "Nurture with product newsletter",
    },
    {
        "name": "Vikram Rao",
        "phone": "+919812345674",
        "company": "Rao Financial Services",
        "industry": "Financial Services",
        "requirement": "Loan application pipeline with document checklists",
        "budget": "Rs 1,20,000 / year",
        "timeline": "immediate",
        "decision_maker": True,
        "interest": "high",
        "sentiment": "positive",
        "objection": "",
        "next_action": "Contract review with legal team",
    },
    {
        "name": "Sneha Kulkarni",
        "phone": "+919812345675",
        "company": "Kulkarni Healthcare",
        "industry": "Healthcare",
        "requirement": "Appointment reminders for three clinic branches",
        "budget": "Rs 35,000 / year",
        "timeline": "within 2 weeks",
        "decision_maker": False,
        "interest": "medium",
        "sentiment": "neutral",
        "objection": "Wants clinic manager approval",
        "next_action": "Schedule call with clinic manager",
    },
]


def _lead_transcript(lead: dict) -> list[tuple[str, str]]:
    """Build a short, believable transcript for a seeded lead."""
    return [
        ("assistant", f"Hi, thanks for calling ApexCRM! May I know your name?"),
        ("user", f"Hi, this is {lead['name']} from {lead['company']}."),
        ("assistant", "Great to meet you. What would you like the CRM to help you with?"),
        ("user", lead["requirement"]),
        ("assistant", "Understood. Do you have a budget range in mind for this?"),
        ("user", lead["budget"] or "We are still working that out."),
        ("assistant", "And when would you like this in place?"),
        ("user", lead["timeline"] or "No fixed date yet."),
        ("assistant", "That helps. Would a short demo this week be useful?"),
        ("user", "Yes, that works." if lead["interest"] == "high" else "Maybe later, send me details first."),
    ]


def seed_demo_data(db: Session, tenant_id: int) -> None:
    """Insert demo leads, calls, transcripts, summaries and appointments once."""
    existing = db.scalar(select(Lead.id).where(Lead.tenant_id == tenant_id).limit(1))
    if existing is not None:
        return

    now = datetime.now(timezone.utc)

    for index, data in enumerate(DEMO_LEADS):
        lead = Lead(
            tenant_id=tenant_id,
            name=data["name"],
            phone=data["phone"],
            company=data["company"],
            industry=data["industry"],
            requirement=data["requirement"],
            budget=data["budget"] or None,
            timeline=data["timeline"] or None,
            decision_maker=data["decision_maker"],
            interest=data["interest"],
        )
        lead.score = calculate_lead_score(
            {
                "requirement": data["requirement"],
                "budget": data["budget"],
                "timeline": data["timeline"],
                "decision_maker": data["decision_maker"],
                "interest": data["interest"],
            }
        )
        lead.category = classify_lead(lead.score)
        db.add(lead)
        db.commit()
        db.refresh(lead)

        started = now - timedelta(days=13 - index * 2, hours=index)
        duration = 180 + index * 45
        call = Call(
            tenant_id=tenant_id,
            lead_id=lead.id,
            status="ended",
            language="en",
            started_at=started,
            ended_at=started + timedelta(seconds=duration),
            duration=duration,
            sentiment=data["sentiment"],
            summary=(
                f"{data['name']} from {data['company']} discussed {data['requirement'].lower()}. "
                f"Next step: {data['next_action']}."
            ),
        )
        db.add(call)
        db.commit()
        db.refresh(call)

        for role, text in _lead_transcript(data):
            db.add(Message(call_id=call.id, role=role, text=text, created_at=started))

        db.add(
            CallSummary(
                call_id=call.id,
                requirement=data["requirement"],
                objection=data["objection"] or None,
                next_action=data["next_action"],
                insights={
                    "customer": data["name"],
                    "requirement": data["requirement"],
                    "budget": data["budget"],
                    "timeline": data["timeline"],
                    "sentiment": data["sentiment"],
                    "interest": data["interest"],
                    "objection": data["objection"],
                    "next_action": data["next_action"],
                    "summary": f"{data['name']} is a {lead.category} lead for {data['company']}.",
                    "tool_actions": [
                        {"tool": "update_lead", "result": {"updated": True, "score": lead.score}},
                    ],
                },
            )
        )

        if data["interest"] == "high":
            slot = (now + timedelta(days=2 + index)).replace(
                hour=10 + index, minute=0, second=0, microsecond=0
            )
            db.add(
                Appointment(
                    tenant_id=tenant_id,
                    lead_id=lead.id,
                    starts_at=slot,
                    status="booked",
                )
            )
        db.commit()

    logger.info("Seeded %d demo leads with calls and summaries", len(DEMO_LEADS))
