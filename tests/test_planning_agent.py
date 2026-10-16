from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from learngraph_lite.agent_core import AgentRunner, Budget, ModelResponse, TextMessage, Tool, ToolCall, ToolRegistry
from learngraph_lite.agent_core.gateway import budgeted
from learngraph_lite.application.agent import RunAdmissionError, RunRequest
from learngraph_lite.application.learning import InMemoryLearningRepository
from learngraph_lite.application.planning import InMemoryPlanningRepository, PlanningError, PlanningService
from learngraph_lite.application.planning_agent import PlanningContext, StrictInput
from learngraph_lite.bootstrap import _create_business_app, build_learning_loop
from learngraph_lite.infrastructure import SQLitePlanningRepository
from learngraph_lite.infrastructure.business_fixture import BusinessFixtureModel
from learngraph_lite.infrastructure.run_persistence import SQLiteRunRepository
from learngraph_lite.presentation.sse import public_run


CLEAR = "我想学习绘画，目标是完成一张静物素描，当前基础是零基础，可以投入180分钟。"
CONTINUE = "目标已由我确认，请根据已确认目标生成学习图谱，给我审核，不要发布。"


class FastFixture(BusinessFixtureModel):
    def __init__(self):
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return super().complete(messages, tools)

    def stream_complete(self, messages, tools, on_delta):
        result = self.complete(messages, tools)
        on_delta(result.content)
        return result


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        response = next(self.responses)
        return response(messages, tools) if callable(response) else response

    def stream_complete(self, messages, tools, on_delta):
        return self.complete(messages, tools)

    def close(self):
        pass


def tool_call(name, args, call_id=None):
    return ToolCall(call_id or name, name, json.dumps(args, ensure_ascii=False))


def question_args(skip=True):
    return {"title": "确定范围", "questions": [{"id": "focus", "prompt": "你要聚焦什么？",
        "reason": "避免路线过宽", "options": [{"id": "a", "label": "基础", "value": "基础"}], "allow_skip": skip}]}


def draft_args():
    return {"title": "绘画", "desired_outcome": "完成一张素描", "current_level": "零基础",
            "time_budget_minutes": 180, "constraints": "不联网", "skipped_fields": []}


def graph_response(count=2):
    return ModelResponse(json.dumps({"nodes": [{"id": f"n{i}", "title": f"学习{i}", "explanation": "必要性与顺序",
        "learning_outcome": "可验证成果", "estimated_minutes": 20, "priority": 3} for i in range(count)],
        "edges": [{"source": f"n{i}", "target": f"n{i+1}"} for i in range(count - 1)]}, ensure_ascii=False))


def setup(model=None, confirmed=False, repository=None, runs=None):
    repository = repository or InMemoryPlanningRepository()
    planning = PlanningService(repository)
    planning.create_goal("g", "绘画")
    if confirmed:
        planning.confirm_goal("g", 0)
    loop = build_learning_loop(model or FastFixture(), repository, InMemoryLearningRepository(), runs=runs)
    return loop, planning, repository


def request(planning, key="start", text=CLEAR, **kwargs):
    return RunRequest(session_id="planning:g", goal_id="g", task_ref="goal:g", mode="planning",
                      user_text=text, idempotency_key=key, planning_version=planning.get_state("g").version, **kwargs)


def expect_error(code, action):
    try:
        action()
    except (PlanningError, RunAdmissionError) as exc:
        assert exc.code == code, (exc.code, str(exc))
    else:
        raise AssertionError(f"expected {code}")


def finish(api, submitted):
    assert submitted.status_code == 202, submitted.text
    run_id = submitted.json()["run_id"]
    stream = api.get(f"/api/runs/{run_id}/events")
    assert stream.status_code == 200, stream.text
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "run.snapshot" in stream.text
    result = api.get(f"/api/runs/{run_id}").json()
    assert result["status"] not in {"queued", "running"}, result
    return result


def http_error(response, code):
    assert response.status_code == 409, (code, response.status_code, response.text)
    assert response.json()["error"]["code"] == code, response.text


