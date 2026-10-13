from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator

import httpx
import uvicorn
from fastapi.testclient import TestClient

from learngraph_lite.agent_core import (
    AgentRunner,
    ModelResponse,
    TextMessage,
    Tool,
    ToolCall,
    ToolRegistry,
)
from learngraph_lite.application.agent import AgentLoop
from learngraph_lite.presentation.http import create_app


def _loop(model, tools: ToolRegistry | None = None) -> AgentLoop:
    return AgentLoop(AgentRunner(model, tools or ToolRegistry()))


def _error(response: httpx.Response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "retryable", "run_id"}
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["retryable"], bool)
    return error


def _wait_for(
    predicate, *, timeout: float = 3.0, message: str = "condition was not met"
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), message


def _wait_status(client: TestClient, run_id: str, status: str) -> dict:
    result: dict = {}
    _wait_for(
        lambda: _status_is(client, run_id, status, result),
        message=f"run {run_id} did not reach {status}",
    )
    return result


def _status_is(client: TestClient, run_id: str, status: str, result: dict) -> bool:
    response = client.get(f"/api/runs/{run_id}")
    if response.status_code != 200:
        return False
    result.clear()
    result.update(response.json())
    return result.get("status") == status


def _sse_frames(chunks: Iterator[str]) -> Iterator[dict | str]:
    pending = ""
    for chunk in chunks:
        pending += chunk
        while "\n\n" in pending:
            frame, pending = pending.split("\n\n", 1)
            if frame.startswith(": heartbeat"):
                yield "heartbeat"
                continue
            data = next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
            yield json.loads(data)


class BlockingModel:
    def __init__(self, result: str = "late answer"):
        self.started = threading.Event()
        self.release = threading.Event()
        self.result = result
        self.calls = 0
        self._lock = threading.Lock()

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        with self._lock:
            self.calls += 1
        self.started.set()
        if not self.release.wait(10):
            raise TimeoutError("test model was not released")
        return ModelResponse(content=self.result)


class AnswerModel:
    def __init__(self, text: str = "answer", usage: dict[str, int] | None = None):
        self.text = text
        self.usage = usage or {}

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(content=self.text, usage=self.usage)


class FailingModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        raise RuntimeError("provider failed")


class BudgetModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(tool_calls=(ToolCall(id="repeat", name="echo", arguments="{}"),))


def _echo_tools() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(Tool("echo", "Echo", {"type": "object"}, lambda args: {}))
    return tools


def test_health_model_status_and_prompt_post_is_async_with_public_run_dto():
    model = BlockingModel()
    loop = _loop(model)
    try:
        with TestClient(create_app(loop, model_mode="fixture"), base_url="http://localhost") as client:
            try:
                assert client.get("/api/health").json() == {"status": "ok"}
                assert client.get("/api/model/status").json() == {
                    "mode": "fixture",
                    "configured": False,
                }

                began = time.monotonic()
                response = client.post(
                    "/api/sessions/s1/runs",
                    json={"user_text": "hello", "request_id": "r1"},
                )
                elapsed = time.monotonic() - began
                assert response.status_code == 202, response.text
                assert elapsed < 1.0
                dto = response.json()
                assert set(dto) >= {"run_id", "session_id", "status"}
                assert dto["session_id"] == "s1"
                assert dto["status"] in {"queued", "running"}
                assert model.started.wait(1)
            finally:
                model.release.set()
    finally:
        model.release.set()

    with TestClient(
        create_app(_loop(AnswerModel()), model_mode="real"), base_url="http://localhost"
    ) as client:
        assert client.get("/api/model/status").json() == {"mode": "real", "configured": False}


def test_host_and_origin_policy_rejects_cross_site_requests_but_allows_cli_posts():
    loop = _loop(AnswerModel("ok"))
    with TestClient(create_app(loop), base_url="http://localhost") as client:
        _error(
            client.get("/api/health", headers={"host": "evil.example"}),
            400,
            "untrusted_host",
        )
        _error(
            client.post(
                "/api/sessions/s1/runs",
                headers={"origin": "http://evil.example"},
                json={"user_text": "cross site", "request_id": "origin-1"},
            ),
            403,
            "untrusted_origin",
        )
        same_origin = client.post(
            "/api/sessions/s2/runs",
            headers={"origin": "http://localhost"},
            json={"user_text": "same site", "request_id": "origin-2"},
        )
        assert same_origin.status_code == 202, same_origin.text
        cli_post = client.post(
            "/api/sessions/s3/runs",
            json={"user_text": "no origin", "request_id": "origin-3"},
        )
        assert cli_post.status_code == 202, cli_post.text


