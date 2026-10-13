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
from learngraph_lite.application.documents import DocumentService
from learngraph_lite.application.exercise_generation import GenerateExercise
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.learning_agent import LearningContext
from learngraph_lite.application.planning import PlanningService, candidate_rag_graph
from learngraph_lite.bootstrap import build_learning_loop, build_real_gateway
from learngraph_lite.infrastructure import SQLiteDocumentRepository, SQLiteLearningRepository, SQLitePlanningRepository


class LearningFixtureModel:
    def complete(self, messages, tools):
        if not tools:
            purpose = json.loads(messages[1].content)["purpose"]
            return ModelResponse(content=json.dumps({"exercises": [{
                "prompt": f"清洗资料时如何保留引用定位？（{purpose}）",
                "options": [{"id": "a", "text": "丢弃原文位置"}, {"id": "b", "text": "保存片段与原文偏移"}],
                "correct_option_id": "b", "explanation": "保存偏移可让回答引用返回原文位置；本题非基于上传资料。",
            }]}, ensure_ascii=False))
        results = [json.loads(message.content) for message in messages if message.role == "tool"]
        if any(tool["function"]["name"] == "create_exercise" for tool in tools):
            if not results:
                return ModelResponse(tool_calls=(ToolCall("create-1", "create_exercise", '{"purpose":"demo-teaching"}'),))
            return ModelResponse(content="fixture：练习已保存（非基于上传资料），请选择选项后提交。")
        if not results:
            query = "zzzz-no-match" if "空召回" in messages[2].content else "清洗"
            return ModelResponse(tool_calls=(
                ToolCall("context-1", "get_learning_context", "{}"),
                ToolCall("next-1", "get_next_action", '{"available_minutes":10}'),
                ToolCall("search-1", "search_documents", json.dumps({"query": query})),
            ))
        if len(results) == 3:
            if results[2]["empty"]:
                return ModelResponse(content="fixture：已绑定资料中没有找到依据，资料不足；非基于上传资料的解释应单独标注。")
            citation_id = results[2]["sources"][0]["id"]
            return ModelResponse(tool_calls=(ToolCall("read-1", "read_document_chunk", json.dumps({"citation_id": citation_id})),))
        context, action = results[:2]
        return ModelResponse(content=(
            f"fixture：{context['goal']['title']}；当前节点 {context['node']['title']}，"
            f"掌握度 {context['node']['mastery']}，有效样本 {context['node']['sample_count']}。"
            f"下一步 {action['action_type']}:{action['node_id']}；{action['reason_text']}"
            f"资料原文：{results[3]['text']} [{results[3]['id']}]"
        ))


def run_demo(database: Path, *, real: bool = False) -> dict:
    database.parent.mkdir(parents=True, exist_ok=True)
    # Reserve a new file, so demo setup can never reset an existing user's state.
    with database.open("xb"):
        pass
    planning_repository = SQLitePlanningRepository(database)
    learning_repository = SQLiteLearningRepository(database)
    document_repository = SQLiteDocumentRepository(database)
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

    documents = DocumentService(document_repository)
    documents.upload_text("demo-notes", "资料清洗笔记", "资料清洗先统一换行、去除空白，再分块并保存原文位置用于引用定位。")
    documents.bind_goal("demo-goal", "demo-notes")
    documents.bind_node("demo-goal", "document-loading", "demo-notes")

    model = build_real_gateway() if real else LearningFixtureModel()
    loop = build_learning_loop(model, planning_repository, learning_repository, document_repository)
    try:
        record = loop.run(RunRequest("demo-session", "依据绑定资料解释清洗和引用定位，并告诉我十分钟内下一步做什么。", "demo-1",
                                     goal_id="demo-goal", node_id="document-loading"))
        if record.status != "completed":
            raise RuntimeError(record.error or record.status)
        empty = None
        practice = None
        if not real:
            empty_record = loop.run(RunRequest("empty-session", "演示空召回", "empty-1",
                                              goal_id="demo-goal", node_id="document-loading"))
            if empty_record.status != "completed":
                raise RuntimeError(empty_record.error or empty_record.status)
            empty = {"final_text": empty_record.final_text, "output": empty_record.output}
            button = loop.run(RunRequest("exercise-session", "生成练习", "exercise-1", mode="exercise",
                                         goal_id="demo-goal", node_id="document-loading"))
            tutor = loop.run(RunRequest("teaching-session", "出一道题", "teaching-1", mode="teaching",
                                        goal_id="demo-goal", node_id="document-loading"))
            if button.status != "completed" or tutor.status != "completed":
                raise RuntimeError(button.error or tutor.error)
            context = LearningContext(planning_repository, learning_repository)
            generator = GenerateExercise(learning_repository, context.context)
            feedback = generator.submit_answer("demo-goal", button.output["exercises"][0]["id"], "b", "generated-a1")
            feedback["attempt"]["created_at"] = feedback["attempt"]["created_at"].isoformat()
            practice = {"button": button.output, "teaching": tutor.output,
                        "feedback": feedback, "next_action": context.next_action("demo-goal", "document-loading", 10)}
        return {"mode": "real" if real else "fixture", "data": "fixture-seeded SQLite",
                "goal_id": "demo-goal", "node_id": "document-loading", "status": record.status,
                "final_text": record.final_text, "usage": record.usage, "output": record.output,
                "empty_retrieval": empty, "exercise_generation": practice}
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
