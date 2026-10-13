"""Deterministic mastery scoring rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MasteryState(StrEnum):
    UNKNOWN = "unknown"
    LEARNING = "learning"
    PROFICIENT = "proficient"


@dataclass(frozen=True)
class AttemptResult:
    exercise_id: str
    is_correct: bool


def score_mastery(attempts: tuple[AttemptResult, ...]) -> tuple[MasteryState, int, float]:
    """Score recent distinct first attempts following the project spec."""

    latest_by_exercise: dict[str, bool] = {}
    for attempt in attempts:
        latest_by_exercise.setdefault(attempt.exercise_id, attempt.is_correct)
    recent = list(latest_by_exercise.values())[-5:]
    sample_count = len(recent)
    if sample_count == 0:
        return MasteryState.UNKNOWN, 0, 0.0
    accuracy = sum(1 for item in recent if item) / sample_count
    if sample_count >= 3 and accuracy >= 0.8:
        return MasteryState.PROFICIENT, sample_count, accuracy
    return MasteryState.LEARNING, sample_count, accuracy
