# LearnGraph Lite 从零实现计划

## 目标、范围与风险

- 目标与验收标准：依据 docs/从零构建功能文档.md 从模板项目实现 LearnGraph Lite，最终达到 P0+P1 与 M5 交付：本地原生启动、无 Key 确定性测试、真实模型 smoke 证据、小型评估集/报告、README、复用许可记录、演示脚本、已知局限、分层依赖检查与内核独立运行证据。
- 包含：M0 工程与能力探针；M1 独立 AgentRunner/AgentLoop/fixture smoke；M2 目标与图谱；M3 P0 节点学习与练习闭环；M4A 资料引用；M4B 声明式学习页与解释幂等；M4C 图谱提案审核；M5 回归、真实评估与交接。
- 不包含：登录/权限体系、Android、语音、Docker/沙箱执行、长期记忆、企业级安全平台、任意代码执行。
- 风险及缓解：外部网络不稳定时，不编造 GitHub 或模型核验证据；先实现离线 fixture 与领域接口，并把真实模型/外部源码核验列为待补证据。阶段功能不以 fixture 冒充真实模型能力。
- 已有授权与需要确认的边界：用户已授权本地实现、测试和适当 commit；发布、部署、外部写入、真实供应商 Key 配置和破坏性操作需另行确认或凭已有环境能力执行。

## 进度与决定

- [x] M0：读取功能规格、仓库约束，确认当前仓库仍是模板态。
- [x] M0：建立执行计划、架构说明、开源复用记录和第一条 history。
- [x] M1：新增 agent_core，用 fake/fixture 模型测试普通回答、工具回注、未知工具、坏 JSON、预算和取消。
- [x] M1：新增应用层 AgentLoop，测试幂等、直接生成路径和 Runner 路径分离。
- [x] M1：新增少量纯领域规则，证明判分/图谱校验不依赖模型或 Runner。
- [x] M1：新增轻量 import 边界检查并接入 CI。
- [ ] M1：补 HTTP/SSE 最小生命周期、运行摘要与取消状态的真实路由测试；已完成无依赖公共生命周期与 SSE 投影离线切片，FastAPI 真实路由仍待接入。
- [x] M2：目标澄清、确认、图谱草稿/编辑/发布、revision 与规划离线 E2E。
- [x] M3：节点 Agent 学习、单选题生成、服务端判分、进度与下一步离线闭环。
- [x] M4A：TXT/Markdown 文档解析、分块、简单中英文检索、绑定、引用定位与空召回离线切片。
- [x] M4B：声明式学习页、固定组件、事件 ACK、解释任务幂等离线切片。
- [x] M4C：图谱提案、差异审核、接受/拒绝、base_revision 冲突离线切片。
- [ ] M5：全量回归、真实模型 smoke、20 例评估集与演示交接；已完成 20 例离线 fixture 评估集、可生成报告脚本和可复现 fixture demo，真实模型 smoke 与浏览器演示交接仍待完成。
- 2026-10-13：采用轻量 Python 分层骨架先完成 M0/M1 离线可验证切片；FastAPI/React/SQLite 仍按后续阶段引入，避免在模板态一次性拉入未验证依赖。
- 2026-10-13：已通过 GitHub raw 核验 nanobot 固定 commit 的 README、architecture.md、agent/loop.py、agent/runner.py 和 LICENSE；复用记录已更新。GitHub tree API 受 rate limit，未取得完整目录树。
- 2026-10-13：M2 离线切片完成目标草稿、最多两轮澄清、目标确认、8 节点候选图谱、草稿编辑、发布校验、revision 冲突与刷新恢复所需的内存仓库；HTTP/SQLite/前端 E2E 待后续阶段接入。
- 2026-10-13：M3 离线闭环完成节点 Agent 学习入口、单选题 Public/Private DTO、服务端判分、同题首次作答计分、重复题拒绝、旧内容版本拒绝、掌握度可升可降、按前置依赖/错题/时间预算推荐下一步；HTTP/SSE 与真实模型路径仍待后续接入。
- 2026-10-13：M4A 离线切片完成 TXT/Markdown/PDF-text 文档模型、分块、中文/英文关键词检索、目标/节点绑定、引用定位、空召回说明和旧引用版本拒绝；真实 PDF 二进制解析、SQLite FTS5 和前端原文页仍待接入。
- 2026-10-13：M4B 离线切片完成声明式 LessonPackage、固定组件 schema 校验、Markdown/组件可执行字段拒绝、事件 ACK 幂等、学习页事件不改成绩、正式作答复用 LearningService、解释 run 按 source_event_id/slot 幂等；前端渲染器和真实路由仍待接入。
- 2026-10-13：M4C 离线切片完成 GraphProposal、add/update node、add/remove dependency、pending/accepted/rejected/conflicted 状态、base_revision 冲突、接受才改图、拒绝无副作用、非法操作和成环校验。
- 2026-10-13：M1 生命周期补强完成 AgentLoop run_id 查询、seq 事件、运行摘要、usage 汇总、预算耗尽映射、取消终态和 presentation 公共 DTO/SSE 编码；当前环境无 FastAPI/Starlette，真实 HTTP 路由测试仍待后续依赖接入。
- 2026-10-13：M5 离线评估切片新增 evals/cases/offline-m5.json、evals/run.py 和固定报告，覆盖规划、图谱、学习、资料、学习页、提案和运行生命周期 20 个 deterministic case；报告明确真实模型 smoke 未运行。
- 2026-10-13：M5 fixture demo 切片新增 scripts/run-fixture-demo.py 和 docs/demo/fixture-demo.md，串起目标确认、图谱发布、资料引用、空召回、节点学习、练习掌握、下一步、声明式学习页与图谱提案；输出明确标记为 deterministic fixture demo。

