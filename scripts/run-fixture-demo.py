#!/usr/bin/env python
"""Generate a deterministic fixture demo walkthrough for LearnGraph Lite."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from learngraph_lite.agent_core import ModelResponse, TextMessage
from learngraph_lite.bootstrap import build_learning_loop
from learngraph_lite.application.documents import DocumentService, InMemoryDocumentRepository
from learngraph_lite.application.learning import InMemoryLearningRepository, LearningService
from learngraph_lite.application.lessons import InMemoryLessonRepository, LessonService
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.application.proposals import GraphProposalService, InMemoryProposalRepository
from learngraph_lite.domain.learning import GraphNode, GraphOperation, GraphOperationKind
from learngraph_lite.domain.lessons import ComponentKind, LessonComponent, LessonEvent, build_lesson_package

DEFAULT_OUTPUT = ROOT / "docs" / "demo" / "fixture-demo.md"


class DemoModel:
    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        return ModelResponse(content=f"fixture-demo: {messages[-1].content}", usage={"input_tokens": 8, "output_tokens": 12})


def build_demo() -> dict[str, str]:
    planning_repository, learning_repository = InMemoryPlanningRepository(), InMemoryLearningRepository()
    loop = build_learning_loop(DemoModel(), planning_repository, learning_repository)
    planning = PlanningService(planning_repository)
    goal, questions = planning.create_goal(
        "demo-goal",
        "四周做出 RAG 应用",
        desired_outcome="能演示一个带引用的 RAG 学习助手",
        current_level="有 Python 基础，没系统做过 RAG",
        time_budget_minutes=1200,
    )
    confirmed = planning.confirm_goal("demo-goal")
    graph_draft = candidate_rag_graph("demo-goal")
    planning.save_graph_draft("demo-goal", graph_draft.nodes, graph_draft.edges)
    graph = planning.publish_graph("demo-goal", expected_revision=0)

    docs = DocumentService(InMemoryDocumentRepository())
    docs.upload_text(
        "rag-notes",
        "RAG 入门资料",
        "RAG 系统先检索资料片段，再生成带引用的回答。\n"
        "Chunking controls retrieval quality.\n"
        "--- page 2 ---\n"
        "评估 RAG 时要检查答案是否被引用片段支持。",
    )
    docs.bind_goal("demo-goal", "rag-notes")
    docs.bind_node("demo-goal", "citations", "rag-notes")
    grounded_answer, citations = docs.answer_with_citations("demo-goal", "citations", "chunking retrieval citation")
    empty_answer, empty_citations = docs.answer_with_citations("demo-goal", "citations", "unrelated zebra")

    learning = LearningService(learning_repository, loop)
    learning.start_goal(graph)
    lesson_reply = learning.learn_node("demo-goal", "rag-goal", "解释 RAG 的目标和边界", "learn-1")
    for index in range(3):
        exercise_id = f"rag-goal-{index}"
        learning.create_fixture_exercise("demo-goal", "rag-goal", exercise_id, f"RAG 引用题 {index}")
        learning.submit_answer("demo-goal", exercise_id, "b", f"attempt-{index}")
    mastery, sample_count, accuracy = learning.mastery("demo-goal", "rag-goal")
    next_action = learning.next_action("demo-goal", available_minutes=25)

    lessons = LessonService(InMemoryLessonRepository(), learning, loop)
    package = lessons.save_package(
        build_lesson_package(
            package_id="lesson-1",
            goal_id="demo-goal",
            node_id="rag-goal",
            graph_content_revision=graph.content_revision,
            markdown="## RAG 学习页\n先理解检索、生成和引用之间的边界。",
            components=(
                LessonComponent("choice-1", ComponentKind.CHOICE_CARD, {"prompt": "回答应依据什么？", "options": ["引用片段", "模型猜测"]}),
                LessonComponent("steps-1", ComponentKind.STEPPER, {"steps": ["检索资料", "组织回答", "返回引用"]}),
                LessonComponent("table-1", ComponentKind.COMPARISON_TABLE, {"columns": ["方式", "风险"], "rows": [["无引用", "不可核查"], ["有引用", "可定位来源"]]}),
            ),
        )
    )
    event = lessons.ack_event("demo-goal", LessonEvent("event-1", "lesson-1", "choice-1", "request_explanation", {"choice": "引用片段"}))
    explanation_run_id = lessons.explain_event("demo-goal", event.id, "choice-1", "explain-1")

    proposals = GraphProposalService(InMemoryProposalRepository())
    proposal = proposals.create_proposal(
        proposal_id="proposal-1",
        graph=graph,
        base_revision=graph.revision,
        operations=(GraphOperation(GraphOperationKind.ADD_NODE, node=GraphNode("rerank", "重排入门", 30)),),
        rationale="补充检索质量优化节点",
    )
    decided, updated_graph = proposals.accept(proposal.id, graph)

    return {
        "mode": "fixture",
        "goal": goal.title,
        "questions": str(len(questions)),
        "confirmed": str(confirmed.confirmed).lower(),
        "graph_nodes": str(len(graph.nodes)),
        "graph_revision": str(graph.revision),
        "grounded_answer": grounded_answer,
        "citation_count": str(len(citations)),
        "empty_answer": empty_answer,
        "empty_citation_count": str(len(empty_citations)),
        "lesson_reply": lesson_reply,
        "mastery": mastery.value,
        "sample_count": str(sample_count),
        "accuracy": f"{accuracy:.2f}",
        "next_action": f"{next_action.action_type}:{next_action.node_id}",
        "lesson_components": str(len(package.components)),
        "explanation_run_recorded": str(bool(explanation_run_id)).lower(),
        "proposal_status": decided.status.value,
        "updated_graph_nodes": str(len(updated_graph.nodes)),
    }


def render_demo(data: dict[str, str]) -> str:
    return "\n".join(
        [
            "# LearnGraph Lite Fixture Demo Script",
            "",
            "This is a deterministic fixture demo for local review. It does not call a real model and must not be presented as real model output.",
            "",
            "## Scenario",
            "",
            f"- Goal: {data['goal']}",
            f"- Mode: {data['mode']}",
            f"- Clarification questions: {data['questions']}",
            f"- Goal confirmed: {data['confirmed']}",
            "",
            "## Walkthrough",
            "",
            "| Step | Observable result |",
            "| --- | --- |",
            f"| 1. Confirm goal | graph revision {data['graph_revision']} with {data['graph_nodes']} nodes |",
            f"| 2. Bind material and ask grounded question | {data['citation_count']} citation(s); {data['grounded_answer']} |",
            f"| 3. Ask unrelated question | {data['empty_citation_count']} citation(s); {data['empty_answer']} |",
            f"| 4. Learn first node | {data['lesson_reply']} |",
            f"| 5. Submit three exercises | mastery={data['mastery']}, samples={data['sample_count']}, accuracy={data['accuracy']} |",
            f"| 6. Get next action | {data['next_action']} |",
            f"| 7. Render declarative lesson | {data['lesson_components']} fixed component(s); explanation run recorded={data['explanation_run_recorded']} |",
            f"| 8. Review graph proposal | proposal={data['proposal_status']}; updated graph nodes={data['updated_graph_nodes']} |",
            "",
            "## Evidence boundary",
            "",
            "- This demo proves the current deterministic application/domain slices can be replayed locally.",
            "- Real model smoke, browser UI, FastAPI routes, SQLite persistence and video recording are still separate M5 work.",
            "",
        ]
    )


def write_demo(output_path: Path = DEFAULT_OUTPUT) -> dict[str, str]:
    data = build_demo()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_demo(data), encoding="utf-8")
    return data


def main() -> int:
    write_demo()
    print(f"Fixture demo written: {DEFAULT_OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
