"""Deterministic P0 model, explicitly labelled fixture and never a fallback."""

import json
from time import sleep

from learngraph_lite.agent_core import ModelResponse, ToolCall


class BusinessFixtureModel:
    def complete(self, messages, tools):
        if tools:
            if messages[-1].role != "tool":
                return ModelResponse(tool_calls=(ToolCall("context", "get_learning_context", "{}"),))
            current_input = next(message.content for message in reversed(messages) if message.role == "user")
            can_generate = any(tool["function"]["name"] == "create_exercise" for tool in tools)
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
        elif "CandidateBatch" in instruction:
            offset = len(data["existing_prompts"])
            value = {"exercises": [{"prompt": f"练习 {offset+i+1}：怎样检验自己是否理解当前节点？",
                "options": [{"id": "a", "text": "只阅读标题"}, {"id": "b", "text": "解释原理并完成一个例子"}, {"id": "c", "text": "跳过练习"}],
                "correct_option_id": "b", "explanation": "可解释的原理和可复现的例子能提供学习证据。"} for i in range(data["count"])]}
        else:
            raise ValueError("Fixture does not support this structured task")
        return ModelResponse(json.dumps(value, ensure_ascii=False))

    def stream_complete(self, messages, tools, on_delta):
        result = self.complete(messages, tools)
        for char in result.content:
            sleep(0.025)
            on_delta(char)
        return result

    def close(self):
        pass