def test_idempotency_conflict_and_session_and_global_capacity_admission():
    model = BlockingModel()
    loop = _loop(model)
    try:
        with TestClient(create_app(loop), base_url="http://localhost") as client:
            try:
                first = client.post(
                    "/api/sessions/s1/runs",
                    json={"user_text": "one", "request_id": "same"},
                )
                assert first.status_code == 202
                run_id = first.json()["run_id"]
                assert model.started.wait(1)

                duplicate = client.post(
                    "/api/sessions/s1/runs",
                    json={"user_text": "one", "request_id": "same"},
                )
                assert duplicate.status_code == 202
                assert duplicate.json()["run_id"] == run_id
                assert model.calls == 1

                _error(
                    client.post(
                        "/api/sessions/s1/runs",
                        json={"user_text": "different", "request_id": "same"},
                    ),
                    409,
                    "idempotency_conflict",
                )
                _error(
                    client.post(
                        "/api/sessions/s1/runs",
                        json={"user_text": "two", "request_id": "other"},
                    ),
                    409,
                    "session_busy",
                )

                second = client.post(
                    "/api/sessions/s2/runs",
                    json={"user_text": "two", "request_id": "other"},
                )
                assert second.status_code == 202
                _wait_for(lambda: model.calls == 2, message="second run did not enter the model")
                _error(
                    client.post(
                        "/api/sessions/s3/runs",
                        json={"user_text": "three", "request_id": "third"},
                    ),
                    429,
                    "capacity_exceeded",
                )
            finally:
                model.release.set()
    finally:
        model.release.set()


def test_empty_and_oversized_fields_and_unknown_runs_use_contract_errors():
    loop = _loop(AnswerModel())
    with TestClient(create_app(loop), base_url="http://localhost") as client:
        for body in (
            {"user_text": "", "request_id": "r1"},
            {"user_text": "hello", "request_id": ""},
            {"user_text": "x" * 100_001, "request_id": "r2"},
            {"user_text": "hello", "request_id": "x" * 100_001},
        ):
            _error(
                client.post("/api/sessions/s1/runs", json=body),
                422,
                "invalid_request",
            )

        _error(client.get("/api/runs/missing"), 404, "run_not_found")
        _error(client.post("/api/runs/missing/cancel"), 404, "run_not_found")


def test_cancel_keeps_terminal_state_and_capacity_until_blocking_call_returns():
    model = BlockingModel()
    loop = _loop(model)
    try:
        with TestClient(create_app(loop), base_url="http://localhost") as client:
            try:
                first = client.post(
                    "/api/sessions/s1/runs",
                    json={"user_text": "first", "request_id": "r1"},
                ).json()
                assert model.started.wait(1)
                second = client.post(
                    "/api/sessions/s2/runs",
                    json={"user_text": "second", "request_id": "r2"},
                )
                assert second.status_code == 202
                _wait_for(lambda: model.calls == 2, message="second run did not enter the model")

                cancelled = client.post(f"/api/runs/{first['run_id']}/cancel")
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "cancelled"
                _error(
                    client.post(
                        "/api/sessions/s1/runs",
                        json={"user_text": "retry", "request_id": "after-cancel"},
                    ),
                    409,
                    "session_busy",
                )
                _error(
                    client.post(
                        "/api/sessions/s3/runs",
                        json={"user_text": "third", "request_id": "r3"},
                    ),
                    429,
                    "capacity_exceeded",
                )

                model.release.set()

                def capacity_released() -> bool:
                    response = client.post(
                        "/api/sessions/s1/runs",
                        json={"user_text": "retry", "request_id": "after-cancel"},
                    )
                    assert response.status_code in {202, 409}
                    return response.status_code == 202

                _wait_for(capacity_released, message="worker did not release session capacity")
                loop.close()
                final = loop.get_run(first["run_id"])
                assert final.status == "cancelled"
                assert final.final_text == ""
                events = loop.events(first["run_id"])
                assert [event.type for event in events].count("run.cancelled") == 1
                assert not any(event.type == "run.completed" for event in events)
            finally:
                model.release.set()
    finally:
        model.release.set()


