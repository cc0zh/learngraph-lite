"""Narrow transactional deletion port; tombstones contain identities, never content."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DeletedScope:
    session_ids: frozenset[str] = frozenset()
    run_ids: frozenset[str] = frozenset()


class LifecycleRepository(Protocol):
    def delete_conversation(self, session_id: str) -> DeletedScope: ...

    def delete_goal(self, goal_id: str, expected_version: int) -> DeletedScope: ...
