# Voice AI Agent - Patient Registration

A phone number you can call to register as a new patient by just talking. The agent ("Sam") collects standard U.S. demographics conversationally, reads everything back for confirmation, saves it to a database, and exposes the records through a REST API and a small dashboard. Call back later and the data is still there.

| | |
|---|---|
| **Phone number** | `+1 (___) ___-____` <- fill in after provisioning |
| **API base URL** | `https://YOUR-APP.onrender.com` |
| **API docs (Swagger)** | `<base>/docs` |
| **Dashboard** | `<base>/dashboard` |
| **Seed patients (for the "returning caller" demo)** | Alex Rivera `512-555-0101`, Priya Patel `415-555-0102` |

> All data is fictional. This is an assessment project, not a HIPAA-compliant system.

---

## Architecture

```
                 +----------------------------- Vapi (managed) -----------------------------+
  Caller  <-->   |  Phone number -> STT (Deepgram) -> LLM (GPT-4o + system prompt) -> TTS   |
  (PSTN)         +-------------------------------------+------------------------------------+
                                                        | HTTPS webhook (tool calls, end-of-call report)
                                                        v
                +--------------------- FastAPI service (this repo) ---------------------+
                |  routers/vapi.py      voice tool handlers  ----\                       |
                |  routers/patients.py  REST API (/patients) -----+--> services.py -->  DB |
                |  validators.py        ONE set of rules, shared by both paths           |
                +----------------------------------------------------------------------------+
                                     SQLite (dev) / PostgreSQL (prod)
```

**Separation of concerns**

| Layer | Where | Responsibility |
|---|---|---|
| Telephony / STT / TTS | Vapi (managed) | Number, audio, turn-taking, barge-in |
| Conversation logic | `app/agent_config.py` (prompt + tool schemas) | *What to say and when* |
| Tool bridge | `app/routers/vapi.py` | Converts LLM tool calls into service calls; converts every failure into something speakable |
| Business logic | `app/services.py`, `app/validators.py` | CRUD + validation, used by **both** the API and the agent |
| Persistence | `app/models.py` | Schema + constraints |
| Public API | `app/routers/patients.py` | REST, envelope, status codes |

The voice agent calls the **same service layer** as the REST API (the spec allows this) instead of making HTTP calls to itself. That removes a network hop and a failure mode, and guarantees identical validation.

### Call flow
1. Sam greets and collects the required fields in any order (caller can volunteer several at once).
2. Risky fields (DOB, phone, state, ZIP, email) go through the `validate_field` tool, so the **server** decides validity and the agent re-prompts for exactly that field.
3. As soon as a phone number is valid, `lookup_patient` checks for an existing record (duplicate detection).
4. Sam offers the optional fields once, opt-in only.
5. Sam reads everything back; only after an explicit "yes" does it call `register_patient`.
6. On success: "You're all set, Jane." then hangs up. On failure the tool result tells the agent what to say (see edge cases).
7. Vapi's `end-of-call-report` stores transcript + summary in `call_logs`, linked to the patient.

---

## Tech stack & why

| Choice | Why |
|---|---|
| **Vapi** | Fastest reliable path to a real phone number with low-latency STT/TTS and barge-in handling. Lets the 3 hours go into prompt + integration quality rather than audio plumbing (the brief explicitly encourages this). |
| **GPT-4o** (configurable) | Strong tool-calling + low latency. Swappable via `LLM_PROVIDER` / `LLM_MODEL`. |
| **FastAPI + Pydantic v2** | Typed validation, automatic OpenAPI docs, tiny surface area. |
| **SQLAlchemy 2** | Same code runs on SQLite (zero-setup dev) and PostgreSQL (persistent prod) via `DATABASE_URL`. |
| **PostgreSQL in prod** | Free-tier container disks are usually ephemeral, so a managed DB is what actually guarantees "data survives restarts". |
| **Shared `validators.py`** | One definition of "valid phone/DOB/state" for the API and the voice tools. No drift. |

---

## Setup

### Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit values
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000/docs  and  http://localhost:8000/dashboard
pytest -q                       # 17 tests
```

### Deploy (example: Render + Postgres)
1. Push this repo to GitHub.
2. Create a managed **PostgreSQL** (Render, Neon, or Supabase) and copy its connection string.
3. Create a **Web Service** from the repo (Docker runtime; the `Dockerfile` is included).
4. Set env vars: `DATABASE_URL`, `VAPI_WEBHOOK_SECRET`, `SEED_DEMO_DATA=true`.
5. Verify `GET <base>/health` returns `{"data":{"status":"ok"},"error":null}`.
6. **Avoid cold starts during review:** free web tiers sleep when idle, and a sleeping server makes the first tool call in a call time out. Use an always-on plan, or ping `/health` every few minutes (e.g. UptimeRobot).

*Local alternative:* `ngrok http 8000` and use the ngrok URL as `PUBLIC_BASE_URL`.

### Connect the phone line (Vapi)
1. Create a Vapi account and copy your **private API key**.
2. Put `VAPI_API_KEY` and `PUBLIC_BASE_URL` in `.env`, then:
   ```bash
   python scripts/create_assistant.py --dry-run   # inspect the exact config
   python scripts/create_assistant.py             # creates the assistant, prints its id
   ```
3. In the Vapi dashboard: **Phone Numbers -> Create** (a free Vapi US number works) -> attach the assistant.
4. Call it. Watch logs: `PATIENT_REGISTERED call_id=... payload={...}`.

If the API rejects any field (Vapi's schema evolves), the script prints Vapi's error. Fallback: create the assistant in the dashboard, paste `SYSTEM_PROMPT` from `app/agent_config.py`, and add the four tools pointing at `<base>/vapi/webhook`. Re-running the script after editing the prompt keeps the live agent in sync with the repo (`VAPI_ASSISTANT_ID=<id>` makes it update instead of create).

### Environment variables
| Variable | Used by | Purpose |
|---|---|---|
| `DATABASE_URL` | server | `sqlite:///./patients.db` (default) or a `postgresql://...` URL |
| `VAPI_WEBHOOK_SECRET` | server + script | If set, webhook requires matching `X-Vapi-Secret` header |
| `SEED_DEMO_DATA` | server | Insert 2 fictional patients when the table is empty (default `true`) |
| `LOG_LEVEL` | server | Default `INFO` |
| `VAPI_API_KEY`, `PUBLIC_BASE_URL` | script only | Create/update the assistant. Never needed by the running server |
| `VAPI_ASSISTANT_ID`, `LLM_PROVIDER`, `LLM_MODEL`, `VOICE_PROVIDER`, `VOICE_ID` | script only | Optional overrides |

No secrets are in source control (`.env` is git-ignored).

---

## REST API

All responses: `{ "data": ..., "error": null }` or `{ "data": null, "error": { "code", "message", "details": [{ "field", "message" }] } }`.

| Method | Endpoint | Notes |
|---|---|---|
| GET | `/patients` | Filters: `?last_name=` (case-insensitive exact), `?date_of_birth=` (MM/DD/YYYY or YYYY-MM-DD), `?phone_number=` (any format). Also `limit`, `offset`. |
| GET | `/patients/{id}` | 400 bad UUID, 404 missing/deleted |
| POST | `/patients` | 201 with the record + `patient_id` |
| PUT | `/patients/{id}` | Partial update; only sent fields change |
| DELETE | `/patients/{id}` | Soft delete (`deleted_at`); row retained, hidden from reads |
| GET | `/health` | DB connectivity check |

Status codes: `200/201` success, `400` malformed JSON / bad id / bad query param, `404` not found, `422` field validation, `500` unexpected (logged, generic message returned).

```bash
curl -X POST $BASE/patients -H 'content-type: application/json' -d '{
  "first_name":"Jane","last_name":"Doe","date_of_birth":"03/03/1990","sex":"Female",
  "phone_number":"(512) 555-0199","address_line_1":"12 Main St","city":"Austin","state":"TX","zip_code":"78701"}'
```

Input handling: values are trimmed, control characters stripped, phones normalized to 10 digits, states upper-cased, emails lower-cased, `<>{}` rejected in free text, unknown JSON keys rejected (422). SQL injection is prevented by parameterized queries (SQLAlchemy); the dashboard uses `textContent` (no HTML injection).

## Database schema
`patients` follows the spec exactly (UUID `patient_id`, `created_at`/`updated_at` UTC, `deleted_at` for soft delete) with DB-level `CHECK` constraints (sex enum, 2-char state, 10-digit phone, non-empty names) and indexes on `last_name`, `phone_number`, `date_of_birth`. `call_logs` (bonus) stores `call_id`, `patient_id` (nullable), `ended_reason`, `summary`, `transcript`.

---

## Prompt engineering (see `app/agent_config.py`)
The full system prompt is in code with design notes at the top. Key decisions:

