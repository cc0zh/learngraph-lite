"""Graph change proposal rules.

Agents may propose graph changes, but only an explicit user decision can apply
them to the published learning graph.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .graph import GraphDraft, GraphEdge, GraphNode, GraphSnapshot, GraphStatus, GraphValidationError, validate_graph


class ProposalStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


class GraphOperationKind(StrEnum):
    ADD_NODE = "add_node"
    UPDATE_NODE = "update_node"
    ADD_DEPENDENCY = "add_dependency"
    REMOVE_DEPENDENCY = "remove_dependency"


@dataclass(frozen=True)
class GraphOperation:
    kind: GraphOperationKind
    node: GraphNode | None = None
    node_id: str | None = None
    title: str | None = None
    estimated_minutes: int | None = None
    edge: GraphEdge | None = None


@dataclass(frozen=True)
class GraphProposal:
    id: str
    goal_id: str
    base_revision: int
    operations: tuple[GraphOperation, ...]
    rationale: str
    status: ProposalStatus = ProposalStatus.PENDING


def validate_proposal(proposal: GraphProposal, graph: GraphSnapshot) -> tuple[str, ...]:
    errors: list[str] = []
    if proposal.goal_id != graph.goal_id:
        errors.append("proposal goal scope does not match graph")
    if proposal.status != ProposalStatus.PENDING:
        errors.append("proposal is not pending")
    if not proposal.operations:
        errors.append("proposal needs at least one operation")
    try:
        apply_operations(graph, proposal.operations, validate=True)
    except GraphValidationError as exc:
        errors.extend(exc.errors)
    except ValueError as exc:
        errors.append(str(exc))
    return tuple(errors)


def accept_proposal(proposal: GraphProposal, graph: GraphSnapshot) -> tuple[GraphProposal, GraphSnapshot]:
    if proposal.base_revision != graph.revision:
        return replace(proposal, status=ProposalStatus.CONFLICTED), graph
    errors = validate_proposal(proposal, graph)
    if errors:
        raise GraphValidationError(errors)
    updated = apply_operations(graph, proposal.operations, validate=True)
    accepted = replace(proposal, status=ProposalStatus.ACCEPTED)
    return accepted, updated


def reject_proposal(proposal: GraphProposal) -> GraphProposal:
    if proposal.status != ProposalStatus.PENDING:
        raise ValueError("only pending proposals can be rejected")
    return replace(proposal, status=ProposalStatus.REJECTED)


def apply_operations(graph: GraphSnapshot, operations: tuple[GraphOperation, ...], *, validate: bool) -> GraphSnapshot:
    nodes = list(graph.nodes)
    edges = list(graph.edges)
    for operation in operations:
        if operation.kind == GraphOperationKind.ADD_NODE:
            if operation.node is None:
                raise ValueError("add_node requires node")
            if any(node.id == operation.node.id for node in nodes):
                raise ValueError(f"duplicate node: {operation.node.id}")
            nodes.append(operation.node)
        elif operation.kind == GraphOperationKind.UPDATE_NODE:
            if not operation.node_id:
                raise ValueError("update_node requires node_id")
            found = False
            for index, node in enumerate(nodes):
                if node.id == operation.node_id:
                    found = True
                    nodes[index] = GraphNode(
                        id=node.id,
                        title=operation.title if operation.title is not None else node.title,
                        estimated_minutes=operation.estimated_minutes if operation.estimated_minutes is not None else node.estimated_minutes,
                    )
                    break
            if not found:
                raise ValueError(f"unknown node: {operation.node_id}")
        elif operation.kind == GraphOperationKind.ADD_DEPENDENCY:
            if operation.edge is None:
                raise ValueError("add_dependency requires edge")
            if operation.edge not in edges:
                edges.append(operation.edge)
        elif operation.kind == GraphOperationKind.REMOVE_DEPENDENCY:
            if operation.edge is None:
                raise ValueError("remove_dependency requires edge")
            edges = [edge for edge in edges if edge != operation.edge]
        else:
            raise ValueError(f"unsupported operation: {operation.kind}")

    if validate:
        errors = validate_graph(GraphDraft(nodes=tuple(nodes), edges=tuple(edges)))
        if errors:
            raise GraphValidationError(errors)
    return GraphSnapshot(
        goal_id=graph.goal_id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        status=GraphStatus.PUBLISHED,
        revision=graph.revision + 1,
        content_revision=graph.content_revision + 1,
    )
