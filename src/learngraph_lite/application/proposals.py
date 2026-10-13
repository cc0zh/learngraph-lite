"""Application service for graph proposal review."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from learngraph_lite.domain.learning import GraphSnapshot
from learngraph_lite.domain.learning.proposals import (
    GraphOperation,
    GraphProposal,
    ProposalStatus,
    accept_proposal,
    reject_proposal,
    validate_proposal,
)


@dataclass
class InMemoryProposalRepository:
    proposals: dict[str, GraphProposal] = field(default_factory=dict)

    def save(self, proposal: GraphProposal) -> None:
        self.proposals[proposal.id] = proposal

    def get(self, proposal_id: str) -> GraphProposal:
        try:
            return self.proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"unknown proposal: {proposal_id}") from exc


class GraphProposalService:
    def __init__(self, repository: InMemoryProposalRepository):
        self._repository = repository

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
