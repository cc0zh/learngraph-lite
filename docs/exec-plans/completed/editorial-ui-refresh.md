# 书页式学习工作台视觉重构

## 第二轮：EnsoCode 组件参考（2026-10-17）

用户提供实际 EnsoCode 截图并同意实施。沿用第一轮调色与业务边界，只参考组件组织和交互，不复制 EnsoCode 源码、不增加 IDE 功能。

- [x] 对照现有目录、标签页、输入和运行步骤，确认复用点与回归范围。
- [x] 统一三种对话入口的一体化 composer；改造缩进目录、紧凑 tabs 与可展开步骤。
- [x] 构建、组件专项、既有交互回归及多尺寸真实截图复查。
- [x] 更新本计划与同一 history，完成后重新归档。

### 参考与适配

- 截图的项目/会话树 → 本产品的目标/图谱/独立会话目录。保留全名可访问、原生展开和当前态，不新增虚假的搜索或筛选。
- 截图的工作区 tab → 对话/学习内容，保持节点会话作用域，补齐键盘及 tab/tabpanel 关联。
- 截图的底部一体输入 → 输入、作用域说明、查询、发送/停止组成同一控件。原标签和草稿恢复不变；Ctrl/⌘+Enter 作为显式发送，Enter 换行，中文组字期间不得误发。
- 截图的执行过程 → 用原生 details 展开真实工具步骤，默认紧凑；失败计数、主错误、停止/重试、未确认请求恢复不藏在折叠内容内。
- 不照搬紫色、供应商/模型选择、Code/Bot 模式、文件系统导航、拖动分栏或新后端功能；仍使用纸白/墨黑/橙色与系统字体。
- 风险：折叠会影响依赖旧 DOM 的测试、共享输入可能改变发送门禁、底部控件可能遮挡内容。以真实请求观察、IME/键盘测试、长输入与短屏可达性验证缓解。
- 第一轮验收作为本轮基线，不把过去的检查结果当作第二轮通过证据。此前用户未提交的后端和文档仍不触碰。

### 第二轮实施与验证

- `frontend/src/MessageComposer.tsx` 统一起点、目标规划与已保存会话三个入口；查询/停止/模式切换仅使用原有动作。Textarea 保持可编辑，表单与快捷键都检查发送禁用，快捷键额外拦截输入法组字，延迟响应不清除新草稿。
- `frontend/src/workbench/Workbench.tsx` 采用功能性 folder/chat 图标、原生 disclosure 和缩进目录；长名称保留 DOM 全文与 title，学习会话日期缩写，当前会话和查看图谱仍是不同入口。
- `frontend/src/workbench/Conversation.tsx` 使用紧凑 tabs，支持左右循环、Home/End、roving focus、双向 ARIA 关联及 Tab 聚焦可滚动面板，切换不发送请求。
- `frontend/src/components.tsx` 将真实工具步骤收进默认折叠的原生 details；摘要展示真实总数/失败数，主错误、停止/重试、请求恢复留在外面。未知工具继续显示通用中文标签，不暴露协议名作为 UI 标签。
- 本轮首次实跑定位到 ReactFlow 的 window 空格快捷键会 preventDefault，导致 summary 的 Space 失效；两个新目录/步骤 summary 仅对空格 stopPropagation，不取消原生默认动作、不禁用图谱键盘能力。参见[原生 disclosure 与全局快捷键](../../learnings/2026-10/native-disclosure-global-shortcuts.md)。
- 新增 `frontend/tests/enso-components.spec.ts` 共 9 例：失败/进行中步骤、独立错误与重试、目录键盘、tabs、三个 composer、IME/显式快捷键、disabled 草稿及 390×844/568×320 可点击目标。原有普通消息测试改用 textbox role，避免新增 icon submit 的同名 aria-label 造成定位歧义，未放宽请求/草稿断言。
- `npm.cmd run check:web`：最终 TypeScript/Vite 构建通过。
- 完整 fixture E2E：**113/113 通过（3.6m）**。之后补齐 tabpanel 可聚焦能力，最终相关 UI/组件/工具标签 **26/26 通过**；没有把两次运行伪称为一次最终完整运行。
- 最终 skill 源码 lint 为 0 FAIL / 0 WARN；真实渲染 inspect 在 1440/768/390 为 0 FAIL / 0 WARN，继续使用下方已有 app 适用性例外，不宣称通过营销站完整要求。
- 独立只读审查未发现可高置信归属于本轮的回归；未执行跨浏览器矩阵，实际自动化使用 Chromium。
- 截图已实看 1440/1024/768/390、展开步骤、手机完整 composer、390 目录与 568×320 输入。证据位于 `.local/enso-ui/final/` 与 `.local/enso-ui/inspect/`；首次批量截图残留上一尺寸的 tab 选择，已修正采集脚本并重新采集，不误认成运行态回归。
- 第二轮截图自评（应用适配）：design 7.9 / usability 8.2 / creativity 6.8 / content 8.0 → overall 7.8。缩略图仍靠缩放/完整节点列表补足；窄侧栏名称使用省略与全名访问；手机完整输入需要纵向滚动，不通过隐藏错误节省高度。未增加摄影、动画或虚构功能。
- 本地预览为 `http://127.0.0.1:5186/`，使用独立 `.local/enso-ui-reference-preview.sqlite3` 与明确 Fixture 标记；seed URL 保存在 `.local/enso-ui/seed.json`。截图的未绑定资料错误是真实 fixture 工具结果，不当作真实模型引用证据。没有更改生产数据、API 或后端；UI 交付时未提交/推送，后续本地提交按 history 中用户追加的授权范围执行。

