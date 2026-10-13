# 技术债追踪

这里记录那些暂时不阻塞当前任务、但已经值得留档的技术债。

| 日期 | 区域 | 债务描述 | 为什么会存在 | 计划中的后续动作 |
| --- | --- | --- | --- | --- |
| 2026-10-13 | 真实供应商兼容性 | assistant/tool 配对、Pydantic 参数校验与官方 SDK MockTransport 测试已完成；尚无真实 endpoint smoke | 当前未配置外部 Key，真实入口仅注册 echo；适配器使用 max_tokens，模型/endpoint 支持范围有限 | 配置模型后运行 smoke:real 验证普通回答和原生 tool calling，再接业务工具；按实际模型需求考虑 max_completion_tokens/Responses API，不把离线协议证据写成供应商兼容结论。 |
| 2026-10-13 | HTTP 测试依赖 | Starlette 1.8.0 的 TestClient 提示 httpx 接口弃用，当前锁定组合仍可运行 | HTTP 切片沿用 HTTPX 0.28.1 做 TestClient 与 TCP 流验证 | 后续统一升级 TestClient 适配和 httpx2，并重新验证跨平台流测试。 |
