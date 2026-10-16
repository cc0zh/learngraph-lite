from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import Budget, ModelResponse, ToolCall
from learngraph_lite.application.agent import RunRequest
from learngraph_lite.application.learning import LearningService
from learngraph_lite.application.planning import PlanningService, candidate_rag_graph
from learngraph_lite.application.skills import SkillDefinition, SkillTurn
from learngraph_lite.bootstrap import _create_business_app, build_learning_loop
from learngraph_lite.domain.lessons import build_lesson_package
from learngraph_lite.infrastructure import SQLiteLearningRepository, SQLiteLessonRepository, SQLitePlanningRepository
from learngraph_lite.infrastructure.run_persistence import SQLiteRunRepository


class Catalog:
    def __init__(self, teaching="TEACHING_BODY_SENTINEL"):
        self.skills = (
            SkillDefinition("goal-planning", "帮助澄清目标", "PLANNING_BODY_SENTINEL", ("planning",)),
            SkillDefinition("concept-teaching", "解释当前概念", teaching, ("runner", "teaching", "explanation")),
        )

    def list_skills(self):
        return self.skills


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        response = next(self.responses)
        return response(messages, tools) if callable(response) else response

    def close(self):
        self.closed = True


def call(name, args, call_id="skill"):
    return ToolCall(call_id, name, json.dumps(args))


def repositories(database):
    planning = SQLitePlanningRepository(database)
    learning = SQLiteLearningRepository(database)
    service = PlanningService(planning)
    service.create_goal("g", "学习 RAG")
    service.confirm_goal("g")
    candidate = candidate_rag_graph("g")
    service.save_graph_draft("g", candidate.nodes, candidate.edges)
    graph = service.publish_graph("g", expected_revision=0)
    LearningService(learning).start_goal(graph)
    return planning, learning


def node_request(key="r", text="解释当前节点"):
    return RunRequest("s", text, key, goal_id="g", node_id="document-loading")


def assert_pairs(messages):
    pending = []
    for message in messages:
        if message["role"] == "tool":
            assert pending and message["tool_call_id"] == pending.pop(0)
        else:
            assert not pending
            pending = [item["id"] for item in message.get("tool_calls", [])]
    assert not pending


def test_learning_skill_roundtrip_cannot_load_planning_or_change_business_state():
    with tempfile.TemporaryDirectory() as directory:
        planning, learning = repositories(Path(directory) / "test.sqlite3")
        model = Model([
            ModelResponse(tool_calls=(call("read_skill", {"skill_id": "goal-planning"}, "wrong-mode"),
                                       call("read_skill", {"skill_id": "concept-teaching"}, "read"))),
            ModelResponse("解释完成"),
        ])
        catalog = Catalog()
        loop = build_learning_loop(model, planning, learning, skills=catalog)
        before = (planning.get("g"), learning.get("g"))
        try:
            run = loop.run(node_request())
            assert run.status == "completed", run.error
            assert "skill unavailable" in run.error
            first = model.calls[0]
            assert {item["function"]["name"] for item in first[1]} == {
                "get_learning_context", "get_next_action", "read_skill"}
            assert "concept-teaching" in first[0][0].content and "goal-planning" not in first[0][0].content
            assert "TEACHING_BODY_SENTINEL" not in first[0][0].content
            results = [json.loads(item.content) for item in model.calls[1][0] if item.role == "tool"]
            assert "error" in results[0] and results[1]["instructions"] == "TEACHING_BODY_SENTINEL"
            assert run.output == {"skill_usage": [{"skill_id": "concept-teaching",
                "content_hash": catalog.skills[1].content_hash, "activation": "tool"}]}
            assert (planning.get("g"), learning.get("g")) == before
            assert_pairs(run.protocol_messages)
        finally:
            loop.close()


