"""OpenAI-compatible Chat Completions adapter for the standalone model port."""

from __future__ import annotations

import math
from typing import Any

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI

from learngraph_lite.agent_core import ModelResponse, TextMessage, ToolCall


class ModelGatewayError(RuntimeError):
    """A provider request failed or returned an unusable response."""


class OpenAIChatGateway:
    """Adapt the official OpenAI Python client to ``ModelGateway``."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_output_tokens: int = 1024,
        http_client: httpx.Client | None = None,
    ):
        if not api_key.strip():
            raise ValueError("api_key is required for real model mode")
        if not model.strip():
            raise ValueError("model is required for real model mode")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
            http_client=http_client,
        )
        self._model = model
        self._max_output_tokens = max_output_tokens

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict[str, Any], ...]) -> ModelResponse:
        try:
            options = {"tools": list(tools)} if tools else {}
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[_message_payload(message) for message in messages],
                max_tokens=self._max_output_tokens,
                **options,
            )
        except APITimeoutError as exc:
            raise ModelGatewayError("Model request timed out") from exc
        except APIConnectionError as exc:
            raise ModelGatewayError("Model provider connection failed") from exc
        except APIStatusError as exc:
            # Provider bodies can echo credentials or prompts; only expose the status.
            raise ModelGatewayError(f"Model provider returned HTTP {exc.status_code}") from exc
        except APIError as exc:
            raise ModelGatewayError("Model provider returned an invalid response") from exc

        try:
            choice = response.choices[0]
            message = choice.message
            if choice.finish_reason in {"length", "content_filter"}:
                raise ModelGatewayError(f"Model response stopped: {choice.finish_reason}")
            if message.refusal:
                raise ModelGatewayError("Model declined the request")
            calls = message.tool_calls or ()
            if any(call.type != "function" for call in calls):
                raise ModelGatewayError("Model returned an unsupported tool call")
            tool_calls = tuple(
                ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments)
                for call in calls
            )
            if not message.content and not tool_calls:
                raise ModelGatewayError("Model returned an empty response")
            if any(not call.id or not call.name or not isinstance(call.arguments, str) for call in tool_calls):
                raise ModelGatewayError("Model returned an invalid tool call")
            if len({call.id for call in tool_calls}) != len(tool_calls):
                raise ModelGatewayError("Model returned duplicate tool call IDs")
            usage = _usage_payload(response.usage)
        except (AttributeError, IndexError, TypeError) as exc:
            raise ModelGatewayError("Model provider returned an invalid response") from exc
        return ModelResponse(content=message.content or "", tool_calls=tool_calls, usage=usage)

    def close(self) -> None:
        self._client.close()

    def stream_complete(self, messages, tools, on_delta) -> ModelResponse:
        """Aggregate native SDK tool fragments; execute only after a valid finish."""
        text = ""
        calls = {}
        usage = {}
        finish = None
        try:
            options = {"tools": list(tools)} if tools else {}
            with self._client.chat.completions.create(
                model=self._model, messages=[_message_payload(m) for m in messages],
                max_tokens=self._max_output_tokens, stream=True,
                stream_options={"include_usage": True}, **options,
            ) as stream:
                for chunk in stream:
                    if chunk.usage is not None:
                        usage = _usage_payload(chunk.usage)
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.delta.refusal:
                        raise ModelGatewayError("Model declined the request")
                    if choice.delta.content:
                        text += choice.delta.content
                        on_delta(choice.delta.content)
                    for fragment in choice.delta.tool_calls or ():
                        if fragment.type not in {None, "function"}:
                            raise ModelGatewayError("Model returned an unsupported tool call")
                        item = calls.setdefault(fragment.index, {"id": "", "name": "", "arguments": ""})
                        item["id"] += fragment.id or ""
                        if fragment.function:
                            item["name"] += fragment.function.name or ""
                            item["arguments"] += fragment.function.arguments or ""
                    if choice.finish_reason:
                        finish = choice.finish_reason
        except APITimeoutError as exc:
            raise ModelGatewayError("Model request timed out") from exc
        except APIConnectionError as exc:
            raise ModelGatewayError("Model provider connection failed") from exc
        except APIStatusError as exc:
            raise ModelGatewayError(f"Model provider returned HTTP {exc.status_code}") from exc
        except APIError as exc:
            raise ModelGatewayError("Model provider returned an invalid response") from exc
        if finish not in {"stop", "tool_calls"}:
            raise ModelGatewayError(f"Model stream stopped: {finish or 'incomplete'}")
        tool_calls = tuple(ToolCall(**item) for _, item in sorted(calls.items()))
        if any(not c.id or not c.name or not c.arguments for c in tool_calls):
            raise ModelGatewayError("Model returned an invalid tool call")
        if len({c.id for c in tool_calls}) != len(tool_calls):
            raise ModelGatewayError("Model returned duplicate tool call IDs")
        if not text and not tool_calls:
            raise ModelGatewayError("Model returned an empty response")
        return ModelResponse(text, tool_calls, usage)


def _message_payload(message: TextMessage) -> dict[str, Any]:
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in message.tool_calls
            ],
        }
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.role == "tool":
        payload["tool_call_id"] = message.tool_call_id
    return payload


def _usage_payload(usage: Any) -> dict[str, int]:
    if usage is None:
        return {}
    fields = {
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
    return {key: int(value) for key, value in fields.items() if value is not None}
