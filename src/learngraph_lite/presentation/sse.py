"""Public run DTO and SSE encoding helpers.

The application layer owns run lifecycle state. This module only projects that
state into browser-safe dictionaries and Server-Sent Event frames.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from learngraph_lite.application.agent import RunEvent, RunRecord


def public_run(record: RunRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": record.run_id,
        "session_id": record.session_id,
        "root_task_id": record.root_task_id,
        "status": record.status,
        "summary": record.summary,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "user_text": record.user_text,
        "mode": record.mode,
        "partial_text": record.partial_text,
        "tool_activity": deepcopy(record.tool_activity),
    }
    if record.goal_id is not None:
        payload["goal_id"] = record.goal_id
        payload["node_id"] = record.node_id
    if record.final_text:
        payload["final_text"] = record.final_text
    if record.task_ref is not None:
        payload["task_ref"] = record.task_ref
    if record.error:
        payload["error"] = record.error
    if record.usage:
        payload["usage"] = dict(record.usage)
    if record.output:
        payload["output"] = deepcopy(record.output)
    return payload


def public_run_event(event: RunEvent) -> dict[str, Any]:
    payload = deepcopy(event.payload)
    return {
        "run_id": event.run_id,
        "seq": event.seq,
        "type": event.type,
        "schema_version": 1,
        "timestamp": event.created_at.isoformat(),
        "payload": payload,
    }


def encode_sse(event: RunEvent) -> str:
    public = public_run_event(event)
    data = json.dumps(public, ensure_ascii=False, sort_keys=True)
    return f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n"


def encode_snapshot(record: RunRecord, seq: int) -> str:
    event = RunEvent(
        run_id=record.run_id,
        seq=seq,
        type="run.snapshot",
        payload=public_run(record),
    )
    return encode_sse(event)
