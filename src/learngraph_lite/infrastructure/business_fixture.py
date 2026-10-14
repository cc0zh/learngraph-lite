"""Deterministic P0/P1 model, explicitly labelled fixture and never a fallback."""

import json
from time import sleep

from learngraph_lite.agent_core import ModelResponse, ToolCall


class BusinessFixtureModel:
    def complete(self, messages, tools):
        if tools:
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
            count = data["node_count"]
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

    def stream_complete(self, messages, tools, on_delta):
        result = self.complete(messages, tools)
        for char in result.content:
            sleep(0.025)
            on_delta(char)
        return result

    def close(self):
        pass
