# 技术债追踪

这里记录那些暂时不阻塞当前任务、但已经值得留档的技术债。

| 日期 | 区域 | 债务描述 | 为什么会存在 | 计划中的后续动作 |
| --- | --- | --- | --- | --- |
| 2026-10-13 | 真实供应商兼容性 | assistant/tool 配对、Pydantic 参数校验与官方 SDK MockTransport 测试已完成；尚无真实 endpoint smoke | 当前未配置外部 Key；节点入口已接上下文、推荐与资料两只工具，适配器使用 max_tokens，模型/endpoint 支持范围有限 | 配置模型后运行 smoke:real 验证普通回答和原生 tool calling，并自选执行 demo:learning-agent -- --real 验证业务调用；按实际模型需求考虑 max_completion_tokens/Responses API，不把离线协议证据写成供应商兼容结论。 |
| 2026-10-13 | 资料检索与版本 | 当前 tokenize + SQLite FTS5 不是规格中的 jieba/BM25；旧 upload_text 可同版本覆盖，来源通过 hash/位置检测失效 | 本切片先复用已有适配器连接 Agent 引用，不扩建整套资料管理 | 后续上传/PDF 切片完善文档版本及检索算法；回答/出题/学习页 grounding 增加语义支持评估，不能仅依赖有效 citation_id。 |
| 2026-10-13 | 图谱与学习快照同步 | 上下文拒绝未发布或与学习状态不一致的图谱，但尚无显式学习状态迁移用例与跨仓库事务 | 当前使用已有 planning/learning JSON snapshot repository，避免在只读工具内隐式重置成绩 | 接完整图谱变更 HTTP 时实现显式同步/迁移并验证并发发布；start_goal 仅用于首次初始化或隔离 fixture。 |
| 2026-10-13 | HTTP 测试依赖 | Starlette 1.8.0 的 TestClient 提示 httpx 接口弃用，当前锁定组合仍可运行 | HTTP 切片沿用 HTTPX 0.28.1 做 TestClient 与 TCP 流验证 | 后续统一升级 TestClient 适配和 httpx2，并重新验证跨平台流测试。 |
