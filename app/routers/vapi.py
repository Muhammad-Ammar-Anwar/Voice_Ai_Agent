"""
Vapi webhook: the bridge between the voice agent (LLM) and our service layer.

Vapi POSTs JSON here:
  * type "tool-calls"         -> the LLM invoked one of our tools; we must reply
                                 {"results": [{"toolCallId", "result": "<string>"}]}
  * type "end-of-call-report" -> call finished (also fires on dropped calls);
                                 we persist the transcript + summary.

Design rules for tool handlers:
  1. NEVER raise to Vapi. Every failure is converted into a structured result the
     LLM can speak from (so the caller never gets dead air).
  2. Tool results always carry an "instruction" telling the LLM what to do next.
  3. Validation errors are returned per-field so the agent re-asks ONLY that field.
"""
import json
import logging
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Header, Request
from pydantic import ValidationError

from app import services
from app.config import VAPI_WEBHOOK_SECRET
from app.database import SessionLocal
from app.envelope import format_validation_errors
from app.schemas import PatientCreate, PatientUpdate
from app.validators import ALL_FIELDS, InvalidValue, display_value, validate_field
from fastapi.responses import JSONResponse

log = logging.getLogger("patient-agent.vapi")
router = APIRouter(prefix="/vapi", tags=["voice-agent"])


# ---- tool handlers ---------------------------------------------------------

def _link_call(ctx: dict, patient_id: str) -> None:
    """Associate this call with the patient. Failure here must never affect the caller."""
    if not ctx.get("call_id"):
        return
    try:
        with SessionLocal() as db:
            services.link_call_to_patient(db, ctx["call_id"], patient_id, ctx.get("caller"))
    except Exception:
        log.exception("could not link call %s to patient", ctx["call_id"])


def tool_validate_field(args: dict, ctx: dict) -> dict:
    field, value = args.get("field"), args.get("value")
    try:
        normalized = validate_field(str(field), value)
    except InvalidValue as e:
        return {"valid": False, "problem": str(e),
                "instruction": "Tell the caller specifically what was wrong and ask for that field again."}
    return {"valid": True, "normalized_value": display_value(normalized)}


def tool_lookup_patient(args: dict, ctx: dict) -> dict:
    try:
        phone = validate_field("phone_number", args.get("phone_number"))
    except InvalidValue as e:
        return {"found": False, "problem": str(e)}
    with SessionLocal() as db:
        p = services.find_by_phone(db, phone)
        if p is None:
            return {"found": False}
        # Only expose what the agent needs to confirm identity - not the full record.
        return {"found": True, "patient_id": p.patient_id, "first_name": p.first_name, "last_name": p.last_name,
                "instruction": "Say you already have a record for this person and ask if they want to update it instead of registering again."}


def tool_register_patient(args: dict, ctx: dict) -> dict:
    payload = {k: v for k, v in args.items() if k in ALL_FIELDS and v not in (None, "")}
    try:
        data = PatientCreate(**payload)
    except ValidationError as e:
        errors = format_validation_errors(e.errors())
        log.warning("register_patient rejected: %s", errors)
        return {"success": False, "error_type": "validation", "errors": errors,
                "instruction": "Nothing was saved. Ask the caller again ONLY for the fields listed, then call register_patient again."}
    try:
        with SessionLocal() as db:
            patient = services.create_patient(db, data)
    except Exception:
        log.exception("register_patient DB write failed")
        return {"success": False, "error_type": "system",
                "instruction": "Apologize briefly, say there was a technical problem saving. Offer to try once more. If it fails again, apologize and tell them our team will follow up, then end the call."}
    _link_call(ctx, patient.patient_id)  # best effort: the record is already saved
    # Observability requirement: final collected payload goes to stdout.
    log.info("PATIENT_REGISTERED call_id=%s payload=%s", ctx.get("call_id"),
             json.dumps({**data.model_dump(mode="json"), "patient_id": patient.patient_id}))
    return {"success": True, "patient_id": patient.patient_id, "first_name": patient.first_name}


