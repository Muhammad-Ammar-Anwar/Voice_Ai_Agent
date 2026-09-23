"""Optional demo data (SEED_DEMO_DATA=true). Fictional people only - never real PHI."""
import logging
from datetime import date

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Patient

log = logging.getLogger("patient-agent.seed")

SEED = [
    dict(first_name="Alex", last_name="Rivera", date_of_birth=date(1988, 4, 12), sex="Other",
         phone_number="5125550101", email="alex.rivera@example.com", address_line_1="101 Congress Ave",
         city="Austin", state="TX", zip_code="78701", preferred_language="English"),
    dict(first_name="Priya", last_name="Patel", date_of_birth=date(1975, 11, 3), sex="Female",
         phone_number="4155550102", address_line_1="500 Market Street", address_line_2="Apt 4B",
         city="San Francisco", state="CA", zip_code="94105", insurance_provider="Blue Shield",
         insurance_member_id="XYZ123456", preferred_language="Spanish"),
]


def seed_if_empty() -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Patient)) == 0:
            db.add_all(Patient(**row) for row in SEED)
            db.commit()
            log.info("Seeded %d demo patients", len(SEED))
