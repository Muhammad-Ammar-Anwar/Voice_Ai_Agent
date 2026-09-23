"""Consistent JSON envelope: { "data": ..., "error": ... } for every REST response."""
from typing import Any, Optional

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def ok(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"data": jsonable_encoder(data), "error": None})


def fail(status_code: int, code: str, message: str, details: Optional[list] = None) -> JSONResponse:
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"data": None, "error": error})


def format_validation_errors(errors: list[dict]) -> list[dict]:
    """Turn Pydantic error dicts into [{field, message}] (also reused by the voice tools)."""
    out = []
    for e in errors:
        loc = [str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path")]
        msg = str(e.get("msg", "invalid")).removeprefix("Value error, ")
        if e.get("type") == "missing":
            msg = "This field is required"
        out.append({"field": ".".join(loc) or "body", "message": msg})
    return out