def assert_protocol_pairs(protocol):
    pending = []
    for message in protocol:
        if message["role"] == "tool":
            assert pending and message["tool_call_id"] == pending.pop(0), message
        else:
            assert not pending, ("unpaired tool calls", pending)
            if message["role"] == "assistant":
                pending = [call["id"] for call in message.get("tool_calls", [])]
    assert not pending, ("unpaired tool calls", pending)


def test_native_ends_turn_question_skips_generation_batch_and_preserves_pairs():
    model = ScriptedModel([ModelResponse("先确定范围", tool_calls=(
        tool_call("request_clarification", question_args(), "question"),
        tool_call("generate_route_draft", {"node_count": 2}, "forbidden")))])
    loop, planning, _ = setup(model, confirmed=True)
    try:
        before = planning.describe("g")
        run = loop.run(request(planning))
        assert run.status == "completed", run.error
        assert run.output["planning_agent"]["card"]["kind"] == "questions"
        assert planning.describe("g") == before and len(model.calls) == 1
        tools = model.calls[0][1]
        assert {item["function"]["name"] for item in tools} == {
            "read_planning_context", "request_clarification", "propose_goal_draft", "generate_route_draft"}
        assert not any(name in str(tools) for name in ('"confirm"', '"publish"', '"grade"'))
        protocol = run.protocol_messages
        assert [item["tool_call_id"] for item in protocol if item["role"] == "tool"] == ["question", "forbidden"]
        assert "skipped" in protocol[-1]["content"]
        assert len(protocol[1]["tool_calls"]) == 2 and run.user_text == CLEAR
        assert_protocol_pairs(protocol)
    finally:
        loop.close()


def test_ends_turn_error_does_not_stop_runner_or_execute_invalid_handler():
    invoked = []
    tools = ToolRegistry()
    tools.register(Tool.from_model("review", "review", StrictInput, lambda args: invoked.append(args), ends_turn=True))
    model = ScriptedModel([ModelResponse(tool_calls=(tool_call("review", {"extra": 1}, "invalid"),)),
                           ModelResponse("已解释参数错误")])
    result = AgentRunner(model, tools).run((TextMessage("user", "开始"),))
    assert result.status == "completed" and result.final_text == "已解释参数错误"
    assert len(model.calls) == 2 and not invoked and "invalid arguments" in result.errors[0]


def test_goal_review_ends_turn_and_revokes_confirmation_before_route():
    model = ScriptedModel([ModelResponse("请审核新目标", tool_calls=(tool_call("propose_goal_draft", draft_args()),
                                 tool_call("generate_route_draft", {"node_count": 2}, "skip")))])
    loop, planning, _ = setup(model, confirmed=True)
    try:
        result = loop.run(request(planning, text="修改目标为绘画"))
        output = result.output["planning_agent"]
        assert result.status == "completed" and output["card"] == {"kind": "goal_review"}
        assert output["planning"]["version"] == 2 and not output["planning"]["goal"]["confirmed"]
        assert output["planning"]["questions"] == () and output["planning"]["clarification_round"] == 0
        assert output["planning"]["graph"] is None and len(model.calls) == 1
    finally:
        loop.close()


def test_route_shared_gateway_one_write_budget_and_read_updated_version():
    model = ScriptedModel([
        ModelResponse(tool_calls=(tool_call("generate_route_draft", {"node_count": 2}),)), graph_response(),
        ModelResponse(tool_calls=(tool_call("read_planning_context", {}, "read-after"),
            tool_call("generate_route_draft", {"node_count": 1}, "second-write"),
            tool_call("propose_goal_draft", draft_args(), "second-goal"))), ModelResponse("请审核两个节点，尚未发布")])
    loop, planning, _ = setup(model, confirmed=True)
    try:
        result = loop.run(request(planning), Budget(max_model_calls=4))
        assert result.status == "completed", result.error
        output = result.output["planning_agent"]
        assert output["card"] == {"kind": "route_review"} and len(output["planning"]["graph"]["nodes"]) == 2
        assert output["planning"]["version"] == 2 and output["planning"]["goal"]["confirmed"]
        assert len(model.calls) == 4 and model.calls[1][1] == ()
        tool_results = {item["tool_call_id"]: json.loads(item["content"]) for item in result.protocol_messages if item["role"] == "tool"}
        assert tool_results["read-after"]["version"] == 2
        assert "planning_write_limit" in tool_results["second-write"]["error"]
        assert "planning_write_limit" in tool_results["second-goal"]["error"]
        assert output["changes"]["added"] == ["n0", "n1"] and output["changes"]["after_minutes"] == 40
        assert output["changes"]["node_titles"] == {"n0": "学习0", "n1": "学习1"}
        assert planning.current_graph("g").status.value == "draft"
    finally:
        loop.close()


