import os
import tempfile

# Must be set BEFORE the app is imported so it binds to a throwaway DB.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["VAPI_WEBHOOK_SECRET"] = ""

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


VALID = {
    "first_name": "Jane", "last_name": "O'Doe-Smith", "date_of_birth": "03/03/1990", "sex": "Female",
    "phone_number": "(512) 555-0199", "address_line_1": "12 Main St", "city": "Austin",
    "state": "tx", "zip_code": "78701",
}
