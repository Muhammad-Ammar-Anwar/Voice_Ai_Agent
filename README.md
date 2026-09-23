# 🎙️ Voice AI Agent — Patient Registration

A phone number you can call to register as a new patient by just talking. The agent **"Sam"** collects standard U.S. demographics conversationally, reads everything back for confirmation, saves it to a PostgreSQL database, and exposes the records through a REST API and a live dashboard.

> All data is fictional. This is a demo project, not a HIPAA-compliant system.

---

## 🔗 Live Links

| | |
|---|---|
| **Phone Number** | `+1 (513) 901 0470` |
| **API Base URL** | `https://voiceaiagent-production-7c45.up.railway.app` |
| **Swagger Docs** | `https://voiceaiagent-production-7c45.up.railway.app/docs` |
| **Dashboard** | `https://voiceaiagent-production-7c45.up.railway.app/dashboard` |
| **Health Check** | `https://voiceaiagent-production-7c45.up.railway.app/health` |
| **Repository** | `https://github.com/Muhammad-Ammar-Anwar/Voice_Ai_Agent` |

---

## 🏗️ Architecture

```
                 +----------------------------- Vapi (managed) -----------------------------+
  Caller  <-->   |  Phone number -> STT (Deepgram) -> LLM (GPT-4o + system prompt) -> TTS   |
  (PSTN)         +-------------------------------------+------------------------------------+
                                                        | HTTPS webhook (tool calls, end-of-call report)
                                                        v
                +--------------------- FastAPI service (this repo) ---------------------+
                |  routers/vapi.py      voice tool handlers  ----\                      |
                |  routers/patients.py  REST API (/patients) -----+--> services.py --> DB|
                |  validators.py        shared validation rules                          |
                +------------------------------------------------------------------------+
                                     PostgreSQL (Neon - hosted)
```

---

## 🚀 Quick Start (Local)

```bash
# 1. Clone the repo
git clone https://github.com/Muhammad-Ammar-Anwar/Voice_Ai_Agent.git
cd Voice_Ai_Agent

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env          # Edit values as needed

# 5. Run the server
uvicorn app.main:app --reload --port 8000

# 6. Open in browser
# http://localhost:8000/docs
# http://localhost:8000/dashboard
```

---

## 🧪 Testing

### Voice Agent
Call **+1 (513) 901 0470)** or use the Vapi dashboard Talk button.

Sam will ask for:
- First and last name
- Date of birth
- Sex
- Phone number
- Address, city, state, ZIP (required)
- Email, insurance (optional)

### REST API
```bash
# Health check
curl https://voiceaiagent-production-7c45.up.railway.app/health

# List all patients
curl https://voiceaiagent-production-7c45.up.railway.app/patients

# Create a patient
curl -X POST https://voiceaiagent-production-7c45.up.railway.app/patients \
  -H "content-type: application/json" \
  -d '{
    "first_name": "Jane",
    "last_name": "Doe",
    "date_of_birth": "03/03/1990",
    "sex": "Female",
    "phone_number": "(512) 555-0199",
    "address_line_1": "12 Main St",
    "city": "Austin",
    "state": "TX",
    "zip_code": "78701"
  }'
```

### Automated Tests
```bash
pytest -q    # runs 17 tests
```

### Demo Patients (pre-seeded)
| Name | Phone |
|---|---|
| Alex Rivera | 512-555-0101 |
| Priya Patel | 415-555-0102 |

---

## 📡 REST API Reference

All responses follow the envelope format:
```json
{ "data": ..., "error": null }
{ "data": null, "error": { "code": "...", "message": "...", "details": [] } }
```

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | DB connectivity check |
| GET | `/patients` | List patients. Filters: `last_name`, `date_of_birth`, `phone_number`, `limit`, `offset` |
| GET | `/patients/{id}` | Get patient by UUID |
| POST | `/patients` | Register new patient (201) |
| PUT | `/patients/{id}` | Partial update |
| DELETE | `/patients/{id}` | Soft delete |

---

## ⚙️ Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `DATABASE_URL` | PostgreSQL or SQLite URL | Yes |
| `VAPI_WEBHOOK_SECRET` | Webhook auth secret | Recommended |
| `SEED_DEMO_DATA` | Seed 2 demo patients on startup | Optional (default: true) |
| `LOG_LEVEL` | Logging level | Optional (default: INFO) |
| `VAPI_API_KEY` | Vapi private key (script only) | For setup only |
| `PUBLIC_BASE_URL` | Public server URL (script only) | For setup only |
| `VAPI_ASSISTANT_ID` | Existing assistant ID to update | Optional |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Telephony / STT / TTS | Vapi, Deepgram, GPT-4o |
| Backend | FastAPI + Python 3.12 |
| Database | PostgreSQL via Neon (SQLite for local dev) |
| ORM | SQLAlchemy 2 |
| Validation | Pydantic v2 |
| Hosting | Railway |
| Tests | pytest (17 tests) |

---

## 📁 Project Structure

```
app/
  main.py              App wiring, error handlers, /health, /dashboard
  agent_config.py      System prompt + tool schemas
  validators.py        Shared validation/normalization
  schemas.py           Pydantic request/response models
  services.py          Data-access layer
  models.py            SQLAlchemy schema (patients, call_logs)
  routers/
    patients.py        REST endpoints
    vapi.py            Voice webhook + tool handlers
scripts/
  create_assistant.py  Creates/updates Vapi assistant
static/
  dashboard.html       Live patient dashboard
tests/                 API + webhook tests
```

---

## 📋 Call Flow

1. Sam greets and collects required fields in any order
2. Risky fields (DOB, phone, state, ZIP, email) validated server-side via `validate_field` tool
3. Phone number checked for existing record (duplicate detection)
4. Optional fields offered once
5. Sam reads everything back — only after explicit "yes" calls `register_patient`
6. On success: "You're all set!" then hangs up
7. End-of-call report stores transcript + summary in `call_logs`

---

## ⚠️ Known Limitations

- No authentication on `/patients` or `/dashboard` (demo only)
- Phone validation is "10 digits" not full NANP rules
- English only
- Free Railway tier has usage limits
