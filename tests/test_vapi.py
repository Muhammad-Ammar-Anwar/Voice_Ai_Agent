"""Simulates exactly what Vapi sends to the webhook during a call."""
import json

from tests.conftest import VALID

CALL = {"id": "call_123", "customer": {"number": "+15125550000"}}


def tool(client, name, args, headers=None):
    body = {"message": {"type": "tool-calls", "call": CALL,
                        "toolCallList": [{"id": "tc_1", "name": name, "arguments": args}]}}
    r = client.post("/vapi/webhook", json=body, headers=headers or {})
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["toolCallId"] == "tc_1"               # Vapi requires the id echoed back
    return json.loads(res["result"])                 # result must be a string


def test_validate_field(client):
    assert tool(client, "validate_field", {"field": "phone_number", "value": "555 123"})["valid"] is False
    out = tool(client, "validate_field", {"field": "phone_number", "value": "(512) 555-0199"})
    assert out == {"valid": True, "normalized_value": "5125550199"}
    bad = tool(client, "validate_field", {"field": "date_of_birth", "value": "01/01/2999"})
    assert "future" in bad["problem"]


def test_register_success_persists_and_links_call(client):
    out = tool(client, "register_patient", VALID)
    assert out["success"] is True and out["first_name"] == "Jane"
    data = client.get("/patients?last_name=O'Doe-Smith").json()["data"]
    assert len(data) == 1 and data[0]["patient_id"] == out["patient_id"]
    from app.database import SessionLocal
    from app.models import CallLog
    with SessionLocal() as db:
        assert db.query(CallLog).one().patient_id == out["patient_id"]


def test_register_validation_failure_lists_only_bad_fields_and_saves_nothing(client):
    out = tool(client, "register_patient", {**VALID, "phone_number": "12345", "zip_code": "78701"})
    assert out["success"] is False and out["error_type"] == "validation"
    assert [e["field"] for e in out["errors"]] == ["phone_number"]
    assert client.get("/patients").json()["data"] == []


def test_db_failure_returns_spoken_error_not_silence(client, monkeypatch):
    from app import services
    monkeypatch.setattr(services, "create_patient", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    out = tool(client, "register_patient", VALID)
    assert out["success"] is False and out["error_type"] == "system" and "instruction" in out


def test_returning_caller_lookup_and_update(client):
    assert tool(client, "lookup_patient", {"phone_number": "5125550199"})["found"] is False
    pid = tool(client, "register_patient", VALID)["patient_id"]
    found = tool(client, "lookup_patient", {"phone_number": "512-555-0199"})
    assert found["found"] and found["patient_id"] == pid and found["first_name"] == "Jane"
    assert "email" not in found                       # no extra PHI leaked to the LLM
    up = tool(client, "update_patient", {"patient_id": pid, "city": "Houston"})
    assert up["success"] and client.get(f"/patients/{pid}").json()["data"]["city"] == "Houston"
    assert tool(client, "update_patient", {"patient_id": "nope", "city": "X"})["error_type"] == "not_found"


def test_string_arguments_and_unknown_tool_are_handled(client):
    body = {"message": {"type": "tool-calls", "call": CALL, "toolCallList": [
        {"id": "a", "name": "validate_field", "arguments": json.dumps({"field": "state", "value": "tx"})},
        {"id": "b", "name": "does_not_exist", "arguments": {}}]}}
    res = client.post("/vapi/webhook", json=body).json()["results"]
    assert json.loads(res[0]["result"])["normalized_value"] == "TX"
    assert "error" in json.loads(res[1]["result"])


def test_end_of_call_report_stored_even_without_registration(client):
    body = {"message": {"type": "end-of-call-report", "endedReason": "customer-ended-call", "call": CALL,
                        "artifact": {"transcript": "AI: Hi\nUser: Hi"}, "analysis": {"summary": "Caller hung up early"}}}
    assert client.post("/vapi/webhook", json=body).status_code == 200
    from app.database import SessionLocal
    from app.models import CallLog
    with SessionLocal() as db:
        row = db.query(CallLog).one()
        assert row.patient_id is None and row.summary == "Caller hung up early"


def test_webhook_secret_enforced(client, monkeypatch):
    from app.routers import vapi
    monkeypatch.setattr(vapi, "VAPI_WEBHOOK_SECRET", "s3cret")
    body = {"message": {"type": "status-update"}}
    assert client.post("/vapi/webhook", json=body).status_code == 401
    assert client.post("/vapi/webhook", json=body, headers={"x-vapi-secret": "s3cret"}).status_code == 200
