"""FastAPI application: visitor API, IIIF, staff API, health checks."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from archive import __version__, storage, tracing
from archive.api import iiif, staff, visitor
from archive.config import get_settings
from archive.db import db_healthy, get_engine
from archive.logging_setup import configure_logging
from archive.search.models import get_embedder, get_reranker, model_status

settings = get_settings()
configure_logging(settings.log_level)
log = logging.getLogger("archive.api")

def _warm_models() -> None:
    """Load the embedding and reranking models before the first visitor query (first Ask was ~22 s cold)."""
    t0 = time.perf_counter()
    try:
        get_embedder().embed_query("warm up")
        get_reranker().score("warm up", ["warm up"])
        log.info("models warm", extra={"ms": int((time.perf_counter() - t0) * 1000)})
    except Exception:  # noqa: BLE001 - warm-up is best effort; search loads models lazily anyway
        log.exception("model warm-up failed; models will load on first use")


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.ensure_roots()
    threading.Thread(target=_warm_models, name="model-warmup", daemon=True).start()
    yield


app = FastAPI(title="Ambedkar Digital Heritage Archive - Edge API", version=__version__,
              docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = int((time.perf_counter() - t0) * 1000)
    response.headers["x-request-id"] = rid
    if not request.url.path.startswith("/api/health"):
        log.info("request", extra={"request_id": rid, "method": request.method, "path": request.url.path,
                                   "status": response.status_code, "ms": ms})
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", extra={"path": request.url.path})
    return JSONResponse({"detail": "Internal error. The request was logged."}, status_code=500)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness: the process is up."""
    return {"status": "ok", "version": __version__}


@app.get("/api/health/ready")
def ready() -> JSONResponse:
    """Readiness: database reachable, migrations applied, storage writable."""
    checks: dict[str, Any] = {"database": db_healthy()}
    try:
        with get_engine().connect() as conn:
            checks["migration"] = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        checks["migration"] = None
    try:
        probe = settings.derivative_root / ".ready"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok")
        checks["storage"] = True
    except OSError:
        checks["storage"] = False
    checks["models"] = model_status()
    checks["trace_backend"] = tracing.backend_name()
    checks["sarvam_configured"] = settings.sarvam_available
    checks["llm_configured"] = settings.llm_available
    ok = bool(checks["database"] and checks["migration"] and checks["storage"])
    return JSONResponse({"status": "ready" if ok else "not_ready", **checks}, status_code=200 if ok else 503)


app.include_router(visitor.router)
app.include_router(iiif.router)
app.include_router(staff.router)
