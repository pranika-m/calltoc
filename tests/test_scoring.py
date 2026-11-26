"""Unit tests for pure-Python lead scoring and classification."""

from backend.crm import calculate_lead_score, classify_lead, merge_lead_data


def test_calculate_lead_score_full_hot_lead():
    lead = {
        "requirement": "Need a 20-seat CRM for real estate sales",
        "budget": "$1000/month",
        "timeline": "Within 2 weeks",
        "decision_maker": True,
        "interest": "high",
    }
    assert calculate_lead_score(lead) == 100
    assert classify_lead(100) == "hot"


def test_calculate_lead_score_partial_warm_lead():
    lead = {
        "requirement": "Looking for pipeline tracking",
        "budget": "$400/month",
        "timeline": "In 6 months",
        "decision_maker": False,
        "interest": "medium",
    }
    assert calculate_lead_score(lead) == 40
    assert classify_lead(40) == "warm"


def test_calculate_lead_score_cold_lead():
    lead = {"name": "Sam", "interest": "low"}
    assert calculate_lead_score(lead) == 0
    assert classify_lead(0) == "cold"


def test_classify_lead_boundaries():
    assert classify_lead(70) == "hot"
    assert classify_lead(69) == "warm"
    assert classify_lead(40) == "warm"
    assert classify_lead(39) == "cold"


def test_merge_lead_data_preserves_existing_and_updates_new():
    existing = {"name": "Asha", "company": "Acme Realty"}
    extracted = {"name": None, "budget": "$500/mo", "timeline": "30 days"}
    merged = merge_lead_data(existing, extracted)
    assert merged == {
        "name": "Asha",
        "company": "Acme Realty",
        "budget": "$500/mo",
        "timeline": "30 days",
    }
