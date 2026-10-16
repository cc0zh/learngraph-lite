# 当前质量与验收

更新于 **2026-10-16**。本页是当前版本状态入口；README、架构和测试指南只链接此处，不再维护各自的累计测试数量。历史计划保留当时证据，不自动成为当前版本结论。

| 区域 | 当前状态 | 证据 | 下一步 |
| --- | --- | --- | --- |
| 产品与架构 | 唯一学习工作台、专用规划 Agent、共享 Skill 与 React P0/P1 已接通 | 资料/原文、推荐、图谱编辑与提案已迁入工作台；旧 UI 只读定位，API 与历史数据保留 | 当前默认流程的真实模型质量验收 |
| 离线测试 | 前端及浏览器回归通过；总门禁仍有既有失败 | 236 Python、24/25 Node、87/87 fixture/mock 浏览器用例、TypeScript/Vite build | 先澄清模板 README 命名契约；不将 fixture/mock 通过推论为内容质量或供应商稳定性 |
| 文档与分发 | 文档已同步；源码归档工具有一项契约失败 | CLI 生成项目期望 README 标题为项目名，当前保留 LearnGraph Lite 品牌；与本轮前端路由无关 | 不删断言凑绿；归档不是安装器，分发/数据库升级策略另行设计 |
| 安全与恢复 | 本机单用户边界、显式恢复及公共结果隔离已测 | localhost/同源、私有答案隔离、run/SSE/usage、429 同 ID 恢复、提案原子迁移 | 无阻塞硬中断/独立 tool timeout/实际累计 token 硬预算；初次发布两写、跨资料生成窄窗口与完整历史版本仍有限制 |

## 本次离线证据

- `npm.cmd run check`：Python runner 236 通过，Node 24/25；`tests/tooling.test.cjs:462` 的 `/^# generated-app/` 与实际 `# LearnGraph Lite` 不符，总命令退出 1，未自动进入前端 build。该失败在本任务前调查已存在，本轮未修改脚手架契约或删断言。
- `npm.cmd run check:web`：TypeScript 与 Vite 通过。
- 浏览器全套：最终 **87/87 通过**，retries=0；使用新临时 SQLite、独立 18349/18350，`UV_OFFLINE=1 UV_NO_SYNC=1`，不复用日常服务或付费后端。包括原工作台用例、迁移后的资料/规划/提案/恢复用例及 9 项单工作台回归。
- 新覆盖：旧书签及历史 session 只读恢复，工具保留聊天与独立资料范围、显式清空范围、Back 取消后再次 Back/Forward、父/节点资料面板联动、迟到删除不劫持导航、推荐浏览零模型调用、练习熟练中文文案，以及 375/768/1024/1440 无横向溢出。解绑回归等待 DELETE 完成后再验证，避免读取旧关联的竞态。
- 本轮迁移过程中首轮全套有旧选择器/隐藏标签以及恢复等待失败，逐项迁移后在全新库重跑全部通过；没有增加 skip/retries，也没有把定向通过冒充全套通过。
- 离线评估此前有 20/20 证据；本轮未改后端与评估规则、未重跑生成评估报告，不把此前结果计作本次命令。
- `npm.cmd run check:docs` 文档骨架/本地链接、`git diff --check` 通过。
- 仍有已知 Starlette/httpx 弃用警告、Windows 符号链接条件跳过、关闭测试 graceful timeout/CancelledError 日志；Python runner 报告通过，总门禁失败原因是上述 Node 断言。浏览器存储损坏/配额故障不在本轮修复，仍见技术债。

变更与完整交接记录见[单工作台收敛计划](exec-plans/completed/workbench-only.md)；此前整理见[版本收敛计划](exec-plans/completed/version-consolidation.md)，复现见[测试指南](demo/stage-review-real-testing.md)。本地 Windows 证据不代表已运行 GitHub 跨平台矩阵、依赖扫描或签名发布。

## 历史真实证据与未完成项

2026-10-14 DeepSeek/deepseek-flash 协议 smoke、P0 HTTP 及一次真实 Chromium P0 旅程曾通过；浏览器旅程为 6 次调用、13317 tokens，原始脱敏证据留在本地。详细事实见[原实施计划](exec-plans/active/learngraph-lite-implementation.md)文首。这些结果**早于规划 Agent、Skill 和统一工作台改动**，不能当成当前默认流程的真实模型验收。本次没有付费模型调用。

付费浏览器脚本已迁移到唯一工作台，但未执行当前版本真实调用；当前工作台/Agent/Skill、P1 引用语义与教学内容、真实异常/取消/重试、多供应商及 20 例真实评估仍未验收，M5 最终交接未完成。技术限制与优先级见[技术债](exec-plans/tech-debt-tracker.md)。
