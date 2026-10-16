from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from importlib import import_module

from learngraph_lite.agent_core import AgentRunner, Budget, ModelResponse, TextMessage, ToolCall, ToolError, ToolRegistry


def skills_api():
    # Import inside each test so a missing public module produces individual REDs.
    return import_module("learngraph_lite.application.skills")


class MemoryCatalog:
    """Structural SkillCatalog with no filesystem or read_skill dependency."""

    def __init__(self, *definitions):
        self.definitions = tuple(definitions)

    def list_skills(self):
        return self.definitions


class ScriptedModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict, ...]) -> ModelResponse:
        self.calls.append((messages, tools))
        assert self.responses, "unexpected model call"
        return self.responses.pop(0)


def definition(api, skill_id="goal-planning", **updates):
    values = {"id": skill_id, "description": f"Summary for {skill_id}.",
              "instructions": f"PRIVATE BODY for {skill_id}: inspect before advising."}
    return api.SkillDefinition(**{**values, **updates})


def read_tool(turn):
    tools = ToolRegistry()
    turn.register(tools)
    tool = tools.get("read_skill")
    assert tool is not None, "available skills must register read_skill"
    return tool


def expect_error(error_type, action):
    try:
        action()
    except error_type as exc:
        return exc
    raise AssertionError(f"expected {error_type.__name__}")


def usage_entry(skill, activation):
    return {"skill_id": skill.id, "content_hash": skill.content_hash, "activation": activation}


def skill_call(skill_id, call_id="read-1"):
    return ToolCall(id=call_id, name="read_skill", arguments=json.dumps({"skill_id": skill_id}))


def skill_result(skill):
    return {"skill_id": skill.id, "content_hash": skill.content_hash, "instructions": skill.instructions}


def test_skill_definition_is_frozen_and_hashes_exact_utf8_instructions():
    api = skills_api()
    body = "先读上下文。\nPreserve trailing space. \n"
    skill = definition(api, instructions=body)
    assert skill.instructions == body
    assert skill.content_hash == sha256(body.encode("utf-8")).hexdigest()
    assert skill.modes == ("planning", "runner", "teaching", "explanation")
    expect_error(FrozenInstanceError, lambda: setattr(skill, "instructions", "changed"))
    assert definition(api, description="Different summary", instructions=body).content_hash == skill.content_hash
    assert definition(api, instructions=body + " ").content_hash != skill.content_hash


def test_skill_definition_rejects_invalid_or_non_string_ids():
    api = skills_api()
    for value in ("", " ", "Goal-Planning", "../goal-planning", "goal/planning", "goal\\planning",
                  "goal planning", "goal_planning", "-goal", "goal-", "goal--planning", "计划",
                  "$goal-planning", 1, True, None):
        expect_error(ValueError, lambda: definition(api, skill_id=value))


def test_skill_definition_rejects_blank_or_non_string_descriptions():
    api = skills_api()
    for value in ("", " \n\t", 1, True, None, ["summary"]):
        expect_error(ValueError, lambda: definition(api, description=value))


def test_skill_definition_rejects_blank_or_non_string_instructions():
    api = skills_api()
    for value in ("", " \n\t", 1, True, None, b"instructions"):
        expect_error(ValueError, lambda: definition(api, instructions=value))


def test_skill_definition_rejects_invalid_modes_without_coercion():
    api = skills_api()
    for value in ((), "runner", ["runner"], ("unknown",), ("Runner",), (1,), (None,), None):
        expect_error(ValueError, lambda: definition(api, modes=value))
    assert definition(api, modes=("planning",)).modes == ("planning",)


def test_skill_definition_accepts_exactly_8192_utf8_body_bytes():
    api = skills_api()
    body = "学" * 2730 + "ab"
    assert len(body.encode("utf-8")) == 8192
    skill = definition(api, instructions=body)
    turn = api.SkillTurn(MemoryCatalog(skill), "runner")
    assert read_tool(turn).execute({"skill_id": skill.id}) == skill_result(skill)


