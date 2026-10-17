# Taste UI 实验性重构

## 目标、范围与风险

- 在独立分支 `experiment/ui-taste-rebuild` 重构 LearnGraph Lite 工作台；保留规划、会话作用域、显式提交、资料、学习包和请求恢复行为。
- 范围为 React 展现层、响应式布局、视觉 tokens 与相应 UI 测试；不改业务 API、不新增付费模型调用、不发布。
- 开始时已有后端、package.json 与验收文档未提交改动，全部保留，不纳入本次归属。
- 验收：TypeScript/Vite 构建；fixture E2E 回归；1440、768、390px 的首屏、图谱、对话和工具人工截图走查；键盘与 reduced-motion；文档检查。
- 风险：旧 UI 测试写死奶油橘色，仅更新过时视觉断言，不削弱作用域、触屏尺寸与只读导航断言。使用独立 fixture 端口/数据库，不写当前真实学习数据。

## 设计依据

- 使用 `design-taste-frontend`，方向 `one-motif` / One motif，seed `1435838436`；未重抽。
- 这是应用屏幕而非营销页：采用 skill 的内容盘点、方向抽取、单一概念、截图评审与去模板规则；不套展示页四图/视频/八个入场元素配额，不用假媒体或重复截图凑门禁。
- 盘点：本机单用户、中文学习意图、知识前置边、独立节点会话、人工确认目标、人工发布图谱、节点共享教材与练习、正式作答证据、资料原文引用、SQLite 恢复、fixture/real 明确分离。
- 内容论证：起点以可编辑输入证明从好奇开始；互动示例证明知识如何相连；真实图谱全景证明节点与前置关系；节点详情和独立对话证明浏览不改变学习焦点；资料工具证明来源可追溯。
- 概念句：在这里，LearnGraph 的「节点与前置关系」成为从品牌、起始预览到真实图谱与节点导航贯穿的视觉语法。
- Live thing：起点可切换知识示例、浏览节点并把示例填入目标草稿；只有显式发送才创建与调用模型。真实图谱继续使用 ReactFlow。
- 将抽取的多色字段比例收敛为冷白、sage 和森林绿，以 chartreuse 标记学习起点。系统本地字体替代抽到的网络字体，遵循本机应用无外连的既有测试边界。
- 起点 copy deck：标题「把好奇，连成知识。」；说明「从一个问题出发，与学习助手一起梳理知识，再沿着节点逐步深入。」；普通输入「你想弄懂什么？」；创建模式标题「一个想法，一张新图谱。」；示例明确标注而非冒充已有数据。

## 进度与决定

- [x] 检查仓库、创建分支、执行 skill baseline lint/inspect。
- [x] 重构全局 shell、起始体验、图谱全景、节点 rail 与响应式布局。
- [x] 补充行为与视觉契约测试，运行构建、E2E 与截图评审；最终尺寸修复后的 129 项全量复验通过。
- [x] 同步 README、history 与学习记录，归档本计划。

### 实施结果与审查修复

- 全局品牌栏保持 64px，采用原创节点 SVG、本地系统无衬线字体；fixture/real 在窄屏也保持可辨识。
- 深森林绿目录、冷白阅读区与 sage 节点区构成明确分区；重做按钮、表单、规划审核、Markdown、运行状态、练习和资料的共享视觉样式。
- `KnowledgePreview` 提供三个明确标注的静态示例；主题切换不写入业务数据，起草显式操作、保护未发送草稿，手机自动切区并把焦点转到可见节点。
- `KnowledgeOverview` 将真实图谱置于主区，纵向排列；右栏优先节点详情和开始学习，避免详情埋在缩略图与长列表下方。
- 对话历史单独滚动，输入保持可达；学习内容采用阅读优先布局，避免长教材被压成很窄的滚动条带。短窗口允许文档滚动。
- 只读审查发现并修复：当前侧栏会话 hover 低对比度、手机主题切换后的焦点丢失。另补触屏 hover、顶级模型状态错误挤压画布高度、React Flow attribution 对比度修复。
- 三宽度多页面截图复现图谱测量边界：平板全景 DOM 有节点但不可见。向画布节点显式提供与 Dagre 一致的固定宽高，修复后十八张截图序列完成，增加实际可见性回归。
- 未改业务 API、会话与请求持久化模型；未触碰原有后端和验收文档的用户改动。

### 截图评审

评分用于应用界面，不声称营销页画廊评分。skill 的四幅照片、视频与高数量持续动效配额不适用于本次应用工作区；若机械套用展示页规则，图片数量将限制 design 为 6.5，不能拿本次应用分数与该模式混比。