def test_planning_skill_preserves_host_review_stop_and_tool_whitelist():
    with tempfile.TemporaryDirectory() as directory:
        planning = SQLitePlanningRepository(Path(directory) / "test.sqlite3")
        learning = SQLiteLearningRepository(Path(directory) / "test.sqlite3")
        service = PlanningService(planning)
        service.create_goal("g", "学习绘画")
        questions = {"title": "确定范围", "questions": [{"id": "q", "prompt": "希望画什么？",
            "reason": "决定范围", "options": [], "allow_skip": True}]}
        model = Model([
            ModelResponse(tool_calls=(call("read_skill", {"skill_id": "goal-planning"}),)),
            ModelResponse("先澄清", tool_calls=(call("request_clarification", questions, "ask"),
                call("read_skill", {"skill_id": "concept-teaching"}, "skipped"))),
        ])
        loop = build_learning_loop(model, planning, learning, skills=Catalog())
        try:
            run = loop.run(RunRequest("planning:g", "想学绘画", "r", mode="planning",
                goal_id="g", task_ref="goal:g", planning_version=0))
            assert run.status == "completed", run.error
            assert run.output["planning_agent"]["card"]["kind"] == "questions"
            assert run.output["skill_usage"][0]["skill_id"] == "goal-planning"
            assert not service.get_state("g").goal.confirmed and service.get_state("g").version == 0
            assert {item["function"]["name"] for item in model.calls[0][1]} == {
                "read_planning_context", "request_clarification", "propose_goal_draft",
                "generate_route_draft", "read_skill"}
            assert "skipped" in run.protocol_messages[-1]["content"]
            assert len(model.calls) == 2
            assert_pairs(run.protocol_messages)
        finally:
            loop.close()


def test_structured_planning_answers_cannot_explicitly_activate_skills():
    for reference in ("$goal-planning", "$concept-teaching"):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite3"
            planning = SQLitePlanningRepository(database)
            learning = SQLiteLearningRepository(database)
            service = PlanningService(planning)
            service.create_goal("g", "学习绘画")
            question = {"id": "q", "prompt": "希望画什么？", "reason": "决定范围",
                        "options": [], "allow_skip": True}
            model = Model([
                ModelResponse(tool_calls=(call("request_clarification", {
                    "title": "确定范围", "questions": [question]}, "ask"),)),
                ModelResponse("已收到回答"),
            ])
            loop = build_learning_loop(model, planning, learning, skills=Catalog())
            try:
                source = loop.run(RunRequest("planning:g", "想学绘画", "ask", mode="planning",
                    goal_id="g", task_ref="goal:g", planning_version=0))
                assert source.status == "completed", source.error
                value = "了解示例中的" + reference
                # Questions in AgentPlanning flatten the card prompt and answer into user_text.
                text = f"{question['prompt']}：{value}"
                answers = [{"question_id": "q", "value": value, "skipped": False}]
                result = loop.run(RunRequest("planning:g", text, "answer", mode="planning",
                    goal_id="g", task_ref="goal:g", planning_version=0,
                    response_to_run_id=source.run_id, planning_answers_json=json.dumps(answers)))
                assert result.status == "completed", result.error
                assert "skill_usage" not in result.output
                assert len(model.calls) == 2
                messages, tools = model.calls[-1]
                protocol = json.loads(messages[-1].content)
                assert protocol["user_text"] == text
                assert protocol["planning_response"]["answers"][0]["value"] == value
                assert "当前用户显式选择的技能" not in messages[0].content
                assert "PLANNING_BODY_SENTINEL" not in messages[0].content
                assert "read_skill" in {item["function"]["name"] for item in tools}
                assert service.get_state("g").version == 0
            finally:
                loop.close()


