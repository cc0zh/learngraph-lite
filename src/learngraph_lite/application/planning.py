"""Application use cases for M2 goal planning and graph publication."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from learngraph_lite.domain.learning import (
    GoalDraft,
    GraphDraft,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphStatus,
    build_goal_draft,
    clarification_questions,
    confirm_goal,
    publish_graph,
)


@dataclass
class PlanningState:
    goal: GoalDraft
    graph: GraphSnapshot | None = None
    clarification_round: int = 0


class PlanningRepository(Protocol):
    def save(self, goal_id: str, state: PlanningState) -> None: ...

    def get(self, goal_id: str) -> PlanningState: ...


@dataclass
class InMemoryPlanningRepository:
    """In-memory port implementation for offline M2 tests."""

    _states: dict[str, PlanningState] = field(default_factory=dict)

    def save(self, goal_id: str, state: PlanningState) -> None:
        self._states[goal_id] = state

    def get(self, goal_id: str) -> PlanningState:
        try:
            return self._states[goal_id]
        except KeyError as exc:
            raise KeyError(f"unknown goal: {goal_id}") from exc


class PlanningService:
    def __init__(self, repository: PlanningRepository):
        self._repository = repository

    def create_goal(self, goal_id: str, title: str, **fields: object) -> tuple[GoalDraft, tuple[str, ...]]:
        draft = build_goal_draft(title, **fields)
        state = PlanningState(goal=draft)
        self._repository.save(goal_id, state)
        questions = tuple(question.question for question in clarification_questions(draft, state.clarification_round))
        return draft, questions

    def answer_clarification(self, goal_id: str, **fields: object) -> tuple[GoalDraft, tuple[str, ...]]:
        state = self._repository.get(goal_id)
        merged = build_goal_draft(
            state.goal.title,
            desired_outcome=fields.get("desired_outcome", state.goal.desired_outcome),
            current_level=fields.get("current_level", state.goal.current_level),
            time_budget_minutes=fields.get("time_budget_minutes", state.goal.time_budget_minutes),
            constraints=fields.get("constraints", state.goal.constraints),
            document_ids=fields.get("document_ids", state.goal.document_ids),
        )
        next_round = state.clarification_round + 1
        self._repository.save(goal_id, PlanningState(goal=merged, graph=state.graph, clarification_round=next_round))
        questions = tuple(question.question for question in clarification_questions(merged, next_round))
        return merged, questions

    def confirm_goal(self, goal_id: str) -> GoalDraft:
        state = self._repository.get(goal_id)
        confirmed = confirm_goal(state.goal)
        self._repository.save(goal_id, PlanningState(goal=confirmed, graph=state.graph, clarification_round=state.clarification_round))
        return confirmed

    def save_graph_draft(self, goal_id: str, nodes: tuple[GraphNode, ...], edges: tuple[GraphEdge, ...]) -> GraphSnapshot:
        state = self._repository.get(goal_id)
        if not state.goal.confirmed:
            raise ValueError("goal must be confirmed before graph generation")
        previous = state.graph
        snapshot = GraphSnapshot(
            goal_id=goal_id,
            nodes=nodes,
            edges=edges,
            status=GraphStatus.DRAFT,
            revision=previous.revision if previous else 0,
            content_revision=previous.content_revision if previous else 0,
        )
        self._repository.save(goal_id, PlanningState(goal=state.goal, graph=snapshot, clarification_round=state.clarification_round))
        return snapshot

    def update_node(self, goal_id: str, node_id: str, *, title: str | None = None, estimated_minutes: int | None = None) -> GraphSnapshot:
        state = self._repository.get(goal_id)
        if state.graph is None:
            raise ValueError("graph draft is required")
        nodes = []
        found = False
        for node in state.graph.nodes:
            if node.id == node_id:
                found = True
                nodes.append(
                    GraphNode(
                        id=node.id,
                        title=title if title is not None else node.title,
                        estimated_minutes=estimated_minutes if estimated_minutes is not None else node.estimated_minutes,
                    )
                )
            else:
                nodes.append(node)
        if not found:
            raise ValueError(f"unknown node: {node_id}")
        return self.save_graph_draft(goal_id, tuple(nodes), state.graph.edges)

    def add_dependency(self, goal_id: str, source: str, target: str) -> GraphSnapshot:
        state = self._repository.get(goal_id)
        if state.graph is None:
            raise ValueError("graph draft is required")
        edge = GraphEdge(source, target)
        if edge in state.graph.edges:
            return state.graph
        return self.save_graph_draft(goal_id, state.graph.nodes, state.graph.edges + (edge,))

    def publish_graph(self, goal_id: str, expected_revision: int) -> GraphSnapshot:
        state = self._repository.get(goal_id)
        if state.graph is None:
            raise ValueError("graph draft is required")
        published = publish_graph(state.graph, expected_revision=expected_revision)
        self._repository.save(goal_id, PlanningState(goal=state.goal, graph=published, clarification_round=state.clarification_round))
        return published

    def current_graph(self, goal_id: str) -> GraphSnapshot | None:
        return self._repository.get(goal_id).graph


def candidate_rag_graph(goal_id: str) -> GraphDraft:
    """Deterministic fixture graph for offline planning E2E."""

    nodes = (
        GraphNode("rag-goal", "RAG 应用目标与边界", 20),
        GraphNode("document-loading", "资料加载与清洗", 25),
        GraphNode("chunking", "分块策略", 35),
        GraphNode("retrieval-basics", "检索基础", 30),
        GraphNode("prompt-grounding", "基于资料的提示词约束", 30),
        GraphNode("citations", "引用与可核查回答", 40),
        GraphNode("evaluation", "RAG 评估样例", 35),
        GraphNode("demo-assembly", "最小 RAG Demo 组装", 45),
    )
    edges = (
        GraphEdge("rag-goal", "document-loading"),
        GraphEdge("document-loading", "chunking"),
        GraphEdge("chunking", "retrieval-basics"),
        GraphEdge("retrieval-basics", "prompt-grounding"),
        GraphEdge("prompt-grounding", "citations"),
        GraphEdge("citations", "evaluation"),
        GraphEdge("evaluation", "demo-assembly"),
    )
    return GraphDraft(nodes=nodes, edges=edges)
