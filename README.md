# LearnGraph Lite

**从一个想学的主题出发，把知识连成图，把学习落到每个节点。**

LearnGraph Lite 是一个本地单用户学习 Agent Web 应用。在同一个工作台中，与 AI 澄清目标、审核知识图谱、围绕节点展开独立对话，并逐步积累教材、练习与成绩。

知识地图优先 · Agent 辅助学习 · 本地 SQLite 持久化 · 无 Key 演示

[核心亮点](#核心亮点) · [学习旅程](#一次完整的学习旅程) · [快速开始](#快速开始) · [真实模型](#接入真实模型) · [技术架构](#技术架构) · [开发与验证](#开发与验证) · [文档导航](#文档导航)

> **早期开发版本，仅供本机体验、研究和开发，不适合生产环境。**
> 当前已接通工作台与主要学习流程，但离线演示和测试通过不等于真实模型质量已验收。最新证据与未完成项统一见[质量与验收](docs/QUALITY_SCORE.md)。

## 核心亮点

| 能力 | 你可以做什么 |
| --- | --- |
| **用图谱组织知识** | 从自然语言目标生成知识节点与前置关系，审核、修订后再发布。路线只是图谱的一种用法，不必把兴趣探索变成项目排期。 |
| **与 Agent 一起规划和学习** | 通过对话澄清目标、提出草稿；进入节点后，让 Agent 组织解释、生成练习和学习包。目标确认与图谱发布始终由你决定。 |
| **一个工作台，独立的学习对话** | 左侧管理图谱与会话，中间对话和阅读，右侧浏览知识图谱。教材、题目和成绩归属节点，重开对话不会丢失积累，也不会自动合并聊天历史。 |
| **带来源的资料学习** | 导入 UTF-8 TXT、Markdown 或文本型 PDF，绑定目标或节点；通过本地全文检索辅助问答，并从引用定位原文片段。 |
| **可阅读、可追问的学习内容** | 生成固定组件学习包，在“学习内容”中阅读教材、操作步骤和练习；围绕具体章节、步骤或题目追问，不把长教材塞满聊天气泡。 |
| **练习驱动的反馈** | 正式提交答案后获得判分与反馈，由确定性规则更新掌握度和下一步建议；阅读、点击或模型自述不会被当作学习成绩。 |
| **可恢复、可审核的过程** | SQLite 保存业务与运行状态。刷新只读取，响应丢失后显式恢复；Agent 只能提出图谱变更，接受或拒绝由用户审核。 |
| **按需加载的 Skill** | 规划与节点学习共用可信仓库内的流程指南，可自动按需读取，也可用 `$skill-name` 显式选择；Skill 不增加工具权限。 |

## 一次完整的学习旅程

1. **说出想学什么**：首页直接输入学习意图，点击“发送并创建目标”；不必先切换模式。Agent 围绕真正影响知识范围的信息进行澄清，不强制填写成果或时间预算。“普通提问”或左侧“新对话”打开不绑定图谱的聊天。
2. **确认目标、审核图谱**：在工作台查看目标草稿和知识节点，提出修改意见；明确确认目标，并在审核后发布图谱。AI 生成不等于自动发布。
3. **从一个节点开始**：发布后点击“选择节点开始学习”，在知识全景选择节点并开始；已有对话时优先提供继续入口。右侧也可浏览节点并点击“开始学习此节点”新建独立对话。浏览与继续只读取，不会自动调用模型或改变已有聊天范围。
4. **边读、边问、边练**：在“对话／学习内容”之间切换，结合节点教材、资料引用与练习理解概念。通过“当前节点资料”管理显式绑定，通过“我的资料”上传并阅读原文，始终留在工作台。
5. **根据反馈继续探索**：正式作答积累成绩，在学习内容中查看练习表现与下一步建议；查看推荐节点不会自动创建对话。需要调整已发布图谱时，进入“图谱管理”审核 Agent 提案后再接受变更。
6. **整理学习空间**：会话旁的删除入口清理本条对话，保留节点共享内容和成绩；主题目录支持“放弃目标”或“删除图谱”，确认后清理主题专属记录，原始上传资料与其他主题保留。任务尚未退出时拒绝删除；删除响应不确定时先查询，不因刷新自动重发。

```text
学习意图 → 对话澄清 → 目标确认 → 图谱草稿 → 用户审核发布
                                                ↓
审核图谱变更 ← 提案                         选择知识节点
                                                ↓
下一步建议 ← 掌握状态 ← 正式作答与反馈 ← 对话 / 教材 / 练习
```

**只保留一个学习工作台 `/`**：桌面端使用三栏，窄屏按区域切换。“我的资料”在主区打开上传、原文与绑定；“图谱管理”提供直接目标编辑、图谱生成/修订、节点和前置编辑、显式发布与提案审核。不再维护第二套首页、独立规划/学习页或固定三题问卷。

工作台起点提供检索增强生成、Python 基础、概率与统计三个交互示例。它们是静态知识关系演示，不是已有图谱或模型输出；点击“用此主题起草目标”只填入草稿，发送后才创建。替换已有目标草稿需要确认。已有图谱可在主区查看知识全景，点击节点只浏览，显式开始学习才创建独立对话。

工作台工具使用 `tool=documents|document|graph` 保存位置，保留原 `goal/session`；原文和绑定范围使用独立的 `source_goal/source_node`，不改变聊天焦点。返回对话、刷新和前进后退只读取。旧 `/library`、`/goals/:id/plan|learn`、`/documents[/:id]` 仅兼容定位到工作台，不新建会话、不调用模型，历史学习数据和业务 API 保留。

## 快速开始

### 1. 准备环境

| 依赖 | 要求 |
| --- | --- |
| Node.js | 22.12+，包含 npm |
| Python | 3.13+，SQLite 必须支持 FTS5 |
| uv | 用于安装锁定的 Python 依赖与运行后端 |
| Git | 用于获取与管理源码 |
| tar | 打包与完整 Node 工具测试需要，日常启动不依赖它 |

### 2. 安装并启动无 Key 演示

获取本仓库源码后，在仓库根目录执行：

```powershell
npm.cmd ci
uv sync --locked --group dev
npm.cmd run dev
```

> 以下命令使用 Windows PowerShell 写法，`npm.cmd` 可避免执行策略问题；macOS / Linux 将其替换为 `npm`。环境排错见 [Windows 指南](docs/WINDOWS.md)。

打开 **<http://127.0.0.1:5173>**，即可体验 fixture 模式。它使用确定性的演示模型，不调用真实供应商，页面应明确显示 fixture 标识。使用 Ctrl+C 停止服务。

| 服务 | 默认地址 | 说明 |
| --- | --- | --- |
| Web 工作台 | <http://127.0.0.1:5173> | Vite 前端，代理业务 API |
| 业务 API | <http://127.0.0.1:8000> | FastAPI，由 `dev` 联合启动 |

### 3. 了解数据存放位置

- fixture 模式默认使用 `.local/fixture.sqlite3`。
- 真实模型模式默认使用 `.local/learngraph.sqlite3`。
- 可通过 `LEARNGRAPH_DATABASE_PATH` 指定数据库；**不要让两种模式共用同一日常数据库**。
- 业务与运行状态保存在 SQLite 中；重启不会自动继续未完成的模型任务，需要查询状态后显式恢复。

## 接入真实模型

**此模式会向配置的模型供应商发送请求，并可能产生费用。** 使用前请确认供应商、数据处理要求与调用成本。

后端读取进程环境变量和仓库根目录 `.env`，进程变量优先。在根目录 `.env` 中配置以下内容，不要提交真实密钥：

```dotenv
MODEL_API_KEY=<你的 API Key>
MODEL_NAME=<支持 Chat Completions、function tool calling 和 max_tokens 的模型名>
# 可选：使用供应商提供的兼容接口
# MODEL_BASE_URL=https://供应商地址/v1
```

停止已运行的演示服务，然后启动：

```powershell
npm.cmd run dev -- --real
```

- 缺少 Key 或模型名会启动失败，不会静默退回 fixture。
- `/api/model/status` 的 `configured` 只表示配置已装配，不证明认证、连通性或内容质量。
- 当前通过 OpenAI Chat Completions 兼容接口接入；不承诺所有供应商及模型都兼容。
- 超时、输出限额、独立 API 启动与请求示例见 [API 手册](docs/api-guide.md)；付费 smoke 与人工验收见[测试指南](docs/demo/stage-review-real-testing.md)。付费调用不进入默认检查。

## 技术架构

前端负责工作台与可审核的学习产物，后端负责模型调用、业务规则、工具作用域和持久化。通用 Agent 内核与学习领域保持分离。

```text
Web · React 19 / TypeScript / Vite / React Flow
                       │ HTTP / SSE
                       ▼
FastAPI · 输入校验 / 公共 DTO / 流式事件
                       │
                       ▼
Application · 规划 / 会话 / 教学 / 资料 / 学习包 / 提案
              ├─ Domain：图谱校验、掌握度与推荐规则
              └─ Agent Core：模型与工具回合、共享预算
                       │ 通过端口接入适配器
                       ▼
Infrastructure · SQLite / FTS5 / 文档解析 / 模型网关
                       │
                       └─ OpenAI Chat Completions 兼容接口
```

```text
mini-learngraph4/
├─ frontend/                  React 工作台、图谱与学习内容
├─ src/learngraph_lite/
│  ├─ agent_core/             通用 AgentRunner、工具协议与预算
│  ├─ domain/                 学习领域纯规则
│  ├─ application/            用例、AgentLoop 与业务编排
│  ├─ infrastructure/         SQLite、文档与模型适配器
│  ├─ presentation/           HTTP / SSE 边界
│  ├─ skills/                 可信内置 Skill
│  └─ bootstrap.py            fixture / real 显式装配
├─ tests/                     Python 与 Node 工具测试
├─ evals/                     离线评估样例与报告
├─ scripts/                   启动、检查、演示与打包
└─ docs/                      架构、API、验收与版本化知识
```

完整依赖约束与一致性边界见[架构总览](docs/ARCHITECTURE.md)。Skill 的新增方式、模式和安全限额见[应用 Agent Skill](docs/agent-skills.md)。

## 当前边界与安全说明

- **仅限本机单用户**：后端没有登录功能。不要监听公网或通过隧道暴露；Host 白名单与浏览器同源写校验不是公开部署的访问控制。同一 SQLite 只支持一个 API 进程。
- **引用可定位，不代表语义已验证**：资料解析不支持 OCR；引用校验核对来源片段、版本与位置，不能证明原文支持模型的结论。
- **成绩来自正式作答**：阅读、事件 ACK、解释和模型自述不更新掌握度；初始基础自述也不是已验证能力。
- **会话历史不是长期记忆**：不同对话不自动合并 transcript，当前没有跨会话长期记忆系统；共享的是节点教材、题目和成绩等业务积累。
- **恢复需要明确操作**：刷新、导航和切换标签只读取；请求结果不确定时保留原标识，由用户显式恢复，不自动重复调用模型。
- **预算与事务仍有限制**：支持调用次数、估算输入与协作 deadline，但不提供阻塞调用硬中断或实际累计 token 硬预算。提案接受可原子迁移，初次发布与学习初始化仍是两次写入。
- **不把参考项目能力当作本项目能力**：当前没有 Android 客户端、实时语音、Docker 执行沙箱、第三方 Skill 市场或多协议 Provider 管理。

第一轮开始/继续/清理闭环已完成离线验收；下一步以代表节点核对内容的具体用途，并整理本人能解释的求职演示。教学内容可信度按当前任务边界暂缓，已有语义问题、更多真实样本和 20 例真实评估仍未完成，不因本轮通过而转绿或自动追加付费调用。详细状态见[质量与验收](docs/QUALITY_SCORE.md)，遗留风险见[技术债](docs/exec-plans/tech-debt-tracker.md)。

## 开发与验证

以下命令均在仓库根目录运行：

| 命令 | 用途 |
| --- | --- |
| `npm.cmd run check` | 仓库 / Python / Node 门禁与 TypeScript / Vite 构建，不含浏览器 E2E |
| `npm.cmd run check:docs` | 文档骨架与本地 Markdown 链接检查 |
| `npm.cmd run test:e2e` | fixture / mock 浏览器回归，首次需安装 Chromium，见测试指南 |
| `npm.cmd run eval:offline` | 确定性离线评估，不代表真实模型质量 |
| `npm.cmd run smoke:fixture` | 无 Key 内核与工具协议 smoke |
| `npm.cmd run demo:fixture` | 生成离线流程演示文档 |
| `npm.cmd run demo:learning-agent` | 无 Key SQLite 节点学习闭环演示 |
| `npm.cmd run dev:api:business` | 独立启动 SQLite 业务 fixture API |
| `npm.cmd run dev:api:real` | 独立启动真实模型业务 API，需要模型配置 |
| `npm.cmd run dev:api` | 独立内存 echo 协议 fixture，**不是工作台的业务后端** |

`npm.cmd run ci` 是基础门禁，不等于 GitHub CI 全流程。完整检查范围、浏览器环境与占位 release 制品限制分别见[测试指南](docs/demo/stage-review-real-testing.md)和 [CI/CD](docs/CICD.md)。

`demo:fixture` 会生成 [fixture-demo.md](docs/demo/fixture-demo.md)，离线评估会生成 `evals/reports/offline-fixture-report.md`；报告只声明各自覆盖的范围，不替代当前质量状态。

## 文档导航

新加入项目？从[文档总览](docs/index.md)选择“先跑起来”“理解核心机制”或“修改与验证功能”；按能力查询可直接进入[核心机制总览](docs/core/index.md)，需要实现细节再读领域概念与架构链路。同一份 Markdown 可通过本地文档站浏览：`npm.cmd run docs:dev`，打开 <http://127.0.0.1:4173>；不需要启动 API 或配置模型。维护与构建见[文档维护指南](docs/developer/documentation.md)。

| 文档 | 适合什么时候看 |
| --- | --- |
| [质量与验收](docs/QUALITY_SCORE.md) | 了解当前已验证内容、历史证据与未完成项，唯一当前状态入口 |
| [测试指南](docs/demo/stage-review-real-testing.md) | 复现离线回归、付费 opt-in 与人工验收 |
| [API 手册](docs/api-guide.md) | 查询规划、资料、练习、学习包、提案及运行协议 |
| [架构总览](docs/ARCHITECTURE.md) / [产品原则](docs/PRODUCT_SENSE.md) | 理解模块边界、依赖方向与交互取舍 |
| [产品规格](docs/从零构建功能文档.md) | 查看目标要求；不代表所有条目均已完成 |
| [应用 Agent Skill](docs/agent-skills.md) | 编写或调整可信内置技能 |
| [恢复与可靠性](docs/RELIABILITY.md) | 了解持久化、恢复与预算限制 |
| [技术债](docs/exec-plans/tech-debt-tracker.md) / [原实施计划](docs/exec-plans/active/learngraph-lite-implementation.md) | 追踪遗留风险与分阶段历史证据 |
| [开源复用](docs/references/open-source-reuse.md) | 查询来源、许可证与复用边界 |
| [Windows 指南](docs/WINDOWS.md) | 排查本地环境与命令问题 |
| [贡献指南](CONTRIBUTING.md) / [Agent 协作入口](AGENTS.md) | 参与开发，按任务查阅仓库规范 |

## 许可证与参考

本仓库代码基于 [MIT License](docs/license.md) 开源，许可原文位于根目录 `LICENSE`。

README 的组织与表达参考 [SunnyBoy-y/LearnGraph](https://github.com/SunnyBoy-y/LearnGraph)。本仓库以 **LearnGraph Lite** 为名实现本地单用户的轻量学习流程，不代表参考项目的完整实现或功能等价版本；功能与验收以本仓库文档为准。