## 目标、范围与风险

- 用户选择 B：参考纸白、墨黑、橙色的学习界面，保留当前功能、三栏职责和工作台导航，重做视觉系统、排版与控件状态。
- 包含：全局设计 token，品牌栏、学习空间目录、对话/学习内容、图谱侧栏，以及使用相同基础组件的资料、练习与图谱审核工具；桌面、平板、手机和键盘可用性。
- 不包含：后端/API/持久化改动、每日计划/时长统计、虚构完成率、品牌改名、外部字体或图片请求、支付/部署。
- 保持会话焦点与浏览节点分离，刷新只读、显式生成、未确认请求恢复、版本审核等行为不变。
- 风险：全局 CSS 影响工具与 ReactFlow，固定视口内滚动可能遮挡输入框；以既有 E2E、增加的布局回归和多尺寸截图检查缓解。
- 已有用户未提交的后端、文档与 package.json 等改动不纳入本任务，不提交、不覆盖。

## 进度与决定

- [x] 建立现状基线，确认工作台和工具组件的样式依赖。
- [x] 实现视觉系统与书页式三栏，检查窄屏和控件状态。
- [x] 构建、交互回归、多尺寸截图检查，修复本次引入的问题。
- [x] 完成文档与 history，归档本计划。
- 2026-10-17：方向为“目录—阅读页—旁注”。主底色 #f7f5f0、正文 #181816、强调 #ea4c16；小号橙色文字和白字按钮使用更深橙以保证对比度。标题宋体、正文系统黑体，不增加网络字体依赖。
- 2026-10-17：design-taste-frontend 明确不面向 dashboard/app。本次采用其排版、色彩比例、去装饰与真实截图复查方法，不抽营销站构图，不要求四张图片、展示站标题尺度或八个滚动动画；功能性图谱线、表单边界保留，状态提示不是装饰性眉题。动效仅用于控件反馈，尊重 reduced-motion。
- 2026-10-17：字族按角色分工，Latin 标题 Georgia、中文标题系统宋体回退，正文 Segoe UI / 系统中文黑体。避免先选 SimSun 导致 Latin 等宽；不把浏览器返回的 CSS 字族名误当成所有中文字形都来自第一字族。
- 2026-10-17：只读审查提出短屏风险，新增用例先复现 568×320 下输入框下缘超出视口，再用 max-height:600px 的文档纵向滚动模式修复；不通过隐藏操作或减少触控面积解决。

## 受影响文件

- `frontend/src/styles.css`：颜色/字体/尺寸 token、控件与状态、阅读和基础工具样式；鲜橙与深橙分别承担标记和可读文字/按钮角色。
- `frontend/src/workbench/workbench.css`：贯穿式目录、中心阅读区、旁注式图谱、手机区域切换、短屏滚动。
- `frontend/src/main.tsx`、`frontend/src/workbench/Workbench.tsx`、`frontend/src/workbench/Conversation.tsx`：文字品牌、导航当前态、范围信息顺序与精简空态标题；业务事件处理未重写。
- `frontend/src/components.tsx`：真实图谱去点阵背景，保留连线、缩放和选择；只有图谱使用 data-ui 例外，没有给整个应用加该属性来绕过测量。
- `frontend/src/documents/`、`frontend/src/lessons/`、`frontend/src/proposals/proposals.css`：共用视觉 token；去紫蓝、装饰眉题和卡片阴影，保持原有数据、操作和语义状态。
- `frontend/tests/editorial-ui.spec.ts`：16 个新增用例，涵盖三尺寸横向几何、44px 控件、颜色、只读导航/刷新、独立会话、长标题、reduced-motion 与短屏输入可达性。
- [短屏布局学习笔记](../../learnings/2026-10/short-viewport-workbench.md)：固定视口与内部滚动的可迁移陷阱。

## 视觉复查

以下分数是基于截图的应用界面自评，不是严格营销站评奖分数；摄影/营销标题/滚动动画的 caps 不适用于本任务。未随机抽方向，无 seed、无重抽。

### ROUND 1

- Seen in one second：宋体学习标题，左右两条辅助阅读区域。
- Idea：把本项目的图谱—节点—独立会话关系，表达为目录—阅读页—旁注。
- Live thing：点击真实节点浏览，明确开始独立学习或恢复指定会话。
- Layout words by section：目录=缩进索引 / 中区=阅读与输入 / 右栏=图谱与节点注释 / 工具=表单与原文。
- Scores：design 7.2 · usability 7.0 · creativity 6.8 · content 8.0 → overall 7.1。
- Caps applied：不采用 app 范围之外的图片/营销尺度/入场动画项；不把功能性状态提示当装饰眉题。
- Top three problems：手机消息缩进挤窄正文（learning-390，移除该缩进）；学习内容上方控件与状态过松（content-1440，收紧标题、版本标签和运行提示）；目录主要入口缺少明确表面（round-1 desktop，修正样式优先级）。

