# 统一图谱学习工作台

## 目标、范围与风险

- 将默认入口改成三栏工作台：左侧按图谱归集会话，中间目标创建/节点学习对话与关联内容，右侧图谱浏览和节点详情；顶部明确模式、图谱、会话和节点范围。
- 目标按钮仅切换创建模式，发送才创建目标并授权规划。继续复用既有规划 Agent、动态卡片、确定性确认和发布边界。
- 查看节点不切换会话范围；“开始学习”新建节点会话并由本次点击授权首轮讲解，“继续对话”恢复独立历史。新会话共享节点教材、题目和成绩，不共享其他会话 transcript。
- 已有目标/运行/旧节点会话保持可读；新增会话元数据持久化并校验不可变作用域。刷新、导航、切换标签只读，不重复生成。
- 学习包/练习放入中间内容标签，组件解释有明确来源并在相邻位置显示；不增加固定第四栏。
- 不包含：知识图谱领域模型扩展、功能快捷工具栏、图谱提案入口改造、资料绑定规则/反馈体系改造、登录/长期记忆/付费模型调用。旧资料与提案能力保留在兼容入口，不删除数据。
- 风险：工作树已有规划 Agent 与 Skill 未提交变更，原样保留并基于它们增量实现；前后端作用域漂移、迟到 GET 覆盖、创建响应丢失/自动重复请求、旧历史丢失为主要回归点。
- 用户已授权本地实施与验证；不发布、不部署、不读取密钥、不调用真实模型。验证使用独立端口与数据库。

## 进度与决定

- [x] 读取现状、架构和规范，确认改造边界与执行计划。
- [x] 后端：新增持久会话目录、创建/读取接口、不可变作用域校验和旧学习历史发现；Python 测试覆盖重开、幂等和隔离。
- [x] 前端：统一工作台/导航/上下文/图谱浏览与独立会话，复用规划审核组件；浏览不影响学习范围。
- [x] 内容：教材与练习在主区打开，保留节点积累；会话草稿与解释来源明确。
- [x] 验证：构建、Python/Node、现有回归、新工作台浏览器旅程、窄屏和真实浏览器手工走查；只用 fixture/mock。
- [x] 文档：同步产品/架构/启动与测试说明，沉淀 history/learning，归档计划。
- 2026-10-16：统一的是界面，不是 transcript；持久会话目录是导航事实，运行历史仍由 AgentLoop 保存，节点学习事实仍由 learning/lesson repositories 保存。不重写已完成的规划 Agent 和 Skill 功能。

## 验收与交接

- 验收旅程：点击创建目标不发生成请求 → 发送/澄清/确认 → 图谱审核发布 → 浏览节点不新建聊天 → 开始学习创建有界上下文的新对话 → 同节点再开对话历史独立而题目/教材共享 → 切换、刷新和继续均不发模型写请求。
- 必查：不同图谱/节点不能复用受管理会话；请求不确定时保留原身份显式恢复；切换会话草稿保留；右侧浏览与顶部会话节点区分；375/768/1440px 可用。
- 已执行的命令及结果见下。
- 真实模型内容质量不属于本次 fixture 验收，保留既有验收边界。

## 实现边界与主要文件

- `application/conversations.py`、`infrastructure/conversation_persistence.py`：持久 learning/general 元数据、按目标派生 planning、只读发现旧 runner/teaching；新建客户端 UUID、同指纹201、冲突409。目标创建指纹与 planning state 同事务保存；所有模型调用在事务外。
- `presentation/http.py`、`bootstrap.py`、`application/agent/loop.py`：官方 real/业务 fixture 装配目录，所有写 run 路由入队前校验受管理作用域，提供公开只读 run 快照；底层无目录装配保持兼容。
- `frontend/src/workbench/{Workbench,Conversation}.tsx`、`workbench.css`、`main.tsx`：三栏及窄屏区域、URL/后退恢复、会话草稿、创建/首轮分层恢复、图谱浏览与会话焦点分离。旧列表在 `/library`，旧规划/学习页不删除。
- `AgentPlanning.tsx`、`RouteOverview.tsx`：嵌入规划、portal 当前方案、发布后留工作台、知识节点审核；独立页仍保留旧阶段展示。
- `LessonPanel.tsx`：按 conversation 隔离生成/解释子会话与初始 slot，节点教材和事件仍共享，解释紧邻具体来源；未传 conversationId 的旧页行为不变。
- `components.tsx` 的 compact 图谱自上而下排列，避免右栏缩成不可读横链；原画布默认行为兼容。
- `planning_agent.py`、`planning_generation.py`、`skills/goal-planning/SKILL.md`：知识地图优先，成果/预算不是必填问卷，仅为真实前置连线。不扩展数据库层的关系类型。
- `tests/test_conversations.py`、`frontend/tests/workbench.spec.ts`：10个后端用例、11个新工作台旅程；原独立规划/付费 opt-in 浏览器脚本的列表入口改为 `/library`。

