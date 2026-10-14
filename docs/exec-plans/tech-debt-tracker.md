# 技术债追踪

这里记录那些暂时不阻塞当前任务、但已经值得留档的技术债。

| 日期 | 区域 | 债务描述 | 为什么会存在 | 计划中的后续动作 |
| --- | --- | --- | --- | --- |
| 2026-10-13 | run 与上下文预算 | 已有六次共享模型调用/八步/十二次工具调用、12,000 估算输入 token 上限、usage 汇总、120 秒协作 deadline；同 session/同 mode 的 completed 回合可恢复完整 user/assistant/tool 协议历史（保留调用配对）。仍无阻塞调用硬中断、独立 tool timeout 或实际累计输入/输出 token 硬预算 | 当前按 UTF-8 bytes/3 估算并删除最旧完整回合，只在协作检查点检查 deadline；SQLite 恢复历史不自动继续未完成模型执行 | 保持单数据库单 API 进程；后续按风险补累计 token 预算和工具超时，必要时用可终止执行边界实现硬截止，不把 SDK 网络 timeout 当成 run 硬截止。 |
| 2026-10-13 | 生成内容支持质量 | 图谱/练习/学习包已输入实际检索片段，保存各自产物来源表；程序校验来源存在、版本/hash/位置，尚无真实模型的语义支持评估 | fixture 只验证数据流与引用边界；私有答案不回注教学 transcript | 暂停开发期间按阶段测试指南人工检查真实模型内容支持程度、错误引用、资料不足与组件质量。 |
| 2026-10-13 | 真实供应商兼容性 | assistant/tool 配对、Pydantic 参数校验与官方 SDK MockTransport 测试已完成；尚无真实 endpoint smoke | 当前未配置外部 Key；节点入口已接上下文、推荐、资料工具与显式 teaching 生成工具，适配器使用 max_tokens，模型/endpoint 支持范围有限 | 配置模型后运行 smoke:real 验证普通回答和原生 tool calling，并自选执行 demo:learning-agent -- --real 验证业务调用；按实际模型需求考虑 max_completion_tokens/Responses API，不把离线协议证据写成供应商兼容结论。 |
| 2026-10-13 | 资料版本与解析边界 | 已实现上传、pypdf、jieba/FTS5 BM25、原文件重试及原子 ready；HTTP 文件固定 revision 1，旧 upload_text 可同版本覆盖，来源通过 hash/位置检测失效 | 本地单进程恢复足够用于作品；乱码检测仅 replacement/control chars 启发式，不能识别所有乱码；Markdown 仅 ATX 标题切块，无 OCR | 后续语义支持评估与 React 原文页；需要内容更新时重新上传/绑定，完整版本历史另行设计。若改为多进程部署再设计解析任务归属与恢复，不扩建队列平台。 |
| 2026-10-13 | 图谱与学习快照同步 | 发布与初始化仍是两次写入；启动/发布的 ensure_goal 已仅补建缺失学习状态，不覆盖已有成绩，尚无图谱变更后的成绩迁移 | 当前复用 planning/learning JSON snapshot repository；上下文继续拒绝版本不一致状态 | 后续补跨仓库原子发布与中断回归；图谱变更采用显式迁移，不能在只读工具里重置。 |
| 2026-10-13 | 生成提交与重试 | 图谱/练习保存前重查绑定与来源，document 和 planning/learning 非同事务，仍有校验后变更窄窗口。run 输出是提交快照，但图谱没有持久生成 operation，提交后取消不能用旧 version 盲重试 | 当前复用有界检索、Loop/预算与各 repository，不扩建任务平台；图谱仅保存当前版本 | 后续补绑定/业务保存一致性。取消后读取最新规划，版本变化需重新审核/新任务；结合 run 持久化完善恢复。 |
| 2026-10-13 | HTTP 测试依赖 | Starlette 1.8.0 的 TestClient 提示 httpx 接口弃用，当前锁定组合仍可运行 | HTTP 切片沿用 HTTPX 0.28.1 做 TestClient 与 TCP 流验证 | 后续统一升级 TestClient 适配和 httpx2，并重新验证跨平台流测试。 |
| 2026-10-13 | 学习页交互与解释质量 | 解释 HTTP 已实现事件/slot、root、首个run及输入原子关联、并发复用与显式重试；尚无 React 学习包固定组件渲染/事件解释浏览器 E2E，也无真实解释质量证据 | 本切片保持 SQLite 单进程与固定组件，旧离线解释入口仅兼容 demo/eval | 按阶段指南真实测试 chapter/stepper/quiz 解释、重复/失败/重启，记录质量问题；后续接 React。额外 request ID 的业务复用不持久化别名，需扩展语义时再增加 alias 表。 |

## P1 与本轮验收边界

- React P0 节点对话、练习与恢复页面已实现，不能将学习包后端完成写成固定组件前端完成；资料原文页、学习包固定组件前端、提案 HTTP/前端仍未完成。M4C 已有离线提案领域用例，不等于公开产品入口。
- 当前配置隔离及审查修复后的 P0 基线为 119 Python/19 Node/build/11 E2E/20 fixture 与文档、仓库检查通过；结果维护在[执行计划](active/learngraph-lite-implementation.md)文首。mock 失败/完成 run DTO 仅证明 UI 和重试协议，不是供应商证据。
