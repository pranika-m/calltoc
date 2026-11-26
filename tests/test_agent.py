"""Unit and integration tests for AI agent tool dispatch and summary generation."""

import json
from unittest.mock import MagicMock, patch

import httpx
from openai import APIStatusError
from openai.types.chat import ChatCompletion
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.agent as agent_mod
from backend.database import Base, Lead, Tenant


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    tenant = Tenant(name="ApexCRM", agent_config={"agent_name": "Aria"})
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    lead = Lead(tenant_id=tenant.id, name="Asha")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return db, tenant, lead


def test_run_agent_turn_executes_rag_tool_and_returns_sources():
    db, tenant, lead = _make_db()
    tool_call = MagicMock()
    tool_call.id = "call_rag_1"
    tool_call.function.name = "search_knowledge_base"
    tool_call.function.arguments = json.dumps({"query": "Growth Plan pricing"})

    first_msg = MagicMock(content=None, tool_calls=[tool_call])
    second_msg = MagicMock(content="The Growth Plan is $59 per user per month.", tool_calls=None)

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=first_msg)]),
        MagicMock(choices=[MagicMock(message=second_msg)]),
    ]

    fake_rag = {
        "found": True,
        "results": [{"source": "pricing.md", "text": "Growth Plan — $59 per user / month", "similarity": 0.9}],
    }
    with patch.object(agent_mod, "_get_client", return_value=mock_client), \
         patch.object(agent_mod, "search_knowledge_base", return_value=fake_rag):
        res = agent_mod.run_agent_turn(
            [{"role": "user", "content": "How much is Growth?"}],
            tenant_name=tenant.name,
            agent_config=tenant.agent_config,
            lead_data={"name": "Asha"},
            db=db,
            tenant_id=tenant.id,
            lead_id=lead.id,
        )

    assert "$59" in res["reply"]
    assert res["sources"] == ["pricing.md"]
    db.close()


def test_generate_call_summary_normalizes_invalid_sentiment():
    bad_summary = MagicMock(
        content=json.dumps(
            {
                "customer": "Asha",
                "requirement": "CRM",
                "budget": "$500",
                "timeline": "2 weeks",
                "sentiment": "ecstatic",  # invalid -> should normalize to neutral
                "interest": "high",
                "objection": "",
                "next_action": "Send quote",
                "summary": "Good call.",
            }
        )
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=bad_summary)])

    with patch.object(agent_mod, "_get_client", return_value=mock_client):
        result = agent_mod.generate_call_summary([{"role": "user", "content": "Hi"}], {"name": "Asha"})

    assert result["sentiment"] == "neutral"
    assert result["interest"] == "high"
    assert result["next_action"] == "Send quote"


# --- Tool-result follow-up regression tests -------------------------------
#
# Gemini returns a `thought_signature` with every function call and rejects the
# follow-up request when it is not echoed back. These tests pin the behaviour
# without needing live provider quota.


def _completion(payload: dict) -> ChatCompletion:
    """Parse a raw provider payload through the real SDK models."""
    return ChatCompletion.model_validate(payload)


def _tool_call_completion(signature: str | None = None) -> ChatCompletion:
    tool_call: dict = {
        "id": "call_rag_1",
        "type": "function",
        "function": {"name": "search_knowledge_base", "arguments": json.dumps({"query": "Growth pricing"})},
    }
    if signature:
        tool_call["extra_content"] = {"google": {"thought_signature": signature}}
    return _completion(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                }
            ],
        }
    )


def _text_completion(text: str) -> ChatCompletion:
    return _completion(
        {
            "id": "chatcmpl-2",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
        }
    )


def _signature_error() -> APIStatusError:
    """Build the exact 400 Gemini raises when a signature is missing."""
    body = {
        "error": {
            "code": 400,
            "message": "Function call is missing a thought_signature in functionCall parts.",
            "status": "INVALID_ARGUMENT",
        }
    }
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(400, json=body, request=request)
    return APIStatusError("missing thought_signature", response=response, body=body)


def test_tool_result_followup_echoes_thought_signature():
    """The signature the provider returned must be present on the replay."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        _tool_call_completion(signature="SIG-abc123"),
        _text_completion("The Growth plan is $59 per user per month."),
    ]

    with patch.object(agent_mod, "_get_client", return_value=mock_client), \
         patch.object(agent_mod, "search_knowledge_base", return_value={"found": True, "results": []}):
        agent_mod.run_agent_turn(
            [{"role": "user", "content": "How much is Growth?"}],
            tenant_name="ApexCRM",
        )

    replay_messages = mock_client.chat.completions.create.call_args_list[1].kwargs["messages"]
    replayed_calls = [m for m in replay_messages if m.get("tool_calls")]
    assert len(replayed_calls) == 1
    assert replayed_calls[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "SIG-abc123"


def test_tool_result_followup_retries_with_placeholder_signature():
    """An unsigned replay is retried once instead of failing the whole call."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        _tool_call_completion(signature=None),
        _signature_error(),
        _text_completion("The Growth plan is $59 per user per month."),
    ]

    with patch.object(agent_mod, "_get_client", return_value=mock_client), \
         patch.object(agent_mod, "search_knowledge_base", return_value={"found": True, "results": []}):
        result = agent_mod.run_agent_turn(
            [{"role": "user", "content": "How much is Growth?"}],
            tenant_name="ApexCRM",
        )

    assert "$59" in result["reply"]
    retry_messages = mock_client.chat.completions.create.call_args_list[2].kwargs["messages"]
    replayed_calls = [m for m in retry_messages if m.get("tool_calls")]
    signature = replayed_calls[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"]
    assert signature == agent_mod.SIGNATURE_PLACEHOLDER


def test_status_message_is_actionable_for_quota_and_auth():
    assert "quota" in agent_mod._status_message(429, "quota exceeded").lower()
    assert "LLM_API_KEY" in agent_mod._status_message(401, "bad key")
    assert "HTTP 500" in agent_mod._status_message(500, "boom")


def test_run_agent_turn_strips_shim_metadata_prefix():
    """The Gemini shim's `id: "1"` prefix must never reach the transcript or TTS."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _text_completion(
        'id: "1"\nOur Growth Plan is $59 per user per month.'
    )

    with patch.object(agent_mod, "_get_client", return_value=mock_client):
        result = agent_mod.run_agent_turn(
            [{"role": "user", "content": "How much is Growth?"}],
            tenant_name="ApexCRM",
        )

    assert result["reply"] == "Our Growth Plan is $59 per user per month."

