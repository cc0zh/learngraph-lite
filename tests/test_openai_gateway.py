from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from learngraph_lite.agent_core import AgentRunner, TextMessage
from learngraph_lite.application.agent import AgentLoop, RunRequest
from learngraph_lite.bootstrap import build_echo_tools, create_real_app
from learngraph_lite.infrastructure.openai_gateway import OpenAIChatGateway


def completion(content=None, calls=None, *, finish_reason="stop"):
    return {
        "id": "chat-test", "object": "chat.completion", "created": 0, "model": "test-model",
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content, "tool_calls": calls}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def tool_call(call_id, arguments):
    return {"id": call_id, "type": "function", "function": {"name": "echo", "arguments": arguments}}


def test_sdk_transport_round_trips_multiple_tools_and_repair_with_usage():
    requests = []
    responses = [
        completion(calls=[tool_call("call-valid", '{"text":"hello"}'),
                          tool_call("call-invalid", '{"text":42}')], finish_reason="tool_calls"),
        completion(calls=[tool_call("call-repair", '{"text":"repaired"}')], finish_reason="tool_calls"),
        completion("done"),
    ]

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=responses.pop(0))

    client = httpx.Client(transport=httpx.MockTransport(handle))
    gateway = OpenAIChatGateway(api_key="test-key", model="test-model", base_url="https://mock.test/v1",
                                timeout=2.5, max_output_tokens=128, http_client=client)
    try:
        result = AgentRunner(gateway, build_echo_tools()).run((TextMessage(role="user", content="echo"),))
        assert result.status == "completed" and result.final_text == "done"
        assert result.usage == {"input_tokens": 33, "output_tokens": 21, "total_tokens": 54}
        assert len(result.errors) == 1 and "invalid arguments" in result.errors[0]
        assert len(requests) == 3
        first, second, third = [json.loads(r.content) for r in requests]
        assert str(requests[0].url) == "https://mock.test/v1/chat/completions"
        assert requests[0].headers["authorization"] == "Bearer test-key"
        assert requests[0].extensions["timeout"] == dict(connect=2.5, read=2.5, write=2.5, pool=2.5)
        assert first["model"] == "test-model" and first["max_tokens"] == 128
        assert first["tools"][0]["function"]["parameters"]["additionalProperties"] is False
        assert second["messages"][1]["content"] is None
        assert second["messages"][1]["tool_calls"] == [
            tool_call("call-valid", '{"text":"hello"}'), tool_call("call-invalid", '{"text":42}')]
        assert [m["tool_call_id"] for m in second["messages"][2:]] == ["call-valid", "call-invalid"]
        assert json.loads(second["messages"][2]["content"]) == {"text": "hello"}
        assert "invalid arguments" in second["messages"][3]["content"]
        assert third["messages"][-1]["tool_call_id"] == "call-repair"
        assert json.loads(third["messages"][-1]["content"]) == {"text": "repaired"}
    finally:
        gateway.close()
    assert client.is_closed


def test_sdk_failures_are_bounded_sanitized_and_not_successful_answers():
    for kind, expected in [
        ("timeout", "timed out"), ("connection", "connection failed"),
        ("status", "HTTP 429"), ("no-choices", "invalid response"),
        ("truncated", "stopped: length"), ("empty", "empty response"),
    ]:
        requests = []

        def handle(request):
            requests.append(request)
            if kind == "timeout":
                raise httpx.ReadTimeout("private-provider-body", request=request)
            if kind == "connection":
                raise httpx.ConnectError("private-provider-body", request=request)
            if kind == "status":
                return httpx.Response(429, json={"error": {"message": "private-provider-body"}})
            if kind == "no-choices":
                return httpx.Response(200, json={"choices": []})
            if kind == "truncated":
                return httpx.Response(200, json=completion("partial", finish_reason="length"))
            return httpx.Response(200, json=completion())

        gateway = OpenAIChatGateway(api_key="test-key", model="test-model",
                                    http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        loop = AgentLoop(AgentRunner(gateway, build_echo_tools()))
        try:
            record = loop.run(RunRequest(session_id="s", user_text="hello", idempotency_key="failure"))
            assert record.status == "failed" and expected in record.error
            assert "private-provider-body" not in record.error
        finally:
            loop.close()
            gateway.close()
        assert len(requests) == 1, "SDK must not retry outside the run budget"


def test_real_factory_requires_configuration_and_closes_sdk_after_workers():
    with patch.dict(os.environ, {}, clear=True):
        try:
            create_real_app()
        except RuntimeError as exc:
            assert "MODEL_API_KEY" in str(exc) and "MODEL_NAME" in str(exc)
        else:
            raise AssertionError("missing configuration was accepted")
    for timeout in [0, -1, float("nan"), float("inf")]:
        try:
            OpenAIChatGateway(api_key="test", model="test-model", timeout=timeout)
        except ValueError:
            pass
        else:
            raise AssertionError("unbounded timeout was accepted")
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=completion("hi"))))
    gateway = OpenAIChatGateway(api_key="test", model="test-model", http_client=client)
    with tempfile.TemporaryDirectory() as directory:
        with patch("learngraph_lite.bootstrap.build_real_gateway", return_value=gateway):
            app = create_real_app(database=os.path.join(directory, "test.sqlite3"))
        with TestClient(app, base_url="http://localhost") as api:
            assert api.get("/api/model/status").json() == {"mode": "real", "configured": True}
            assert not client.is_closed
    assert client.is_closed
