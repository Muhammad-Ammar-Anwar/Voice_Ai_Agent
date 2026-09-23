"""REST API for patients. Every response uses the { "data", "error" } envelope."""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.envelope import fail, ok
from app.schemas import PatientCreate, PatientOut, PatientUpdate
from app.validators import InvalidValue, clean_dob, clean_phone

router = APIRouter(prefix="/patients", tags=["patients"])


def _parse_uuid(value: str) -> Optional[str]:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _out(p) -> dict:
    return PatientOut.model_validate(p).model_dump(mode="json")


@router.get("")
def list_patients(
    last_name: Optional[str] = None,
    date_of_birth: Optional[str] = Query(None, description="MM/DD/YYYY or YYYY-MM-DD"),
    phone_number: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        dob: Optional[date] = clean_dob(date_of_birth) if date_of_birth else None
        phone = clean_phone(phone_number) if phone_number else None
    except InvalidValue as e:
        return fail(400, "bad_query", str(e))
    rows = services.list_patients(db, last_name, dob, phone, limit, offset)
    return ok([_out(p) for p in rows])


@router.get("/{patient_id}")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    pid = _parse_uuid(patient_id)
    if pid is None:
        return fail(400, "bad_id", "patient_id must be a valid UUID")
    patient = services.get_patient(db, pid)
    if patient is None:
        return fail(404, "not_found", "Patient not found")
    return ok(_out(patient))


@router.post("", status_code=201)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    return ok(_out(services.create_patient(db, payload)), 201)


@router.put("/{patient_id}")
def update_patient(patient_id: str, payload: PatientUpdate, db: Session = Depends(get_db)):
    pid = _parse_uuid(patient_id)
    if pid is None:
        return fail(400, "bad_id", "patient_id must be a valid UUID")
    if not payload.model_dump(exclude_unset=True):
        return fail(400, "empty_update", "Provide at least one field to update")
    patient = services.update_patient(db, pid, payload)
    if patient is None:
        return fail(404, "not_found", "Patient not found")
    return ok(_out(patient))


@router.delete("/{patient_id}")
def delete_patient(patient_id: str, db: Session = Depends(get_db)):
    """Soft delete: sets deleted_at; the row is kept but hidden from all reads."""
    pid = _parse_uuid(patient_id)
    if pid is None:
        return fail(400, "bad_id", "patient_id must be a valid UUID")
    patient = services.soft_delete_patient(db, pid)
    if patient is None:
        return fail(404, "not_found", "Patient not found")
    return ok(_out(patient))