def test_completed_failed_and_budget_exceeded_are_projected_with_usage_and_summary():
    completed_loop = _loop(AnswerModel("done", {"input_tokens": 2, "output_tokens": 3}))
    with TestClient(create_app(completed_loop), base_url="http://localhost") as client:
        run = client.post(
            "/api/sessions/s1/runs",
            json={"user_text": "complete", "request_id": "done"},
        ).json()
        completed = _wait_status(client, run["run_id"], "completed")
        assert completed["final_text"] == "done"
        assert completed["summary"] == "run completed"
        assert completed["usage"] == {"input_tokens": 2, "output_tokens": 3}

    failed_loop = _loop(FailingModel())
    with TestClient(create_app(failed_loop), base_url="http://localhost") as client:
        run = client.post(
            "/api/sessions/s1/runs",
            json={"user_text": "fail", "request_id": "fail"},
        ).json()
        failed = _wait_status(client, run["run_id"], "failed")
        assert "provider failed" in failed["error"]
        assert failed["summary"] == "run failed before producing a result"

    budget_loop = _loop(BudgetModel(), _echo_tools())
    with TestClient(create_app(budget_loop), base_url="http://localhost") as client:
        run = client.post(
            "/api/sessions/s1/runs",
            json={"user_text": "budget", "request_id": "budget"},
        ).json()
        budget = _wait_status(client, run["run_id"], "budget_exceeded")
        assert "budget" in budget["summary"]


def test_testclient_sse_for_terminal_run_is_snapshot_only_and_has_stream_headers():
    loop = _loop(AnswerModel("done"))
    with TestClient(create_app(loop, heartbeat_seconds=0.05), base_url="http://localhost") as client:
        run = client.post(
            "/api/sessions/s1/runs",
            json={"user_text": "stream", "request_id": "stream"},
        ).json()
        completed = _wait_status(client, run["run_id"], "completed")
        with client.stream("GET", f"/api/runs/{run['run_id']}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["x-accel-buffering"] == "no"
            frames = list(_sse_frames(response.iter_text()))
        assert [frame["type"] for frame in frames if isinstance(frame, dict)] == [
            "run.snapshot"
        ]
        snapshot = frames[0]
        assert snapshot["schema_version"] == 1
        assert snapshot["run_id"] == run["run_id"]
        assert snapshot["payload"]["run_id"] == completed["run_id"]
        assert snapshot["payload"]["session_id"] == completed["session_id"]
        assert snapshot["payload"]["status"] == completed["status"]
        assert snapshot["payload"]["summary"] == completed["summary"]
        assert snapshot["payload"]["final_text"] == completed["final_text"]
        assert snapshot["payload"]["created_at"].replace("+00:00", "Z") == completed["created_at"]
        assert snapshot["payload"]["updated_at"].replace("+00:00", "Z") == completed["updated_at"]
        assert snapshot["payload"]["status"] == "completed"


class CloseTrackingLoop(AgentLoop):
    def __init__(self, runner: AgentRunner):
        super().__init__(runner)
        self.closed = False
        self.closed_event = threading.Event()

    def close(self) -> None:
        self.closed = True
        self.closed_event.set()
        super().close()


def test_lifespan_closes_loop_and_real_tcp_sse_supports_disconnect_and_reconnect():
    model = BlockingModel("tcp done")
    loop = CloseTrackingLoop(AgentRunner(model, ToolRegistry()))
    app = create_app(loop, heartbeat_seconds=0.05)
    server = None
    thread = None
    client = None
    try:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="on", log_level="error")
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [probe]}, daemon=True)
        thread.start()
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2.0)
        _wait_for(
            lambda: _tcp_health(client),
            timeout=5.0,
            message="uvicorn did not accept TCP connections",
        )
        run = client.post(
            "/api/sessions/tcp/runs",
            json={"user_text": "tcp", "request_id": "tcp-1"},
        ).json()
        assert model.started.wait(1)

        with client.stream("GET", f"/api/runs/{run['run_id']}/events") as response:
            assert response.status_code == 200
            frames = _sse_frames(response.iter_text())
            snapshot = next(frames)
            assert snapshot["type"] == "run.snapshot"
            assert snapshot["payload"]["status"] in {"queued", "running"}
            assert next(frames) == "heartbeat"

        model.release.set()
        completed = _wait_tcp_status(client, run["run_id"], "completed")
        assert completed["final_text"] == "tcp done"
        assert completed["status"] == "completed"

        with client.stream("GET", f"/api/runs/{run['run_id']}/events") as response:
            frames = list(_sse_frames(response.iter_text()))
        assert [frame["type"] for frame in frames if isinstance(frame, dict)] == [
            "run.snapshot"
        ]
        assert frames[0]["payload"]["status"] == "completed"
        assert len(loop.events(run["run_id"])) == 2
    finally:
        model.release.set()
        if client is not None:
            client.close()
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        assert thread is None or not thread.is_alive()
        probe.close()
        assert loop.closed


