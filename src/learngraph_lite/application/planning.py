"""Application use cases for M2 goal planning and graph publication."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from threading import RLock
from typing import Callable, Protocol, TypeVar

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
from learngraph_lite.domain.learning.graph import validate_node_citations

T = TypeVar("T")


class PlanningError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class PlanningState:
    goal: GoalDraft
    graph: GraphSnapshot | None = None
    clarification_round: int = 0
    version: int = 0
    questions: tuple[str, ...] = ()


class PlanningRepository(Protocol):
    def save(self, goal_id: str, state: PlanningState) -> None: ...

    def get(self, goal_id: str) -> PlanningState: ...

    def create(self, goal_id: str, state: PlanningState) -> None: ...

    def list_ids(self) -> tuple[str, ...]: ...

    def mutate(self, goal_id: str, update: Callable[[PlanningState], T]) -> T: ...


@dataclass
class InMemoryPlanningRepository:
    """In-memory port implementation for offline M2 tests."""

    _states: dict[str, PlanningState] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def save(self, goal_id: str, state: PlanningState) -> None:
        with self._lock:
            self._states[goal_id] = deepcopy(state)

    def get(self, goal_id: str) -> PlanningState:
        with self._lock:
            try:
                return deepcopy(self._states[goal_id])
            except KeyError as exc:
                raise KeyError(f"unknown goal: {goal_id}") from exc

    def create(self, goal_id: str, state: PlanningState) -> None:
        with self._lock:
            if goal_id in self._states:
                raise PlanningError("goal_exists", "Goal already exists.")
            self.save(goal_id, state)

    def list_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._states))

    def mutate(self, goal_id: str, update: Callable[[PlanningState], T]) -> T:
        with self._lock:
            state = self.get(goal_id)
            result = update(state)
            state.version += 1
            self.save(goal_id, state)
            return result


class PlanningService:
    def __init__(self, repository: PlanningRepository):
        self._repository = repository

    def create_goal(self, goal_id: str, title: str, **fields: object) -> tuple[GoalDraft, tuple[str, ...]]:
        draft = build_goal_draft(title, **fields)
        state = PlanningState(goal=draft)
        self._repository.create(goal_id, state)
        questions = tuple(question.question for question in clarification_questions(draft, state.clarification_round))
        return draft, questions

    def answer_clarification(self, goal_id: str, **fields: object) -> tuple[GoalDraft, tuple[str, ...]]:
        def update(state):
            self._require_editable(state)
            state.goal = self._merge_goal(state.goal, fields)
            state.clarification_round = min(2, state.clarification_round + 1)
            state.questions = ()
            questions = tuple(question.question for question in clarification_questions(state.goal, state.clarification_round))
            return state.goal, questions
        return self._mutate(goal_id, update)

    def confirm_goal(self, goal_id: str, expected_version: int | None = None) -> GoalDraft:
        def update(state):
            self.check_version(state, expected_version)
            state.goal = confirm_goal(state.goal)
            state.questions = ()
            return state.goal
        return self._mutate(goal_id, update)

    def get_state(self, goal_id: str) -> PlanningState:
        try:
            return self._repository.get(goal_id)
        except KeyError as exc:
            raise PlanningError("goal_not_found", "Goal does not exist.") from exc

    def list_goals(self) -> list[dict]:
        return [self.describe(goal_id) for goal_id in self._repository.list_ids()]

    def describe(self, goal_id: str) -> dict:
        return {"goal_id": goal_id, **asdict(self.get_state(goal_id))}

    def edit_goal(self, goal_id: str, expected_version: int, **fields: object) -> None:
        def update(state):
            self.check_version(state, expected_version)
            self._require_editable(state)
            state.goal = self._merge_goal(state.goal, fields)
            state.questions = ()
            # Any old candidate was based on the previous goal.
            state.graph = None
        self._mutate(goal_id, update)

    def save_clarification(self, goal_id: str, expected_version: int, questions: tuple[str, ...],
                           before_save: Callable[[], None]) -> PlanningState:
        def update(state):
            self.check_version(state, expected_version)
            if state.goal.confirmed or state.clarification_round >= 2:
                raise PlanningError("clarification_limit", "Goal is confirmed or clarification limit was reached.")
            before_save()
            state.questions = questions
            state.clarification_round += 1
            return state
        return self._mutate(goal_id, update)

    @staticmethod
    def _merge_goal(goal: GoalDraft, fields: dict) -> GoalDraft:
        values = {name: fields.get(name, getattr(goal, name)) for name in
                  ("desired_outcome", "current_level", "time_budget_minutes", "constraints", "document_ids")}
        return build_goal_draft(fields.get("title", goal.title), **values)

    @staticmethod
    def check_version(state: PlanningState, expected: int | None) -> None:
        if expected is not None and state.version != expected:
            raise PlanningError("planning_conflict", f"Planning version changed: expected {expected}, actual {state.version}.")

    @staticmethod
    def _require_editable(state: PlanningState) -> None:
        if state.graph is not None and state.graph.status == GraphStatus.PUBLISHED:
            raise PlanningError("graph_published", "Published routes must be changed through proposals.")

    def _mutate(self, goal_id: str, update: Callable[[PlanningState], T]) -> T:
        try:
            return self._repository.mutate(goal_id, update)
        except KeyError as exc:
            raise PlanningError("goal_not_found", "Goal does not exist.") from exc

    def save_graph_draft(self, goal_id: str, nodes: tuple[GraphNode, ...], edges: tuple[GraphEdge, ...],
                         expected_version: int | None = None, before_save: Callable[[], None] | None = None,
                         *, allow_published: bool = False, source_mode: str = "general",
                         citation_map: dict | None = None) -> GraphSnapshot:
        def update(state):
            self.check_version(state, expected_version)
            if not allow_published:
                self._require_editable(state)
            if not state.goal.confirmed:
                raise PlanningError("goal_unconfirmed", "goal must be confirmed before graph generation")
            if before_save is not None:
                before_save()
            previous = state.graph
            # Keep the source table when editing, but do not inherit the generation claim.
            sources = citation_map if citation_map is not None else (previous.citation_map if previous else {})
            errors = validate_node_citations(nodes, sources)
            if errors:
                raise PlanningError("invalid_graph_citations", "; ".join(errors))
            mode = source_mode if citation_map is not None else ("edited" if sources else "general")
            state.graph = GraphSnapshot(goal_id, nodes, edges, GraphStatus.DRAFT,
                                        previous.revision if previous else 0,
                                        previous.content_revision if previous else 0,
                                        mode, sources)
            return state.graph
        return self._mutate(goal_id, update)

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
                    replace(node,
                        title=title if title is not None else node.title,
                        estimated_minutes=estimated_minutes if estimated_minutes is not None else node.estimated_minutes,
                    )
                )
            else:
                nodes.append(node)
        if not found:
            raise ValueError(f"unknown node: {node_id}")
        return self.save_graph_draft(goal_id, tuple(nodes), state.graph.edges, expected_version=state.version, allow_published=True)

    def add_dependency(self, goal_id: str, source: str, target: str) -> GraphSnapshot:
        state = self._repository.get(goal_id)
        if state.graph is None:
            raise ValueError("graph draft is required")
        edge = GraphEdge(source, target)
        if edge in state.graph.edges:
            return state.graph
        return self.save_graph_draft(goal_id, state.graph.nodes, state.graph.edges + (edge,), expected_version=state.version,
                                     allow_published=True)

    def publish_graph(self, goal_id: str, expected_revision: int, expected_version: int | None = None) -> GraphSnapshot:
        def update(state):
            self.check_version(state, expected_version)
            if state.graph is None:
                raise PlanningError("graph_required", "graph draft is required")
            if not state.goal.confirmed:
                raise PlanningError("goal_unconfirmed", "Confirm the edited goal before publication.")
            published = publish_graph(state.graph, expected_revision=expected_revision)
            self._require_editable(state)
            state.graph = published
            return state.graph
        return self._mutate(goal_id, update)

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