def test_skill_definition_rejects_more_than_8192_utf8_body_bytes():
    api = skills_api()
    for body in ("a" * 8193, "学" * 2731):
        expect_error(ValueError, lambda: definition(api, instructions=body))


def test_prompt_contains_contract_and_summaries_but_no_unselected_bodies():
    api = skills_api()
    first, second = definition(api), definition(api, "concept-teaching")
    turn = api.SkillTurn(MemoryCatalog(first, second), "runner")
    prompt = turn.prompt()
    assert isinstance(prompt, str)
    assert "read_skill" in prompt and "instructions" in prompt
    for skill in (first, second):
        assert skill.id in prompt and skill.description in prompt
        assert skill.instructions not in prompt
    assert turn.project_usage() == {}


def test_prompt_filters_catalog_by_each_supported_mode():
    api = skills_api()
    modes = ("planning", "runner", "teaching", "explanation")
    definitions = tuple(definition(api, f"only-{mode}", modes=(mode,)) for mode in modes)
    for mode in modes:
        turn = api.SkillTurn(MemoryCatalog(*definitions), mode)
        prompt = turn.prompt()
        for skill in definitions:
            if skill.modes == (mode,):
                assert skill.id in prompt and skill.description in prompt
            else:
                assert skill.id not in prompt and skill.description not in prompt
            assert skill.instructions not in prompt
        assert read_tool(turn).name == "read_skill"


def test_no_catalog_empty_catalog_or_no_applicable_skills_registers_no_tool():
    api = skills_api()
    planning_only = definition(api, modes=("planning",))
    for catalog in (None, MemoryCatalog(), MemoryCatalog(planning_only)):
        turn = api.SkillTurn(catalog, "runner")
        tools = ToolRegistry()
        turn.register(tools)
        assert tools.model_tools() == () and tools.get("read_skill") is None
        assert planning_only.id not in turn.prompt()
        assert turn.project_usage() == {}


def test_summary_budget_is_bounded_in_utf8_bytes_without_body_leakage():
    api = skills_api()
    definitions = tuple(definition(api, f"skill-{index}", description=f"摘要{index}：" + "学" * 160)
                        for index in range(30))
    # Either reject an oversized catalog or bound its advertised summary window.
    # The contract does not require truncation instead of fail-fast rejection.
    try:
        turn = api.SkillTurn(MemoryCatalog(*definitions), "runner")
    except ValueError as exc:
        assert "summary" in str(exc).lower() and "budget" in str(exc).lower()
        return
    prompt = turn.prompt()
    assert len(prompt.encode("utf-8")) <= 8192
    assert definitions[0].id in prompt
    assert all(skill.instructions not in prompt for skill in definitions)
    assert turn.project_usage() == {}


def test_read_skill_schema_is_strict_and_exposes_only_skill_id():
    api = skills_api()
    turn = api.SkillTurn(MemoryCatalog(definition(api)), "runner")
    tools = ToolRegistry()
    turn.register(tools)
    advertised = tools.model_tools()
    assert len(advertised) == 1
    function = advertised[0]["function"]
    assert function["name"] == "read_skill"
    schema = function["parameters"]
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert schema["required"] == ["skill_id"]
    assert set(schema["properties"]) == {"skill_id"}
    assert schema["properties"]["skill_id"]["type"] == "string"


def test_read_skill_rejects_extra_arguments_without_loading():
    api = skills_api()
    skill = definition(api)
    turn = api.SkillTurn(MemoryCatalog(skill), "runner")
    tool = read_tool(turn)
    for extra in ({"path": "SKILL.md"}, {"instructions": "override"}, {"mode": "planning"}):
        expect_error(ToolError, lambda: tool.execute({"skill_id": skill.id, **extra}))
    assert turn.project_usage() == {}