class BlockThenToolModel:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.tool_calls = 0

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        self.started.set()
        if not self.release.wait(10):
            raise TimeoutError("shutdown test model was not released")
        return ModelResponse(tool_calls=(ToolCall(id="late", name="late", arguments="{}"),))


def test_tcp_shutdown_cancels_active_sse_before_releasing_blocked_model():
    model = BlockThenToolModel()
    tools = ToolRegistry()
    tools.register(
        Tool("late", "must not run after cancellation", {"type": "object"}, lambda args: _count_tool(model))
    )
    loop = CloseTrackingLoop(AgentRunner(model, tools))
    app = create_app(loop, heartbeat_seconds=0.05)
    server = None
    thread = None
    client = None
    stream = None
    try:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                lifespan="on",
                log_level="error",
                timeout_graceful_shutdown=0.2,
            )
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [probe]}, daemon=True)
        thread.start()
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2.0)
        _wait_for(lambda: _tcp_health(client), timeout=5.0, message="shutdown server did not start")
        run = client.post(
            "/api/sessions/shutdown/runs",
            json={"user_text": "shutdown", "request_id": "shutdown-1"},
        ).json()
        assert model.started.wait(1)
        stream = client.stream("GET", f"/api/runs/{run['run_id']}/events")
        response = stream.__enter__()
        frames = _sse_frames(response.iter_text())
        assert next(frames)["type"] == "run.snapshot"
        assert next(frames) == "heartbeat"

        server.should_exit = True
        assert loop.closed_event.wait(3), "lifespan did not enter loop.close"
        _wait_for(
            lambda: loop.get_run(run["run_id"]).status == "cancelled",
            message="shutdown did not cooperatively cancel the run",
        )
        assert model.tool_calls == 0
        model.release.set()
        assert thread is not None
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert model.tool_calls == 0
    finally:
        model.release.set()
        if stream is not None:
            try:
                stream.__exit__(None, None, None)
            except Exception:
                pass
        if client is not None:
            client.close()
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=3)
        assert thread is None or not thread.is_alive()
        probe.close()


class QueuedLoop(AgentLoop):
    def __init__(self, runner: AgentRunner):
        super().__init__(runner)
        self.execute_release = threading.Event()

    def _execute(self, *args, **kwargs):
        assert self.execute_release.wait(10), "test worker was not released"
        return super()._execute(*args, **kwargs)


def test_real_tcp_stream_receives_started_heartbeat_and_one_terminal_in_order():
    model = BlockingModel("live done")
    loop = QueuedLoop(AgentRunner(model, ToolRegistry()))
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(loop, heartbeat_seconds=0.05),
            host="127.0.0.1",
            port=port,
            lifespan="on",
            log_level="error",
            timeout_graceful_shutdown=0.2,
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [probe]}, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
            _wait_for(lambda: _tcp_health(client), timeout=5)
            response = client.post(
                "/api/sessions/live/runs",
                json={"user_text": "live", "request_id": "live-1"},
            )
            assert response.status_code == 202
            run_id = response.json()["run_id"]
            with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
                frames = _sse_frames(stream.iter_text())
                snapshot = next(frames)
                assert snapshot["type"] == "run.snapshot"
                assert snapshot["payload"]["status"] == "queued"
                loop.execute_release.set()
                assert model.started.wait(1)
                started = next(frame for frame in frames if frame != "heartbeat")
                assert started["type"] == "run.started"
                assert started["seq"] == snapshot["seq"] + 1
                assert next(frames) == "heartbeat"
                model.release.set()
                remaining = list(frames)
                terminal = [frame for frame in remaining if frame != "heartbeat"]
                assert len(terminal) == 1
                assert terminal[0]["type"] == "run.completed"
                assert terminal[0]["seq"] == started["seq"] + 1
                assert client.get(f"/api/runs/{run_id}").json()["final_text"] == "live done"
    finally:
        loop.execute_release.set()
        model.release.set()
        server.should_exit = True
        thread.join(timeout=5)
        probe.close()
        assert not thread.is_alive()


def _count_tool(model: BlockThenToolModel) -> dict:
    model.tool_calls += 1
    return {}


def _tcp_health(client: httpx.Client) -> bool:
    try:
        return client.get("/api/health").status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def _wait_tcp_status(client: httpx.Client, run_id: str, status: str) -> dict:
    result: dict = {}

    def ready() -> bool:
        response = client.get(f"/api/runs/{run_id}")
        if response.status_code != 200:
            return False
        result.clear()
        result.update(response.json())
        return result.get("status") == status

    _wait_for(ready, message=f"TCP run {run_id} did not reach {status}")
    return result