def test_route_optional_node_count_not_forced_to_ten_and_nested_budget_counts():
    for budget, expected in ((Budget(max_model_calls=3), "completed"), (Budget(max_model_calls=1), "budget_exceeded")):
        model = ScriptedModel([ModelResponse(tool_calls=(tool_call("generate_route_draft", {}),)),
                               graph_response(3), ModelResponse("解释三节点路线")])
        loop, planning, _ = setup(model, confirmed=True)
        try:
            result = loop.run(request(planning), budget)
            assert result.status == expected, result.error
            if expected == "completed":
                assert len(planning.current_graph("g").nodes) == 3
                assert json.loads(model.calls[1][0][1].content)["node_count"] is None
            else:
                assert planning.current_graph("g") is None
        finally:
            loop.close()


def test_first_route_tool_treats_feedback_as_initial_guidance_without_dropping_it():
    guidance = "围绕素描组织知识点，突出光影，不要求完成项目。"
    model = ScriptedModel([
        ModelResponse(tool_calls=(tool_call("generate_route_draft", {"feedback": guidance}),)),
        graph_response(), ModelResponse("图谱草稿已生成，请审核。")])
    loop, planning, _ = setup(model, confirmed=True)
    try:
        run = loop.run(request(planning, text=CONTINUE))
        assert run.status == "completed" and not run.error, run.error
        assert len(model.calls) == 3
        context = json.loads(model.calls[1][0][1].content)
        assert context["initial_guidance"] == guidance
        assert context["feedback"] == "" and context["current_graph"] is None
        assert context["node_count"] is None
        assert run.output["planning_agent"]["card"] == {"kind": "route_review"}
        assert planning.current_graph("g").status.value == "draft"
        assert planning.get_state("g").goal.confirmed
        assert_protocol_pairs(run.protocol_messages)
    finally:
        loop.close()


def test_route_tool_existing_draft_keeps_feedback_and_edited_goal_uses_initial_guidance():
    feedback = "范围太宽，请聚焦光影。"
    model = ScriptedModel([
        ModelResponse(tool_calls=(tool_call("generate_route_draft", {"node_count": 2}),)),
        graph_response(), ModelResponse("请审核。"),
        ModelResponse(tool_calls=(tool_call("generate_route_draft", {"node_count": 1, "feedback": feedback}),)),
        graph_response(1), ModelResponse("已缩小范围，请审核。"),
        ModelResponse(tool_calls=(tool_call("generate_route_draft", {"node_count": 2, "feedback": feedback}),)),
        graph_response(), ModelResponse("已按新目标生成，请审核。")])
    loop, planning, _ = setup(model, confirmed=True)
    try:
        first = loop.run(request(planning, text=CONTINUE))
        assert first.status == "completed" and not first.error, first.error
        before = json.loads(json.dumps(first.output["planning_agent"]["planning"]["graph"]))
        revised = loop.run(request(planning, "revise", feedback))
        assert revised.status == "completed" and not revised.error, revised.error
        revision_context = json.loads(model.calls[4][0][1].content)
        assert revision_context["feedback"] == feedback and revision_context["current_graph"] == before
        assert revision_context["initial_guidance"] == ""
        assert len(planning.current_graph("g").nodes) == 1
        planning.edit_goal("g", planning.get_state("g").version, title="光影素描")
        planning.confirm_goal("g", planning.get_state("g").version)
        assert planning.current_graph("g") is None
        regenerated = loop.run(request(planning, "new-goal", CONTINUE))
        assert regenerated.status == "completed" and not regenerated.error, regenerated.error
        initial_context = json.loads(model.calls[7][0][1].content)
        assert initial_context["initial_guidance"] == feedback
        assert initial_context["feedback"] == "" and initial_context["current_graph"] is None
        assert initial_context["goal"]["title"] == "光影素描"
        assert len(model.calls) == 9 and len(planning.current_graph("g").nodes) == 2
        assert planning.current_graph("g").status.value == "draft"
    finally:
        loop.close()