def test_read_skill_rejects_missing_and_wrong_type_arguments_without_loading():
    api = skills_api()
    turn = api.SkillTurn(MemoryCatalog(definition(api)), "runner")
    tool = read_tool(turn)
    for args in ({}, {"skill_id": 1}, {"skill_id": True}, {"skill_id": None}, {"skill_id": ["goal-planning"]}):
        expect_error(ToolError, lambda: tool.execute(args))
    assert turn.project_usage() == {}


def test_read_skill_rejects_paths_and_unknown_ids_without_loading():
    api = skills_api()
    turn = api.SkillTurn(MemoryCatalog(definition(api)), "runner")
    tool = read_tool(turn)
    for skill_id in ("../goal-planning", "goal-planning/SKILL.md", "goal-planning\\SKILL.md",
                     "D:\\skills\\goal-planning", "/skills/goal-planning", "unknown", ""):
        expect_error(ToolError, lambda: tool.execute({"skill_id": skill_id}))
    assert turn.project_usage() == {}


def test_read_skill_rejects_known_but_mode_unavailable_skill():
    api = skills_api()
    allowed = definition(api, "concept-teaching", modes=("teaching",))
    forbidden = definition(api, modes=("planning",))
    turn = api.SkillTurn(MemoryCatalog(allowed, forbidden), "teaching")
    tool = read_tool(turn)
    expect_error(ToolError, lambda: tool.execute({"skill_id": forbidden.id}))
    assert turn.project_usage() == {}
    assert tool.execute({"skill_id": allowed.id}) == skill_result(allowed)


def test_read_skill_returns_exact_content_and_deduplicates_usage():
    api = skills_api()
    skill = definition(api)
    turn = api.SkillTurn(MemoryCatalog(skill), "runner")
    tool = read_tool(turn)
    assert turn.project_usage() == {}
    assert tool.execute({"skill_id": skill.id}) == skill_result(skill)
    assert tool.execute({"skill_id": skill.id}) == skill_result(skill)
    assert turn.project_usage() == {"skill_usage": [usage_entry(skill, "tool")]}
    assert skill.instructions not in turn.prompt()
    assert skill.instructions not in json.dumps(turn.project_usage())


def test_runner_lazily_round_trips_skill_content_and_usage():
    api = skills_api()
    selected, unselected = definition(api), definition(api, "concept-teaching")
    turn = api.SkillTurn(MemoryCatalog(selected, unselected), "runner")
    tools = ToolRegistry()
    turn.register(tools)
    model = ScriptedModel([ModelResponse(tool_calls=(skill_call(selected.id, "full-call-id"),)),
                           ModelResponse(content="Used the selected guide.")])
    assert turn.project_usage() == {}
    result = AgentRunner(model, tools).run((TextMessage("system", turn.prompt()), TextMessage("user", "Help me plan.")))
    assert result.status == "completed" and result.errors == ()
    assert result.final_text == "Used the selected guide." and len(model.calls) == 2
    initial_messages = model.calls[0][0]
    assert all(selected.instructions not in m.content and unselected.instructions not in m.content for m in initial_messages)
    second_messages = model.calls[1][0]
    assistant = next(m for m in second_messages if m.role == "assistant")
    tool_message = next(m for m in second_messages if m.role == "tool")
    assert assistant.tool_calls == (skill_call(selected.id, "full-call-id"),)
    assert tool_message.tool_call_id == "full-call-id" and json.loads(tool_message.content) == skill_result(selected)
    assert all(unselected.instructions not in m.content for m in result.messages)
    assert turn.project_usage() == {"skill_usage": [usage_entry(selected, "tool")]}