### ROUND 2 / 最终复查

- Seen in one second：学习主题为主，橙色只指示当前位置与操作。
- Idea、Live thing、Layout words by section：沿用 ROUND 1，并完整保留真实业务范围。
- Scores：design 7.6 · usability 7.8 · creativity 6.8 · content 8.0 → overall 7.5。
- Caps applied：同 ROUND 1，未声称营销站完整流程/评奖达标。
- Top three problems：已修复横屏输入裁切（short-568 截图可见完整输入框及操作）；图谱节点多时缩略图文字仍偏小，保留可缩放画布与相邻完整名称列表；运行步骤和恢复说明较密，仍完整保留，不用隐藏错误美化截图。后两项是保留能力的密度取舍，不是阻塞。
- 已查看 1440/1024/768/390 布局，以及学习正文、资料工具、图谱管理、空态和短屏输入截图。独立截图保存在 `.local/ui-editorial/final/`，skill 最终结果保存在 `.local/ui-editorial/final-inspect/`；本地生成物不入 Git。

## Skill 检查适用性

- 最终 lint：`node <skill>/scripts/lint.mjs frontend/src`，0 FAIL / 0 WARN。
- 最终 inspect：针对已保存 fixture 学习会话，在 1440/768/390 下为 0 FAIL / 0 WARN；显式使用 `--allow few-pictures,focal-point,still-page,no-footage,palette-cream`。
- `few-pictures` / `no-footage`：这是实际学习应用，没有真实封面/摄影/视频，不为凑数量增加装饰或外部资源。
- `focal-point`：界面标题按长期阅读和工具效率设计，不采用占屏营销标题。
- `still-page`：没有滚动入场编排，保留控件按压/悬停/焦点反馈和实际运行状态；reduced-motion 不隐藏内容。
- `palette-cream`：保留用户参考及讨论确定的纸白 #f7f5f0，不随营销站色族偏好改色。深橙文字、次要文字仍通过可读性检查。
- `box-shadow:none` 的 lint 行内注释只用于移除 ReactFlow 自带阴影，不是保留阴影的豁免。
- 没有外部图片/视频/字体，没有版权素材或摄影替身需要替换。预览 RAG 节点、教材与会话只属于独立 fixture 数据库，页面明确标记 Fixture，不是新增的生产演示数据或能力证据。

## 内容与设计依据

- 项目真实材料：本地单用户、知识图谱、prerequisite 关系、目标审核、独立学习会话、节点教材、作答证据、资料引用、显式恢复、版本提案。没有课程封面或摄影素材，不添加占位图。
- 目录证明“我在哪里”：目标和会话层次清楚，当前会话有选中状态。
- 阅读区证明“我正在学什么”：当前范围可见，内容和操作有明确层级，正文可读。
- 图谱旁注证明“知识如何相连”：真实节点/关系可浏览，浏览与对话焦点同时保留。
- 实际交互沿用点击节点浏览、明确开始新学习或恢复已有会话，不添加演示用假交互。

## 验收与交接

- 基线：skill lint 45 FAIL / 10 WARN；默认工作台 inspect 7 FAIL / 3 WARN，截图发现紫蓝、多处小字号、手机顶部占用大与空态层次弱。图片、展示站尺度与滚动动画检查不适用于本次应用界面，其他排版/对比/溢出检查继续执行。
- `npm.cmd run check:web`：最终 TypeScript + Vite 构建通过。
- 全前端 `npm.cmd run test:e2e -- --max-failures=5`：103/103 通过，包括当时新增的 15 个 UI 用例与原有 88 个交互用例。
- 审查后新增短屏测试先 RED（568×320 的输入框下缘为 355px），修复后单文件 `npm.cmd run test:e2e -- editorial-ui.spec.ts`：16/16 通过（含 568×320、390×550、1024×500）。未将不同时间执行的用例合称一次 104/104 全量运行。
- 浏览器测试使用独立 fixture 数据库和本机端口；拦截非本机请求，不调用真实模型。覆盖生成/停止/重试、资料、学习包/练习/解释、图谱提案和恢复等既有行为。
- 最终代码另经只读审查；唯一高优先级候选为短屏裁切，已用回归先复现再修复。未发现其他高置信高优先级缺陷。
- `npm.cmd run check:docs` 与 `git diff --check`：文档骨架、本地 Markdown 链接和 diff 空白检查通过。
- 截图放入被忽略的本地测试产物目录，不将本机数据库、运行日志或截图基线混入源码。
- 无发布、外部写入或真实模型调用。
- 未做真实模型内容质量评估、跨操作系统字体像素一致性或生产部署；本次没有改变这些能力。