def test_initial_route_guidance_does_not_bypass_user_confirmation():
    model = ScriptedModel([
        ModelResponse(tool_calls=(tool_call("generate_route_draft", {"feedback": "请先画知识地图"}),)),
        ModelResponse("需要先由你确认目标。")])
    loop, planning, _ = setup(model)
    try:
        before = planning.describe("g")
        run = loop.run(request(planning))
        assert "goal_unconfirmed" in run.error
        assert planning.describe("g") == before and len(model.calls) == 2
        assert run.output["planning_agent"]["card"] is None
    finally:
        loop.close()


def test_structured_answers_checked_by_host_before_model_with_ids_and_skips():
    model = ScriptedModel([ModelResponse(tool_calls=(tool_call("request_clarification", question_args()),)), ModelResponse("只解释回答")])
    loop, planning, _ = setup(model)
    try:
        card = loop.run(request(planning))
        source = card.run_id
        valid = request(planning, "answer", "我的结构化回答", response_to_run_id=source,
                        planning_answers_json=json.dumps([{"question_id": "focus", "value": "", "skipped": True}]))
        for answers in ([{"question_id": "wrong", "value": "基础", "skipped": False}],
                        [{"question_id": "focus", "value": "", "skipped": False}],
                        [{"question_id": "focus", "value": "不能带值", "skipped": True}],
                        [{"question_id": "focus", "value": "x" * 2001, "skipped": False}],
                        [{"question_id": "focus", "value": "a", "skipped": False}] * 2):
            expect_error("invalid_planning_response", lambda: loop.run(replace(valid, planning_answers_json=json.dumps(answers))))
        assert len(model.calls) == 1
        answer = loop.run(valid)
        assert answer.status == "completed", answer.error
        assert answer.user_text == valid.user_text and answer.response_to_run_id == source
        assert answer.output["planning_agent"]["response_to_run_id"] == source
        assert answer.output["planning_agent"]["card"] is None
        saved_input = json.loads(answer.protocol_messages[0]["content"])
        assert saved_input["planning_response"]["answers"] == [
            {"question_id": "focus", "value": "", "skipped": True, "prompt": "你要聚焦什么？"}]
        # History reuses the full native protocol of the prior question round.
        messages = model.calls[1][0]
        assert any(m.role == "tool" and m.tool_call_id == "request_clarification" for m in messages)
        assert loop.run(valid).run_id == answer.run_id
        expect_error("planning_response_used", lambda: loop.run(replace(valid, idempotency_key="new-answer")))
    finally:
        loop.close()


def test_non_skippable_question_and_wrong_goal_or_uncompleted_run_rejected():
    model = ScriptedModel([ModelResponse(tool_calls=(tool_call("request_clarification", question_args(False)),))])
    loop, planning, _ = setup(model)
    try:
        card = loop.run(request(planning))
        valid = request(planning, "answer", response_to_run_id=card.run_id,
                        planning_answers_json=json.dumps([{"question_id": "focus", "value": "", "skipped": True}]))
        expect_error("invalid_planning_response", lambda: loop.run(valid))
        planning.create_goal("other", "音乐")
        other = replace(valid, goal_id="other", task_ref="goal:other", session_id="planning:other", planning_version=0)
        expect_error("invalid_planning_response", lambda: loop.run(other))
        expect_error("invalid_planning_response", lambda: loop.run(replace(valid, response_to_run_id="unknown")))
    finally:
        loop.close()


