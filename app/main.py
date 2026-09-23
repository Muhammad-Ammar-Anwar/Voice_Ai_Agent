"""FastAPI entrypoint: wires the REST API, Vapi webhook, dashboard, and error handling."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.database import Base, SessionLocal, engine
from app.envelope import fail, format_validation_errors, ok
from app.routers import patients, vapi
from app.seed import seed_if_empty

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("patient-agent")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # simple bootstrap; use Alembic for real migrations
    if config.SEED_DEMO_DATA:
        seed_if_empty()
    log.info("Ready. DB=%s", engine.url.render_as_string(hide_password=True))
    yield


app = FastAPI(title="Patient Registration API", version="1.0.0", lifespan=lifespan)
app.include_router(patients.router)
app.include_router(vapi.router)


# ---- error handling: always the { data, error } envelope -------------------

@app.exception_handler(RequestValidationError)
async def on_validation_error(_: Request, exc: RequestValidationError):
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        return fail(400, "bad_json", "Request body is not valid JSON")
    details = format_validation_errors(errors)
    if all(e.get("loc", ("",))[0] in ("query", "path") for e in errors):
        return fail(400, "bad_request", "Invalid query or path parameter", details)
    return fail(422, "validation_error", "One or more fields are invalid", details)


@app.exception_handler(StarletteHTTPException)
async def on_http_error(_: Request, exc: StarletteHTTPException):
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return fail(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def on_unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return fail(500, "internal_error", "Something went wrong on our side")


# ---- misc routes -----------------------------------------------------------

@app.get("/health", tags=["meta"])
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return ok({"status": "ok"})


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).parent.parent / "static" / "dashboard.html")


@app.get("/", include_in_schema=False)
def root():
    return ok({"service": "patient-registration", "docs": "/docs", "dashboard": "/dashboard", "patients": "/patients"})
