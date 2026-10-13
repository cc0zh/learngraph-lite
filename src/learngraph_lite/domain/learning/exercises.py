"""Deterministic exercise and attempt rules."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class ExerciseOption:
    id: str
    text: str


@dataclass(frozen=True)
class ExercisePrivate:
    id: str
    goal_id: str
    node_id: str
    graph_content_revision: int
    prompt: str
    options: tuple[ExerciseOption, ...]
    correct_option_id: str
    explanation: str
    normalized_hash: str
    source_mode: str = "general"
    citation_ids: tuple[str, ...] = ()
    citation_map: dict[str, dict] = field(default_factory=dict)

    def to_public(self) -> "ExercisePublic":
        return ExercisePublic(
            id=self.id,
            goal_id=self.goal_id,
            node_id=self.node_id,
            graph_content_revision=self.graph_content_revision,
            prompt=self.prompt,
            options=self.options,
            source_mode=self.source_mode,
            citation_ids=self.citation_ids,
            citation_map=self.citation_map,
        )


@dataclass(frozen=True)
class ExercisePublic:
    id: str
    goal_id: str
    node_id: str
    graph_content_revision: int
    prompt: str
    options: tuple[ExerciseOption, ...]
    source_mode: str = "general"
    citation_ids: tuple[str, ...] = ()
    citation_map: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class Attempt:
    id: str
    exercise_id: str
    goal_id: str
    node_id: str
    selected_option_id: str
    is_correct: bool
    counted: bool
    created_at: datetime


def build_single_choice_exercise(
    *,
    exercise_id: str,
    goal_id: str,
    node_id: str,
    graph_content_revision: int,
    prompt: str,
    options: tuple[ExerciseOption, ...],
    correct_option_id: str,
    explanation: str,
) -> ExercisePrivate:
    option_ids = [option.id for option in options]
    if len(options) < 2:
        raise ValueError("single choice exercise needs at least two options")
    if len(option_ids) != len(set(option_ids)):
        raise ValueError("option ids must be unique")
    if correct_option_id not in option_ids:
        raise ValueError("correct option must exist")
    normalized = _normalize_exercise(prompt, options)
    return ExercisePrivate(
        id=exercise_id,
        goal_id=goal_id,
        node_id=node_id,
        graph_content_revision=graph_content_revision,
        prompt=prompt.strip(),
        options=options,
        correct_option_id=correct_option_id,
        explanation=explanation.strip(),
        normalized_hash=normalized,
    )


def judge_attempt(
    *,
    attempt_id: str,
    exercise: ExercisePrivate,
    selected_option_id: str,
    previous_attempts_for_exercise: tuple[Attempt, ...],
) -> Attempt:
    if selected_option_id not in {option.id for option in exercise.options}:
        raise ValueError("selected option does not exist")
    first_counted = not any(attempt.counted for attempt in previous_attempts_for_exercise)
    return Attempt(
        id=attempt_id,
        exercise_id=exercise.id,
        goal_id=exercise.goal_id,
        node_id=exercise.node_id,
        selected_option_id=selected_option_id,
        is_correct=selected_option_id == exercise.correct_option_id,
        counted=first_counted,
        created_at=datetime.now(UTC),
    )


def _normalize_exercise(prompt: str, options: tuple[ExerciseOption, ...]) -> str:
    payload = {
        "prompt": " ".join(prompt.casefold().split()),
        "options": [" ".join(option.text.casefold().split()) for option in options],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
