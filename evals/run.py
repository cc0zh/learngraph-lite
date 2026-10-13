#!/usr/bin/env python
"""Run the deterministic offline LearnGraph Lite evaluation suite."""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from learngraph_lite.agent_core import AgentRunner, Budget, ModelResponse, TextMessage, Tool, ToolCall, ToolRegistry
from learngraph_lite.application.agent import AgentLoop, RunRequest
from learngraph_lite.application.documents import DocumentService, InMemoryDocumentRepository
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.lessons import InMemoryLessonRepository, LessonService
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.application.proposals import GraphProposalService, InMemoryProposalRepository
from learngraph_lite.domain.documents import DocumentKind
from learngraph_lite.domain.learning import GraphEdge, GraphNode, GraphOperation, GraphOperationKind, MasteryState, ProposalStatus
from learngraph_lite.domain.lessons import ComponentKind, LessonComponent, LessonEvent, build_lesson_package
from learngraph_lite.presentation import encode_sse

CASES_FILE = ROOT / "evals" / "cases" / "offline-m5.json"
DEFAULT_REPORT = ROOT / "evals" / "reports" / "offline-fixture-report.md"


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    area: str
    title: str
    status: str
    detail: str


class AnswerModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(content=f"fixture answer: {messages[-1].content}", usage={"input_tokens": 3, "output_tokens": 5})


class ToolLoopModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(tool_calls=(ToolCall(id="private-tool-call", name="echo", arguments='{"text":"x"}'),))


def _planning() -> PlanningService:
    return PlanningService(InMemoryPlanningRepository())


def _published_graph():
    planning = _planning()
    planning.create_goal("g1", "四周做出 RAG 应用", desired_outcome="demo", current_level="Python", time_budget_minutes=1200)
    planning.confirm_goal("g1")
    graph = candidate_rag_graph("g1")
    planning.save_graph_draft("g1", graph.nodes, graph.edges)
    return planning.publish_graph("g1", expected_revision=0)


def _learning() -> LearningService:
    loop = AgentLoop(AgentRunner(AnswerModel(), ToolRegistry()))
    learning = LearningService(InMemoryLearningRepository(), loop)
    learning.start_goal(_published_graph())
    return learning


def _make_proficient(learning: LearningService, node_id: str = "rag-goal", *, count: int = 3) -> None:
    for index in range(count):
        exercise_id = f"{node_id}-right-{index}"
        learning.create_fixture_exercise("g1", node_id, exercise_id, f"{node_id} 正确题 {index}")
        learning.submit_answer("g1", exercise_id, "b", f"attempt-{exercise_id}")


def _assert_raises(expected: str, action: Callable[[], object]) -> str:
    try:
        action()
    except Exception as exc:
        if expected not in str(exc):
            raise AssertionError(f"expected {expected!r} in {exc!r}") from exc
        return str(exc)
    raise AssertionError(f"expected exception containing {expected!r}")


def case_goal_clarification_questions() -> str:
    _, questions = _planning().create_goal("g1", "学习 RAG")
    assert len(questions) == 3
    assert any("基础" in question for question in questions)
    return "returned 3 clarification questions"


def case_goal_confirm_with_assumptions() -> str:
    planning = _planning()
    draft, _ = planning.create_goal("g1", "学习 RAG")
    confirmed = planning.confirm_goal("g1")
    assert confirmed.confirmed
    assert draft.assumptions
    return f"confirmed with {len(draft.assumptions)} assumptions"


def case_graph_publish_revision() -> str:
    graph = _published_graph()
    assert graph.status == "published"
    assert graph.revision == 1
    assert graph.content_revision == 1
    return "published graph revision 1/content revision 1"


def case_graph_cycle_rejected() -> str:
    planning = _planning()
    planning.create_goal("g1", "学习 RAG", desired_outcome="demo", current_level="Python")
    planning.confirm_goal("g1")
    planning.save_graph_draft("g1", (GraphNode("a", "A", 10), GraphNode("b", "B", 10)), (GraphEdge("a", "b"), GraphEdge("b", "a")))
    return _assert_raises("acyclic", lambda: planning.publish_graph("g1", expected_revision=0))


def case_learning_node_run_idempotent() -> str:
    learning = _learning()
    first = learning.learn_node("g1", "rag-goal", "hello", "req-1")
    second = learning.learn_node("g1", "rag-goal", "changed", "req-1")
    assert first == second == "fixture answer: hello"
    return "same request_id reused the first run result"


def case_exercise_public_hides_answer() -> str:
    public = _learning().create_fixture_exercise("g1", "rag-goal", "e1", "如何处理引用？")
    assert not hasattr(public, "correct_option_id")
    assert not hasattr(public, "explanation")
    return "public exercise excludes answer and explanation"


def case_attempt_first_counted_retry_not_counted() -> str:
    learning = _learning()
    learning.create_fixture_exercise("g1", "rag-goal", "e1", "同题重答？")
    first = learning.submit_answer("g1", "e1", "b", "a1")
    second = learning.submit_answer("g1", "e1", "a", "a2")
    assert first.counted
    assert not second.counted
    return "first attempt counted; retry ignored for mastery"