def test_runner_returns_strict_argument_errors_and_allows_repair():
    api = skills_api()
    skill = definition(api)
    turn = api.SkillTurn(MemoryCatalog(skill), "runner")
    tools = ToolRegistry()
    turn.register(tools)
    bad_args = ({"skill_id": skill.id, "path": "SKILL.md"}, {"skill_id": 1},
                {"skill_id": "../goal-planning"}, {})
    calls = tuple(ToolCall(str(index), "read_skill", json.dumps(args)) for index, args in enumerate(bad_args))
    model = ScriptedModel([ModelResponse(tool_calls=calls), ModelResponse(tool_calls=(skill_call(skill.id, "repair"),)),
                           ModelResponse(content="Repaired.")])
    result = AgentRunner(model, tools).run((TextMessage("user", "Read a guide."),))
    assert result.status == "completed" and len(result.errors) == len(bad_args)
    outputs = [m for m in result.messages if m.role == "tool"]
    assert [m.tool_call_id for m in outputs] == ["0", "1", "2", "3", "repair"]
    assert all("error" in json.loads(m.content) for m in outputs[:-1])
    assert json.loads(outputs[-1].content) == skill_result(skill)
    assert turn.project_usage() == {"skill_usage": [usage_entry(skill, "tool")]}


def test_runner_reports_third_distinct_load_as_tool_error_but_repeats_are_allowed():
    api = skills_api()
    first, second, third = (definition(api, skill_id) for skill_id in ("first-guide", "second-guide", "third-guide"))
    turn = api.SkillTurn(MemoryCatalog(first, second, third), "runner")
    tools = ToolRegistry()
    turn.register(tools)
    calls = (skill_call(first.id, "first"), skill_call(first.id, "repeat"), skill_call(second.id, "second"),
             skill_call(third.id, "third"), skill_call(first.id, "repeat-after-limit"))
    model = ScriptedModel([ModelResponse(tool_calls=calls), ModelResponse(content="Limit handled.")])
    result = AgentRunner(model, tools).run((TextMessage("user", "Read three guides."),))
    assert result.status == "completed" and len(result.errors) == 1
    outputs = {m.tool_call_id: json.loads(m.content) for m in result.messages if m.role == "tool"}
    assert outputs["first"] == outputs["repeat"] == outputs["repeat-after-limit"] == skill_result(first)
    assert outputs["second"] == skill_result(second)
    assert set(outputs["third"]) == {"error"} and outputs["third"]["error"]
    assert third.instructions not in json.dumps(outputs, ensure_ascii=False)
    assert turn.project_usage() == {"skill_usage": [usage_entry(first, "tool"), usage_entry(second, "tool")]}


def test_explicit_current_text_activation_loads_body_once_and_marks_source():
    api = skills_api()
    selected, other = definition(api), definition(api, "concept-teaching")
    turn = api.SkillTurn(MemoryCatalog(selected, other), "runner", f"Use ${selected.id}; again ${selected.id}. $unknown")
    prompt = turn.prompt()
    assert prompt.count(selected.instructions) == 1 and other.instructions not in prompt
    assert turn.project_usage() == {"skill_usage": [usage_entry(selected, "explicit")]}
    assert read_tool(turn).execute({"skill_id": selected.id}) == skill_result(selected)
    assert turn.project_usage() == {"skill_usage": [usage_entry(selected, "explicit")]}


def test_explicit_activation_ignores_unknown_uppercase_and_plain_ids():
    api = skills_api()
    skill = definition(api)
    for text in ("$unknown", "$GOAL-PLANNING", "goal-planning", "$goal-planning-extra"):
        turn = api.SkillTurn(MemoryCatalog(skill), "runner", text)
        assert skill.instructions not in turn.prompt()
        assert turn.project_usage() == {}
    assert api.SkillTurn(None, "runner", "$unknown").project_usage() == {}


def test_explicit_known_but_mode_unavailable_reference_raises_value_error():
    api = skills_api()
    skill = definition(api, modes=("planning",))
    expect_error(ValueError, lambda: api.SkillTurn(MemoryCatalog(skill), "teaching", f"Use ${skill.id}"))


def test_explicit_three_distinct_skills_are_rejected_during_construction():
    api = skills_api()
    definitions = tuple(definition(api, skill_id) for skill_id in ("first-guide", "second-guide", "third-guide"))
    text = " ".join(f"${skill.id}" for skill in definitions)
    expect_error(ValueError, lambda: api.SkillTurn(MemoryCatalog(*definitions), "runner", text))