def test_stale_question_version_and_newer_question_same_version_rejected():
    model = ScriptedModel([ModelResponse(tool_calls=(tool_call("request_clarification", question_args()),))] * 2)
    loop, planning, _ = setup(model)
    try:
        first = loop.run(request(planning))
        second = loop.run(request(planning, "second"))
        def answer(card, key):
            return request(planning, key, response_to_run_id=card.run_id,
                           planning_answers_json=json.dumps([{"question_id": "focus", "value": "custom", "skipped": False}]))
        expect_error("stale_planning_card", lambda: loop.run(answer(first, "old")))
        planning.edit_goal("g", 0, title="不同范围")
        expect_error("stale_planning_card", lambda: loop.run(answer(second, "stale")))
        assert len(model.calls) == 2
    finally:
        loop.close()


def test_fixture_clear_input_questions_partial_skips_and_repeated_feedback():
    fixture = FastFixture()
    loop, planning, _ = setup(fixture)
    try:
        initial = loop.run(request(planning))
        assert initial.status == "completed", initial.error
        assert initial.output["planning_agent"]["card"] == {"kind": "goal_review"}
        assert planning.get_state("g").goal.time_budget_minutes == 180
        assert not planning.get_state("g").goal.confirmed and planning.current_graph("g") is None
        explained = loop.run(request(planning, "why-goal", "为何这样安排？"))
        assert explained.output["planning_agent"]["card"] is None and planning.get_state("g").version == 1
        agreed = loop.run(request(planning, "agree", "好"))
        assert not agreed.output["planning_agent"]["planning"]["goal"]["confirmed"]
        planning.confirm_goal("g", planning.get_state("g").version)
        route = loop.run(request(planning, "route", "我已确认目标，请依据已确认目标生成待审核图谱。"))
        assert route.status == "completed", route.error
        assert route.output["planning_agent"]["card"] == {"kind": "route_review"}
        start_count = len(planning.current_graph("g").nodes)
        version = planning.get_state("g").version
        explained = loop.run(request(planning, "why-route", "为什么要学这些？"))
        assert explained.output["planning_agent"]["card"] is None and explained.output["planning_agent"]["changes"] is None
        assert planning.get_state("g").version == version
        for key, text in (("hard", "太难，请补基础"), ("wide", "太宽，请缩小范围"), ("hard2", "还是太难")):
            previous = planning.describe("g")
            revised = loop.run(request(planning, key, text))
            assert revised.status == "completed", revised.error
            output = revised.output["planning_agent"]
            before = {node["id"]: node for node in previous["graph"]["nodes"]}
            after = {node["id"]: node for node in output["planning"]["graph"]["nodes"]}
            changes = output["changes"]
            assert set(changes["added"]) == after.keys() - before.keys()
            assert set(changes["removed"]) == before.keys() - after.keys()
            assert set(changes["updated"]) == {node_id for node_id in before.keys() & after.keys()
                                               if before[node_id] != after[node_id]}
            assert changes["before_minutes"] == sum(node["estimated_minutes"] for node in before.values())
            assert changes["after_minutes"] == sum(node["estimated_minutes"] for node in after.values())
            for node_id in changes["added"] + changes["updated"]:
                assert changes["node_titles"][node_id] == after[node_id]["title"]
            for node_id in changes["removed"]:
                assert changes["node_titles"][node_id] == before[node_id]["title"]
            assert output["planning"]["version"] == previous["version"] + 1
            assert revised.final_text.strip() and output["planning"]["graph"]["status"] == "draft"
        assert len(planning.current_graph("g").nodes) == start_count + 1
    finally:
        loop.close()
    # Partial clear input is kept through host-constructed answer protocol.
    loop, planning, _ = setup(FastFixture())
    try:
        partial = loop.run(request(planning, text="我希望完成一幅画，可以投入90分钟"))
        questions = partial.output["planning_agent"]["card"]["questions"]
        assert [q["id"] for q in questions] == ["current_level"]
        answered = loop.run(request(planning, "answer", "已回答", response_to_run_id=partial.run_id,
            planning_answers_json=json.dumps([{"question_id": "current_level", "value": "", "skipped": True}])))
        goal = answered.output["planning_agent"]["planning"]["goal"]
        assert goal["time_budget_minutes"] == 90 and goal["desired_outcome"] == "完成一幅画"
        assert goal["skipped_fields"] == ("current_level",) and not goal["confirmed"]
    finally:
        loop.close()


