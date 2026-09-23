"""
Data-access / service layer.

The REST routes AND the voice-agent tool handlers both call these functions,
so business rules live in exactly one place (the spec allows either approach;
sharing the service layer avoids the agent making HTTP calls to itself).
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CallLog, Patient
from app.schemas import PatientCreate, PatientUpdate


def create_patient(db: Session, data: PatientCreate) -> Patient:
    patient = Patient(**data.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def get_patient(db: Session, patient_id: str) -> Optional[Patient]:
    stmt = select(Patient).where(Patient.patient_id == patient_id, Patient.deleted_at.is_(None))
    return db.scalars(stmt).first()


def list_patients(
    db: Session,
    last_name: Optional[str] = None,
    date_of_birth: Optional[date] = None,
    phone_number: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Patient]:
    stmt = select(Patient).where(Patient.deleted_at.is_(None))
    if last_name:
        stmt = stmt.where(func.lower(Patient.last_name) == last_name.strip().lower())
    if date_of_birth:
        stmt = stmt.where(Patient.date_of_birth == date_of_birth)
    if phone_number:
        stmt = stmt.where(Patient.phone_number == phone_number)
    stmt = stmt.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def find_by_phone(db: Session, phone_number: str) -> Optional[Patient]:
    """Most recently registered active patient with this phone (duplicate detection)."""
    return next(iter(list_patients(db, phone_number=phone_number, limit=1)), None)


def update_patient(db: Session, patient_id: str, data: PatientUpdate) -> Optional[Patient]:
    patient = get_patient(db, patient_id)
    if patient is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    db.commit()
    db.refresh(patient)
    return patient


def soft_delete_patient(db: Session, patient_id: str) -> Optional[Patient]:
    patient = get_patient(db, patient_id)
    if patient is None:
        return None
    patient.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(patient)
    return patient


# ---- call logs -------------------------------------------------------------

def _get_or_create_call(db: Session, call_id: str, caller_number: Optional[str] = None) -> CallLog:
    log = db.scalars(select(CallLog).where(CallLog.call_id == call_id)).first()
    if log is None:
        log = CallLog(call_id=call_id, caller_number=caller_number)
        db.add(log)
    return log


def link_call_to_patient(db: Session, call_id: str, patient_id: str, caller_number: Optional[str] = None) -> None:
    log = _get_or_create_call(db, call_id, caller_number)
    log.patient_id = patient_id
    db.commit()


def save_call_report(
    db: Session, call_id: str, caller_number: Optional[str], ended_reason: Optional[str],
    summary: Optional[str], transcript: Optional[str],
) -> None:
    log = _get_or_create_call(db, call_id, caller_number)
    log.ended_reason, log.summary, log.transcript = ended_reason, summary, transcript
    db.commit()
