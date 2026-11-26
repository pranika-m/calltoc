# Autonomous AI Sales Voice Agent

An AI voice sales agent MVP that talks to prospects in the browser, qualifies leads, answers product questions from a company knowledge base (RAG), books appointments, and updates a CRM dashboard automatically.

## Demo Workflow

1. A prospect starts a voice call from the **Live Call Console**.
2. The agent greets the caller, learns their business needs, and asks one qualifying question at a time.
3. The prospect asks product questions; the agent answers using the company knowledge base (RAG) and cites the source document.
4. When interest is clear, the agent checks availability and books a demo appointment.
5. When the call ends, the backend generates a structured call summary, updates lead score and sentiment, and displays everything in the CRM dashboard.

## P1 Checklist (MVP Core)

- [ ] Browser voice conversation (Deepgram STT + OpenAI-compatible LLM + ElevenLabs TTS)
- [ ] Per-call conversation memory and live lead extraction
- [ ] Pure-Python lead scoring and Hot / Warm / Cold classification
- [ ] PostgreSQL persistence with `tenant_id` isolation
- [ ] Appointment booking with DB-level duplicate protection
- [ ] Automatic post-call summary
- [ ] React + Tailwind CRM dashboard ("Conversation Intelligence Studio")
- [ ] One complete end-to-end demo workflow

## Setup (Phase 1)

1. Create a Python 3.11+ virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # macOS / Linux:
   # source .venv/bin/activate

   pip install -r backend/requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your API keys (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `DATABASE_URL`):

   ```bash
   cp .env.example .env
   ```

3. Verify settings load without exposing secrets:

   ```bash
   python -c "from backend.config import settings; print(settings.llm_base_url, settings.llm_model, bool(settings.llm_api_key))"
   ```

## Testing

Run all unit and integration tests:

```bash
python -m pytest tests/ -v
```

## Docker Compose (Local Full Stack)

Run PostgreSQL, the FastAPI backend, and the React frontend with one command:

```bash
docker compose up --build
```

- Frontend: `http://localhost:5173`
- Backend API & Swagger docs: `http://localhost:8000/docs`

## Cloud Deployment (Render / Railway / AWS + Vercel)

1. **Database:** Provision a managed PostgreSQL instance and copy its connection string into `DATABASE_URL`.
2. **Backend:** Deploy the root [Dockerfile](Dockerfile) to Render, Railway, or AWS App Runner/ECS. Set all keys from `.env.example` in the host's secret store (including `PUBLIC_BASE_URL=https://<your-backend-domain>`).
3. **Frontend:** Deploy `frontend/` to Vercel with `VITE_API_BASE=https://<your-backend-domain>` and `VITE_WS_BASE=wss://<your-backend-domain>`.
4. **Verify:** Open the deployed Vercel URL, confirm `GET https://<your-backend-domain>/health` returns `{"status": "ok"}`, and run a live voice call over `wss://`.
