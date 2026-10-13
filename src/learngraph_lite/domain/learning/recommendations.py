"""Deterministic next-step recommendation rules."""

from __future__ import annotations

from dataclasses import dataclass

from .graph import GraphSnapshot
from .mastery import MasteryState


@dataclass(frozen=True)
class NextAction:
    node_id: str | None
    action_type: str
    reason_codes: tuple[str, ...]
    reason_text: str
    estimated_minutes: int
    graph_revision: int


def recommend_next_action(
    *,
    graph: GraphSnapshot,
    mastery_by_node: dict[str, MasteryState],
    recent_wrong_node_ids: tuple[str, ...] = (),
    available_minutes: int | None = None,
) -> NextAction:
    nodes = {node.id: node for node in graph.nodes}
    prerequisites: dict[str, set[str]] = {node.id: set() for node in graph.nodes}
    for edge in graph.edges:
        prerequisites.setdefault(edge.target, set()).add(edge.source)

    available = [
        node
        for node in graph.nodes
        if mastery_by_node.get(node.id, MasteryState.UNKNOWN) != MasteryState.PROFICIENT
        and all(mastery_by_node.get(source, MasteryState.UNKNOWN) == MasteryState.PROFICIENT for source in prerequisites.get(node.id, set()))
    ]
    if not available:
        blocked = [
            node.id
            for node in graph.nodes
            if mastery_by_node.get(node.id, MasteryState.UNKNOWN) != MasteryState.PROFICIENT
            and any(mastery_by_node.get(source, MasteryState.UNKNOWN) != MasteryState.PROFICIENT for source in prerequisites.get(node.id, set()))
        ]
        if blocked:
            return NextAction(
                node_id=blocked[0],
                action_type="review_prerequisite",
                reason_codes=("blocked_by_prerequisite",),
                reason_text="当前节点仍有未熟练的前置依赖，建议先补齐前置节点。",
                estimated_minutes=0,
                graph_revision=graph.revision,
            )
        return NextAction(
            node_id=None,
            action_type="finish_or_project",
            reason_codes=("all_proficient",),
            reason_text="当前路线节点都已达到练习熟练标准，建议进入综合实践或结束本轮学习。",
            estimated_minutes=0,
            graph_revision=graph.revision,
        )

    wrong_priority = {node_id: index for index, node_id in enumerate(recent_wrong_node_ids)}
    available.sort(key=lambda node: (0 if node.id in wrong_priority else 1, wrong_priority.get(node.id, 999),
                                     -node.priority, node.estimated_minutes, node.id))
    chosen = available[0]
    reason_codes = ["available_after_prerequisites"]
    if chosen.id in wrong_priority:
        reason_codes.insert(0, "recent_wrong")
    action_type = "practice" if chosen.id in wrong_priority else "learn_node"
    estimated = chosen.estimated_minutes
    if available_minutes is not None and available_minutes < chosen.estimated_minutes:
        action_type = "short_explanation"
        estimated = available_minutes
        reason_codes.append("limited_time")
    return NextAction(
        node_id=chosen.id,
        action_type=action_type,
        reason_codes=tuple(reason_codes),
        reason_text=f"建议学习 {nodes[chosen.id].title}，因为前置依赖已满足。",
        estimated_minutes=max(0, estimated),
        graph_revision=graph.revision,
    )
