"""Deterministic P0/P1 model, explicitly labelled fixture and never a fallback."""

import json
import re
from time import sleep

from learngraph_lite.agent_core import ModelResponse, ToolCall


class BusinessFixtureModel:
    def complete(self, messages, tools):
        if tools:
            if any(tool["function"]["name"] == "read_planning_context" for tool in tools):
                return self._planning_turn(messages)
            if messages[-1].role != "tool":
                return ModelResponse(tool_calls=(ToolCall("context", "get_learning_context", "{}"),))
            current_input = next(message.content for message in reversed(messages) if message.role == "user")
            names = {tool["function"]["name"] for tool in tools}
            can_generate = "create_exercise" in names
            if messages[-1].tool_call_id == "context" and "propose_graph_change" in names and any(
                    word in current_input for word in ("提案", "调整路线")):
                context = json.loads(messages[-1].content)
                return ModelResponse(tool_calls=(ToolCall("proposal", "propose_graph_change", json.dumps({
                    "base_revision": context["graph_revision"], "rationale": "fixture 调整建议，需要人工审核。",
                    "operations": [{"kind": "update_node", "node_id": context["node"]["id"],
                                    "explanation": "通过原理说明、最小例子与反例检验当前节点。"}]}, ensure_ascii=False)),))
            if messages[-1].tool_call_id == "proposal":
                return ModelResponse("fixture 路线调整提案已保存，尚未修改路线或成绩。请在提案面板显式接受或拒绝。")
            if messages[-1].tool_call_id == "context" and "search_documents" in names and any(
                    word in current_input for word in ("资料", "引用", "来源", "文档")):
                return ModelResponse(tool_calls=(ToolCall("documents", "search_documents",
                    json.dumps({"query": current_input[:500], "limit": 3}, ensure_ascii=False)),))
            if messages[-1].tool_call_id == "documents":
                sources = json.loads(messages[-1].content).get("sources", [])
                if sources:
                    return ModelResponse(tool_calls=(ToolCall("original", "read_document_chunk",
                        json.dumps({"citation_id": sources[0]["id"]})),))
                return ModelResponse("当前未召回绑定资料。以下是非基于上传资料的 fixture 讲解：通过练习检验理解。")
            if messages[-1].tool_call_id == "original":
                result = json.loads(messages[-1].content)
                return ModelResponse(f"这是基于绑定资料的 fixture 引用示例 [{result['id']}]。"
                                     "请打开原文核查；fixture 不评估论述是否被来源支持。")
            if messages[-1].tool_call_id == "context" and can_generate and any(word in current_input for word in ("出题", "练习")):
                return ModelResponse(tool_calls=(ToolCall("exercise", "create_exercise", '{"count":1,"purpose":"practice"}'),))
            return ModelResponse("这是 fixture 示例讲解。先理解当前节点的目标，再通过练习检验。后续问题会结合本会话的完整回合。")
        data = json.loads(messages[1].content)
        instruction = messages[0].content
        if "CandidateClarification" in instruction:
            labels = {"desired_outcome": "你希望最终做出什么？", "current_level": "你已有怎样的基础？", "time_budget_minutes": "本轮可投入多少分钟？"}
            value = {"questions": [{"field": k, "question": labels[k]} for k in data["missing_fields"]]}
        elif "CandidateGraph" in instruction:
            titles = ["目标与边界", "核心概念", "最小示例", "常见误区", "练习验证", "综合实践"]
            count = data["node_count"] or 6
            value = {"nodes": [{"id": f"node-{i+1}", "title": titles[i] if i < len(titles) else f"拓展 {i+1}",
                "explanation": "通过一个具体例子理解概念、适用条件与限制。", "learning_outcome": "能够解释原理并完成一个最小例子。",
                "estimated_minutes": 20, "priority": 3} for i in range(count)],
                "edges": [{"source": f"node-{i}", "target": f"node-{i+1}"} for i in range(1, count)]}
            if data.get("feedback", "").strip():
                feedback = data["feedback"]
                easier = any(word in feedback for word in ("太难", "简单", "入门", "基础"))
                for index, node in enumerate(value["nodes"]):
                    previous = data["current_graph"]["nodes"]
                    title = previous[index % len(previous)]["title"]
                    node["title"] = ("基础练习：" if easier else "重点验证：") + title[:100]
                    node["estimated_minutes"] = 10 if easier else 25
                    node["priority"] = 5 if index == 0 else 3
                    node["explanation"] = "fixture 根据反馈调整：先用基础例子验证理解，再依次学习；这是后续实践的必要铺垫。"
                    node["learning_outcome"] = "用自己的话解释一个基础概念，完成对应练习并对照结果纠正错误。"
        elif "CandidateProposal" in instruction:
            graph = data["context"]["graph"]
            value = {"rationale": "fixture 建议补充当前节点的验证步骤，请人工审核。",
                "operations": [{"kind": "update_node", "node_id": graph["nodes"][0]["id"],
                    "explanation": "通过原理说明、最小例子与反例检验当前节点。"}]}
        elif "CandidateBatch" in instruction:
            offset = len(data["existing_prompts"])
            value = {"exercises": [{"prompt": f"练习 {offset+i+1}：怎样检验自己是否理解当前节点？",
                "options": [{"id": "a", "text": "只阅读标题"}, {"id": "b", "text": "解释原理并完成一个例子"}, {"id": "c", "text": "跳过练习"}],
                "correct_option_id": "b", "explanation": "可解释的原理和可复现的例子能提供学习证据。"} for i in range(data["count"])]}
        elif "CandidateLesson" in instruction:
            value = {"schema_version": 1, "title": "当前节点学习包（fixture）",
                "markdown": "## 学习目标\n先解释概念，再完成最小例子。这是固定组件的 fixture 示例。",
                "components": [
                    {"id": "overview", "kind": "markdown", "props": {"text": "把自己的解释与实际结果对照。"}},
                    *[{"id": f"quiz-{index}", "kind": "quiz_choice", "props": {"exercise_id": exercise["id"]}}
                      for index, exercise in enumerate(data["exercises"])],
                    {"id": "steps", "kind": "stepper", "props": {"steps": [
                        {"title": "理解", "description": "用自己的话说明节点目标。", "slots": {"text": "不要只记标题。"}},
                        {"title": "验证", "description": "运行最小例子并对照预期。", "slots": {"text": "记录结果。"}}]}},
                    {"id": "compare", "kind": "comparison_table", "props": {
                        "columns": ["方式", "证据"], "rows": [["阅读", "知道概念"], ["练习", "可以复现"]]}}]}
        else:
            raise ValueError("Fixture does not support this structured task")
        citation_ids = [data["sources"][0]["id"]] if data.get("sources") else []
        suffix = f" [{citation_ids[0]}]" if citation_ids else ""
        if "nodes" in value:
            for node in value["nodes"]:
                node["citation_ids"] = citation_ids
                node["explanation"] += suffix
        elif "exercises" in value:
            for exercise in value["exercises"]:
                exercise["citation_ids"] = citation_ids
                exercise["explanation"] += suffix
        elif "components" in value:
            value["citation_ids"] = citation_ids
            value["markdown"] += suffix
        return ModelResponse(json.dumps(value, ensure_ascii=False))

    def _planning_turn(self, messages):
        """Explicit fixture-only text extraction, not a replacement for a real Agent."""
        def call(name, args, text):
            return ModelResponse(text, tool_calls=(ToolCall(name, name, json.dumps(args, ensure_ascii=False)),))

        if messages[-1].role != "tool":
            return call("read_planning_context", {}, "")
        if messages[-1].tool_call_id == "generate_route_draft":
            result = json.loads(messages[-1].content)
            if "error" in result:
                return ModelResponse("fixture 无法保存路线：" + result["error"])
            changes = result["changes"]
            return ModelResponse(f"fixture 待审核路线已保存。按先基础验证再实践的顺序，共{len(result['planning']['graph']['nodes'])}个节点。"
                f"新增{len(changes['added'])}、移除{len(changes['removed'])}、更新{len(changes['updated'])}，"
                f"总投入由{changes['before_minutes']}变为{changes['after_minutes']}分钟。请审核后显式发布；我没有发布。")
        if messages[-1].tool_call_id != "read_planning_context":
            return ModelResponse("fixture 工具结果已收到，请审核当前方案。")
        state = json.loads(messages[-1].content)
        if "error" in state:
            return ModelResponse("fixture 规划上下文已过期，请刷新。")
        raw = next(message.content for message in reversed(messages) if message.role == "user")
        response = None
        try:
            parsed = json.loads(raw)
            response = parsed.get("planning_response")
            text = parsed["user_text"]
        except (ValueError, TypeError, KeyError):
            text = raw
        goal = state["goal"]
        graph = state["graph"]
        if any(word in text for word in ("为什么", "为何", "解释", "什么依据", "依据是什么", "什么原因")) and response is None:
            return ModelResponse("fixture 解释：先验证基础，再练习和实践，按前置依赖排序。投入与范围来自当前目标，"
                                 "用户自述基础未经验证。这一回合只解释，没有修改目标或路线。")
        if graph and graph["status"] == "published":
            return ModelResponse("fixture 当前路线已发布，规划工具不会重写它，请使用人工审核的提案。")
        edit_goal = any(word in text for word in ("修改目标", "改目标", "换目标"))
        if goal["confirmed"] and not edit_goal:
            if graph is None:
                count = max(1, min(8, (goal["time_budget_minutes"] or 120) // 30))
                return call("generate_route_draft", {"node_count": count},
                            "fixture 根据已确认目标选择必要节点，生成待审核路线，不发布。")
            if any(word in text for word in ("太难", "太宽", "简单", "缩小", "调整", "基础", "太多", "聚焦")):
                count = len(graph["nodes"])
                count = min(30, count + 1) if "太难" in text or "基础" in text else max(1, count - 1)
                return call("generate_route_draft", {"node_count": count, "feedback": text[:2000]},
                            "fixture 根据反馈重新安排范围与基础验证，完成后说明实际差异。")
            return ModelResponse("fixture 当前路线可供审核。聊天认可不会自动发布，请使用明确的发布按钮。")

        draft = {key: goal[key] for key in ("title", "desired_outcome", "current_level",
                                           "time_budget_minutes", "constraints", "skipped_fields")}
        draft["skipped_fields"] = list(draft["skipped_fields"])
        extraction_text = (response["original_user_text"] + "，" + text) if response else text
        # Fixture supports explicit labels and common Chinese planning descriptions.
        outcome = re.search(r"(?:期望成果|成果|目标|希望|想要)[：:是为]?\s*([^，。；;\n]+)", extraction_text)
        level = re.search(r"(?:当前基础|基础|当前水平)[：:是为]?\s*([^，。；;\n]+)", extraction_text)
        if outcome:
            draft["desired_outcome"] = outcome.group(1)[:2000]
        elif any(word in extraction_text for word in ("做出", "完成", "写出", "能够", "能写", "能做", "掌握")):
            draft["desired_outcome"] = extraction_text[:2000]
        if level:
            draft["current_level"] = level.group(1)[:2000]
        elif any(word in extraction_text for word in ("零基础", "初学", "新手", "没有基础", "学过", "熟悉", "会Python", "会 Python")):
            draft["current_level"] = extraction_text[:2000]
        minutes = re.search(r"(\d+)\s*(分钟|小时)", extraction_text)
        if minutes:
            draft["time_budget_minutes"] = max(1, min(1000000, int(minutes.group(1)) * (60 if minutes.group(2) == "小时" else 1)))
        if edit_goal:
            draft["title"] = text[:2000]
        if response:
            for answer in response["answers"]:
                field = answer["question_id"]
                if field not in ("desired_outcome", "current_level", "time_budget_minutes"):
                    continue
                if answer["skipped"]:
                    draft[field] = None if field == "time_budget_minutes" else ""
                    if field not in draft["skipped_fields"]:
                        draft["skipped_fields"].append(field)
                elif field == "time_budget_minutes":
                    number = re.search(r"\d+", answer["value"])
                    if number:
                        draft[field] = max(1, min(1000000, int(number.group()) * (60 if "小时" in answer["value"] else 1)))
                else:
                    draft[field] = answer["value"]
        missing = [field for field in ("desired_outcome", "current_level", "time_budget_minutes")
                   if not draft[field] and field not in draft["skipped_fields"]]
        if missing and response is None and not edit_goal:
            labels = {"desired_outcome": ("你希望学完能做什么？", "确定可验证的成果，避免范围过宽。",
                                          [("practice", "完成一个小实践", "完成一个小实践"), ("concepts", "理解核心概念", "理解核心概念")]),
                      "current_level": ("你对这个主题有什么基础？", "选择铺垫和验证起点；自述不代表已掌握。",
                                        [("beginner", "零基础", "零基础"), ("some", "了解一些概念", "了解一些概念")]),
                      "time_budget_minutes": ("本次大约能投入多少时间？", "据此选择必要节点数和路线深度。",
                                              [("short", "60分钟", "60"), ("long", "240分钟", "240")])}
            questions = [{"id": field, "prompt": labels[field][0], "reason": labels[field][1],
                          "options": [{"id": o[0], "label": o[1], "value": o[2]} for o in labels[field][2]],
                          "allow_skip": True} for field in missing]
            return call("request_clarification", {"title": "只补充影响当前路线的信息（fixture）", "questions": questions},
                        "fixture 我先提取了已知信息，只询问仍影响范围、难度或投入的缺项；可自定义或跳过。")
        return call("propose_goal_draft", draft,
                    "fixture 已整理待审核的目标草稿。基础仍待验证；缺项只用明确假设，请审核并点击确认，我不会替你确认。")

    def stream_complete(self, messages, tools, on_delta):
        result = self.complete(messages, tools)
        for char in result.content:
            sleep(0.025)
            on_delta(char)
        return result

    def close(self):
        pass