## 审查与修正

独立只读审查发现并修复三项边界，均有对应工作台回归：

1. 首轮4xx拒绝不能吞掉完整输入或提示；先保存会话草稿，429保留原命令，只有确认接收且草稿未变化才清空。创建等待期间的新草稿不会被迟到响应删除。
2. 创建响应丢失后，已发现目标不能从 fallback 启动替代首轮；匹配的待恢复对象先阻止替代入口，显式恢复原创建与 request_id/expected_version。
3. 旧 runner 节点会话续问沿用 runner；不能在显示旧历史的同时静默改成 teaching，导致模型丢失同模式历史并扩大工具权限。

额外修正：URL 中图谱与保存会话冲突时明确拒绝；教材/练习 run 不渲染成普通聊天；分离 label/textarea，避免重挂载后的初始文本污染可访问名称；创建恢复测试等待写响应落定再读，避免把仍在处理误当响应丢失。

## 验证结果（2026-10-16）

- `npm.cmd run ci`：通过，231 Python / 19 Node、import boundaries 与仓库检查。Windows symlink 平台跳过、Starlette httpx 弃用告警和既有 graceful shutdown SSE CancelledError 日志存在，均不导致测试失败。
- `npm.cmd run check:web`：TypeScript 与 Vite production build 通过。
- `npm.cmd run eval:offline`：20/20 fixture 用例通过，不代表真实模型质量。
- 完整 `npm.cmd run test:e2e --workspace frontend -- --reporter=line`：77/77通过；独立 web/API 端口5185/8015、专用 `.local` fixture 数据库，阻止浏览器外连，不读取日常数据库。
- 浏览器走查后仅调整 compact 画布、视口高度和内容滚动；相关 `tests/workbench.spec.ts tests/p0.spec.ts` 13/13再次通过，web build再次通过。后端与其余业务未变化，不重复整套 CI。
- Enso 浏览器使用另一份独立 fixture 数据与5186/8016：UI创建目标、确认、生成、发布、浏览节点、新建学习对话全程走查；未调用真实模型。
- 额外 Chromium 1440/768/375px 截图检查通过：页面无横向溢出，窄屏视口高度适配、输入可见，无页面异常或外部请求。截图与数据库只留忽略的 `.local`，不提交。
- 文档骨架、新增/修改的本仓库链接与 `git diff --check` 通过；规格第16节保留的19条“相对原仓库根目录”源码链接不属于本仓库文件，本次不改写为本地实现引用。未部署、未提交Git，既有工作树改动保留。

复现浏览器测试时设置 `LEARNGRAPH_E2E_WEB_PORT`、`LEARNGRAPH_E2E_API_PORT` 和新的 `LEARNGRAPH_E2E_DATABASE_PATH`，避免日常端口/数据。使用前台 PowerShell 工具运行；本环境显式后台命令曾立即返回空结果，不计作测试成功证据。

## 未扩大范围与后续限制

- 仍为小型无环 prerequisite 图；没有 hierarchy/related 关系、任意图谱持续展开、自动修改已发布图谱、本体融合或跨会话记忆。
- 原资料绑定、推荐和提案审核仍在兼容页，本轮不重做其交互或算法。新工作台保留已有题目判分及节点学习统计。
- 元数据/服务器历史可重开；输入草稿、子 session 映射和解释来源关联保存在当前浏览器 localStorage，不提供跨设备草稿/解释关联同步。
- 旧目标未保存创建时间：planning 目录用最早 run，完全无 run 时用 epoch；工作台新目标保存真实首次时间。没有会话分页、重命名、删除或多 API 进程支持。
- 本次改变了界面、规划提示词和 Skill，但未用真实模型重新验收知识结构与解释质量；历史付费样例不覆盖本次流程。付费 opt-in 保持兼容 `/library` 旅程，不宣称已覆盖统一工作台。

学习沉淀见[会话与学习积累边界](../../learnings/2026-10/20261016-conversation-is-not-learning-state.md)。