def test_explicit_duplicates_do_not_consume_two_skill_limit():
    api = skills_api()
    first, second = definition(api), definition(api, "concept-teaching")
    turn = api.SkillTurn(MemoryCatalog(first, second), "runner", f"${first.id} ${first.id} ${second.id} ${first.id}")
    assert turn.prompt().count(first.instructions) == turn.prompt().count(second.instructions) == 1
    assert turn.project_usage() == {"skill_usage": [usage_entry(first, "explicit"), usage_entry(second, "explicit")]}


def test_explicit_and_tool_loads_share_limit_and_preserve_activation_metadata():
    api = skills_api()
    first, second, third = (definition(api, skill_id) for skill_id in ("first-guide", "second-guide", "third-guide"))
    turn = api.SkillTurn(MemoryCatalog(first, second, third), "runner", f"${first.id}")
    tool = read_tool(turn)
    assert tool.execute({"skill_id": second.id}) == skill_result(second)
    expect_error(ToolError, lambda: tool.execute({"skill_id": third.id}))
    assert tool.execute({"skill_id": first.id}) == skill_result(first)
    assert turn.project_usage() == {"skill_usage": [usage_entry(first, "explicit"), usage_entry(second, "tool")]}
    assert first.instructions in turn.prompt() and second.instructions not in turn.prompt()


def test_new_turn_does_not_inherit_explicit_activation_or_tool_usage():
    api = skills_api()
    skill = definition(api)
    catalog = MemoryCatalog(skill)
    prior = api.SkillTurn(catalog, "runner", f"${skill.id}")
    assert prior.project_usage() == {"skill_usage": [usage_entry(skill, "explicit")]}
    current = api.SkillTurn(catalog, "runner", "Explain normally.")
    assert current.project_usage() == {} and skill.instructions not in current.prompt()
    assert read_tool(current).execute({"skill_id": skill.id}) == skill_result(skill)
    assert current.project_usage() == {"skill_usage": [usage_entry(skill, "tool")]}
    assert prior.project_usage() == {"skill_usage": [usage_entry(skill, "explicit")]}


def test_small_input_budget_rejects_model_and_does_not_load_skills():
    api = skills_api()
    skill = definition(api)
    turn = api.SkillTurn(MemoryCatalog(skill), "runner")
    tools = ToolRegistry()
    turn.register(tools)
    model = ScriptedModel([ModelResponse(tool_calls=(skill_call(skill.id),))])
    budget = Budget(max_input_tokens=1)
    result = AgentRunner(model, tools).run((TextMessage("system", turn.prompt()), TextMessage("user", "Read.")), budget)
    assert result.status == "failed" and result.errors == ("context budget exhausted",)
    assert model.calls == [] and budget.model_calls == budget.tool_calls == 0
    assert turn.project_usage() == {}


def test_explicit_body_cannot_bypass_small_input_token_budget():
    api = skills_api()
    skill = definition(api)
    turn = api.SkillTurn(MemoryCatalog(skill), "runner", f"${skill.id}")
    tools = ToolRegistry()
    turn.register(tools)
    model = ScriptedModel([ModelResponse(content="Should never be called.")])
    result = AgentRunner(model, tools).run((TextMessage("system", turn.prompt()), TextMessage("user", f"${skill.id}")),
                                          Budget(max_input_tokens=1))
    assert result.status == "failed" and result.errors == ("context budget exhausted",)
    assert model.calls == []