- **Voice-first style rules:** one question at a time, 1-2 short sentences, no lists/markdown, numbers spoken naturally, varied acknowledgements so it doesn't sound scripted.
- **State lives in the conversation, server stays stateless.** This is what makes out-of-order answers, corrections, and "start over" work naturally.
- **Validation is a tool, not a promise.** The LLM never decides what a valid phone/DOB is; the server does, and the prompt says to relay the *specific* problem.
- **Hard confirmation gate:** `register_patient` may only be called after a full read-back and an explicit "yes".
- **Names and emails are spelled back** because STT is lossy; the caller's spelling always wins.
- **Every tool result includes an `instruction`,** so failure behavior is data-driven, not left to LLM improvisation.
- **Low temperature (0.4):** consistent data collection without robotic phrasing.

## Edge cases & resilience

| Scenario | Behavior |
|---|---|
| Invalid DOB (future, `02/30`, no year) | `validate_field` returns a specific problem; agent re-asks only DOB |
| 3-digit / 9-digit phone | Agent says how many digits it heard, asks for the full 10-digit number |
| Caller corrects a name mid-call | Accepted immediately, corrected value repeated back, nothing else re-asked |
| Caller says "start over" | Agent confirms, discards all collected info, restarts (nothing was saved yet) |
| Info given out of order / several at once | Agent takes all of it and skips ahead |
| Caller interrupts | Vapi barge-in stops speech; prompt tells agent to answer briefly then resume |
| Validation failure at save time | Nothing saved; result lists bad fields; agent re-asks only those |
| **DB write fails** | Tool returns `error_type: system`; agent apologizes, offers one retry, then says the team will follow up. Never silent, never claims success |
| Webhook handler crashes | Caught per-tool; converted to a spoken apology |
| Call drops mid-conversation | Nothing partial is written to `patients` (save happens only after confirmation). `end-of-call-report` still stores an abandoned `call_logs` row (`patient_id` NULL) with `ended_reason` |
| Existing phone number | `lookup_patient` -> "we already have a record for X. Update instead?" -> `update_patient` (sends only changed fields). Handles "different person, same number" too |
| Dead line / silence | Vapi `silenceTimeoutSeconds=30`, `maxDurationSeconds=900` |

## Tests
`pytest -q` runs 17 tests against a throwaway SQLite DB: API happy path, filters, 400/404/422 paths, partial update, soft delete, and the voice webhook (simulated Vapi payloads: validation, registration, DB failure, returning caller, call-log for abandoned calls, webhook secret).

## Known limitations / trade-offs
- **No authentication on `/patients` or `/dashboard`.** Acceptable for fictional demo data; would need auth before any real use. The webhook does support a shared secret.
- **Phone validation is "10 digits", not full NANP rules** (spec wording; also avoids rejecting reviewers' fake numbers like `123-456-7890`).
- **Duplicate detection is phone-only,** and family members can legitimately share a number, so the agent asks rather than blocking. There is no unique constraint on phone.
- **English only.** The transcriber is set to `en`; Spanish would need a multilingual transcriber + voice.
- **`create_all()` instead of migrations** (Alembic) to keep the bootstrap simple.
- **Name validation** allows spaces, so "Mary Ann" works, plus Unicode letters (e.g. "Jose", "Nguyen" with diacritics).
- **Transcript quality depends on STT;** unusual names/street names may need the spell-back step, which the prompt enforces for names only, to keep the call short.
- **Cold starts** on free hosting can break the first tool call; see the deploy notes.

## Next steps
- Alembic migrations, API auth (API key / OAuth), rate limiting.
- Address verification (USPS/Google) and insurance eligibility lookup.
- Spanish support (multilingual STT + voice, language switch on "Hablo espanol").
- Appointment scheduling after registration (mock slots -> real calendar).
- Post-call evals: replay stored transcripts against a rubric to catch regressions when the prompt changes.
- Voice-quality tuning: endpointing/backchannel settings, per-field "spell it out" fallback.

## Project layout
```
app/
  main.py            app wiring, error handlers, /health, /dashboard
  agent_config.py    SYSTEM PROMPT + tool schemas (source of truth for the agent)
  validators.py      shared validation/normalization
  schemas.py         Pydantic request/response models
  services.py        data-access layer (used by API and agent)
  models.py          SQLAlchemy schema (patients, call_logs)
  routers/patients.py   REST endpoints
  routers/vapi.py       voice webhook + tool handlers
scripts/create_assistant.py   pushes prompt+tools to Vapi
static/dashboard.html         simple live patient table
tests/                        API + webhook tests
```
