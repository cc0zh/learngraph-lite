"""Pure graph validation for goal-scoped learning routes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphNode:
    id: str
    title: str
    estimated_minutes: int


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str = "prerequisite"


@dataclass(frozen=True)
class GraphDraft:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


def validate_graph(graph: GraphDraft) -> tuple[str, ...]:
    errors: list[str] = []
    ids = [node.id for node in graph.nodes]
    id_set = set(ids)
    if len(ids) != len(id_set):
        errors.append("node ids must be unique")
    for node in graph.nodes:
        if not node.id.strip():
            errors.append("node id is required")
        if not node.title.strip():
            errors.append(f"node {node.id} title is required")
        if node.estimated_minutes <= 0:
            errors.append(f"node {node.id} estimated_minutes must be positive")
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in id_set}
    for edge in graph.edges:
        if edge.kind != "prerequisite":
            errors.append(f"unsupported edge kind: {edge.kind}")
        if edge.source == edge.target:
            errors.append(f"self edge is not allowed: {edge.source}")
        if edge.source not in id_set or edge.target not in id_set:
            errors.append(f"edge endpoint missing: {edge.source}->{edge.target}")
        else:
            adjacency[edge.source].append(edge.target)
    if _has_cycle(adjacency):
        errors.append("graph must be acyclic")
    return tuple(errors)


def _has_cycle(adjacency: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for next_node in adjacency.get(node, []):
            if visit(next_node):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in adjacency)
