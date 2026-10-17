## [2026-10-16 18:44] | Task: 按核心能力优化主文档站

### Execution Context

- **Agent ID**: `01a1444b-1601-70bf-8b08-3df02374d3ce`
- **Base Model**: `gpt-6.1-sol`
- **Runtime**: pi / Enso Code，Windows PowerShell

### User Query

> 参考 CountBot 文档的组织方式优化主文档站，补齐核心机制入口，降低阅读长调用链的门槛。

### Changes Overview

**Scope:** 文档内容、VitePress 导航与文档浏览器回归；不改变应用业务逻辑，不迁移站点框架或引入外部服务。

- 首页提供“先跑起来”“理解核心机制”“修改与验证功能”三条路径；导航拆成开始使用、核心机制、参与开发、参考手册。
- 新增核心机制总览及规划审核、节点学习、资料引用、学习包解释、Agent 执行恢复五篇指南，连接既有 Skill、概念、API 与调用链。
- 调用链的六条路径补流程摘要；概念、架构与 Skill 补读者问题。原页面地址和原调用链标题保留。
- 文档维护指南明确解释页与精确参考的分工；当前验收结论仍只维护在质量页。
- 扩充浏览器回归，覆盖机制入口、全部机制页、中文搜索、片段目标、旧地址和窄屏溢出；全角逗号锚点问题由新增断言发现并修正。

### Design Intent

把“理解能力如何工作”与“追踪函数及协议细节”分开，让新人先建立流程与权限边界，再按需深入源码。精确字段、评分阈值、测试证据和当前状态继续链接正式来源，避免维护第二份手册。

锚点验证涉及可迁移的链接契约与 Unicode 标点陷阱，单独沉淀为[文档片段链接验证](../../learnings/2026-10/20261016-docs-fragment-validation.md)。

### Files Modified

- `docs/index.md`、`docs/core/`、`docs/.vitepress/config.mts`
- `docs/developer/flows.md`、`concepts.md`、`architecture.md`、`documentation.md`（同目录）
- `docs/agent-skills.md`、`README.md`
- `tests/docs-site.spec.ts`
- `docs/learnings/2026-10/20261016-docs-fragment-validation.md`

### Validation

- `npm.cmd run check:docs`：文档骨架与本地 Markdown 文件链接通过。
- `npm.cmd run docs:build`：站点编译和死链检查通过；保留构建输出中的大于 500 kB chunk 提示，不通过关闭检查绕过。
- `npm.cmd run test:docs`：13/13 通过，覆盖桌面入口、五机制页、中文搜索、站内片段及真实定位、旧页面地址、390px 导航和横向溢出；测试输出桌面、平板和手机截图供走查。
- `git diff --check`：通过；只读内容审查未发现未解决的能力或验收口径问题。
- 只验证文档站，不运行业务 API 或付费模型，不新增产品质量验收结论。
