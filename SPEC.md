# Autonomous AI Sales Voice Agent – Master Build Spec

## 0. How to use this document

- **For you:** read Sections 1–4 once, then work through Section 7 phase by phase.
- **For your IDE agent (Cursor, Copilot, Claude Code, etc.):** paste Section 1 and Section 2 as the standing instructions (or save them as `AGENTS.md` / `.cursorrules`), then give the agent **one phase at a time** from Section 7. Never ask for the whole app in one go.
- **For Round 4:** Section 13 lists what you must be able to explain.

---

## 1. Master agent prompt (paste this first)

> You are a senior software engineer, software architect and UI/UX designer. Help me build an **Autonomous AI Sales Voice Agent**: a working MVP that talks to a customer by voice, qualifies the lead, answers questions from a company knowledge base (RAG), books an appointment, and saves everything to a CRM with a summary, shown in a polished dashboard.
>
> Rules:
>
> 1. Work on **one phase at a time** from the build spec. Finish and test it before the next. Do not generate the whole app at once.
> 2. Before each phase: state the goal, the files you will create or change, and why.
> 3. Give complete, working code with the exact file path. Do not rewrite working files for small changes.
> 4. After each phase: give the run command, a test I can perform, and the expected result.
> 5. Follow the code standards in Section 2 strictly. No overengineering, no unnecessary files, folders, frameworks or dependencies.
> 6. Business logic (lead scoring, booking validation) lives in plain Python, never inside the LLM.
> 7. The LLM may only *request* tools. The backend validates and executes them.
> 8. Never hardcode secrets. Use `.env`.
> 9. Follow the UI/UX direction in Section 8 for every screen.
> 10. If something is unclear, make the simplest reasonable assumption, state it in one line, and continue.

---

## 2. Code standards (mandatory)

**Simplicity**

- Plain, readable code that a new engineer understands in one pass.
- Meaningful names. Short functions with one responsibility. Type hints where useful.
- Prefer simple functions over classes and design patterns. Prefer the Python standard library over new packages.

**Structure**

- Create a file only when a real feature needs it. Keep related code together.
- No duplicate code, dead code, unused files or empty "professional-looking" folders.
- Separate four concerns only: API routes, database access, AI logic, business logic.

**Reliability**

- Handle exceptions explicitly (provider timeouts, bad input, dropped sockets).
- Validate every incoming request with Pydantic.
- Log meaningful events; never log secrets or full phone numbers.
- Keep AI providers behind thin functions so one can be swapped without a rewrite.

**Dependencies**

- Install only what is used. Keep `requirements.txt` and `package.json` minimal.
- One AI approach only: direct OpenAI SDK with tool calling. LangChain and LangGraph are *optional later*, not part of the MVP.

**Process**

- Test each feature before extending it. Commit working increments to Git with clear messages.
- Understand all AI-generated code before accepting it. Never paste API keys into prompts or the frontend.

**Good example (this is the target style):**

```python
def classify_lead(score: int) -> str:
    if score >= HOT_THRESHOLD:
        return "hot"
    if score >= WARM_THRESHOLD:
        return "warm"
    return "cold"
```

---

## 3. Project goal and scope

**Business problem.** Sales teams lose leads because calling, qualifying, explaining products, scheduling and CRM data entry are manual and slow.

**Solution.** A voice agent that handles those steps in a natural conversation and hands the sales team a qualified lead with a summary and a booked meeting.

**Demo scenario.** A company sells CRM software. A prospect calls to enquire. The agent greets them, learns their business, qualifies them, answers product questions from company documents, offers and books a demo, and the CRM updates itself when the call ends.

The agent **assists** sales staff. Sensitive or complex cases are handed to a human.

### Feature priorities

