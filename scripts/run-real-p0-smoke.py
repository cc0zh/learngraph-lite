#!/usr/bin/env python
"""Opt-in, bounded real-model P0 HTTP journey; never part of default CI."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from learngraph_lite.bootstrap import _create_business_app, build_real_gateway


class SmokeFailure(RuntimeError):
    """Only controlled, public diagnostics may enter the report."""


class MeteredGateway:
    """Observe real calls without changing responses; cap the entire journey."""

    def __init__(self, gateway, limit=12):
        self.gateway = gateway
        self.limit = limit
        self.calls = 0
        self.usage = {}
        self._lock = Lock()

    def _take(self):
        with self._lock:
            if self.calls >= self.limit:
                raise SmokeFailure("smoke model-call limit reached")
            self.calls += 1

    def _record(self, response):
        with self._lock:
            for key, value in response.usage.items():
                self.usage[key] = self.usage.get(key, 0) + value
        return response

    def complete(self, messages, tools):
        self._take()
        return self._record(self.gateway.complete(messages, tools))

    def stream_complete(self, messages, tools, on_delta):
        self._take()
        return self._record(self.gateway.stream_complete(messages, tools, on_delta))

    def close(self):
        self.gateway.close()


def checked(api, method, path, *, status=200, body=None):
    response = api.request(method, path, **({"json": body} if body is not None else {}))
    if response.status_code != status:
        raise SmokeFailure(f"{method} {path}: expected HTTP {status}, got {response.status_code}")
    return response.json()


def completed(api, report, phase, path, body):
    started = monotonic()
    admitted = checked(api, "POST", path, status=202, body=body)
    run_id = admitted["run_id"]
    # This consumes the actual API event stream until its terminal state.
    events = api.get(f"/api/runs/{run_id}/events")
    if events.status_code != 200:
        raise SmokeFailure(f"{phase}: SSE unavailable")
    frames = [json.loads(line[6:]) for line in events.text.splitlines() if line.startswith("data: ")]
    run = checked(api, "GET", f"/api/runs/{run_id}")
    report["runs"].append({"phase": phase, "run_id": run_id, "status": run["status"],
        "elapsed_seconds": round(monotonic() - started, 3), "usage": run.get("usage", {}),
        "event_types": sorted({frame["type"] for frame in frames}),
        "tools": [{"name": item["name"], "status": item["status"]}
                  for item in run.get("tool_activity", {}).values()]})
    if run["status"] != "completed":
        raise SmokeFailure(f"{phase}: {run['status']}; {run.get('error', 'no public error')}")
    if not frames or frames[0]["type"] != "run.snapshot":
        raise SmokeFailure(f"{phase}: initial SSE snapshot missing")
    return run


def journey(factory, report):
    """Drive production HTTP; the caller chooses real mode or an offline test fixture."""
    report.setdefault("runs", [])
    report.setdefault("checks", [])
    with TestClient(factory(), base_url="http://localhost") as api:
        model = checked(api, "GET", "/api/model/status")
        if model["mode"] != report["mode"]:
            raise SmokeFailure("model mode does not match report")
        plan = checked(api, "POST", "/api/goals", status=201,
            body={"title": "理解 Python 列表与元组的区别"})
        goal = plan["goal_id"]
        report["goal_id"] = goal
        completed(api, report, "clarify", f"/api/goals/{goal}/clarify",
            {"request_id": "real-p0-clarify", "expected_version": plan["version"]})
        plan = checked(api, "GET", f"/api/goals/{goal}")
        if plan["goal"]["confirmed"] or not plan["questions"]:
            raise SmokeFailure("clarification must ask questions without confirming the goal")
        plan = checked(api, "PATCH", f"/api/goals/{goal}", body={"expected_version": plan["version"],
            "desired_outcome": "能说明可变性差异并为简单场景选择列表或元组",
            "current_level": "会 Python 变量与基本语法", "time_budget_minutes": 60})
        plan = checked(api, "POST", f"/api/goals/{goal}/confirm",
            body={"expected_version": plan["version"]})
        completed(api, report, "graph", f"/api/goals/{goal}/graph-drafts",
            {"request_id": "real-p0-graph", "expected_version": plan["version"], "node_count": 3})
        plan = checked(api, "GET", f"/api/goals/{goal}")
        graph = plan["graph"]
        if graph["status"] != "draft" or len(graph["nodes"]) != 3:
            raise SmokeFailure("model graph must remain a three-node draft for user review")
        # Explicit human-equivalent review/edit/publish, never a model tool decision.
        nodes = graph["nodes"]
        nodes[0]["title"] += "（已审核）"
        plan = checked(api, "PATCH", f"/api/goals/{goal}/graph",
            body={"expected_version": plan["version"], "nodes": nodes, "edges": graph["edges"]})
        plan = checked(api, "POST", f"/api/goals/{goal}/graph/publish",
            body={"expected_version": plan["version"], "expected_revision": plan["graph"]["revision"]})
        incoming = {edge["target"] for edge in plan["graph"]["edges"]}
        node = next(item["id"] for item in plan["graph"]["nodes"] if item["id"] not in incoming)
        report["node_id"] = node
        session = f"real-p0:{goal}"
        report["session_id"] = session
        path = f"/api/sessions/{session}/runs"
        command = {"request_id": "real-p0-teaching", "mode": "teaching", "goal_id": goal, "node_id": node,
            "user_text": "能举个简单的例子讲讲，再出一道单选练习让我试试吗？"}
        teaching = completed(api, report, "teaching", path, command)
        tools = teaching.get("tool_activity", {}).values()
        if not any(item["name"] == "create_exercise" and item["status"] == "completed" for item in tools):
            raise SmokeFailure("teaching did not actually complete create_exercise")
        if not teaching.get("final_text"):
            raise SmokeFailure("teaching returned no final answer")
        duplicate = checked(api, "POST", path, status=202, body=command)
        if duplicate["run_id"] != teaching["run_id"]:
            raise SmokeFailure("duplicate request did not reuse the teaching run")
        exercises_path = f"/api/goals/{goal}/nodes/{node}/exercises"
        listing = checked(api, "GET", exercises_path)
        if len(listing["exercises"]) != 1:
            raise SmokeFailure("teaching did not persist exactly one exercise")
        exercise = listing["exercises"][0]
        if "correct_option_id" in exercise or "explanation" in exercise:
            raise SmokeFailure("public exercise contains a private answer")
        # Select a public option, not a private answer. Correctness is not pre-assumed.
        answer = {"submission_id": "real-p0-answer", "selected_option_id": exercise["options"][0]["id"]}
        attempts = f"/api/goals/{goal}/exercises/{exercise['id']}/attempts"
        feedback = checked(api, "POST", attempts, body=answer)
        if not feedback["attempt"]["counted"] or not feedback["explanation"]:
            raise SmokeFailure("first answer was not counted or has no feedback")
        if checked(api, "POST", attempts, body=answer) != feedback:
            raise SmokeFailure("duplicate submission changed the feedback")
        context_path = f"/api/goals/{goal}/nodes/{node}/context"
        context = checked(api, "GET", context_path)
        if context["node"]["sample_count"] != 1:
            raise SmokeFailure("duplicate submission changed mastery sample count")
        recommendation = checked(api, "GET", f"/api/goals/{goal}/nodes/{node}/next-action")
        if not recommendation["reason_text"]:
            raise SmokeFailure("next-action recommendation has no reason")
        completed(api, report, "button-exercise", exercises_path,
            {"session_id": session, "request_id": "real-p0-button", "count": 1, "purpose": "practice"})
        listing = checked(api, "GET", exercises_path)
        if len(listing["exercises"]) != 2:
            raise SmokeFailure("button did not persist a separate exercise")
        report["checks"].extend(["explicit-confirm-edit-publish", "native-teaching-exercise",
            "request-id-reuse", "private-answer-isolation", "answer-feedback",
            "submission-id-reuse", "mastery-and-next-action", "button-exercise"])

    # Reopen the same SQLite with zero permitted provider calls: no automatic rerun.
    with TestClient(factory(restore=True), base_url="http://localhost") as api:
        if checked(api, "GET", context_path) != context:
            raise SmokeFailure("learning context changed across restart")
        if checked(api, "GET", exercises_path) != listing:
            raise SmokeFailure("exercises or feedback changed across restart")
        old = checked(api, "GET", f"/api/runs/{teaching['run_id']}")
        if old != teaching:
            raise SmokeFailure("completed teaching run changed across restart")
        if checked(api, "POST", path, status=202, body=command)["run_id"] != teaching["run_id"]:
            raise SmokeFailure("restart lost request idempotency")
        if "event: run.snapshot" not in api.get(f"/api/runs/{teaching['run_id']}/events").text:
            raise SmokeFailure("restart lost SSE snapshot")
        report["checks"].append("sqlite-reopen-without-model-calls")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="New isolated SQLite file; refuses to overwrite")
    parser.add_argument("--report", type=Path, help="Sanitized JSON evidence (default under .local)")
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    database = args.database or Path(".local") / f"real-p0-{stamp}.sqlite3"
    report_path = args.report or Path(".local") / f"real-p0-{stamp}.json"
    if database.exists() or report_path.exists():
        parser.error("database/report must be new files; existing files are never overwritten")
    report = {"suite": "real-p0-http", "mode": "real", "timestamp": stamp, "status": "failed",
        "scope": "One HTTP journey; browser fixture tests and model quality assessment are separate",
        "model_call_limit": 12, "runs": [], "checks": []}
    meters = []

    def factory(restore=False):
        gateway = build_real_gateway()
        report["model"] = os.environ["MODEL_NAME"]
        report["provider_host"] = urlsplit(os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1")).hostname
        report["timeout_seconds"] = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "30"))
        report["max_output_tokens"] = int(os.environ.get("MODEL_MAX_OUTPUT_TOKENS", "4096"))
        meter = MeteredGateway(gateway, limit=0 if restore else 12)
        meters.append(meter)
        return _create_business_app(meter, "real", database)

    try:
        journey(factory, report)
        report["status"] = "passed"
    except Exception as exc:
        # Never print raw SDK exceptions, request headers, prompts or dotenv values.
        report["error"] = str(exc) if isinstance(exc, SmokeFailure) else type(exc).__name__
    finally:
        report["model_calls"] = sum(meter.calls for meter in meters)
        report["restore_model_calls"] = sum(meter.calls for meter in meters[1:])
        report["usage"] = meters[0].usage if meters else {}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"REAL P0 HTTP {report['status']}: calls={report['model_calls']}; report={report_path}")
    if report["status"] != "passed":
        print(report["error"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
