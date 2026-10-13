from __future__ import annotations

from learngraph_lite.agent_core import AgentRunner, ModelResponse, TextMessage, ToolRegistry
from learngraph_lite.application.agent import AgentLoop, DirectResult, RunRequest


class AnswerModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(content=f"answer: {messages[-1].content}")


def test_loop_deduplicates_by_idempotency_key():
    loop = AgentLoop(AgentRunner(AnswerModel(), ToolRegistry()))
    request = RunRequest(session_id="s1", user_text="hello", idempotency_key="k1")
    first = loop.run(request)
    second = loop.run(request)
    assert first is second
    assert second.final_text == "answer: hello"


def test_loop_supports_direct_generation_without_runner():
    loop = AgentLoop(
        AgentRunner(AnswerModel(), ToolRegistry()),
        direct_handlers={"draft_goal": lambda request, budget, root: DirectResult(f"draft: {request.user_text}")},
    )
    record = loop.run(RunRequest(session_id="s1", user_text="RAG", idempotency_key="k2", mode="draft_goal"))
    assert record.status == "completed"
    assert record.final_text == "draft: RAG"