def test_cancellation_before_generation_commit_and_version_change_do_not_save():
    for change in ("cancel", "version"):
        def candidate(_messages, _tools):
            if change == "cancel":
                budget.cancelled = True
            else:
                planning.edit_goal("g", 1, title="并发修改")
            return graph_response()
        budget = Budget()
        model = ScriptedModel([ModelResponse(tool_calls=(tool_call("generate_route_draft", {"node_count": 2}),)),
                               candidate, ModelResponse("读取后说明过期")])
        loop, planning, _ = setup(model, confirmed=True)
        try:
            result = loop.run(request(planning), budget)
            assert result.status == ("cancelled" if change == "cancel" else "failed"), result.error
            assert planning.current_graph("g") is None
            assert result.output == {}
            if change == "version":
                assert "Planning version changed" in result.error
        finally:
            loop.close()


def test_planning_session_serializes_legacy_graph_and_cancelled_worker_retry():
    started, release = Event(), Event()
    def blocking(_messages, _tools):
        started.set()
        assert release.wait(5)
        return ModelResponse("晚到解释")
    model = ScriptedModel([blocking, ModelResponse("重试解释")])
    loop, planning, _ = setup(model, confirmed=True)
    try:
        original = request(planning)
        run = loop.submit(original)
        assert started.wait(5)
        legacy = replace(request(planning, "legacy"), mode="graph")
        expect_error("session_busy", lambda: loop.submit(legacy))
        cancelled = loop.cancel(run.run_id)
        assert cancelled.status == "cancelled"
        retry = replace(original, idempotency_key="retry", retry_of_run_id=run.run_id)
        expect_error("session_busy", lambda: loop.submit(retry))
        release.set()
        loop.close()
        assert loop.get_run(run.run_id).status == "cancelled" and planning.current_graph("g") is None
    finally:
        release.set()
        loop.close()


def test_published_goal_cannot_be_rewritten_by_planning_tools():
    model = ScriptedModel([ModelResponse(tool_calls=(tool_call("generate_route_draft", {"node_count": 2}),)),
                           graph_response(), ModelResponse("审核"),
                           ModelResponse(tool_calls=(tool_call("propose_goal_draft", draft_args()),
                                                     tool_call("generate_route_draft", {"node_count": 1}, "again"))),
                           ModelResponse("已发布，不可改写")])
    loop, planning, _ = setup(model, confirmed=True)
    try:
        run = loop.run(request(planning))
        assert run.status == "completed"
        planning.publish_graph("g", 0, planning.get_state("g").version)
        before = planning.describe("g")
        run = loop.run(request(planning, "published", "修改目标"))
        assert run.status == "completed" and "graph_published" in run.error
        assert run.output["planning_agent"]["card"] is None and planning.describe("g") == before
    finally:
        loop.close()


