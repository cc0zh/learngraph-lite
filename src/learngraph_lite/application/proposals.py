"""Application service for graph proposal review."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import json
from threading import RLock
from typing import Annotated, Callable, Literal, Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from learngraph_lite.application.learning import LearningState, migrate_learning_graph
from learngraph_lite.application.planning import PlanningState
from learngraph_lite.application.documents import DocumentAccessError, DocumentRepository, DocumentService
from learngraph_lite.application.document_agent import locate_source

from learngraph_lite.domain.learning import GraphEdge, GraphNode, GraphSnapshot, GraphStatus
from learngraph_lite.domain.learning.proposals import (
    GraphOperation,
    GraphOperationKind,
    GraphProposal,
    ProposalStatus,
    accept_proposal,
    apply_operations,
    reject_proposal,
    validate_proposal,
)

T = TypeVar("T")
Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2000)]
Identifier = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128)]


class ProposalError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProposalNode(StrictInput):
    id: Identifier
    title: Text
    estimated_minutes: int = Field(ge=1, le=10080)
    explanation: str = Field(default="", max_length=2000)
    learning_outcome: str = Field(default="", max_length=2000)
    priority: int = Field(default=0, ge=0, le=5)
    citation_ids: list[Identifier] = Field(default_factory=list, max_length=5)


class ProposalEdge(StrictInput):
    source: Identifier
    target: Identifier
    kind: Literal["prerequisite"] = "prerequisite"


class AddNode(StrictInput):
    kind: Literal["add_node"]
    node: ProposalNode


class UpdateNode(StrictInput):
    kind: Literal["update_node"]
    node_id: Identifier
    title: Text | None = None
    explanation: str | None = Field(default=None, max_length=2000)
    learning_outcome: str | None = Field(default=None, max_length=2000)
    priority: int | None = Field(default=None, ge=0, le=5)
    estimated_minutes: int | None = Field(default=None, ge=1, le=10080)

    @model_validator(mode="before")
    @classmethod
    def valid_update(cls, value):
        if isinstance(value, dict) and (not (value.keys() - {"kind", "node_id"})
                                       or any(item is None for item in value.values())):
            raise ValueError("update requires a non-null editable field")
        return value


class DependencyOperation(StrictInput):
    kind: Literal["add_dependency", "remove_dependency"]
    edge: ProposalEdge


OperationInput = Annotated[AddNode | UpdateNode | DependencyOperation, Field(discriminator="kind")]


class CandidateProposal(StrictInput):
    rationale: Text
    operations: list[OperationInput] = Field(min_length=1, max_length=60)

    def domain_operations(self) -> tuple[GraphOperation, ...]:
        operations = []
        for item in self.operations:
            data = item.model_dump(exclude_unset=True)
            data["kind"] = GraphOperationKind(data["kind"])
            if isinstance(item, AddNode):
                data["node"] = GraphNode(**{**item.node.model_dump(), "citation_ids": tuple(item.node.citation_ids)})
            if isinstance(item, DependencyOperation):
                data["edge"] = GraphEdge(**item.edge.model_dump())
            operations.append(GraphOperation(**data))
        return tuple(operations)


class ProposalInput(CandidateProposal):
    base_revision: int = Field(ge=0)


def public_proposal(proposal: GraphProposal) -> dict:
    operations = []
    for operation in proposal.operations:
        value = {name: value for name, value in asdict(operation).items() if value is not None}
        if value.get("node") is not None:
            value["node"]["citation_ids"] = list(value["node"]["citation_ids"])
        operations.append(value)
    return {"id": proposal.id, "goal_id": proposal.goal_id, "base_revision": proposal.base_revision,
            "operations": operations, "rationale": proposal.rationale, "status": proposal.status.value}


@dataclass
class ProposalReviewState:
    planning: PlanningState
    learning: LearningState | None
    proposals: dict[str, GraphProposal]
    operations: dict[str, dict]


class ProposalCoordinator(Protocol):
    """A short atomic unit of work; the callback must never call a model."""
    def transact(self, goal_id: str, update: Callable[[ProposalReviewState], T]) -> T: ...


class ProposalRepository(Protocol):
    def list(self, goal_id: str) -> tuple[GraphProposal, ...]: ...
    def get(self, proposal_id: str) -> GraphProposal: ...
    def operation(self, goal_id: str, key: str) -> dict | None: ...


@dataclass
class InMemoryProposalRepository:
    proposals: dict[str, GraphProposal] = field(default_factory=dict)
    operations: dict[str, dict[str, dict]] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def save(self, proposal: GraphProposal) -> None:
        self.proposals[proposal.id] = proposal

    def get(self, proposal_id: str) -> GraphProposal:
        try:
            return self.proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"unknown proposal: {proposal_id}") from exc

    def list(self, goal_id: str) -> tuple[GraphProposal, ...]:
        with self._lock:
            return tuple(item for item in self.proposals.values() if item.goal_id == goal_id)

    def operation(self, goal_id: str, key: str) -> dict | None:
        with self._lock:
            return deepcopy(self.operations.get(goal_id, {}).get(key))


class InMemoryProposalCoordinator:
    """Offline adapter with the same rollback boundary as the SQLite adapter."""
    def __init__(self, proposals: InMemoryProposalRepository, planning, learning):
        self._proposals, self._planning, self._learning = proposals, planning, learning

    def transact(self, goal_id: str, update: Callable[[ProposalReviewState], T]) -> T:
        with self._proposals._lock, self._planning._lock, self._learning._lock:
            try:
                learning = deepcopy(self._learning.get(goal_id))
            except KeyError:
                learning = None
            state = ProposalReviewState(self._planning.get(goal_id), learning,
                {p.id: p for p in self._proposals.list(goal_id)},
                deepcopy(self._proposals.operations.get(goal_id, {})))
            result = update(state)
            self._planning.save(goal_id, state.planning)
            if state.learning is not None:
                self._learning.save(goal_id, state.learning)
            self._proposals.proposals.update(state.proposals)
            self._proposals.operations[goal_id] = state.operations
            return result


class GraphProposalService:
    def __init__(self, repository: ProposalRepository, coordinator: ProposalCoordinator | None = None,
                 documents: DocumentRepository | None = None):
        self._repository = repository
        self._coordinator = coordinator
        self._documents = DocumentService(documents) if documents is not None else None

    def _check_sources(self, graph: GraphSnapshot) -> None:
        for citation_id in {key for node in graph.nodes for key in node.citation_ids}:
            if self._documents is None:
                raise ProposalError("source_unavailable", "Graph citation retrieval is not configured.")
            try:
                locate_source(self._documents, graph.goal_id, None, graph.citation_map[citation_id])
            except (DocumentAccessError, KeyError, TypeError) as exc:
                raise ProposalError("stale_proposal_sources", "Graph source is unavailable or stale; retrieve it again.") from exc

    def published(self, goal_id: str) -> GraphSnapshot:
        def read(state):
            return self._graph(state)
        return self._transact(goal_id, read)

    @staticmethod
    def _graph(state: ProposalReviewState) -> GraphSnapshot:
        graph = state.planning.graph
        if not state.planning.goal.confirmed or graph is None or graph.status != GraphStatus.PUBLISHED:
            raise ProposalError("graph_not_published", "A confirmed goal and published graph are required.")
        return graph

    def _transact(self, goal_id: str, update):
        if self._coordinator is None:
            raise ProposalError("proposal_not_configured", "Proposal review is not configured.")
        try:
            return self._coordinator.transact(goal_id, update)
        except KeyError as exc:
            raise ProposalError("goal_not_found", "Goal does not exist.") from exc

    def list_proposals(self, goal_id: str) -> dict:
        self.published(goal_id)
        return {"proposals": [public_proposal(item) for item in self._repository.list(goal_id)]}

    def get_proposal(self, goal_id: str, proposal_id: str) -> dict:
        return public_proposal(self._scoped(goal_id, proposal_id))

    def _scoped(self, goal_id: str, proposal_id: str) -> GraphProposal:
        try:
            proposal = self._repository.get(proposal_id)
        except KeyError as exc:
            raise ProposalError("proposal_not_found", "Proposal does not exist in this goal.") from exc
        if proposal.goal_id != goal_id:
            raise ProposalError("proposal_not_found", "Proposal does not exist in this goal.")
        return proposal

    def existing(self, goal_id: str, key: str, fingerprint: str) -> dict | None:
        operation = self._repository.operation(goal_id, key)
        if operation is None:
            return None
        if operation["fingerprint"] != fingerprint:
            raise ProposalError("operation_conflict", "This operation already used different input.")
        result = self.get_proposal(goal_id, operation["id"])
        if result["status"] == ProposalStatus.CONFLICTED:
            raise ProposalError("revision_conflict", "Proposal is conflicted; read the current graph.")
        return result

    def create(self, goal_id: str, operation_key: str, args: dict, *, fingerprint: str | None = None,
               before_save: Callable[[], None] | None = None) -> dict:
        try:
            config = ProposalInput.model_validate(args, strict=True)
        except ValidationError as exc:
            raise ProposalError("invalid_proposal", "Invalid graph proposal operations or fields.") from exc
        fingerprint = fingerprint if fingerprint is not None else json.dumps(config.model_dump(exclude_none=True),
                                                                           ensure_ascii=False, sort_keys=True)
        def commit(state):
            previous = state.operations.get(operation_key)
            if previous is not None:
                if previous["fingerprint"] != fingerprint:
                    raise ProposalError("operation_conflict", "This operation already used different input.")
                return state.proposals[previous["id"]]
            graph = self._graph(state)
            proposal = GraphProposal(str(uuid4()), goal_id, config.base_revision,
                                     config.domain_operations(), config.rationale)
            if proposal.base_revision != graph.revision:
                proposal = replace(proposal, status=ProposalStatus.CONFLICTED)
            else:
                errors = validate_proposal(proposal, graph)
                if errors:
                    raise ProposalError("invalid_proposal", "; ".join(errors))
                self._check_sources(apply_operations(graph, proposal.operations, validate=True))
            if before_save is not None:
                before_save()
            state.proposals[proposal.id] = proposal
            state.operations[operation_key] = {"fingerprint": fingerprint, "id": proposal.id}
            return proposal
        result = self._transact(goal_id, commit)
        if result.status == ProposalStatus.CONFLICTED:
            raise ProposalError("revision_conflict", "Proposal base revision is stale; conflict was saved.")
        return public_proposal(result)

    def decide(self, goal_id: str, proposal_id: str, decision: str, expected_revision: int) -> dict:
        self._scoped(goal_id, proposal_id)
        if decision not in {"accept", "reject"} or type(expected_revision) is not int or expected_revision < 0:
            raise ProposalError("invalid_decision", "Decision and nonnegative expected_revision are required.")
        def commit(state):
            proposal = state.proposals[proposal_id]
            graph = self._graph(state)
            target = ProposalStatus.ACCEPTED if decision == "accept" else ProposalStatus.REJECTED
            if proposal.status == target and proposal.decision_revision == expected_revision:
                return proposal
            if proposal.status != ProposalStatus.PENDING:
                raise ProposalError("decision_conflict", "Proposal already has a different decision or revision.")
            if graph.revision != expected_revision or graph.revision != proposal.base_revision:
                decided = replace(proposal, status=ProposalStatus.CONFLICTED)
            elif decision == "reject":
                decided = replace(reject_proposal(proposal), decision_revision=expected_revision)
            else:
                if state.learning is None or state.learning.graph != graph:
                    raise ProposalError("stale_learning_graph", "Learning state is unavailable or stale; no implicit reset.")
                decided, updated = accept_proposal(proposal, graph)
                self._check_sources(updated)
                reset = migrate_learning_graph(state.learning, updated)
                state.planning.graph = updated
                state.planning.version += 1
                decided = replace(decided, decision_revision=expected_revision, learning_reset=reset)
            state.proposals[proposal_id] = decided
            return decided
        def review(state):
            decided = commit(state)
            return {"proposal": public_proposal(decided), "planning": {"goal_id": goal_id, **asdict(state.planning)},
                    "learning_reset": decided.learning_reset}
        result = self._transact(goal_id, review)
        if result["proposal"]["status"] == ProposalStatus.CONFLICTED:
            raise ProposalError("revision_conflict", "Graph revision changed; proposal conflict was saved.")
        return result

    def create_proposal(
        self,
        *,
        proposal_id: str,
        graph: GraphSnapshot,
        base_revision: int,
        operations: tuple[GraphOperation, ...],
        rationale: str,
    ) -> GraphProposal:
        proposal = GraphProposal(
            id=proposal_id,
            goal_id=graph.goal_id,
            base_revision=base_revision,
            operations=operations,
            rationale=rationale,
        )
        errors = validate_proposal(proposal, graph)
        if errors:
            raise ValueError("; ".join(errors))
        self._repository.save(proposal)
        return proposal

    def reject(self, proposal_id: str) -> GraphProposal:
        proposal = reject_proposal(self._repository.get(proposal_id))
        self._repository.save(proposal)
        return proposal

    def accept(self, proposal_id: str, graph: GraphSnapshot) -> tuple[GraphProposal, GraphSnapshot]:
        proposal = self._repository.get(proposal_id)
        decided, updated = accept_proposal(proposal, graph)
        self._repository.save(decided)
        return decided, updated

    def mark_conflicted(self, proposal_id: str) -> GraphProposal:
        proposal = replace(self._repository.get(proposal_id), status=ProposalStatus.CONFLICTED)
        self._repository.save(proposal)
        return proposal