def test_planning_chat_still_parses_explicit_skills():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        planning = SQLitePlanningRepository(database)
        learning = SQLiteLearningRepository(database)
        PlanningService(planning).create_goal("g", "学习绘画")
        model = Model([ModelResponse("已按技能解释规划")])
        loop = build_learning_loop(model, planning, learning, skills=Catalog())
        try:
            result = loop.run(RunRequest("planning:g", "请用$goal-planning解释规划", "chat",
                mode="planning", goal_id="g", task_ref="goal:g", planning_version=0))
            assert result.status == "completed", result.error
            assert result.output["skill_usage"][0]["activation"] == "explicit"
            assert "PLANNING_BODY_SENTINEL" in model.calls[0][0][0].content
            wrong = loop.run(RunRequest("planning:g", "请用$concept-teaching解释", "wrong",
                mode="planning", goal_id="g", task_ref="goal:g", planning_version=0))
            assert wrong.status == "failed" and "skill unavailable" in wrong.error
            assert len(model.calls) == 1
        finally:
            loop.close()


def test_explicit_skill_is_current_turn_only_and_raw_user_input_is_preserved():
    with tempfile.TemporaryDirectory() as directory:
        planning, learning = repositories(Path(directory) / "test.sqlite3")
        model = Model([ModelResponse("第一轮"), ModelResponse("第二轮")])
        loop = build_learning_loop(model, planning, learning, skills=Catalog())
        text = "用 $concept-teaching 解释，$concept-teaching 不要重复加载"
        try:
            first = loop.run(node_request(text=text))
            second = loop.run(node_request("second", "再解释一个例子"))
            assert first.status == second.status == "completed"
            assert first.user_text == text and first.protocol_messages[0]["content"] == text
            assert first.output["skill_usage"][0]["activation"] == "explicit"
            assert len(first.output["skill_usage"]) == 1 and second.output == {}
            assert "TEACHING_BODY_SENTINEL" in model.calls[0][0][0].content
            assert "TEACHING_BODY_SENTINEL" not in str(model.calls[1][0])
        finally:
            loop.close()


def test_skill_usage_survives_sqlite_restart_without_reactivating_old_instructions():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        planning, learning = repositories(database)
        old = Catalog("OLD_SKILL_SENTINEL")
        model = Model([ModelResponse(tool_calls=(call("read_skill", {"skill_id": "concept-teaching"}),)),
                       ModelResponse("第一轮结束")])
        loop = build_learning_loop(model, planning, learning, runs=SQLiteRunRepository(database), skills=old)
        try:
            first = loop.run(node_request())
            assert first.status == "completed", first.error
        finally:
            loop.close()

        current = Catalog("NEW_SKILL_SENTINEL")
        model = Model([ModelResponse(tool_calls=(call("read_skill", {"skill_id": "concept-teaching"}),)),
                       ModelResponse("第二轮结束")])
        loop = build_learning_loop(model, planning, learning, runs=SQLiteRunRepository(database), skills=current)
        try:
            recovered = loop.get_run(first.run_id)
            assert recovered.output["skill_usage"] == first.output["skill_usage"]
            assert "OLD_SKILL_SENTINEL" in str(recovered.protocol_messages)
            second = loop.run(node_request("second", "继续解释"))
            assert second.status == "completed", second.error
            assert "OLD_SKILL_SENTINEL" not in str(model.calls[0][0])
            history_result = [item for item in model.calls[0][0] if item.role == "tool"]
            assert history_result[0].tool_call_id == "skill"
            assert json.loads(history_result[0].content)["historical_skill_result"] is True
            assert "NEW_SKILL_SENTINEL" in str(model.calls[1][0])
            assert second.output["skill_usage"][0]["content_hash"] == current.skills[1].content_hash
            assert_pairs(second.protocol_messages)
        finally:
            loop.close()


def test_explicit_wrong_mode_rejected_before_model_and_loading_shares_tool_budget():
    with tempfile.TemporaryDirectory() as directory:
        planning, learning = repositories(Path(directory) / "test.sqlite3")
        model = Model([ModelResponse(tool_calls=(call("read_skill", {"skill_id": "concept-teaching"}),))])
        loop = build_learning_loop(model, planning, learning, skills=Catalog())
        before = learning.get("g")
        try:
            wrong = loop.run(node_request(text="$goal-planning 帮我自动发布"))
            assert wrong.status == "failed" and "skill unavailable" in wrong.error and not model.calls
            limited = loop.run(node_request("budget"), Budget(max_tool_calls=0))
            assert limited.status == "budget_exceeded" and "tool call budget" in limited.error
            assert len(model.calls) == 1 and limited.output == {}
            assert learning.get("g") == before
        finally:
            loop.close()