## 验收与交接

- 已执行的命令及结果：
  - python scripts/check-python-boundaries.py：通过，输出 Python import boundaries passed。
  - python scripts/run-python-tests.py：通过，9 Python tests passed。
  - python -X utf8 scripts/run-fixture-smoke.py：通过，输出“工具结果已收到，继续学习下一步。”
  - npm.cmd run ci：M0/M1 通过，包含 Python 边界检查、9 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M2 后通过，包含 Python 边界检查、13 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M3 后通过，包含 Python 边界检查、18 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M4A 后通过，包含 Python 边界检查、21 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M4B 后通过，包含 Python 边界检查、25 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run ci：M4C 后通过，包含 Python 边界检查、29 个 Python 测试和 19 个 Node 模板工具测试。
  - python scripts/run-python-tests.py：M1 生命周期补强后通过，32 Python tests passed。
  - python scripts/check-python-boundaries.py：M1 生命周期补强后通过，输出 Python import boundaries passed。
  - npm.cmd run ci：M1 生命周期补强后通过，包含 Python 边界检查、32 个 Python 测试和 19 个 Node 模板工具测试。
  - python evals/run.py：M5 离线评估切片通过，输出 20/20 offline fixture eval cases passed，并生成 evals/reports/offline-fixture-report.md。
  - python scripts/run-python-tests.py：M5 离线评估切片通过，34 Python tests passed。
  - npm.cmd run ci：M5 离线评估切片通过，包含 Python 边界检查、34 个 Python 测试和 19 个 Node 模板工具测试。
  - npm.cmd run demo:fixture：M5 fixture demo 切片通过，生成 docs/demo/fixture-demo.md。
  - python scripts/run-python-tests.py：M5 fixture demo 切片通过，36 Python tests passed。
  - npm.cmd run ci：M5 fixture demo 切片通过，包含 Python 边界检查、36 个 Python 测试和 19 个 Node 模板工具测试。
- 未执行的检查、阻塞和遗留事项：
  - 真实模型 smoke 未执行，当前没有配置供应商 Key。
  - nanobot GitHub tree API 本轮受 rate limit，未取得完整目录树；已核验 README、架构文档、核心 Loop/Runner 文件与 LICENSE。
  - FastAPI/React/SQLite/P1 功能尚未实现。
  - M1 真实 HTTP/SSE 路由测试未执行；当前只验证应用层生命周期与 presentation SSE 编码，不声称已完成 FastAPI 路由。
  - M4A 当前支持 TXT/Markdown 和已抽取文本的 PDF_TEXT；真实 PDF 二进制解析与 SQLite FTS5 适配器未实现。
  - M4B 当前只有后端声明式包与事件用例；React 固定组件渲染器、HTTP ACK 路由和浏览器 E2E 未实现。
  - fixture demo 不是浏览器录屏或真实模型演示；M5 仍需真实模型 smoke 与最终演示交接材料。
- 必要的复验方式：
  - python scripts/run-python-tests.py
  - python scripts/check-python-boundaries.py
  - npm.cmd run eval:offline
  - npm.cmd run demo:fixture
  - npm.cmd run ci
  - 后续阶段按本计划逐项补充 E2E 与真实模型记录。
