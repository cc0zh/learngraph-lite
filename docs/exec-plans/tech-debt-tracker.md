# 技术债追踪

这里记录那些暂时不阻塞当前任务、但已经值得留档的技术债。

| 日期 | 区域 | 债务描述 | 为什么会存在 | 计划中的后续动作 |
| --- | --- | --- | --- | --- |
| 2026-10-13 | run 与上下文预算 | 六次共享模型调用、usage 和协作取消已实现；仍无 token/context/deadline 控制，run/root/session 与对话仍仅在进程内 | 当前切片先贯通共用生成与作答，避免同时扩展全部运行存储 | 后续补有限协议历史和 session/run 持久化；共享 gateway 增加保守 token 估算、实际 usage 与 deadline，验证刷新/重启与恢复失败任务。 |
| 2026-10-13 | 练习 grounding | 结构化练习当前 source_mode=general，无资料支持评估 | 本切片明确区分普通知识练习与资料型练习，私有答案不回注教学 transcript | 后续复用检索用例构建生成上下文，校验来源与原文支持；失败不得伪造资料型题目。 |
| 2026-10-13 | 真实供应商兼容性 | assistant/tool 配对、Pydantic 参数校验与官方 SDK MockTransport 测试已完成；尚无真实 endpoint smoke | 当前未配置外部 Key；节点入口已接上下文、推荐与资料两只工具，适配器使用 max_tokens，模型/endpoint 支持范围有限 | 配置模型后运行 smoke:real 验证普通回答和原生 tool calling，并自选执行 demo:learning-agent -- --real 验证业务调用；按实际模型需求考虑 max_completion_tokens/Responses API，不把离线协议证据写成供应商兼容结论。 |
| 2026-10-13 | 资料检索与版本 | 当前 tokenize + SQLite FTS5 不是规格中的 jieba/BM25；旧 upload_text 可同版本覆盖，来源通过 hash/位置检测失效 | 本切片先复用已有适配器连接 Agent 引用，不扩建整套资料管理 | 后续上传/PDF 切片完善文档版本及检索算法；回答/出题/学习页 grounding 增加语义支持评估，不能仅依赖有效 citation_id。 |
| 2026-10-13 | 图谱与学习快照同步 | 首次 HTTP 发布后初始化学习快照；发布与初始化仍是两次写入，中间退出可能留下未初始化状态，尚无成绩迁移 | 当前复用 planning/learning JSON snapshot repository；上下文继续拒绝不一致状态 | 后续补原子首次发布或可恢复的 create-only 初始化协议，验证中断/重启和成绩不被覆盖；图谱变更采用显式迁移，不能在只读工具里重置。 |
| 2026-10-13 | 资料型图谱规划与重试 | 图谱仅 general，有资料的目标拒绝生成；planning 和绑定重查非同事务。run 输出是提交快照，但没有持久生成 operation，提交后取消不能用旧 version 盲重试 | 当前先贯通可审核规划 HTTP，共用 Loop/预算，不扩建任务平台 | 资料型规划复用检索上下文并验证支持证据；补绑定一致性。取消后读取最新规划，版本变化需重新审核/新任务；结合 run 持久化完善恢复。 |
| 2026-10-13 | HTTP 测试依赖 | Starlette 1.8.0 的 TestClient 提示 httpx 接口弃用，当前锁定组合仍可运行 | HTTP 切片沿用 HTTPX 0.28.1 做 TestClient 与 TCP 流验证 | 后续统一升级 TestClient 适配和 httpx2，并重新验证跨平台流测试。 |