def test_business_factory_exposes_builtin_skill_usage_in_http_and_sse_without_body():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "test.sqlite3"
        repositories(database)
        model = Model([ModelResponse(tool_calls=(call("read_skill", {"skill_id": "concept-teaching"}),)),
                       ModelResponse("技能读取完成")])
        app = _create_business_app(model, "fixture", database)
        with TestClient(app, base_url="http://localhost") as api:
            response = api.post("/api/sessions/s/runs", json={"request_id": "r", "user_text": "解释概念",
                               "goal_id": "g", "node_id": "document-loading"})
            assert response.status_code == 202, response.text
            run_id = response.json()["run_id"]
            events = api.get(f"/api/runs/{run_id}/events")
            payload = api.get(f"/api/runs/{run_id}").json()
            assert payload["status"] == "completed", payload
            usage = payload["output"]["skill_usage"]
            assert usage[0]["skill_id"] == "concept-teaching" and usage[0]["activation"] == "tool"
            assert len(usage[0]["content_hash"]) == 64
            assert "skill_usage" in events.text
            assert "instructions" not in json.dumps(payload) and "instructions" not in events.text
            assert "SKILL.md" not in str(payload) and "SKILL.md" not in events.text
        assert model.closed


def test_explicit_skill_supports_adjacent_chinese_without_matching_ascii_identifiers():
    catalog = Catalog()
    for text in ("请用$concept-teaching解释当前概念", "用$concept-teaching，再给一个例子"):
        turn = SkillTurn(catalog, "runner", text)
        assert turn.project_usage()["skill_usage"][0]["activation"] == "explicit"
        assert "TEACHING_BODY_SENTINEL" in turn.prompt()
    for text in ("prefix$concept-teaching", "$concept-teaching-extra", "$concept-Teaching",
                 "$$concept-teaching", "$concept-teaching_suffix"):
        assert SkillTurn(catalog, "runner", text).project_usage() == {}


def test_saved_lesson_content_cannot_explicitly_activate_skills_in_event_explanation():
    for reference in ("$goal-planning", "$concept-teaching"):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.sqlite3"
            planning, _ = repositories(database)
            lessons = SQLiteLessonRepository(database)
            package = build_lesson_package(package_id="pkg", goal_id="g", node_id="document-loading",
                graph_content_revision=PlanningService(planning).current_graph("g").content_revision,
                markdown="资料中的示例 " + reference, components=())
            state = lessons.state("g")
            state.packages[package.id] = package
            lessons.save("g", state)
            model = Model([ModelResponse("解释事件完成")])
            app = _create_business_app(model, "fixture", database)
            with TestClient(app, base_url="http://localhost") as api:
                ack = api.post("/api/goals/g/lessons/pkg/events", json={"event_id": "event",
                    "package_version": 1, "component_id": "chapter", "action": "request_explanation"})
                assert ack.status_code == 200, ack.text
                submitted = api.post("/api/sessions/explain/runs", json={"request_id": "explain",
                    "goal_id": "g", "node_id": "document-loading", "mode": "explanation",
                    "source_event_id": "event", "explanation_slot": "initial"})
                assert submitted.status_code == 202, submitted.text
                run_id = submitted.json()["run_id"]
                api.get(f"/api/runs/{run_id}/events")
                run = api.get(f"/api/runs/{run_id}").json()
                assert run["status"] == "completed", run
                assert "skill_usage" not in run.get("output", {})
                assert reference in model.calls[0][0][-1].content
                assert "当前用户显式选择的技能" not in model.calls[0][0][0].content
                assert "read_skill" in {item["function"]["name"] for item in model.calls[0][1]}
