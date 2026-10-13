from __future__ import annotations

from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningService, candidate_rag_graph
from learngraph_lite.application.proposals import GraphProposalService, InMemoryProposalRepository
from learngraph_lite.domain.learning import GraphEdge, GraphNode, GraphOperation, GraphOperationKind, ProposalStatus


def published_graph():
    planning = PlanningService(InMemoryPlanningRepository())
    planning.create_goal("g1", "四周做出 RAG 应用", desired_outcome="demo", current_level="Python", time_budget_minutes=1200)
    planning.confirm_goal("g1")
    graph = candidate_rag_graph("g1")
    planning.save_graph_draft("g1", graph.nodes, graph.edges)
    return planning.publish_graph("g1", expected_revision=0)


def test_agent_proposal_does_not_change_graph_until_accepted():
    graph = published_graph()
    service = GraphProposalService(InMemoryProposalRepository())
    proposal = service.create_proposal(
        proposal_id="p1",
        graph=graph,
        base_revision=graph.revision,
        operations=(GraphOperation(GraphOperationKind.ADD_NODE, node=GraphNode("rerank", "重排入门", 30)),),
        rationale="补充检索质量优化节点",
    )
    assert proposal.status == ProposalStatus.PENDING
    assert all(node.id != "rerank" for node in graph.nodes)

    decided, updated = service.accept("p1", graph)
    assert decided.status == ProposalStatus.ACCEPTED
    assert any(node.id == "rerank" for node in updated.nodes)
    assert updated.revision == graph.revision + 1
    assert updated.content_revision == graph.content_revision + 1


def test_rejected_proposal_has_no_graph_side_effect():
    graph = published_graph()
    service = GraphProposalService(InMemoryProposalRepository())
    proposal = service.create_proposal(
        proposal_id="p1",
        graph=graph,
        base_revision=graph.revision,
        operations=(GraphOperation(GraphOperationKind.UPDATE_NODE, node_id="chunking", title="新标题"),),
        rationale="用户不一定接受",
    )
    rejected = service.reject(proposal.id)
    assert rejected.status == ProposalStatus.REJECTED
    assert next(node for node in graph.nodes if node.id == "chunking").title == "分块策略"


def test_stale_base_revision_conflicts_without_overwrite():
    graph = published_graph()
    service = GraphProposalService(InMemoryProposalRepository())
    proposal = service.create_proposal(
        proposal_id="p1",
        graph=graph,
        base_revision=graph.revision,
        operations=(GraphOperation(GraphOperationKind.ADD_DEPENDENCY, edge=GraphEdge("rag-goal", "citations")),),
        rationale="补一条依赖",
    )
    newer = type(graph)(
        goal_id=graph.goal_id,
        nodes=graph.nodes,
        edges=graph.edges,
        status=graph.status,
        revision=graph.revision + 1,
        content_revision=graph.content_revision,
    )
    decided, updated = service.accept(proposal.id, newer)
    assert decided.status == ProposalStatus.CONFLICTED
    assert updated == newer


def test_invalid_proposal_operations_are_rejected():
    graph = published_graph()
    service = GraphProposalService(InMemoryProposalRepository())
    try:
        service.create_proposal(
            proposal_id="p1",
            graph=graph,
            base_revision=graph.revision,
            operations=(GraphOperation(GraphOperationKind.ADD_DEPENDENCY, edge=GraphEdge("citations", "rag-goal")),),
            rationale="会形成环",
        )
    except ValueError as exc:
        assert "acyclic" in str(exc)
    else:
        raise AssertionError("cyclic proposal should fail")
