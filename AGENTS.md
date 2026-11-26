# Working agreement — Autonomous AI Sales Voice Agent

Read this before touching any file. It exists because earlier sessions added breadth
before the core voice loop worked. Do not repeat that.

## What we are building

A browser voice sales agent: STT → LLM (tool calling) → TTS, with lead qualification,
RAG over `knowledge_base/`, appointment booking, post-call summary, and a CRM dashboard.
Stack is fixed: FastAPI, React + Vite + Tailwind, Deepgram, OpenAI, ElevenLabs,
SQLite/PostgreSQL. No substitutions.

## Non-negotiables

1. **One phase at a time.** Before coding: state the goal, the files you will touch and
   why. After coding: give the run command, one test to perform, the expected result.
2. **Business logic is plain Python**, never in a prompt: lead scoring, classification,
   availability, booking validation, tenant filtering.
3. **The LLM only requests tools.** The backend validates arguments and writes rows. No
   model output ever reaches the database unvalidated.
4. **One LLM call per turn.** Lead capture rides the same call as the reply via
   `update_lead`. No second extraction pass per turn.
5. **Secrets only in `.env`.** Never log keys, full phone numbers or raw audio.
6. **Finish before extending.** A failing acceptance test blocks all new features.

## File budget (this is the whole repo)

```
backend/config.py      settings only
backend/database.py    engine, session, 6 models (tenants, leads, calls, messages,
                       appointments, call_summaries) + kb_chunks if RAG uses the DB
backend/crm.py         scoring, classification, lead/call queries, analytics
backend/booking.py     availability, book, reschedule
backend/rag.py         ingest, embed, search, threshold
backend/agent.py       system prompt, tool schemas, dispatch, summary
backend/voice.py       transcribe_stream, synthesize_stream, sentence buffer
backend/main.py        app, REST routes, exception handlers
backend/call_ws.py     /ws/call handler: state machine, barge-in, provider wiring
frontend/src/pages/    LiveCall, Leads, Calls, Appointments, Insights, KnowledgeBase, Settings
frontend/src/components/  Layout, VoiceOrb, ScoreGauge, and only what pages reuse twice
```

**Hard caps:** 300 lines per file, 3 files added per phase maximum. If a file passes 300
lines it has two responsibilities — split it once, at a real seam, and say which.

**Do not create** `services/`, `utils/`, `helpers/`, `models/`, `repositories/`,
`core/`, `api/v1/`, `types.py`, `constants.py`, an `__init__.py` package tree, or a
README per folder. There are no layers here, only four concerns: routes, data, AI,
business rules.

## Forbidden until the phase that needs them

| Not before | Thing |
| --- | --- |
| Core voice loop works | Twilio, telephony webhooks, outbound calling |
| Demo data flows from a real call | seed fixtures that fake transcripts or scores |
| Real users exist | JWT issuance, login screens, RBAC, password hashing |
| ~50 concurrent calls | Redis, Celery, queues, workers |
| Explicit request | LangChain, LangGraph, CrewAI, vector-DB service, Kubernetes |

Adding a dependency requires: one sentence on why the standard library or an existing
dependency cannot do it, and the line it adds to `requirements.txt`.

## Code rules

- Readable in one pass. Named for the business, not the pattern
  (`book_appointment`, not `AppointmentService.create`).
- Functions do one thing and stay under ~40 lines. Type hints on public functions.
- Prefer functions over classes. A class only for something that genuinely holds state.
- Explicit error handling at the provider boundary: timeout, bad input, dropped socket,
  provider 5xx → a specific message the UI can render. Never a bare `except:`.
- Log events, not payloads: `booked appointment id=12 tenant=1` — never the transcript.
- No dead code, no commented-out blocks, no "for later" abstractions, no duplicated
  threshold numbers (they live in `config.py`).
- Every incoming request validated with Pydantic; every query filtered by `tenant_id`.
- Tests cover pure logic (scoring, booking, parsing) with no network. Provider calls are
  monkeypatched at the `voice.py` / `agent.py` boundary.

## Definition of done per phase

1. The acceptance test in the build spec passes, by hand.
2. `pytest` is green and no new warnings.
3. The app starts from a clean shell with `uvicorn backend.main:app --reload`.
4. One commit, message says what changed and why.

## Answer format

Goal and files → complete code with exact paths → run command → manual test → expected
result → one line on what is deliberately not done yet. Do not rewrite working files
wholesale for a small change; edit the specific function.
