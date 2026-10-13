#!/usr/bin/env python
"""Replay a scoped Agent turn over SQLite; real calls require explicit --real."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from learngraph_lite.agent_core import ModelResponse, ToolCall
from learngraph_lite.application.agent import RunRequest
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.planning import PlanningService, candidate_rag_graph
from learngraph_lite.bootstrap import build_learning_loop, build_real_gateway
from learngraph_lite.infrastructure import SQLiteLearningRepository, SQLitePlanningRepository


class LearningFixtureModel:
    def complete(self, messages, tools):
        results = [json.loads(message.content) for message in messages if message.role == "tool"]
        if not results:
            return ModelResponse(tool_calls=(
                ToolCall("context-1", "get_learning_context", "{}"),
                ToolCall("next-1", "get_next_action", '{"available_minutes":10}'),
            ))
        context, action = results
        return ModelResponse(content=(
            f"fixture：{context['goal']['title']}；当前节点 {context['node']['title']}，"
            f"掌握度 {context['node']['mastery']}，有效样本 {context['node']['sample_count']}。"
            f"下一步 {action['action_type']}:{action['node_id']}；{action['reason_text']}"
        ))


def run_demo(database: Path, *, real: bool = False) -> dict:
    database.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a new file, so demo setup can never reset an existing user's state.
    with database.open("xb"):
        pass
    planning_repository = SQLitePlanningRepository(database)
    learning_repository = SQLiteLearningRepository(database)
    planning = PlanningService(planning_repository)
    planning.create_goal("demo-goal", "四周做出带引用的 RAG 应用", desired_outcome="可演示的 RAG demo",
                         current_level="Python 基础", time_budget_minutes=1200)
    planning.confirm_goal("demo-goal")
    draft = candidate_rag_graph("demo-goal")
    planning.save_graph_draft("demo-goal", draft.nodes, draft.edges)
    graph = planning.publish_graph("demo-goal", expected_revision=0)
    learning = LearningService(learning_repository)
    learning.start_goal(graph)
    for index in range(3):
        learning.create_fixture_exercise("demo-goal", "rag-goal", f"e{index}", f"演示引用题 {index}")
        learning.submit_answer("demo-goal", f"e{index}", "b", f"a{index}")

    model = build_real_gateway() if real else LearningFixtureModel()
    loop = build_learning_loop(model, planning_repository, learning_repository)
    try:
        record = loop.run(RunRequest("demo-session", "解释当前节点，并告诉我十分钟内下一步做什么。", "demo-1",
                                     goal_id="demo-goal", node_id="document-loading"))
        if record.status != "completed":
            raise RuntimeError(record.error or record.status)
        return {"mode": "real" if real else "fixture", "data": "fixture-seeded SQLite",
                "goal_id": "demo-goal", "node_id": "document-loading", "status": record.status,
                "final_text": record.final_text, "usage": record.usage}
    finally:
        loop.close()
        if real:
            model.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="Keep a NEW demo database; refuses existing files.")
    parser.add_argument("--real", action="store_true", help="Call configured provider (may incur cost); data stays fixture.")
    args = parser.parse_args()
    try:
        if args.database is not None:
            result = run_demo(args.database, real=args.real)
        else:
            with TemporaryDirectory() as directory:
                result = run_demo(Path(directory) / "demo.sqlite3", real=args.real)
    except FileExistsError:
        parser.exit(2, "Refusing to overwrite an existing demo database. Choose a new path.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
