# 工具调用必须保留完整消息配对

工具执行成功，并不意味着下一次模型请求有效。Chat Completions 需要看到“assistant 提出调用 → tool 回答该调用”的完整记录；只留下 assistant 的文本和 tool 结果，会丢失调用声明。

例如模型一次返回两个调用，下一次请求应包含：

```text
user: 执行任务
assistant: tool_calls=[{id: call-a, ...}, {id: call-b, ...}]
tool: tool_call_id=call-a, content=结果 A
tool: tool_call_id=call-b, content=参数错误 B
```

assistant 可以没有文本，但这条消息仍然必须保存。ID 应保留供应商原值，不能用工具名替代：同一工具可以在一轮被调用多次。错误参数、未知工具也应返回对应 ID 的结果，让模型有机会在预算内修正。取消或预算耗尽可以留下未完成 transcript，但本项目不会把这种已终止 run 的记录继续提交给模型。

工具 schema 只是告诉模型“应该填什么”，不会自动保护 handler。执行前仍要验证 JSON object、必填字段、类型及多余字段。本项目用 Pydantic 生成 schema，再以 strict=True、extra='forbid' 校验；字符串 `"2"` 不会悄悄变成整数。可修正的参数错误作为 tool 消息回注，handler 的意外编程错误仍让 run 失败。

SDK 协议测试应检查真正发送的 JSON，而不只是检查假 client 收到了哪些 Python 参数。HTTPX MockTransport 可以让官方 SDK 完成序列化、响应解析、超时映射和重试流程，同时保持离线；它仍不能证明真实供应商支持该模型或参数，需要另行执行 smoke。
