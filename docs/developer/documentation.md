# 维护文档与运行文档站

这套文档帮助读者启动项目、按能力理解业务，再独立修改功能。首页按“先跑起来”“理解核心机制”“修改与验证功能”分流；侧栏对应开始使用、核心机制、参与开发和参考手册。仓库 Markdown 与 VitePress 站点使用同一份源，不手工复制一套“网站版”。

## 本地阅读和预览

只阅读 Markdown 不需要安装任何工具。从[文档总览](../index.md)按相对链接进入；源码路径用行内代码，直接在编辑器打开，不伪装成站内页面链接。

运行站点只需要 Node.js 22.12+ 和 npm，不需要 Python、API、数据库或模型 Key。在仓库根目录执行：

```powershell
npm.cmd ci
npm.cmd run docs:dev
```

打开 <http://127.0.0.1:4173>。Windows PowerShell 使用 `.cmd`，macOS/Linux 改为 `npm`。开发和静态预览都只绑定 loopback，不配置公开部署。

```powershell
npm.cmd run check:docs
npm.cmd run docs:build
npm.cmd run docs:preview
```

生产构建输出到 `docs/.vitepress/dist/`；预览地址 <http://127.0.0.1:4174>。修改正文后需要重新构建，静态预览不会自动生成新内容。用 Ctrl+C 停止服务。

## 哪些内容放在哪里

| 内容 | 正式来源 | 维护方式 |
| --- | --- | --- |
| 阅读路径和首次使用 | `docs/index.md`、`docs/developer/getting-started.md` 等 | 按阅读目的分流，帮助完成第一次启动 |
| 按能力理解正常流程 | `docs/core/`、`docs/agent-skills.md` | 先解释怎么用、谁决定与失败怎么办，再链接实现与精确规则 |
| 开发概念和实现追踪 | `docs/developer/concepts.md`、`architecture.md`、`flows.md` 等 | 解释状态归属、依赖方向、提交点与代表性测试，不复制机制页的整篇说明 |
| 实现约束、协议和操作 | `ARCHITECTURE.md`、`api-guide.md`、`RELIABILITY.md` 等 | 核对当前源码，标清边界，不复制大段到多页 |
| 当前质量与未完成验收 | [质量与验收](../QUALITY_SCORE.md) | 只在这里维护当前结论；指南链接它 |
| 计划、变更与可迁移知识 | `exec-plans/`、`histories/`、`learnings/` | 保留历史证据的时间和适用范围，不当成当前能力 |
| 站点导航和样式 | `docs/.vitepress/config.mts`、`theme/` | 与 Markdown 阅读路径同步，禁止外部字体/分析脚本 |

配置显式排除仓库中除 `docs/` 与五个根级正式 Markdown（README、CONTRIBUTING、AGENTS、CLAUDE、SECURITY）以外的输入。站点不会把应用源码、`.env`、本地证据、依赖或数据库当页面构建。不要在正式文档中写入密钥和私人资料；构建不等于脱敏。

站点 URL 移除 `docs/` 前缀，例如 `docs/developer/concepts.md` 对应 `/developer/concepts.html`。根级正式文档保持 `/CONTRIBUTING.html` 等路径；根级漏洞反馈 `SECURITY.md` 使用 `/repository/SECURITY.html`，避免与 `docs/SECURITY.md` 的安全约束页面重名。Markdown 渲染钩子依据原文件位置解析相对 `.md` 链接，再转换站点 URL；仓库里的原链接不变。

## 新增或修改一页

1. 先确定读者要完成什么动作；机制讲能力与正常流程、概念讲归属、链路讲先后、参考讲精确协议，不按文件名堆清单。
2. 沿当前 UI、HTTP、应用服务、提交点和测试核对事实；旧规格和历史测试只能作为背景，不能证明当前实现。
3. 使用标准相对 Markdown 链接，如 `[核心概念](concepts.md)`。链接片段时核对实际标题，避免重复标题；链接检查不会验证所有锚点。
4. 若页面属于主要阅读路径，同时更新 `docs/index.md` 和配置中的侧栏。根 README 保持简短导航，不重复整份手册。
5. 模型生成、用户确认、程序评分、版本冲突和恢复机制必须说清。fixture/mock 与真实模型的质量证据分开。
6. 验证后按 [history 规则](../HISTORY_GUIDE.md)留记录；复杂任务在原计划里维护验收，不重复粘贴日志。

### 核心机制页的写法

使用“本页解决什么问题 → 一个贯穿例子 → 正常流程 → 谁决定、保存什么 → 遇到问题 → 修改与验证入口”的组织方式。示例沿用 RAG 检索学习，流程图使用普通文本，保证仓库 Markdown 和站点都能阅读，不为图示引入外部脚本。

机制页是解释入口，不是第二份字段手册：精确身份、版本和阈值链接领域概念，函数顺序和测试证据链接调用链，请求字段链接 API / OpenAPI，当前验收结论只链接质量页。调用链新增能力时同步补摘要和机制入口，但不改掉已有标题与页面地址，以保留书签和锚点。

不要直接把标题原文当作片段 ID：例如“谁决定，保存什么”渲染为 `#谁决定-保存什么`。新增跨页锚点后核对构建页面的真实 ID，并用浏览器测试验证；原因与轻量验证方法见[文档片段链接验证](../learnings/2026-10/20261016-docs-fragment-validation.md)。

## 本地搜索与验证

搜索使用 VitePress 本地索引，按中文分词，不需要外部账号或搜索服务。历史变更、执行记录和计划正文保留可浏览链接，但不进入默认索引，避免旧验收材料冒充当前行为；技术债与学习文章仍可搜索。开发预览的索引更新与生产构建分开验证。当前实现要求支持 `Intl.Segmenter` 的现代浏览器。

```powershell
npx.cmd playwright install chromium
npm.cmd run docs:build
npm.cmd run test:docs
```

`test:docs` 使用独立配置和 4174 静态预览，只测试文档，不启动业务 API。它覆盖桌面/窄屏导航、核心机制入口与页面、中文搜索、相对链接、机制与链路的片段定位和横向溢出。新装 Linux 浏览器可能需要 `--with-deps`。

`check:docs` 检查仓库 Markdown 骨架与本地文件链接；`docs:build` 检查页面编译与站内死链，不得关闭死链检查绕过失败。章节含义、命令准确性和历史口径仍需人工复核。GitHub CI 单独构建文档，并在 Linux 运行文档浏览器测试；不自动发布。其他验证选择见[测试与验证](testing.md)。
