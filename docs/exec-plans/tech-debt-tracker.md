# 技术债追踪

这里记录那些暂时不阻塞当前任务、但已经值得留档的技术债。

| 日期 | 区域 | 债务描述 | 为什么会存在 | 计划中的后续动作 |
| --- | --- | --- | --- | --- |
| 2026-10-13 | Agent 内核与真实模型适配 | 当前 TextMessage 未表达 assistant tool_calls，工具参数未按 input_schema 校验 | 现有 fixture 只验证工具回注控制流，尚未接入供应商 SDK | 接入真实模型前补齐 assistant/tool 消息配对、参数 schema 校验与协议测试；然后执行真实 tool calling smoke，不能把当前 fixture 结果作为供应商兼容证据。 |
| 2026-10-13 | HTTP 测试依赖 | Starlette 1.8.0 的 TestClient 提示 httpx 接口弃用，当前锁定组合仍可运行 | HTTP 切片沿用 HTTPX 0.28.1 做 TestClient 与 TCP 流验证 | 后续统一升级 TestClient 适配和 httpx2，并重新验证跨平台流测试。 |
