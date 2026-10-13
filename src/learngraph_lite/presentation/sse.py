"""Public run DTO and SSE encoding helpers.

The application layer owns run lifecycle state. This module only projects that
state into browser-safe dictionaries and Server-Sent Event frames.
"""

from __future__ import annotations

import json
from typing import Any

from learngraph_lite.application.agent import RunEvent, RunRecord


def public_run(record: RunRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": record.run_id,
        "session_id": record.session_id,
        "status": record.status,
        "summary": record.summary,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
    if record.final_text:
        payload["final_text"] = record.final_text
    if record.error:
        payload["error"] = record.error
    if record.usage:
        payload["usage"] = dict(record.usage)
    return payload


def public_run_event(event: RunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    return {
        "run_id": event.run_id,
        "seq": event.seq,
        "type": event.type,
        "created_at": event.created_at.isoformat(),
        "payload": payload,
    }


def encode_sse(event: RunEvent) -> str:
    public = public_run_event(event)
    data = json.dumps(public, ensure_ascii=False, sort_keys=True)
    return f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n"