def test_http_contract_strict_inputs_clear_goal_confirm_route_publish_and_get_only_restart():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "app.sqlite"
        fixture = FastFixture()
        app = _create_business_app(fixture, "fixture", database)
        with TestClient(app, base_url="http://localhost") as api:
            created = api.post("/api/goals", json={"title": CLEAR}).json()
            goal_id = created["goal_id"]
            base = f"/api/goals/{goal_id}"
            body = {"request_id": "initial", "expected_version": 0, "user_text": CLEAR}
            assert created["version"] == 0
            for updates in ({"request_id": "x" * 129}, {"expected_version": True}, {"user_text": " "},
                            {"user_text": "x" * 16001}, {"confirmed": True}, {"answers": []},
                            {"response_to_run_id": "x" * 129}, {"response_to_run_id": "missing"},
                            {"answers": [{"question_id": "q", "value": "ok", "skipped": False}]}):
                response = api.post(base + "/planning-runs", json={**body, **updates})
                assert response.status_code == 422, response.text
            assert fixture.calls == []
            result = finish(api, api.post(base + "/planning-runs", json=body))
            run_id = result["run_id"]
            assert result["status"] == "completed", result
            assert result["mode"] == "planning" and result["session_id"] == f"planning:{goal_id}"
            assert result["task_ref"] == f"goal:{goal_id}" and result["node_id"] is None and result["user_text"] == CLEAR
            plan = result["output"]["planning_agent"]["planning"]
            assert plan["goal_id"] == goal_id and plan["version"] == 1 and not plan["goal"]["confirmed"]
            assert api.post(base + "/planning-runs", json=body).json()["run_id"] == run_id
            assert api.post(base + "/planning-runs", json={**body, "user_text": "不同"}).status_code == 409
            assert api.post(base + "/planning-runs", json={**body, "request_id": "stale"}).status_code == 409
            confirmed = api.post(base + "/confirm", json={"expected_version": 1}).json()
            assert confirmed["version"] == 2 and confirmed["goal"]["confirmed"]
            route = finish(api, api.post(base + "/planning-runs", json={"request_id": "route", "expected_version": 2,
                "user_text": CONTINUE}))
            output = route["output"]["planning_agent"]
            assert output["planning"]["graph"]["status"] == "draft" and output["card"] == {"kind": "route_review"}
            assert output["changes"]["node_titles"] and output["planning"]["version"] == 3
            published = api.post(base + "/graph/publish", json={"expected_version": 3, "expected_revision": 0}).json()
            assert published["graph"]["status"] == "published"
            calls = len(fixture.calls)
            history = api.get(f"/api/sessions/planning:{goal_id}/runs").json()
            assert len(history) == 2 and len(fixture.calls) == calls
        restored_fixture = FastFixture()
        with TestClient(_create_business_app(restored_fixture, "fixture", database), base_url="http://localhost") as api:
            assert api.get(base).json() == published
            assert api.get(f"/api/sessions/planning:{goal_id}/runs").json() == history
            assert restored_fixture.calls == []


def test_http_answers_custom_value_skip_validation_failed_consumption_restart_and_retry():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "app.sqlite"
        question = ModelResponse(tool_calls=(tool_call("request_clarification", question_args()),))
        def fail(_messages, _tools):
            raise RuntimeError("fixture model unavailable")
        model = ScriptedModel([question, fail])
        with TestClient(_create_business_app(model, "fixture", database), base_url="http://localhost",
                        raise_server_exceptions=False) as api:
            created = api.post("/api/goals", json={"title": "绘画"}).json()
            goal_id = created["goal_id"]
            base = f"/api/goals/{goal_id}/planning-runs"
            card = finish(api, api.post(base, json={"request_id": "q", "expected_version": 0, "user_text": "帮我聚焦"}))
            body = {"request_id": "a", "expected_version": 0, "user_text": "回答",
                    "response_to_run_id": card["run_id"], "answers": [{"question_id": "focus", "value": "任意自定义", "skipped": False}]}
            for answers in ([{"question_id": "wrong", "value": "a", "skipped": False}],
                            [{"question_id": "focus", "value": "", "skipped": False}],
                            [{"question_id": "focus", "value": "带值", "skipped": True}]):
                response = api.post(base, json={**body, "answers": answers})
                assert response.status_code == 409 and response.json()["error"]["code"] == "invalid_planning_response"
            for updates in ({"value": "x" * 2001}, {"skipped": "false"}, {"question_id": "x" * 129}):
                answer = {**body["answers"][0], **updates}
                assert api.post(base, json={**body, "answers": [answer]}).status_code == 422
            failed = finish(api, api.post(base, json=body))
            assert failed["status"] == "failed" and failed["response_to_run_id"] == card["run_id"]
            assert "output" not in failed
            http_error(api.post(base, json={**body, "request_id": "again"}), "planning_response_used")
        stored = SQLiteRunRepository(database).load()
        durable = next(item for item in stored if item[1].run_id == failed["run_id"])
        assert json.loads(durable[0].planning_answers_json)[0]["value"] == "任意自定义"
        assert public_run(durable[1])["response_to_run_id"] == card["run_id"]
        retry_model = ScriptedModel([ModelResponse("仅解释，不改草稿")])
        with TestClient(_create_business_app(retry_model, "fixture", database), base_url="http://localhost") as api:
            history = api.get(f"/api/sessions/planning:{goal_id}/runs").json()
            assert history[-1]["response_to_run_id"] == card["run_id"] and retry_model.calls == []
            assert api.post(base, json=body).json()["run_id"] == failed["run_id"]
            retry_body = {**body, "request_id": "retry", "retry_of_run_id": failed["run_id"]}
            changed = {**retry_body, "user_text": "改输入"}
            assert api.post(base, json=changed).json()["error"]["code"] == "invalid_retry"
            retried = finish(api, api.post(base, json=retry_body))
            assert retried["status"] == "completed" and retried["root_task_id"] == failed["run_id"]
            assert retried["response_to_run_id"] == card["run_id"]
            assert retried["output"]["planning_agent"]["response_to_run_id"] == card["run_id"]
            assert retried["output"]["planning_agent"]["card"] is None
            protocol = json.loads(retry_model.calls[0][0][-1].content)
            assert protocol["planning_response"]["answers"][0]["question_id"] == "focus"