def test_history_replaces_only_skill_tool_content_and_preserves_protocol():
    api = skills_api()
    skill = definition(api)
    calls = (skill_call(skill.id, "skill-call"), ToolCall("other-call", "read_context", "{}"))
    history = (TextMessage("user", f"Previously used ${skill.id}"),
               TextMessage("assistant", "Reading guides.", tool_calls=calls),
               TextMessage("tool", json.dumps(skill_result(skill)), tool_call_id="skill-call"),
               TextMessage("tool", '{"context":"KEEP OTHER TOOL"}', tool_call_id="other-call"),
               TextMessage("assistant", "Prior answer."))
    projected = api.prepare_skill_history(history)
    assert isinstance(projected, tuple) and len(projected) == len(history)
    assert projected[2].content.strip() and projected[2].content != history[2].content
    assert skill.instructions not in projected[2].content
    assert replace(projected[2], content=history[2].content) == history[2]
    assert projected[:2] == history[:2] and projected[3:] == history[3:]
    assert projected[1].tool_calls == calls and projected[2].tool_call_id == "skill-call"
    assert skill.instructions in history[2].content
    assert api.prepare_skill_history(projected) == projected
    current = api.SkillTurn(MemoryCatalog(skill), "runner", "Continue without an explicit reference.")
    assert current.project_usage() == {} and skill.instructions not in current.prompt()


def test_history_call_id_reuse_does_not_rewrite_non_skill_tool_in_later_turn():
    api = skills_api()
    skill = definition(api)
    other_content = json.dumps({"skill_id": skill.id, "instructions": "KEEP NON-SKILL RESULT"})
    history = (TextMessage("user", "First turn."),
               TextMessage("assistant", "", tool_calls=(skill_call(skill.id, "reused"),)),
               TextMessage("tool", json.dumps(skill_result(skill)), tool_call_id="reused"),
               TextMessage("user", "Second turn."),
               TextMessage("assistant", "", tool_calls=(ToolCall("reused", "read_context", "{}"),)),
               TextMessage("tool", other_content, tool_call_id="reused"))
    projected = api.prepare_skill_history(history)
    assert projected[2].content != history[2].content and skill.instructions not in projected[2].content
    assert projected[:2] == history[:2] and projected[3:] == history[3:]
    assert projected[5].content == other_content


def test_history_call_id_reuse_does_not_rewrite_non_skill_tool_in_earlier_turn():
    api = skills_api()
    skill = definition(api)
    history = (TextMessage("user", "First turn."),
               TextMessage("assistant", "", tool_calls=(ToolCall("reused", "read_context", "{}"),)),
               TextMessage("tool", "KEEP EARLIER NON-SKILL RESULT", tool_call_id="reused"),
               TextMessage("user", "Second turn."),
               TextMessage("assistant", "", tool_calls=(skill_call(skill.id, "reused"),)),
               TextMessage("tool", json.dumps(skill_result(skill)), tool_call_id="reused"))
    projected = api.prepare_skill_history(history)
    assert projected[:5] == history[:5]
    assert projected[5].content != history[5].content and skill.instructions not in projected[5].content
    assert projected[5].tool_call_id == "reused"


def test_history_does_not_match_orphan_result_to_previous_user_turn():
    api = skills_api()
    skill = definition(api)
    history = (TextMessage("user", "First turn."),
               TextMessage("assistant", "", tool_calls=(skill_call(skill.id, "reused"),)),
               TextMessage("tool", json.dumps(skill_result(skill)), tool_call_id="reused"),
               TextMessage("user", "New turn without a matching assistant call."),
               TextMessage("tool", "KEEP UNPAIRED RESULT", tool_call_id="reused"))
    projected = api.prepare_skill_history(history)
    assert projected[2].content != history[2].content
    assert projected[3:] == history[3:]


def test_history_without_skill_calls_is_unchanged():
    api = skills_api()
    history = (TextMessage("user", "Mention read_skill without calling it."),
               TextMessage("assistant", "", tool_calls=(ToolCall("context", "read_context", "{}"),)),
               TextMessage("tool", '{"instructions":"NOT A SKILL RESULT"}', tool_call_id="context"))
    assert api.prepare_skill_history(history) == history
    assert api.prepare_skill_history(()) == ()