```text
ROUND 1
Seen in one second: 深绿目录与“把好奇，连成知识”。
Idea (one sentence): 节点与前置关系成为界面的视觉语法。
Live thing: 切换主题，浏览知识节点，显式起草目标。
Layout words by section: start=type / preview=graph / directory=list
Scores: design 7.3 · usability 7.2 · creativity 7.2 · content 8.0 → overall 7.3
Caps applied: 应用适配；不把应用界面伪装成营销照片页。
Top three problems:
1. mobile-fold：重复上下文头部占去近百像素；起点手机端隐藏重复头部。
2. desktop-fold：创建目标不够突出；提升为深绿主操作。
3. desktop-fold：预览控件 hover 与语义选中态冲突；按输入设备区分反馈并验证对比度。

ROUND 2
Seen in one second: 知识全景，但长横向图谱显得过小。
Idea (one sentence): 真实图谱而非占位图成为学习空间主体。
Live thing: 点击真实节点，只浏览而不改会话。
Layout words by section: overview=graph / node=detail / conversation=reading
Scores: design 7.5 · usability 7.4 · creativity 7.4 · content 8.0 → overall 7.5
Caps applied: 同上；没有外部媒体、虚构证明或持续自动播放。
Top three problems:
1. overview-1440：长链横向图谱难读；全景改纵向，并移除桌面重复缩略图。
2. node-1440：开始学习入口在折叠线下；把节点详情移到右栏前部。
3. chat-390：输入框被较长历史推走；聊天历史独立伸缩滚动，阅读标签保留较大阅读区域。

ROUND 3
Seen in one second: 标题、真实知识关系与明确的学习入口。
Idea (one sentence): 同一节点语法连接起始示例、真实全景与独立会话。
Live thing: 示例起草与真实节点浏览均可操作，写入始终显式授权。
Layout words by section: start=type / overview=graph / node=detail / chat=reading / documents=form
Scores: design 7.8 · usability 8.0 · creativity 7.5 · content 8.0 → overall 7.8
Caps applied: 应用适配，不宣称符合展示页图片配额。
Top three problems / remaining trade-offs:
1. overview-390：更多节点仍会缩小全景；保留缩放、适配视图和文字节点目录，未新增复杂布局器。
2. lesson-390：生成控制与版本说明较多；保持完整语义与只读边界，长内容需要滚动阅读。
3. documents-768：目标/节点绑定表单信息密度高；沿用原业务结构，本轮不改资料绑定模型。
```

## 验收与交接

- 基线 lint：0 FAIL / 0 WARN。
- 基线 inspector：3 FAIL（few-pictures、focal-point、still-page）、2 WARN（palette-cream、no-footage）；已查看桌面截图，主要问题是无图谱起点缺乏主体、大块空白、创建入口弱。
- `npm.cmd run check:web`：TypeScript/Vite 构建通过，多次修复后复验。
- 初轮全量 E2E：123 项中 121 通过，修复 attribution 对比度与过时标题断言后，相关 40 项通过。
- 审查修复后全量 E2E：128/128 通过。最后增加图谱可见性回归并修复显式几何后，使用独立 fixture 进行最终全量复验：**129/129 通过**，约 3.9 分钟。
- 阅读布局补充验证：独立 `lessons.spec.ts` 13/13 通过；与 Enso 用例紧邻运行曾有一次服务端 429（两运行名额仍占用）导致生成未受理，重启独立 fixture 后 13 项全部通过。未改准入规则、不以自动重发隐藏限流。
- taste lint：34 源文件，0 FAIL / 0 WARN。
- 最终 inspector：`--allow few-pictures,no-footage`，1440/768/390px：0 FAIL / 1 WARN（13 个元素入场，低于展示页建议值）。保留该 WARN：高频使用的应用不增加持续运动凑数量，reduced-motion 保持完整内容。
- 本地证据：`.local/ui-taste/final/` 为三宽度 inspector 截图/JSON；`.local/ui-taste/screens/` 为起点、全景、对话、学习内容、资料与图谱管理十八张截图，最后截图序列 `errors: []`。已检查三宽度首屏与主要业务页。
- 资源报告：没有下载外部照片、视频、字体或新增依赖；品牌 SVG 与知识示例为原创代码图形，非照片替代。示例内容是 RAG、Python、概率与统计的手写教学演示，界面明确标注，不冒充用户数据或模型输出。
- 真实付费模型 smoke、真实内容质量评估未执行；本次只验证 UI 与 fixture 行为，不改变原产品质量结论。
- `npm.cmd run check:docs`、`npm.cmd run check:repo` 与 `git diff --check` 通过。经用户追加授权，仅将本轮 UI、测试与配套文档单独提交到实验分支；不推送或部署，原有后端和验收改动保持未提交状态、不混入本次提交。
