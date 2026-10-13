"""HTTP lifecycle adapter; model execution and terminal state belong to AgentLoop."""

from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from learngraph_lite.application.agent import AgentLoop, RunAdmissionError, RunRequest, TERMINAL_STATUSES
from learngraph_lite.presentation.sse import encode_snapshot, encode_sse, public_run


Identifier = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128)]


class SubmitRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: Identifier
    user_text: str = Field(strict=True, min_length=1, max_length=16000)

    @field_validator("user_text")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_text must contain text")
        return value


class PublicRun(BaseModel):
    run_id: str
    session_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "budget_exceeded"]
    summary: str
    created_at: datetime
    updated_at: datetime
    final_text: str | None = None
    error: str | None = None
    usage: dict[str, int] | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    run_id: str | None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def _error(status: int, code: str, message: str, *, retryable: bool = False, run_id: str | None = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "retryable": retryable, "run_id": run_id}},
    )


def create_app(
    loop: AgentLoop,
    *,
    model_mode: Literal["fixture", "real"] = "fixture",
    model_configured: bool = False,
    heartbeat_seconds: float = 15.0,
) -> FastAPI:
    """Create a process-local API, with cooperative shutdown and snapshot-first SSE."""
    if not math.isfinite(heartbeat_seconds) or heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be finite and positive")
    if model_mode not in {"fixture", "real"}:
        raise ValueError("model_mode must be fixture or real")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            await asyncio.to_thread(loop.close)

    app = FastAPI(
        title="LearnGraph Lite", version="0.1.0", lifespan=lifespan,
        responses={422: {"model": ErrorEnvelope}},
    )

    @app.middleware("http")
    async def local_request_boundary(request: Request, call_next):
        try:
            hostname = request.url.hostname
        except ValueError:
            hostname = None
        if hostname not in {"127.0.0.1", "localhost", "::1"}:
            return _error(400, "untrusted_host", "Only local hosts are allowed.")
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin is not None:
            expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if origin != expected_origin:
                return _error(403, "untrusted_origin", "Write requests must use the same origin.")
        return await call_next(request)

    @app.exception_handler(RunAdmissionError)
    async def admission_error(request: Request, exc: RunAdmissionError):
        status = {"session_busy": 409, "capacity_exceeded": 429, "idempotency_conflict": 409, "shutting_down": 503}
        return _error(
            status[exc.code], exc.code, str(exc),
            retryable=exc.code in {"session_busy", "capacity_exceeded", "shutting_down"},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return _error(422, "invalid_request", "Invalid request parameters.")

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/model/status")
    async def model_status():
        return {"mode": model_mode, "configured": model_configured and model_mode == "real"}

    @app.post("/api/sessions/{session_id}/runs", status_code=202, response_model=PublicRun,
              response_model_exclude_none=True,
              responses={code: {"model": ErrorEnvelope} for code in (409, 429, 503)})
    async def submit_run(session_id: Identifier, body: SubmitRun):
        record = loop.submit(RunRequest(
            session_id=session_id, user_text=body.user_text, idempotency_key=body.request_id,
        ))
        return public_run(record)

    @app.get("/api/runs/{run_id}", response_model=PublicRun, response_model_exclude_none=True,
             responses={404: {"model": ErrorEnvelope}})
    async def get_run(run_id: Identifier):
        try:
            return public_run(loop.get_run(run_id))
        except KeyError:
            return _error(404, "run_not_found", "Run does not exist.", run_id=run_id)

    @app.post("/api/runs/{run_id}/cancel", response_model=PublicRun, response_model_exclude_none=True,
              responses={404: {"model": ErrorEnvelope}})
    async def cancel_run(run_id: Identifier):
        try:
            return public_run(loop.cancel(run_id))
        except KeyError:
            return _error(404, "run_not_found", "Run does not exist.", run_id=run_id)

    @app.get("/api/runs/{run_id}/events", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}}}, 404: {"model": ErrorEnvelope}})
    async def run_events(run_id: Identifier, request: Request):
        try:
            record, cursor = loop.snapshot(run_id)
        except KeyError:
            return _error(404, "run_not_found", "Run does not exist.", run_id=run_id)

        async def stream():
            nonlocal cursor
            yield encode_snapshot(record, cursor)
            if record.status in TERMINAL_STATUSES:
                return
            while not await request.is_disconnected():
                events = await asyncio.to_thread(loop.wait_events, run_id, cursor, heartbeat_seconds)
                for event in events:
                    yield encode_sse(event)
                    cursor = event.seq
                # Read status and cursor together so a concurrent terminal event cannot be skipped.
                latest, latest_seq = loop.snapshot(run_id)
                if latest.status in TERMINAL_STATUSES and cursor >= latest_seq:
                    return
                if not events:
                    yield ": heartbeat\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