def test_sqlite_interrupted_response_consumption_and_explicit_retry_keep_protocol_history():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "runs.sqlite"
        repository = SQLitePlanningRepository(database)
        runs = SQLiteRunRepository(database)
        loop, planning, _ = setup(ScriptedModel([
            ModelResponse(tool_calls=(tool_call("request_clarification", question_args()),))]), repository=repository, runs=runs)
        try:
            card = loop.run(request(planning))
            pending = request(planning, "pending", response_to_run_id=card.run_id,
                planning_answers_json=json.dumps([{"question_id": "focus", "value": "", "skipped": True}]))
            # Persist a queued request as if the process stopped before execution.
            from learngraph_lite.application.agent import RunRecord
            record = RunRecord("pending-run", pending.session_id, "queued", goal_id="g", task_ref="goal:g",
                mode="planning", user_text=pending.user_text, root_task_id="pending-run", response_to_run_id=card.run_id)
            runs.admit(pending, record)
        finally:
            loop.close()
        fixture = ScriptedModel([ModelResponse("保留跳过身份的重试")])
        restored = build_learning_loop(fixture, repository, InMemoryLearningRepository(), runs=runs)
        try:
            interrupted = restored.get_run("pending-run")
            assert interrupted.status == "interrupted" and public_run(interrupted)["response_to_run_id"] == card.run_id
            expect_error("planning_response_used", lambda: restored.run(replace(pending, idempotency_key="new")))
            result = restored.run(replace(pending, idempotency_key="retry", retry_of_run_id="pending-run"))
            assert result.status == "completed" and result.root_task_id == "pending-run"
            assert any(message.role == "tool" for message in fixture.calls[0][0])
            planning.edit_goal("g", 0, title="版本变化")
            expect_error("planning_conflict", lambda: restored.run(replace(pending, idempotency_key="stale-retry", retry_of_run_id="pending-run")))
        finally:
            restored.close()


def test_planning_tool_schemas_reject_confirmation_extra_fields_and_invalid_questions():
    model = FastFixture()
    loop, planning, _ = setup(model)
    try:
        context = PlanningContext(planning)
        prepared = context.prepare(budgeted(model, Budget()), request(planning), loop)
        tools = prepared.runner._tools
        invalid = [("propose_goal_draft", {**draft_args(), "confirmed": True}),
                   ("propose_goal_draft", {**draft_args(), "time_budget_minutes": True}),
                   ("request_clarification", {"title": "x", "questions": []}),
                   ("request_clarification", {**question_args(), "questions": question_args()["questions"] * 2}),
                   ("generate_route_draft", {"node_count": 31}),
                   ("generate_route_draft", {"node_count": "3"}),
                   ("read_planning_context", {"goal_id": "other"})]
        from learngraph_lite.agent_core import ToolError
        for name, args in invalid:
            try:
                tools.get(name).execute(args)
            except ToolError:
                pass
            else:
                raise AssertionError(f"accepted {name}: {args}")
        assert planning.get_state("g").version == 0
    finally:
        loop.close()