| Priority | Features |
| --- | --- |
| **P1 – must work** | Browser voice conversation (STT + LLM + TTS), conversation memory, lead extraction, lead scoring, PostgreSQL, appointment booking, call summary, CRM dashboard, one full end-to-end workflow |
| **P2 – strong additions** | RAG, sentiment analysis, function calling, Hindi, CRM analytics, Twilio telephony |
| **P3 – design only (explain, don't build)** | Multi-tenancy at scale, human handoff, Redis and workers, distributed voice workers, load testing, production cloud |

Finish P1 properly, then add P2 in the order listed. Explain P3 through the architecture and scalability sections.

---

## 4. Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.11+, FastAPI | REST plus WebSockets, async, simple |
| Frontend | React with Vite, Tailwind CSS | Fast to build, easy to style |
| STT | Deepgram streaming | Interim results and endpointing |
| LLM | OpenAI API (model name in `.env`) | Tool calling and structured outputs |
| TTS | ElevenLabs streaming | Natural voice, multilingual |
| Database | PostgreSQL via SQLAlchemy or SQLModel | Leads, calls, messages, appointments |
| Vector store | ChromaDB (or pgvector to avoid a second service) | RAG retrieval |
| Realtime | WebSocket | Continuous audio both ways |
| Telephony | Twilio Media Streams (phase 2) | Real phone calls |
| Packaging | Docker Compose | One-command local run |

Do **not** start with Twilio, LangGraph, multiple agents, Redis or Kubernetes. Browser voice first, then telephony.

---

## 5. Architecture

```
Customer (browser mic / phone)
        │  audio over WebSocket (later: Twilio Media Streams)
        ▼
FastAPI backend ── Voice layer: Deepgram STT  ⇄  ElevenLabs TTS
        │
        ▼
Agent orchestrator (plain Python)
   ├─ conversation state + extracted lead data (in memory per call)
   ├─ OpenAI LLM with tool calling
   ├─ RAG search (ChromaDB)
   ├─ lead scoring (pure Python rules)
   └─ booking logic (pure Python + DB)
        │
        ▼
PostgreSQL ── tenants, leads, calls, messages, appointments, summaries
        ▲
        │  REST + live status over WebSocket
React CRM dashboard
```

**Core principle:** the LLM never writes to the database. It requests an approved tool (for example `book_appointment`); the backend validates the date and availability, saves it, and returns the result; the LLM then confirms to the customer.

**Turn loop for every utterance:**

1. Deepgram returns a final transcript.
2. Orchestrator adds it to history and calls the LLM with the system prompt, history, current `lead_data` and any tool results.
3. If the LLM requests a tool, the backend validates and runs it, then returns the result to the LLM.
4. The reply text streams to ElevenLabs and audio streams back to the browser.
5. After the turn, extracted lead fields update `lead_data` and the score is recalculated.

**Call states:** `idle → listening → processing → speaking → ended` (plus `error`). Interruption (barge-in) moves `speaking → listening` and stops playback.

---

## 6. Project structure

Start with this and add files only when needed:

```
ai-sales-agent/
├── backend/
│   ├── main.py          # FastAPI app, REST routes, WebSocket endpoint
│   ├── config.py        # settings from .env
│   ├── database.py      # engine, session, table models
│   ├── agent.py         # system prompt, LLM call, tool dispatch, extraction, summary
│   ├── voice.py         # Deepgram and ElevenLabs helpers
│   ├── rag.py           # ingest and search knowledge base
│   ├── crm.py           # lead scoring, classification, lead and call queries, analytics
│   ├── booking.py       # availability check, create/reschedule appointment
│   └── requirements.txt
├── frontend/            # Vite + React + Tailwind (src/pages, src/components)
├── knowledge_base/      # company_faq.md, pricing.md, features.md, policies.md
├── tests/               # test_scoring.py, test_booking.py, test_agent.py, test_api.py
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
└── README.md
```

### Database tables

Every table except `tenants` carries `tenant_id`, and every query filters by it on the backend.

| Table | Key fields |
| --- | --- |
| `tenants` | id, name, agent\_config |
| `leads` | id, tenant\_id, name, phone, company, industry, requirement, budget, timeline, decision\_maker, interest, score, category |
| `calls` | id, tenant\_id, lead\_id, status, language, started\_at, ended\_at, duration, sentiment, summary |
| `messages` | id, call\_id, role, text, created\_at |
| `appointments` | id, tenant\_id, lead\_id, starts\_at, status, UNIQUE(tenant\_id, starts\_at) |
| `call_summaries` | id, call\_id, requirement, objection, next\_action, insights (JSON) |

The unique constraint on `appointments` is what prevents double bookings, so the database enforces it, not just the code.

### Lead scoring (configurable, pure Python in `crm.py`)

| Condition | Points |
| --- | --- |
| Clear product requirement | 20 |
| Budget confirmed | 20 |
| Purchase within 30 days | 25 |
| Decision-maker | 20 |
| High interest | 15 |

Hot ≥ 70, Warm 40–69, Cold < 40. Keep thresholds in config.

### Agent tools (validated by the backend)

| Tool | Purpose |
| --- | --- |
| `update_lead` | Save extracted fields |
| `search_knowledge_base` | RAG lookup |
| `check_availability` | List free slots for a date |
| `book_appointment` | Create a booking |
| `end_call` | Close the call and trigger summary |

### System prompt rules

Professional, warm sales representative. Short conversational replies (one or two sentences, one question at a time). Never ask something already in `lead_data`. Never invent prices, features or policies; if the knowledge base has no answer, say so and offer a human follow-up. Offer a meeting when interest is clear. Hand over to a human on request or anger.

---

## 7. Build phases (follow in order)

Each phase has a deliverable and an acceptance test. Do not move on until it passes.

### Phase 1 – Setup

1. Define the demo workflow (Section 3) and the P1 checklist.
2. Install Python 3.11+, Node.js, Git, VS Code, PostgreSQL (or Docker), Postman.
3. Create accounts and keys for OpenAI, Deepgram and ElevenLabs. Twilio later.
4. Create the Git repo, `.gitignore`, `.env.example` and the folder structure above.

**Done when:** repo exists, keys load from `.env`, nothing secret is committed.

### Phase 2 – Backend and database (no AI yet)

1. FastAPI app with `GET /health`, `GET/POST /leads`, `GET /calls`, `POST /appointments`.
2. PostgreSQL connection and the tables above, with a seed of two sample tenants.
3. Pydantic validation and consistent error responses.

**Done when:** every endpoint works in Postman and data persists.

### Phase 3 – Text sales agent

1. In `agent.py`, write the system prompt and an OpenAI call with conversation history.
2. Add `POST /chat` that returns the agent reply.
3. Test scenarios: full details given, partial details, off-topic, rude customer.

**Done when:** the text agent holds a sensible sales conversation without repeating questions.

### Phase 4 – Memory, lead extraction and scoring

1. Keep per-call history plus a structured `lead_data` dict.
2. After each turn, ask the LLM for structured JSON of newly learned fields and merge them into `lead_data`.
3. Inject `lead_data` into every prompt so the agent knows what it already has.
4. Implement `calculate_lead_score` and `classify_lead` in `crm.py` with unit tests.
5. Persist the lead to PostgreSQL.

**Done when:** unit tests pass and a text conversation produces a saved, scored lead.

### Phase 5 – Voice pipeline

1. WebSocket endpoint `/ws/call`.
2. Browser captures mic audio (MediaRecorder or AudioWorklet) and streams it to the backend.
3. Backend streams audio to Deepgram and uses final transcripts with endpointing to detect end of speech.
4. Send the final utterance to the agent, stream the reply to ElevenLabs, and send audio chunks back to the browser.
5. Implement call states, barge-in (stop playback when the customer speaks), duplicate-utterance guard, reconnect handling and clean call termination.

**Done when:** you can have a spoken conversation in the browser, interrupt the agent, and the call ends cleanly.

### Phase 6 – Booking, tools and RAG

1. `booking.py`: parse requested date/time, check availability, create the appointment, reject duplicates, support reschedule.
2. Expose the Section 6 tools to the LLM with JSON schemas; validate arguments before executing.
3. `rag.py`: load `knowledge_base/*.md`, split into chunks (about 300–500 tokens with small overlap), embed, store in ChromaDB, and retrieve the top-k for a question. Add a relevance threshold so weak matches return "not found".
4. Test questions that are in the documents and ones that are not (the agent must admit it does not know).

**Done when:** the agent books a real appointment by voice, rejects a taken slot, and answers product questions without inventing facts.

### Phase 7 – Summary, sentiment and analytics

1. On call end, make one LLM call returning structured JSON: customer, requirement, budget, timeline, sentiment (positive / neutral / negative / frustrated / interested / hesitant), interest, objection, next action.
2. Save to `call_summaries` and update the call and lead.
3. Analytics queries: total calls, hot/warm/cold counts, appointments booked, common requirements and objections, calls per day.

**Done when:** ending a call automatically produces a correct summary and updated metrics.

### Phase 8 – CRM dashboard

Build the screens in Section 8. Use REST for data and a WebSocket for live call status.

**Done when:** a finished call appears in the dashboard with score, sentiment, summary and appointment, with no manual database edits.

### Phase 9 – Telephony and multilingual (extensions)

- Twilio: inbound and outbound calls, TwiML webhook, Media Streams WebSocket bridged to the same agent code, status webhooks, webhook signature verification.
- Hindi: set Deepgram language, use a multilingual ElevenLabs voice, and instruct the LLM to reply in the customer's language while keeping the same qualification logic.

### Phase 10 – Testing, Docker, deployment

1. Run the test matrix (Section 10).
2. Dockerfile for the backend and `docker-compose.yml` with backend, frontend and Postgres (plus Chroma if separate).
3. Deploy: frontend on Vercel or similar, backend on a simple container host (Render, Railway, Fly.io or AWS), managed PostgreSQL, secrets in the host's secret store, HTTPS and secure WebSockets (`wss://`).
4. Test the deployed URL end to end.

---

## 8. UI/UX design direction

The product should feel like a premium, modern sales tool, not a default admin template.

### Design concept: "Conversation Intelligence Studio"

A calm, dark-first interface in which the **voice** is the hero. The call screen feels alive; the CRM feels clear and fast.

### Visual system

- **Theme:** dark by default with a light mode toggle. Near-black navy background, slightly lighter surface cards, soft 1px borders, subtle glass blur on overlays.
- **Accent:** electric indigo to cyan gradient for primary actions and the voice orb.
- **Lead colors:** Hot = coral/red-orange, Warm = amber, Cold = steel blue. Use color *and* an icon or label so meaning never relies on color alone.
- **Sentiment colors:** positive = green, neutral = grey, hesitant = amber, frustrated/negative = red.
- **Typography:** a geometric sans for UI (for example Inter or Plus Jakarta Sans) and a monospace for transcripts and numbers (for example JetBrains Mono). Large, confident headings; generous spacing.
- **Shape:** 12–16px rounded cards, soft shadows, consistent 8px spacing grid.
- **Motion:** short, purposeful (150–250 ms ease-out). Respect `prefers-reduced-motion`.

### Layout

Left icon sidebar (Live Call, Leads, Calls, Appointments, Insights, Knowledge Base, Settings), top bar with tenant switcher, search, theme toggle and user menu. Mobile: sidebar becomes a bottom tab bar.

### Screens

**1. Live Call Console (the signature screen)**

- Center: a large **voice orb** that reacts to state: slow breathing glow when idle, ripples when listening, rotating gradient when processing, waveform pulses when speaking.
- Big state label (Listening, Thinking, Speaking) and a call timer.
- Primary **Start call / End call** button; mute and "interrupt" controls.
- Right panel, live: **transcript bubbles** that stream in with interim text in a lighter shade; below them a **Lead Card** filling in fields in real time (name, company, budget, timeline, decision-maker) with a subtle highlight each time a field is captured.
- A live **score gauge** (0–100) that animates and changes color as the lead heats up, plus a sentiment chip.
- A "Knowledge used" chip appears when RAG answered, showing the source document name.
- A toast and slide-in confirmation card when an appointment is booked.
- Clear error state ("Connection lost, reconnecting…") and a mic-permission prompt.

**2. Leads**

- Table and Kanban toggle. Kanban columns: Hot, Warm, Cold, with draggable cards.
- Columns: name, company, score bar, category badge, sentiment, last call, next action.
- Filters by category, sentiment and date; search; skeleton loaders; helpful empty state.
- Clicking a lead opens a side drawer with profile, timeline, transcripts and appointments.

**3. Call history and detail**

- List with duration, status, sentiment and score.
- Detail view: audio-style timeline with transcript, structured summary card (requirement, budget, timeline, objection, next action), and the tool actions the agent performed.

**4. Appointments**

- Week calendar view plus an upcoming list; status chips (booked, completed, rescheduled, cancelled).

**5. Insights**

- KPI cards: total calls, qualified conversations, hot leads, appointments booked, booking rate.
- Charts: lead distribution donut, calls per day line, top requirements and top objections bars, sentiment breakdown.
- Each card has one short plain-language takeaway.

**6. Knowledge Base**

- Upload or edit the company documents, a "re-index" button, and a **test question box** that shows the retrieved chunks and the answer. This is a strong live-demo and debugging tool.

**7. Settings**

- Agent name, greeting, voice, language, scoring thresholds, business hours.

### UX principles

- Every screen has loading, empty and error states.
- Fully responsive; keyboard-navigable; visible focus rings; WCAG AA contrast; ARIA labels on call controls; live regions for transcript updates.
- Microcopy is friendly and short ("Listening…", "Booked for Tue 3:00 PM").
- Charts: Recharts. Icons: lucide-react. Keep UI libraries minimal; Tailwind plus a few hand-built components is enough.

---

## 9. Security and privacy

- Secrets only in environment variables or a secrets manager; never in code, Git or the frontend.
- HTTPS and `wss://` in deployment; CORS restricted to your frontend origin.
- Authenticate dashboard users (JWT); role-based access (admin, sales rep).
- **Tenant isolation:** every query filters by `tenant_id` on the backend. Test that tenant A cannot read tenant B.
- Validate all inputs; verify Twilio webhook signatures; rate-limit public endpoints.
- Avoid storing unnecessary personal data; mask sensitive values in logs.
- Configurable retention and deletion for transcripts and recordings; audit log for important CRM actions.
- Use consenting test users only. For any real outbound calling, account for local calling, recording-consent and privacy rules, and have the agent state that the call is AI-assisted.

---

## 10. Testing

**Unit tests:** lead scoring and classification, booking validation, duplicate booking, tenant filtering.

**Integration tests:** API endpoints, database writes, tool-call dispatch, RAG retrieval, summary JSON shape.

**Scenario matrix**

| Scenario | Expected result |
| --- | --- |
| Customer gives all details | Lead scored and saved |
| Product question in the docs | Correct answer, source shown |
| Pricing not in the docs | Agent says it does not know, offers human follow-up |
| Customer requests a meeting | Appointment created and confirmed |
| Slot already taken | Alternative slots offered |
| Customer changes the time | Booking updated, no duplicate |
| Incomplete details | Agent asks one follow-up at a time |
| Uninterested customer | Lead marked cold, polite close |
| Customer interrupts | Playback stops, agent listens |
| STT, LLM or TTS provider fails | Graceful fallback message, call state recovers |
| Network drop | Reconnect or clean end, partial data saved |
| Frustrated customer or human requested | Handoff flag set, next action recorded |

The full demo must run with **no manual database edits**.

---

## 11. Scalability and operations

**Registered users are not concurrent calls.** 1,00,000 registered users is a data and request-volume problem; concurrent calls are a streaming and provider-limit problem. Do not claim the MVP handles 1,00,000 simultaneous calls.

| Component | Strategy |
| --- | --- |
| Frontend | CDN, static hosting |
| API | Stateless FastAPI instances behind a load balancer, autoscaled |
| Voice | Dedicated WebSocket workers scaled on active-call count, separated from REST traffic |
| Session state | Redis for per-call state so any worker can recover a call |
| Slow work | Queue and workers for summaries, analytics, embeddings |
| Database | Indexes on `tenant_id`, `created_at`, foreign keys; connection pooling (PgBouncer); read replicas for dashboards |
| Vector search | Per-tenant collections or pgvector with an index |
| Audio and transcripts | Object storage such as S3 with lifecycle rules |
| AI providers | Concurrency limits, retries with backoff, per-tenant quotas, fallback provider |
| Observability | Structured logs, metrics (latency per STT/LLM/TTS stage, active calls, error rate), alerts |

Explain how you would load-test (simulated calls ramping up) before stating any capacity number.

**Reducing latency:** stream everything, start TTS on the first sentence, keep prompts short, use a fast model for turns and a stronger model for summaries, cache repeated answers, keep services in one region.

**Reducing cost:** shorter replies, smaller model for simple turns, summarise history, cap call length, skip TTS for filler already cached.

### Cost model (build a spreadsheet)

`Total = STT + LLM + TTS + Telephony + Cloud`, then `Cost per call = Total ÷ calls` and `Cost per minute = Total ÷ call minutes`.

- Build three scenarios: **1,000**, **10,000** and **1,00,000** calls per month, with an assumed average call length.
- Use each provider's **current published pricing** and write down the date.
- Separate fixed costs (hosting, database, monitoring) from usage costs (minutes, tokens, characters).
- Present results as estimates with stated assumptions, not as confirmed production figures.

---

## 12. Commercial feasibility

- **Customers:** real estate, education, insurance, financial services, e-commerce, healthcare appointment centres, auto dealerships, B2B SaaS.
- **Value versus manual calling:** automated first calls, instant lead creation, consistent qualification, 24x7 availability, automatic summaries and follow-ups, analytics across all calls.
- **Success metrics:** reduction in manual calling time, cost per qualified lead, leads processed, appointment booking rate, conversion rate, response time.
- **Pricing ideas:** per-seat plus included minutes, or per-minute usage, or tiered plans with overage. Set prices above cost per call with a healthy margin.
- **Limitations to state honestly:** accents and noise, hallucination risk (mitigated by RAG), compliance requirements, need for human handoff on complex or sensitive calls.
- **Future scope:** Google Calendar sync, WhatsApp follow-ups, outbound campaigns, more languages, advanced multi-agent workflows, live human takeover.

---

## 13. Round 3 and Round 4 readiness

### Final demo script (about 5 minutes)

1. Open the Live Call Console and start a call.
2. The agent greets and asks the customer's name.
3. Customer explains a real-estate CRM need; agent asks qualifying questions (watch the Lead Card fill in).
4. Customer asks a product question; agent answers via RAG (source chip appears).
5. Customer asks something not in the docs; agent refuses to invent.
6. Customer requests a meeting tomorrow at 3 PM; agent checks availability and books it.
7. End the call.
8. Switch to the dashboard: lead, score, sentiment, summary, appointment and updated insights are all there.

### Deliverables checklist

- [ ] Working deployed application
- [ ] Git repository with clear history
- [ ] Architecture diagram
- [ ] Database design (ER diagram)
- [ ] API documentation (FastAPI `/docs` plus a short README table)
- [ ] RAG demonstration
- [ ] CRM dashboard
- [ ] README with setup and run steps
- [ ] Test cases and results
- [ ] Cost spreadsheet
- [ ] Scalability design for 1 lakh users
- [ ] Short presentation: problem, solution, tech, business value

### Interview topics you must be able to explain

- **Voice and AI:** STT vs TTS vs LLM; the real-time pipeline; latency reduction; barge-in; contextual memory; multilingual handling; chatbot vs voice agent; what makes it agentic.
- **RAG and LLMs:** what RAG is, embeddings, vector databases, semantic search, RAG vs fine-tuning, function calling, how a booking is executed, how hallucinations are prevented.
- **Backend:** why FastAPI and PostgreSQL; REST vs WebSocket; how conversation history is stored; handling concurrent calls and API failures.
- **System design:** scaling to 1 lakh users; behaviour when the AI provider is down; preventing duplicate appointments; multi-tenancy; securing customer data; monitoring latency; reducing cost.
- **Product:** the problem solved, who buys it, why choose it over human callers, pricing, cost per call, how to measure success.
- **Live modification:** be ready to change the scoring rules, add a field, add a tool, adjust the prompt, and debug a failing endpoint on the spot.

---

## 14. Definition of done

The project is complete only when all of these are true:

- A real voice conversation works with the actual STT, LLM and TTS APIs.
- The agent remembers details and never re-asks them.
- Leads are scored and classified by plain Python rules.
- RAG answers from the documents and refuses to invent missing facts.
- Appointments are booked through validated tool calls, with duplicates blocked.
- A summary and sentiment are generated automatically after each call.
- The dashboard shows live data and matches the design direction in Section 8.
- The app is containerised, deployed over HTTPS, and documented.
- The code is small, clean and readable, and you can explain and modify every part of it.

**Final rule:** optimise for a working, understandable product. Do not optimise for the number of files, frameworks or lines of code.
