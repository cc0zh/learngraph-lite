"""Application use cases for M3 node learning, practice and recommendation."""

from __future__ import annotations

from dataclasses import dataclass, field

from learngraph_lite.application.agent import AgentLoop, RunRequest
from learngraph_lite.domain.learning import GraphSnapshot, MasteryState
from learngraph_lite.domain.learning.exercises import (
    Attempt,
    ExerciseOption,
    ExercisePrivate,
    ExercisePublic,
    build_single_choice_exercise,
    judge_attempt,
)
from learngraph_lite.domain.learning.mastery import AttemptResult, score_mastery
from learngraph_lite.domain.learning.recommendations import NextAction, recommend_next_action


@dataclass
class LearningState:
    graph: GraphSnapshot
    exercises: dict[str, ExercisePrivate] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
    run_ids_by_key: dict[str, str] = field(default_factory=dict)


@dataclass
class InMemoryLearningRepository:
    _states: dict[str, LearningState] = field(default_factory=dict)

    def save(self, goal_id: str, state: LearningState) -> None:
        self._states[goal_id] = state

    def get(self, goal_id: str) -> LearningState:
        try:
            return self._states[goal_id]
        except KeyError as exc:
            raise KeyError(f"unknown learning goal: {goal_id}") from exc


class LearningService:
    def __init__(self, repository: InMemoryLearningRepository, loop: AgentLoop):
        self._repository = repository
        self._loop = loop

    def start_goal(self, graph: GraphSnapshot) -> None:
        self._repository.save(graph.goal_id, LearningState(graph=graph))

    def learn_node(self, goal_id: str, node_id: str, user_text: str, request_id: str) -> str:
        state = self._repository.get(goal_id)
        _require_node(state.graph, node_id)
        record = self._loop.run(
            RunRequest(
                session_id=f"{goal_id}:{node_id}",
                user_text=user_text,
                idempotency_key=request_id,
            )
        )
        state.run_ids_by_key.setdefault(request_id, record.run_id)
        return record.final_text

    def create_fixture_exercise(self, goal_id: str, node_id: str, exercise_id: str, prompt: str) -> ExercisePublic:
        state = self._repository.get(goal_id)
        _require_node(state.graph, node_id)
        exercise = build_single_choice_exercise(
            exercise_id=exercise_id,
            goal_id=goal_id,
            node_id=node_id,
            graph_content_revision=state.graph.content_revision,
            prompt=prompt,
            options=(
                ExerciseOption("a", "只生成没有来源的自然语言回答"),
                ExerciseOption("b", "先检索资料片段，再基于片段回答并返回引用"),
                ExerciseOption("c", "让前端自己判断答案是否可信"),
            ),
            correct_option_id="b",
            explanation="RAG 学习节点要求回答能被资料片段和引用核查。",
        )
        if any(existing.normalized_hash == exercise.normalized_hash and existing.node_id == node_id for existing in state.exercises.values()):
            raise ValueError("duplicate exercise for current node revision")
        state.exercises[exercise.id] = exercise
        return exercise.to_public()

    def submit_answer(self, goal_id: str, exercise_id: str, selected_option_id: str, attempt_id: str) -> Attempt:
        state = self._repository.get(goal_id)
        exercise = state.exercises[exercise_id]
        if exercise.graph_content_revision != state.graph.content_revision:
            raise ValueError("exercise version is stale")
        previous = tuple(attempt for attempt in state.attempts if attempt.exercise_id == exercise_id)
        attempt = judge_attempt(
            attempt_id=attempt_id,
            exercise=exercise,
            selected_option_id=selected_option_id,
            previous_attempts_for_exercise=previous,
        )
        state.attempts.append(attempt)
        return attempt

    def mastery(self, goal_id: str, node_id: str) -> tuple[MasteryState, int, float]:
        state = self._repository.get(goal_id)
        counted = tuple(
            AttemptResult(attempt.exercise_id, attempt.is_correct)
            for attempt in state.attempts
            if attempt.node_id == node_id and attempt.counted
        )
        return score_mastery(counted)

    def next_action(self, goal_id: str, available_minutes: int | None = None) -> NextAction:
        state = self._repository.get(goal_id)
        mastery = {node.id: self.mastery(goal_id, node.id)[0] for node in state.graph.nodes}
        recent_wrong = tuple(attempt.node_id for attempt in state.attempts if attempt.counted and not attempt.is_correct)[-5:]
        return recommend_next_action(
            graph=state.graph,
            mastery_by_node=mastery,
            recent_wrong_node_ids=recent_wrong,
            available_minutes=available_minutes,
        )


def _require_node(graph: GraphSnapshot, node_id: str) -> None:
    if node_id not in {node.id for node in graph.nodes}:
        raise ValueError(f"unknown node: {node_id}")
