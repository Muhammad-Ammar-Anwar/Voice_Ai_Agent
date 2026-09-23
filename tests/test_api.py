from tests.conftest import VALID


def create(client, **over):
    return client.post("/patients", json={**VALID, **over})


def test_create_normalizes_and_returns_envelope(client):
    r = create(client)
    assert r.status_code == 201
    body = r.json()
    assert body["error"] is None
    d = body["data"]
    assert d["phone_number"] == "5125550199"      # digits only
    assert d["state"] == "TX"                      # upper-cased
    assert d["date_of_birth"] == "03/03/1990"      # MM/DD/YYYY
    assert d["preferred_language"] == "English"    # default
    assert d["created_at"].endswith("Z") and len(d["patient_id"]) == 36


def test_get_list_and_filters(client):
    pid = create(client).json()["data"]["patient_id"]
    create(client, first_name="Bob", last_name="Lee", phone_number="4155550100", date_of_birth="01/02/1970")
    assert client.get(f"/patients/{pid}").json()["data"]["first_name"] == "Jane"
    assert len(client.get("/patients").json()["data"]) == 2
    assert len(client.get("/patients?last_name=lee").json()["data"]) == 1
    assert len(client.get("/patients?phone_number=512-555-0199").json()["data"]) == 1
    assert len(client.get("/patients?date_of_birth=01/02/1970").json()["data"]) == 1


def test_validation_errors_are_422_with_field_details(client):
    r = create(client, phone_number="555123", date_of_birth="01/01/2999", state="ZZ", zip_code="1234")
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["error"]["details"]}
    assert {"phone_number", "date_of_birth", "state", "zip_code"} <= fields
    assert r.json()["data"] is None


def test_missing_required_and_unknown_fields(client):
    r = client.post("/patients", json={"first_name": "Only"})
    assert r.status_code == 422
    assert client.post("/patients", json={**VALID, "nickname": "x"}).status_code == 422


def test_invalid_dob_variants(client):
    for bad in ["02/30/1990", "13/01/1990", "not a date", "01/01/1850"]:
        assert create(client, date_of_birth=bad).status_code == 422, bad


def test_malformed_json_and_bad_ids(client):
    r = client.post("/patients", content="{nope", headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert client.get("/patients/not-a-uuid").status_code == 400
    assert client.get("/patients/6f1c8a52-0000-4000-8000-000000000000").status_code == 404
    assert client.get("/patients?date_of_birth=garbage").status_code == 400


def test_partial_update(client):
    pid = create(client).json()["data"]["patient_id"]
    r = client.put(f"/patients/{pid}", json={"city": "Dallas", "email": "JANE@Example.com"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["city"] == "Dallas" and d["email"] == "jane@example.com" and d["first_name"] == "Jane"
    assert client.put(f"/patients/{pid}", json={}).status_code == 400
    assert client.put(f"/patients/{pid}", json={"zip_code": "bad"}).status_code == 422
    assert client.put("/patients/6f1c8a52-0000-4000-8000-000000000000", json={"city": "X"}).status_code == 404


def test_soft_delete_hides_but_keeps_row(client):
    from app.database import SessionLocal
    from app.models import Patient
    pid = create(client).json()["data"]["patient_id"]
    r = client.delete(f"/patients/{pid}")
    assert r.status_code == 200 and r.json()["data"]["deleted_at"]
    assert client.get(f"/patients/{pid}").status_code == 404
    assert client.get("/patients").json()["data"] == []
    with SessionLocal() as db:  # row still exists
        assert db.get(Patient, pid).deleted_at is not None


def test_health_and_unknown_route(client):
    assert client.get("/health").json()["data"]["status"] == "ok"
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
