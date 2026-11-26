"""AI sales agent logic: system prompt, LLM tool calling, and call summarisation."""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from sqlalchemy.orm import Session

from backend.booking import book_appointment, check_availability, reschedule_appointment
from backend.config import settings
from backend.crm import LEAD_FIELDS, merge_lead_data, upsert_lead
from backend.rag import search_knowledge_base

logger = logging.getLogger(__name__)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_lead",
            "description": "Save newly learned customer fields to the CRM lead record.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "company": {"type": "string"},
                    "industry": {"type": "string"},
                    "requirement": {"type": "string"},
                    "budget": {"type": "string"},
                    "timeline": {"type": "string"},
                    "decision_maker": {"type": "boolean"},
                    "interest": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search the company knowledge base for verified product features, pricing, FAQ, or policies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The customer's question or topic."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "List free 1-hour appointment slots for a given date (YYYY-MM-DD).",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format."},
                },
                "required": ["date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book or reschedule a demo appointment at an ISO-8601 UTC date/time (e.g. 2026-11-27T15:00:00Z).",
            "parameters": {
                "type": "object",
                "properties": {
                    "starts_at": {"type": "string", "description": "ISO-8601 UTC date/time."},
                    "reschedule": {"type": "boolean", "description": "Set true to reschedule an existing booking."},
                },
                "required": ["starts_at"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "Close the call politely when the conversation is complete or the customer says goodbye.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
]


class AgentError(Exception):
    """Raised when the LLM provider cannot complete a turn."""


def _provider_error_detail(exc: APIStatusError, limit: int = 300) -> str:
    """Pull the provider's error message out of an APIStatusError for logging."""
    try:
        body = exc.response.json()
    except Exception:
        return str(exc)[:limit]
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else error
    return str(message or body)[:limit]


def _status_message(status_code: int, detail: str) -> str:
    """Turn a provider HTTP error into a message a sales operator can act on."""
    if status_code in (401, 403):
        return "The AI service rejected the API key. Check LLM_API_KEY in .env."
    if status_code == 429:
        return "The AI service quota is exhausted. Check the plan and billing for LLM_API_KEY."
    return f"The AI service rejected the request (HTTP {status_code}): {detail}"


# Provider-specific markers that must be echoed back with a replayed tool call.
# Gemini attaches a `thought_signature` to every function call it returns and
# rejects the follow-up request with HTTP 400 when the signature is missing.
# OpenAI never sends these fields, so the helpers below are no-ops there.
SIGNATURE_MARKER = "thought_signature"
SIGNATURE_PLACEHOLDER = "skip_thought_signature_validator"


def _extra_fields(model: Any, known: set[str]) -> dict[str, Any]:
    """Collect provider-specific fields the SDK kept on a response object."""
    extra = getattr(model, "model_extra", None) or {}
    return {key: value for key, value in extra.items() if key not in known and value is not None}


def _tool_call_history(tool_call: Any) -> dict[str, Any]:
    """Rebuild one tool call for history, keeping any provider metadata."""
    function: dict[str, Any] = {
        "name": tool_call.function.name,
        "arguments": tool_call.function.arguments,
    }
    function.update(_extra_fields(tool_call.function, {"name", "arguments"}))

    call: dict[str, Any] = {"id": tool_call.id, "type": "function", "function": function}
    call.update(_extra_fields(tool_call, {"id", "type", "function"}))
    return call


def _assistant_history_message(message: Any) -> dict[str, Any]:
    """Rebuild an assistant message so replayed tool calls keep their signatures."""
    payload: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
    payload.update(_extra_fields(message, {"role", "content", "tool_calls"}))
    if message.tool_calls:
        payload["tool_calls"] = [_tool_call_history(call) for call in message.tool_calls]
    return payload


def _with_placeholder_signatures(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Fill in missing thought signatures so an unsigned history can still be replayed.

    Returns None when the conversation holds no tool calls, because then the
    provider cannot be complaining about a signature in the first place.
    """
    has_tool_calls = any(message.get("tool_calls") for message in messages)
    if not has_tool_calls:
        return None

    patched: list[dict[str, Any]] = []
    for message in messages:
        calls = message.get("tool_calls")
        if not calls:
            patched.append(message)
            continue

        fixed_calls = []
        for call in calls:
            extra = dict(call.get("extra_content") or {})
            google = dict(extra.get("google") or {})
            if not google.get(SIGNATURE_MARKER):
                google[SIGNATURE_MARKER] = SIGNATURE_PLACEHOLDER
                extra["google"] = google
                call = {**call, "extra_content": extra}
            fixed_calls.append(call)
        patched.append({**message, "tool_calls": fixed_calls})
    return patched


def _needs_signature_retry(exc: APIStatusError) -> bool:
    """True when the provider rejected a replayed tool call for a missing signature."""
    return exc.status_code == 400 and SIGNATURE_MARKER in _provider_error_detail(exc)


def _create_completion(client: OpenAI, messages: list[dict[str, Any]], tools: list | None = None):
    """Send one chat completion, retrying once if a tool-call signature was missing."""
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 220,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        return client.chat.completions.create(**payload)
    except APIStatusError as exc:
        if not _needs_signature_retry(exc):
            raise
        patched = _with_placeholder_signatures(messages)
        if patched is None:
            raise
        logger.info("Retrying LLM turn with placeholder thought signatures")
        return client.chat.completions.create(**{**payload, "messages": patched})


def _get_client() -> OpenAI:
    if not settings.llm_api_key or settings.llm_api_key == "your_llm_api_key_here":
        raise AgentError("LLM_API_KEY is not configured in .env")
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=30.0,
    )


def build_system_prompt(
    tenant_name: str,
    agent_config: dict[str, Any] | None = None,
    lead_data: dict[str, Any] | None = None,
    language: str | None = None,
) -> str:
    """Build the sales representative system prompt for a tenant with known lead_data."""
    config = agent_config or {}
    agent_name = config.get("agent_name", "Aria")
    lang = (language or config.get("language") or settings.default_language).lower()
    lang_rule = (
        "Respond naturally in Hindi (using clear conversational Hindi) while keeping all qualification, RAG, and booking rules. "
        if lang.startswith("hi")
        else "Reply in the customer's language (English or Hindi if they switch) while keeping all qualification, RAG, and booking rules. "
    )
    known_json = json.dumps(lead_data or {}, ensure_ascii=False)
    today_str = datetime.now(timezone.utc).date().isoformat()
    return (
        f"You are {agent_name}, a warm, professional sales representative for {tenant_name}. "
        f"Today's UTC date is {today_str}. {lang_rule}"
        "Keep every reply short and conversational (one or two sentences), and ask only one question at a time. "
        "Your goal is to understand the customer's business, product requirement, budget, timeline, and whether they are a decision-maker. "
        f"Known lead_data (do NOT ask for fields already present here): {known_json}. "
        "Always call search_knowledge_base before answering questions about pricing, features, FAQ, or policies. "
        "Never invent prices, product features, or company policies; if search_knowledge_base returns found=false, "
        "admit you do not have that information and offer to connect them with a human specialist. "
        "When the customer shows clear interest, offer to book a demo meeting using check_availability and book_appointment. "
        "If the customer is frustrated, rude, or asks for a human, stay calm and politely offer a human handover."
    )


def _execute_tool(
    name: str,
    args: dict[str, Any],
    db: Session | None,
    tenant_id: int | None,
    lead_id: int | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Validate and execute an approved tool request in plain Python."""
    if name == "search_knowledge_base":
        query = str(args.get("query", "")).strip()
        if not query:
            return {"found": False, "error": "Query cannot be empty."}
        res = search_knowledge_base(query)
        if res.get("found"):
            for item in res.get("results", []):
                src = item.get("source")
                if src and src not in state["sources"]:
                    state["sources"].append(src)
        return res

    if name == "update_lead":
        if db is None or tenant_id is None:
            return {"updated": False, "error": "Database session unavailable."}
        filtered = {k: v for k, v in args.items() if k in LEAD_FIELDS and v is not None and v != ""}
        if not filtered:
            return {"updated": False, "error": "No valid lead fields provided."}
        merged = merge_lead_data(state["lead_data"], filtered)
        lead = upsert_lead(db, tenant_id, merged, lead_id=lead_id)
        state["lead_data"] = merged
        return {"updated": True, "score": lead.score, "category": lead.category}

    if name == "check_availability":
        if db is None or tenant_id is None:
            return {"error": "Database session unavailable."}
        date_str = str(args.get("date", "")).strip()
        try:
            slots = check_availability(db, tenant_id, date_str)
            return {"date": date_str, "available_slots": slots}
        except ValueError as exc:
            return {"error": str(exc)}

    if name == "book_appointment":
        if db is None or tenant_id is None or lead_id is None:
            return {"booked": False, "error": "Lead context unavailable."}
        starts_at = str(args.get("starts_at", "")).strip()
        try:
            if args.get("reschedule"):
                res = reschedule_appointment(db, tenant_id, lead_id, starts_at)
            else:
                res = book_appointment(db, tenant_id, lead_id, starts_at)
        except ValueError as exc:
            return {"booked": False, "error": str(exc)}
        if res.get("booked") or res.get("rescheduled"):
            state["appointment"] = res.get("appointment")
        return res

    if name == "end_call":
        state["end_call"] = True
        return {"ended": True, "reason": str(args.get("reason", "completed"))}

    return {"error": f"Unknown tool: {name}"}


MAX_TOOL_STEPS = 3

# Gemini's OpenAI-compatible endpoint sometimes prefixes the content with the
# chunk metadata it was about to stream (`id: "1"`), which must never be spoken.
_META_LINE = re.compile(r"^(?:id|object|created|model)\s*:", re.IGNORECASE)


def _clean_reply(text: str) -> str:
    """Strip leading shim metadata lines from a model reply."""
    lines = text.strip().splitlines()
    while lines and _META_LINE.match(lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def run_agent_turn(
    messages: list[dict[str, str]],
    tenant_name: str,
    agent_config: dict[str, Any] | None = None,
    lead_data: dict[str, Any] | None = None,
    db: Session | None = None,
    tenant_id: int | None = None,
    lead_id: int | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Run one LLM turn with validated tool calling and return reply + turn metadata."""
    client = _get_client()
    system_message = {
        "role": "system",
        "content": build_system_prompt(tenant_name, agent_config, lead_data, language=language),
    }
    convo: list[dict[str, Any]] = [system_message, *messages]
    tool_state: dict[str, Any] = {
        "lead_data": dict(lead_data or {}),
        "sources": [],
        "appointment": None,
        "end_call": False,
        "tool_actions": [],
    }

    for _ in range(MAX_TOOL_STEPS):
        try:
            response = _create_completion(client, convo, TOOLS)
        except APITimeoutError as exc:
            logger.warning("LLM request timed out: %s", type(exc).__name__)
            raise AgentError("The AI service timed out. Please try again.") from exc
        except APIConnectionError as exc:
            logger.warning("LLM connection failed: %s", type(exc).__name__)
            raise AgentError("Unable to reach the AI service.") from exc
        except APIStatusError as exc:
            detail = _provider_error_detail(exc)
            logger.warning("LLM returned status %s: %s", exc.status_code, detail)
            raise AgentError(_status_message(exc.status_code, detail)) from exc

        msg = response.choices[0].message if response.choices else None
        if msg is None:
            raise AgentError("The AI service returned an empty response.")

        if not msg.tool_calls:
            content = _clean_reply(msg.content or "")
            if not content:
                raise AgentError("The AI service returned an empty response.")
            return {
                "reply": content,
                "sources": tool_state["sources"],
                "appointment": tool_state["appointment"],
                "end_call": tool_state["end_call"],
                "tool_actions": tool_state["tool_actions"],
            }

        convo.append(_assistant_history_message(msg))
        for tc in msg.tool_calls:
            try:
                parsed_args = json.loads(tc.function.arguments or "{}")
                if not isinstance(parsed_args, dict):
                    parsed_args = {}
            except json.JSONDecodeError:
                parsed_args = {}
            result = _execute_tool(tc.function.name, parsed_args, db, tenant_id, lead_id, tool_state)
            tool_state["tool_actions"].append(
                {
                    "tool": tc.function.name,
                    "args": parsed_args,
                    "result": result,
                }
            )
            convo.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    raise AgentError("The AI agent exceeded the maximum tool-call steps for one turn.")


ALLOWED_SENTIMENTS = {"positive", "neutral", "negative", "frustrated", "interested", "hesitant"}


def generate_call_summary(
    messages: list[dict[str, str]],
    lead_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a structured JSON call summary and sentiment on call end."""
    fallback = {
        "customer": (lead_data or {}).get("name") or "Unknown",
        "requirement": (lead_data or {}).get("requirement") or "",
        "budget": (lead_data or {}).get("budget") or "",
        "timeline": (lead_data or {}).get("timeline") or "",
        "sentiment": "neutral",
        "interest": (lead_data or {}).get("interest") or "medium",
        "objection": "",
        "next_action": "Follow up with customer",
        "summary": "Call completed.",
    }
    if not messages:
        return fallback

    try:
        client = _get_client()
    except AgentError:
        return fallback

    prompt = (
        "Summarize this sales call as a single JSON object with keys: "
        "customer (string), requirement (string), budget (string), timeline (string), "
        "sentiment (one of: positive, neutral, negative, frustrated, interested, hesitant), "
        "interest (one of: high, medium, low), objection (string, or empty if none), "
        "next_action (string), summary (1-2 sentence recap). "
        f"Known lead_data: {json.dumps(lead_data or {}, ensure_ascii=False)}. "
        "Return valid JSON only."
    )
    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "system", "content": prompt}, *messages[-20:]],
            temperature=0.0,
            max_tokens=300,
        )
    except (APITimeoutError, APIConnectionError, APIStatusError) as exc:
        logger.warning("Call summary LLM call failed (%s)", type(exc).__name__)
        return fallback

    raw = (response.choices[0].message.content if response.choices else "") or ""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Call summary returned non-JSON output")
        return fallback

    if not isinstance(parsed, dict):
        return fallback

    sentiment = str(parsed.get("sentiment", "neutral")).strip().lower()
    if sentiment not in ALLOWED_SENTIMENTS:
        sentiment = "neutral"

    interest = str(parsed.get("interest", "medium")).strip().lower()
    if interest not in {"high", "medium", "low"}:
        interest = "medium"

    return {
        "customer": str(parsed.get("customer") or fallback["customer"]).strip(),
        "requirement": str(parsed.get("requirement") or fallback["requirement"]).strip(),
        "budget": str(parsed.get("budget") or fallback["budget"]).strip(),
        "timeline": str(parsed.get("timeline") or fallback["timeline"]).strip(),
        "sentiment": sentiment,
        "interest": interest,
        "objection": str(parsed.get("objection") or "").strip(),
        "next_action": str(parsed.get("next_action") or fallback["next_action"]).strip(),
        "summary": str(parsed.get("summary") or fallback["summary"]).strip(),
    }


def answer_kb_question(query: str) -> dict[str, Any]:
    """Retrieve KB chunks and generate a strictly grounded answer for the KB test box."""
    rag_res = search_knowledge_base(query, top_k=3)
    if not rag_res.get("found"):
        return {
            "found": False,
            "chunks": [],
            "answer": "I could not find that in the company knowledge base. I can connect you with a human specialist.",
        }

    chunks = rag_res["results"]
    context = "\n\n".join(f"[{c['source']}]\n{c['text']}" for c in chunks)
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer the user's question strictly using the provided company documents. "
                        "If the answer is not in the context, say you do not know. Keep it concise (2-3 sentences)."
                    ),
                },
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        answer = (response.choices[0].message.content or "").strip() if response.choices else ""
    except (AgentError, APITimeoutError, APIConnectionError, APIStatusError):
        answer = chunks[0]["text"]

    return {"found": True, "chunks": chunks, "answer": answer or chunks[0]["text"]}
