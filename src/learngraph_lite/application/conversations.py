"""Persistent conversation identities, separate from runs and node learning facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from threading import RLock
from typing import Callable, Literal, Protocol, TypeVar
from uuid import UUID

from learngraph_lite.application.agent import AgentLoop, RunRecord
from learngraph_lite.application.planning import PlanningService, PlanningState
from learngraph_lite.domain.learning import GraphStatus, build_goal_draft


T = TypeVar("T")
UNKNOWN_CREATED_AT = datetime(1970, 1, 1, tzinfo=UTC)


class ConversationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Conversation:
    session_id: str
    kind: Literal["planning", "learning", "general"]
    title: str
    goal_id: str | None
    node_id: str | None
    created_at: datetime
    legacy: bool = False


class ConversationRepository(Protocol):
    def list(self) -> tuple[Conversation, ...]: ...

    def get(self, session_id: str) -> Conversation | None: ...

    def create(self, record: Conversation, fingerprint: str) -> Conversation: ...

    def fingerprint(self, session_id: str) -> str | None: ...

    def create_goal(self, goal_id: str, title: str, state: PlanningState, created_at: datetime) -> None: ...

    def goal_created_at(self, goal_id: str) -> datetime | None: ...


class ConversationService:
    def __init__(self, repository: ConversationRepository, planning: PlanningService, loop: AgentLoop):
        self._repository = repository
        self._planning = planning
        self._loop = loop
        # Creation and admission share a process-local boundary, including the first
        # unmanaged run. Never hold a SQLite transaction while submitting/executing.
        self._lock = RLock()

    def list(self) -> tuple[Conversation, ...]:
        with self._lock:
            goals = {item["goal_id"]: item for item in self._planning.list_goals()}
            runs = self._loop.list_all_runs()
            records = {record.session_id: record for record in self._repository.list()}
            for goal_id, item in goals.items():
                session_id = f"planning:{goal_id}"
                first_run = next((run for run in runs if run.session_id == session_id), None)
                # Older planning records never stored a creation timestamp. Do not
                # invent a new one on every read or mutate historical goal data.
                created_at = (self._repository.goal_created_at(goal_id)
                              or (first_run.created_at if first_run else UNKNOWN_CREATED_AT))
                records[session_id] = Conversation(session_id, "planning", item["goal"]["title"],
                                                     goal_id, None, created_at)
            for run in runs:
                if run.session_id in records or run.session_id.startswith("planning:"):
                    continue
                if run.mode not in {"runner", "teaching"} or (run.goal_id is None) != (run.node_id is None):
                    continue
                kind = "learning" if run.goal_id is not None else "general"
                records[run.session_id] = Conversation(run.session_id, kind,
                    self._legacy_title(run, goals), run.goal_id, run.node_id, run.created_at, legacy=True)
            return tuple(sorted(records.values(), key=lambda record: (record.created_at, record.session_id), reverse=True))

    @staticmethod
    def _legacy_title(run: RunRecord, goals: dict) -> str:
        graph = goals.get(run.goal_id, {}).get("graph")
        if graph is not None:
            node = next((node for node in graph["nodes"] if node["id"] == run.node_id), None)
            if node is not None:
                return f"学习：{node['title']}"
        return run.user_text[:80] or "历史会话"

    def get(self, session_id: str) -> Conversation:
        record = next((record for record in self.list() if record.session_id == session_id), None)
        if record is None:
            raise ConversationError("conversation_not_found", "Conversation does not exist.")
        return record

    def create(self, session_id: str, goal_id: str | None = None, node_id: str | None = None,
               title: str | None = None) -> Conversation:
        with self._lock:
            if session_id.startswith("planning:"):
                raise ConversationError("conversation_conflict", "Planning sessions cannot be created as ordinary conversations.")
            if (goal_id is None) != (node_id is None):
                raise ConversationError("invalid_conversation", "goal_id and node_id must be provided together.")
            fingerprint = json.dumps({"goal_id": goal_id, "node_id": node_id, "title": title},
                                     ensure_ascii=False, sort_keys=True)
            existing = self._repository.get(session_id)
            if existing is not None:
                if self._repository.fingerprint(session_id) != fingerprint:
                    raise ConversationError("conversation_conflict", "Conversation ID was already used for different creation input.")
                # A repeat may read an old/removed node, but never creates a new run.
                return existing
            if any(run.session_id == session_id for run in self._loop.list_all_runs()):
                raise ConversationError("conversation_conflict", "A historical session cannot be overwritten.")
            self._require_uuid(session_id)
            default_title = "新对话"
            if goal_id is not None:
                state = self._planning.get_state(goal_id)
                if not state.goal.confirmed or state.graph is None or state.graph.status != GraphStatus.PUBLISHED:
                    raise ConversationError("graph_not_published", "A confirmed goal and published graph are required.")
                node = next((node for node in state.graph.nodes if node.id == node_id), None)
                if node is None:
                    raise ConversationError("node_not_found", "Node does not exist in the published graph.")
                default_title = f"学习：{node.title}"
            record = Conversation(session_id, "learning" if goal_id is not None else "general",
                                  title or default_title, goal_id, node_id, datetime.now(UTC))
            return self._repository.create(record, fingerprint)

    def create_goal(self, goal_id: str, title: str) -> dict:
        self._require_uuid(goal_id)
        with self._lock:
            self._repository.create_goal(goal_id, title, PlanningState(build_goal_draft(title)), datetime.now(UTC))
            return self._planning.describe(goal_id)

    @staticmethod
    def _require_uuid(value: str) -> None:
        try:
            UUID(value)
        except ValueError as exc:
            raise ConversationError("invalid_conversation", "A client-generated UUID is required.") from exc

    def admit(self, session_id: str, goal_id: str | None, node_id: str | None, mode: str,
              submit: Callable[[], T]) -> T:
        """Check immutable directory scope before any run enters its queue."""
        with self._lock:
            if session_id.startswith("planning:"):
                if (mode not in {"planning", "clarify", "graph"}
                        or session_id != f"planning:{goal_id}" or node_id is not None):
                    raise ConversationError("conversation_scope_conflict", "Planning sessions only accept planning tasks.")
            record = self._repository.get(session_id)
            if record is not None:
                if (record.goal_id, record.node_id) != (goal_id, node_id):
                    raise ConversationError("conversation_scope_conflict", "Run scope must match the conversation.")
                if record.kind == "general" and mode != "runner":
                    raise ConversationError("conversation_scope_conflict", "General conversations cannot run teaching tasks.")
            return submit()
