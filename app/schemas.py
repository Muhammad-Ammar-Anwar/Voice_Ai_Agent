"""Pydantic schemas: request validation (Create/Update) and response shape (Out)."""
from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from app.validators import ALL_FIELDS, InvalidValue, validate_field


class _PatientInput(BaseModel):
    # Reject unknown keys so typos ("phone" vs "phone_number") fail loudly.
    model_config = ConfigDict(extra="forbid")

    @field_validator(*ALL_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _run_shared_validator(cls, v, info):
        try:
            return validate_field(info.field_name, v)
        except InvalidValue as e:
            raise ValueError(str(e))


class PatientCreate(_PatientInput):
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    address_line_1: str
    city: str
    state: str
    zip_code: str
    email: Optional[str] = None
    address_line_2: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: str = "English"
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class PatientUpdate(_PatientInput):
    """Partial update: only fields present in the request body are changed."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[date] = None
    sex: Optional[str] = None
    phone_number: Optional[str] = None
    address_line_1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    email: Optional[str] = None
    address_line_2: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_member_id: Optional[str] = None
    preferred_language: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


def _utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops tzinfo; everything we store is UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: Optional[str]
    address_line_1: str
    address_line_2: Optional[str]
    city: str
    state: str
    zip_code: str
    insurance_provider: Optional[str]
    insurance_member_id: Optional[str]
    preferred_language: str
    emergency_contact_name: Optional[str]
    emergency_contact_phone: Optional[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    @field_serializer("date_of_birth")
    def _dob(self, v: date) -> str:
        return v.strftime("%m/%d/%Y")

    @field_serializer("created_at", "updated_at", "deleted_at")
    def _ts(self, v: Optional[datetime]) -> Optional[str]:
        return _utc_iso(v)