def tool_update_patient(args: dict, ctx: dict) -> dict:
    patient_id = args.get("patient_id")
    payload = {k: v for k, v in args.items() if k in ALL_FIELDS and v not in (None, "")}
    if not payload:
        return {"success": False, "error_type": "validation", "errors": [{"field": "body", "message": "No fields to update"}]}
    try:
        data = PatientUpdate(**payload)
    except ValidationError as e:
        return {"success": False, "error_type": "validation", "errors": format_validation_errors(e.errors()),
                "instruction": "Nothing was changed. Re-ask ONLY for the listed fields."}
    try:
        with SessionLocal() as db:
            patient = services.update_patient(db, str(patient_id), data)
    except Exception:
        log.exception("update_patient DB write failed")
        return {"success": False, "error_type": "system",
                "instruction": "Apologize briefly for the technical problem and offer to try once more."}
    if patient is None:
        return {"success": False, "error_type": "not_found",
                "instruction": "Apologize; the record could not be found. Offer to register them as a new patient instead."}
    _link_call(ctx, patient.patient_id)
    log.info("PATIENT_UPDATED call_id=%s patient_id=%s fields=%s", ctx.get("call_id"), patient_id, sorted(payload))
    return {"success": True, "patient_id": patient.patient_id, "first_name": patient.first_name}


TOOLS = {
    "validate_field": tool_validate_field,
    "lookup_patient": tool_lookup_patient,
    "register_patient": tool_register_patient,
    "update_patient": tool_update_patient,
}


# ---- webhook ---------------------------------------------------------------

def _as_dict(arguments: Any) -> dict:
    """Vapi sends arguments as an object, but some providers stringify it."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    return arguments if isinstance(arguments, dict) else {}


def _extract_tool_calls(message: dict) -> list[dict]:
    calls = message.get("toolCallList")
    if calls:
        return calls
    # Fallback shape: message.toolWithToolCallList[].toolCall
    return [t["toolCall"] for t in message.get("toolWithToolCallList", []) if "toolCall" in t]


def _handle_tool_calls(message: dict) -> dict:
    call = message.get("call") or {}
    ctx = {"call_id": call.get("id"), "caller": (call.get("customer") or {}).get("number")}
    results = []
    for tc in _extract_tool_calls(message):
        name = tc.get("name") or (tc.get("function") or {}).get("name")
        args = _as_dict(tc.get("arguments") or (tc.get("function") or {}).get("arguments"))
        handler = TOOLS.get(name)
        try:
            out = handler(args, ctx) if handler else {"error": f"unknown tool {name}"}
        except Exception:  # last-resort guard: never leave the caller in silence
            log.exception("tool %s crashed", name)
            out = {"success": False, "error_type": "system",
                   "instruction": "Apologize for a technical problem and offer to try again."}
        log.info("tool=%s call_id=%s ok=%s", name, ctx["call_id"], out.get("success", out.get("valid", out.get("found"))))
        results.append({"name": name, "toolCallId": tc.get("id"), "result": json.dumps(out)})
    return {"results": results}


def _handle_end_of_call(message: dict) -> dict:
    call = message.get("call") or {}
    call_id = call.get("id")
    if not call_id:
        return {}
    artifact = message.get("artifact") or {}
    transcript = artifact.get("transcript") or message.get("transcript")
    summary = (message.get("analysis") or {}).get("summary") or message.get("summary")
    ended = message.get("endedReason")
    try:
        with SessionLocal() as db:
            services.save_call_report(db, call_id, (call.get("customer") or {}).get("number"), ended, summary, transcript)
    except Exception:
        log.exception("failed to store call report")
    log.info("CALL_ENDED call_id=%s reason=%s summary=%s", call_id, ended, summary)
    return {}


@router.post("/webhook")
async def vapi_webhook(request: Request, x_vapi_secret: Optional[str] = Header(default=None)):
    if VAPI_WEBHOOK_SECRET and not secrets.compare_digest(x_vapi_secret or "", VAPI_WEBHOOK_SECRET):
        return JSONResponse(status_code=401, content={"error": "invalid webhook secret"})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})
    message = body.get("message") or {}
    mtype = message.get("type")
    if mtype == "tool-calls":
        return _handle_tool_calls(message)
    if mtype == "end-of-call-report":
        return _handle_end_of_call(message)
    return {}  # status-update, transcript, etc. - acknowledged and ignored
