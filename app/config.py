"""Environment-driven configuration. No secrets live in source code."""
import os

from dotenv import load_dotenv

load_dotenv()


def _normalize_db_url(url: str) -> str:
    # Render/Heroku-style URLs use the legacy "postgres://" scheme, which SQLAlchemy 2 rejects.
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///./patients.db"))
# Optional shared secret. If set, /vapi/webhook requires a matching X-Vapi-Secret header.
VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