def case_mastery_reaches_proficient() -> str:
    learning = _learning()
    _make_proficient(learning)
    state, samples, accuracy = learning.mastery("g1", "rag-goal")
    assert state == MasteryState.PROFICIENT
    assert samples == 3
    assert accuracy == 1.0
    return "3/3 counted attempts reached proficient"


def case_mastery_can_drop_after_new_wrong() -> str:
    learning = _learning()
    _make_proficient(learning)
    for index in range(3):
        exercise_id = f"wrong-{index}"
        learning.create_fixture_exercise("g1", "rag-goal", exercise_id, f"新错题 {index}")
        learning.submit_answer("g1", exercise_id, "a", f"attempt-{exercise_id}")
    state, samples, accuracy = learning.mastery("g1", "rag-goal")
    assert state == MasteryState.LEARNING
    assert samples == 5
    assert accuracy < 0.8
    return f"dropped to {state} with accuracy {accuracy:.2f}"


def case_next_action_blocks_until_prereq() -> str:
    learning = _learning()
    action = learning.next_action("g1")
    assert action.node_id == "rag-goal"
    _make_proficient(learning, "rag-goal")
    action = learning.next_action("g1")
    assert action.node_id == "document-loading"
    return "next action advanced only after prerequisite proficiency"


def case_document_upload_chunks() -> str:
    docs = DocumentService(InMemoryDocumentRepository())
    document = docs.upload_text("d1", "RAG notes", "RAG 先检索资料。\n--- page 2 ---\n引用用于核查回答。", kind=DocumentKind.MARKDOWN)
    chunks = docs._repository.chunks_for({"d1"})
    assert document.title == "RAG notes"
    assert len(chunks) >= 2
    assert chunks[1].page_number == 2
    return f"created {len(chunks)} chunks with page metadata"


def case_document_search_citation() -> str:
    docs = DocumentService(InMemoryDocumentRepository())
    docs.upload_text("d1", "RAG notes", "RAG 系统先检索资料片段，再生成带引用的回答。Chunking controls retrieval quality.")
    docs.bind_goal("g1", "d1")
    docs.bind_node("g1", "citations", "d1")
    hits = docs.search("g1", "chunking retrieval", node_id="citations")
    assert hits
    assert hits[0].citation.chunk_id == hits[0].chunk.id
    return "search returned citation tied to a chunk"


def case_document_empty_retrieval() -> str:
    docs = DocumentService(InMemoryDocumentRepository())
    docs.upload_text("d1", "RAG notes", "这里只讨论引用。")
    docs.bind_goal("g1", "d1")
    docs.bind_node("g1", "citations", "d1")
    answer, citations = docs.answer_with_citations("g1", "citations", "unrelated zebra")
    assert not citations
    assert "不能给出带引用的回答" in answer
    return "empty retrieval refused grounded answer"


def case_citation_stale_rejected() -> str:
    docs = DocumentService(InMemoryDocumentRepository())
    docs.upload_text("d1", "RAG notes", "RAG 系统先检索资料片段。")
    docs.bind_goal("g1", "d1")
    hit = docs.search("g1", "RAG")[0]
    stale = type(hit.citation)(
        id=hit.citation.id,
        document_id=hit.citation.document_id,
        document_version=99,
        chunk_id=hit.citation.chunk_id,
        quote=hit.citation.quote,
        start_offset=hit.citation.start_offset,
        end_offset=hit.citation.end_offset,
    )
    return _assert_raises("stale", lambda: docs.locate(stale))


def case_lesson_rejects_executable_markdown() -> str:
    return _assert_raises(
        "executable",
        lambda: build_lesson_package(
            package_id="lp1",
            goal_id="g1",
            node_id="rag-goal",
            graph_content_revision=1,
            markdown="<script>alert(1)</script>",
            components=(),
        ),
    )


def _lesson_service() -> LessonService:
    learning = _learning()
    return LessonService(InMemoryLessonRepository(), learning, AgentLoop(AgentRunner(AnswerModel(), ToolRegistry())))


def _save_lesson(service: LessonService):
    package = build_lesson_package(
        package_id="lp1",
        goal_id="g1",
        node_id="rag-goal",
        graph_content_revision=1,
        markdown="## RAG",
        components=(LessonComponent("choice-1", ComponentKind.CHOICE_CARD, {"prompt": "选依据", "options": ["引用", "猜测"]}),),
    )
    return service.save_package(package)


def case_lesson_event_idempotent() -> str:
    service = _lesson_service()
    _save_lesson(service)
    first = service.ack_event("g1", LessonEvent("event-1", "lp1", "choice-1", "select", {"option": "引用"}))
    second = service.ack_event("g1", LessonEvent("event-1", "lp1", "choice-1", "select", {"option": "猜测"}))
    assert first is second
    assert second.payload["option"] == "引用"
    return "duplicate event id preserved first payload"


