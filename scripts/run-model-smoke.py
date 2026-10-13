#!/usr/bin/env python
"""Opt-in provider smoke: one plain answer and one native tool round trip."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from learngraph_lite.agent_core import AgentRunner, Budget, TextMessage
from learngraph_lite.bootstrap import build_echo_tools, build_real_gateway


def main() -> None:
    gateway = build_real_gateway()
    try:
        answer = gateway.complete((TextMessage(role="user", content="Reply with a short greeting."),), ())
        if not answer.content or answer.tool_calls:
            raise RuntimeError("plain-answer smoke did not produce a text answer")
        result = AgentRunner(gateway, build_echo_tools()).run(
            (TextMessage(role="user", content="Call echo with text='learngraph-smoke', then report its result."),),
            budget=Budget(max_steps=3, max_model_calls=3, max_tool_calls=2),
        )
        if result.status != "completed" or result.errors or not result.final_text:
            raise RuntimeError(f"tool smoke failed: {result.status}; {'; '.join(result.errors)}")
        if not any(m.role == "tool" and '"text": "learngraph-smoke"' in m.content for m in result.messages):
            raise RuntimeError("model did not execute the requested native echo tool call")
        print(f"REAL provider smoke passed: plain answer + native tool round trip; usage={result.usage}")
    finally:
        gateway.close()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        print(f"Real model smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
