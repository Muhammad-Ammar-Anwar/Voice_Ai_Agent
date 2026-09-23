"""
Single source of truth for field validation.

Used by BOTH the REST API (via Pydantic schemas) and the voice agent's
`validate_field` tool, so a value the agent accepts on the phone is guaranteed
to be accepted by the API, and vice versa.

Every InvalidValue message is written so the LLM can turn it directly into a
spoken re-prompt ("That phone number only had 9 digits...").
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Callable

FORMAT_HINT_DOB = "MM/DD/YYYY"


class InvalidValue(ValueError):
    """A value failed validation. The message is safe to relay to the caller."""


US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT "
    "NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WI WY DC "
    "PR VI GU AS MP".split()
)
SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")

_LETTER = r"[^\W\d_]"  # any unicode letter (so "José" and "Nguyễn" work)
_NAME_RE = re.compile(rf"^{_LETTER}+(?:[ '’\-]{_LETTER}+)*$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
_MEMBER_ID_RE = re.compile(r"^[A-Za-z0-9]{1,50}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_SEX_ALIASES = {
    "male": "Male", "m": "Male", "man": "Male",
    "female": "Female", "f": "Female", "woman": "Female",
    "other": "Other", "non-binary": "Other", "nonbinary": "Other",
    "decline to answer": "Decline to Answer", "decline": "Decline to Answer",
    "prefer not to say": "Decline to Answer", "prefer not to answer": "Decline to Answer",
}


def _s(v: Any) -> str:
    """Coerce to a stripped, control-char-free, single-spaced string."""
    if v is None:
        return ""
    return re.sub(r"\s+", " ", _CONTROL_RE.sub(" ", str(v))).strip()


# ---- individual validators -------------------------------------------------

def clean_name(v: Any, label: str = "Name") -> str:
    s = _s(v)
    if not s:
        raise InvalidValue(f"{label} is required")
    if len(s) > 50:
        raise InvalidValue(f"{label} must be 50 characters or fewer")
    if not _NAME_RE.match(s):
        raise InvalidValue(f"{label} may only contain letters, hyphens and apostrophes")
    return s


def clean_dob(v: Any) -> date:
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    else:
        s = _s(v)
        if not s:
            raise InvalidValue("Date of birth is required")
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
        else:
            raise InvalidValue(
                f"'{s}' is not a real calendar date. Use {FORMAT_HINT_DOB} with a 4-digit year"
            )
    if d > datetime.now(timezone.utc).date():
        raise InvalidValue("Date of birth cannot be in the future")
    if d.year < 1900:
        raise InvalidValue("Date of birth year is before 1900; please confirm the year")
    return d


def clean_sex(v: Any) -> str:
    s = _s(v).lower()
    if not s:
        raise InvalidValue("Sex is required")
    if s in _SEX_ALIASES:
        return _SEX_ALIASES[s]
    raise InvalidValue(f"Sex must be one of: {', '.join(SEX_VALUES)}")


def clean_phone(v: Any, label: str = "Phone number") -> str:
    digits = re.sub(r"\D", "", _s(v))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]  # drop U.S. country code
    if len(digits) != 10:
        raise InvalidValue(f"{label} must be a 10-digit U.S. number; it had {len(digits)} digits")
    return digits


def clean_email(v: Any) -> str:
    s = _s(v).lower().replace(" ", "")
    if len(s) > 254 or not _EMAIL_RE.match(s):
        raise InvalidValue("Email address is not in a valid format (name@domain.com)")
    return s


def clean_text(v: Any, label: str, max_len: int, required: bool = True) -> str:
    s = _s(v)
    if not s:
        raise InvalidValue(f"{label} is required")
    if len(s) > max_len:
        raise InvalidValue(f"{label} must be {max_len} characters or fewer")
    if re.search(r"[<>{}]", s):  # cheap defense-in-depth against markup injection
        raise InvalidValue(f"{label} contains characters that are not allowed")
    return s


def clean_state(v: Any) -> str:
    s = _s(v).upper()
    if s not in US_STATES:
        raise InvalidValue("State must be a valid 2-letter U.S. state abbreviation (e.g. TX)")
    return s


def clean_zip(v: Any) -> str:
    s = _s(v).replace(" ", "")
    if not _ZIP_RE.match(s):
        raise InvalidValue("ZIP code must be 5 digits (or ZIP+4 like 12345-6789)")
    return s


def clean_member_id(v: Any) -> str:
    s = re.sub(r"[\s\-]", "", _s(v))
    if not _MEMBER_ID_RE.match(s):
        raise InvalidValue("Insurance member ID must be letters and numbers only")
    return s


def clean_language(v: Any) -> str:
    s = _s(v)
    if not s:
        return "English"
    if len(s) > 50 or not _NAME_RE.match(s):
        raise InvalidValue("Preferred language must be a language name, e.g. Spanish")
    return s.title()


# ---- field registry --------------------------------------------------------

REQUIRED_FIELDS = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)
OPTIONAL_FIELDS = (
    "email", "address_line_2", "insurance_provider", "insurance_member_id",
    "preferred_language", "emergency_contact_name", "emergency_contact_phone",
)
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "first_name": lambda v: clean_name(v, "First name"),
    "last_name": lambda v: clean_name(v, "Last name"),
    "date_of_birth": clean_dob,
    "sex": clean_sex,
    "phone_number": clean_phone,
    "email": clean_email,
    "address_line_1": lambda v: clean_text(v, "Street address", 200),
    "address_line_2": lambda v: clean_text(v, "Address line 2", 100),
    "city": lambda v: clean_text(v, "City", 100),
    "state": clean_state,
    "zip_code": clean_zip,
    "insurance_provider": lambda v: clean_text(v, "Insurance provider", 100),
    "insurance_member_id": clean_member_id,
    "preferred_language": clean_language,
    "emergency_contact_name": lambda v: clean_name(v, "Emergency contact name"),
    "emergency_contact_phone": lambda v: clean_phone(v, "Emergency contact phone"),
}


def validate_field(field: str, value: Any) -> Any:
    """
    Validate + normalize one field. Blank optional fields become None
    (preferred_language becomes "English"); blank required fields raise.
    """
    if field not in _VALIDATORS:
        raise InvalidValue(f"Unknown field '{field}'")
    if field == "preferred_language":
        return clean_language(value)
    if _s(value) == "" and not isinstance(value, date) and field in OPTIONAL_FIELDS:
        return None
    return _VALIDATORS[field](value)


def display_value(v: Any) -> Any:
    """Human/LLM-friendly representation of a normalized value."""
    return v.strftime("%m/%d/%Y") if isinstance(v, date) else v