def case_lesson_explanation_idempotent() -> str:
    service = _lesson_service()
    _save_lesson(service)
    service.ack_event("g1", LessonEvent("event-1", "lp1", "choice-1", "request_explanation", {"option": "引用"}))
    first = service.explain_event("g1", "event-1", "choice-1", "req-1")
    second = service.explain_event("g1", "event-1", "choice-1", "req-2")
    assert first == second
    return "same event and slot reused explanation run"


def case_proposal_pending_no_side_effect() -> str:
    graph = _published_graph()
    service = GraphProposalService(InMemoryProposalRepository())
    proposal = service.create_proposal(
        proposal_id="p1",
        graph=graph,
        base_revision=graph.revision,
        operations=(GraphOperation(GraphOperationKind.ADD_NODE, node=GraphNode("rerank", "重排入门", 30)),),
        rationale="补充检索质量优化节点",
    )
    assert proposal.status == ProposalStatus.PENDING
    assert all(node.id != "rerank" for node in graph.nodes)
    return "pending proposal did not mutate graph"


def case_proposal_accept_updates_graph() -> str:
    graph = _published_graph()
    service = GraphProposalService(InMemoryProposalRepository())
    proposal = service.create_proposal(
        proposal_id="p1",
        graph=graph,
        base_revision=graph.revision,
        operations=(GraphOperation(GraphOperationKind.ADD_NODE, node=GraphNode("rerank", "重排入门", 30)),),
        rationale="补充检索质量优化节点",
    )
    decided, updated = service.accept(proposal.id, graph)
    assert decided.status == ProposalStatus.ACCEPTED
    assert any(node.id == "rerank" for node in updated.nodes)
    return "accepted proposal updated graph"


def case_run_lifecycle_sse_cancel_budget() -> str:
    cancelled = AgentLoop(AgentRunner(ToolLoopModel(), ToolRegistry())).run(
        RunRequest(session_id="s1", user_text="cancel", idempotency_key="cancel"),
        budget=Budget(cancelled=True),
    )
    tools = ToolRegistry()
    tools.register(Tool("echo", "Echo text.", {"type": "object"}, lambda args: args))
    budgeted_loop = AgentLoop(AgentRunner(ToolLoopModel(), tools))
    budgeted = budgeted_loop.run(
        RunRequest(session_id="s1", user_text="budget", idempotency_key="budget"),
        budget=Budget(max_model_calls=1, max_tool_calls=0, max_steps=2),
    )
    frame = encode_sse(budgeted_loop.events(budgeted.run_id)[-1])
    assert cancelled.status == "cancelled"
    assert budgeted.status == "budget_exceeded"
    assert "private-tool-call" not in frame
    return "cancelled and budget_exceeded are distinct public terminal states"


CASE_HANDLERS: dict[str, Callable[[], str]] = {
    name.removeprefix("case_"): value
    for name, value in list(globals().items())
    if name.startswith("case_") and callable(value)
}


def load_cases(path: Path = CASES_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_suite(cases_path: Path = CASES_FILE) -> list[CaseResult]:
    suite = load_cases(cases_path)
    results: list[CaseResult] = []
    for case in suite["cases"]:
        case_id = case["id"]
        handler = CASE_HANDLERS.get(case_id)
        if handler is None:
            results.append(CaseResult(case_id, case["area"], case["title"], "failed", "missing case handler"))
            continue
        try:
            detail = handler()
            results.append(CaseResult(case_id, case["area"], case["title"], "passed", detail))
        except Exception:
            results.append(CaseResult(case_id, case["area"], case["title"], "failed", traceback.format_exc(limit=4).strip()))
    return results


def render_report(results: list[CaseResult]) -> str:
    passed = sum(1 for result in results if result.status == "passed")
    lines = [
        "# Offline M5 Fixture Evaluation Report",
        "",
        "- Suite: offline-m5-fixture",
        "- Mode: fixture / deterministic local services",
        "- Real model smoke: not run; no provider API key is configured in this environment.",
        f"- Result: {passed}/{len(results)} cases passed",
        "",
        "| Case | Area | Status | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for result in results:
        detail = result.detail.replace("|", "\\|").replace("\n", "<br>")
        lines.append(f"| {result.case_id} | {result.area} | {result.status} | {detail} |")
    lines.extend(
        [
            "",
            "This report proves only deterministic fixture behavior for the implemented slices.",
            "It must not be used as evidence of real model quality or browser E2E behavior.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report_path: Path = DEFAULT_REPORT) -> list[CaseResult]:
    results = run_suite()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(results), encoding="utf-8")
    return results


def main() -> int:
    results = write_report()
    failed = [result for result in results if result.status != "passed"]
    print(f"{len(results) - len(failed)}/{len(results)} offline fixture eval cases passed")
    print(f"Report: {DEFAULT_REPORT.relative_to(ROOT)}")
    if failed:
        for result in failed:
            print(f"{result.case_id}: {result.detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
