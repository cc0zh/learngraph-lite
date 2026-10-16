# 讲解与正式练习分离及序列概念修正

## 目标与授权

- 用户要求修复真实复验发现的答案提前提示和 tuple 切片概念错误后提交；内部工具名可见可接受，不扩展为名称过滤任务。
- 不发起新的付费调用，不操作日常库、不改依赖、不部署/推送。保留上一轮真实原证据，修复后的模型语义效果仍待新的有界真实复验。
- 提交范围为本任务链的自然输入审查、真实复验及此次修复/回归/文档，不包括并行 README、文档站/核心机制页面及 docs-site 测试改动。

## 方案与验收

- 给工具提供宿主只读的当前协议上下文（不作为模型可填参数），将已讲解文本交给正式出题器作为避免复用的例子；保持原预算、来源、幂等与原子提交。
- 正式题仍保存在公共 output/题卡；教学模型工具结果只收到成功回执和题目 ID/来源模式，不再读取新题后续写其解法。create_lesson 仍能使用 ID，不删除组合能力。
- 给生成器加入演示/正式题分离约束，拒绝与已讲解题干完全重复的候选；这是有界精确重复保护，不伪装为通用语义等价判定。教学基础规则不讲解待答题的同数值等价解答。
- Python 列表/元组主题注入小型已核对参考：列表切片是新浅拷贝，元组切片不保证新对象，内容比较不用 is；不限于可选 Skill 是否被模型读取。
- 先补失败回归，再修实现；验证当前/历史讲解传递、工具结果隔离、重复候选拒绝/repair、不写半批、预算/重试/学习包组合与概念参考作用域。全套 Python 与受影响 fixture 浏览器回归不计为真实模型质量通过。

## 进度

- [x] 核对实现、已知证据与工作树提交范围。
- [x] 编写失败回归并实现聚焦修复。
- [x] 运行验证、更新质量/技术债/历史并核对聚焦提交范围；本地 commit 标识随交付回复提供。

## 结果

### 实现与审查

- `Tool.with_context` 为显式可选宿主参数，严格 schema 验证后才调用 handler；Runner 传入 immutable tuple，不在工具可填参数里开放 transcript。应用只选 assistant 正文，按最新优先保留最多 6000 UTF-8 字节，不包含私有生成/repair 工具消息。
- `GenerateExercise.generate` 接收内部 taught_examples，不改 HTTP 输入/持久模型/operation fingerprint；按钮路径也收集同 session/goal/node 最近八条记录内的 completed teaching/runner。示例数据进入生成器 JSON，基础指令禁止仅换变量名/拼接已算结果；归一化题干包含检测触发现有一次 repair，仍失败不写入题目/operation。
- `create_exercise` 只返回 ID/source_mode/notice 回执，公共 output.exercises 原样保留，可继续引用 ID 创建学习包。新增 `retain_tool_text` 仅在 teaching 启用，保留本轮工具前演示和末尾回执；不拼接历史，协议消息不改写，流式终态及 SQLite 重开均验证。
- `teaching_guidance` 的 Python 序列参考同时注入 tutor 与练习生成器，Skill 同步表达但不是唯一载体。固定代码验证 list 切片新浅拷贝、tuple 不保证新身份；不执行模型代码、不把 CPython 细节泛化到所有实现。
- 只读审查无 P0/P1，发现中英文紧邻时 Unicode 词边界漏匹配的 P2。先补 `Python列表与元组` 等失败用例，再改为英文标识符边界，覆盖 Python3/3.13 与中文紧邻、保留 Pythonic/playlist/C# 等负例。

### 验证

- 先观察失败：宿主上下文 API 不存在、生成请求没有 taught_examples、已演示题仍落库、主题参考模块不存在、工具前文本保留 API 不存在、按钮未带同会话讲解。对应修复后定向 24 项通过；后续加流式持久化与混合语言标题回归。
- `.venv/Scripts/python.exe -X utf8 scripts/run-python-tests.py` 最终 **248 通过**，退出 0；保留既有 Starlette/httpx 弃用提示、Windows symlink 条件跳过和关闭超时/CancelledError 日志，不把这些旧日志当新断言失败。
- `test:e2e` 选择 P0、学习包、workbench（同时匹配 single-workbench）、恢复、提案和工具状态，**54/54**、retries=0，独立 18811/18812、新临时 SQLite、UV 离线。没有 skip/retry，不是完整 88 用例的新结果；此前全套 87/88 的资料负载等待问题仍未定位，不能用本轮定向通过销账。
- `check:web` TypeScript/Vite build、`check:py-boundaries` 通过；真实脚本 `--list` 退出 0、列出 1 个用例，仅测试发现，无模型调用。单独真实测试 strict tsc 的 Node ambient types 限制沿用前轮记录，不安装依赖或假装覆盖。
- 重测 `node --test tests/tooling.test.cjs` **25/25** 通过；旧记录 README 标题失败已不再复现。当前测试比较生成文件与品牌 README 的替换结果，本轮没有 tooling/scaffold diff，故不能声称本次修好了该历史契约。质量页据当前证据更正，不沿用旧阻塞结论。
- 最终 `npm.cmd run check` **退出 0**，包含文档/卫生/Action/依赖边界、**248 Python、25/25 Node、前端 TypeScript/Vite build**；`docs:build` 和 `git diff --check` 另行通过，文档站保留既有大 chunk 提示。日志保留在忽略目录，不纳入提交。
- 验收证据日志在忽略目录；本轮无真实调用、无日常数据库读写。8010/5183/18681/18682/18811/18812 无任务残留监听。文档和 staged 检查随提交前收尾记录。

### 证据边界与提交范围

- 精确题干检查不能识别任意改写/数值等价关系，例子上下文有界；receipt 也不阻止模型自己编造同题或其他工具返回内容。这里结构性切断的是新题从 create_exercise 返回 tutor 的路径，不是宣称通用语义不泄漏。
- Python 参考是已核对指导，不是事实验证器；修前真实 P0 的 11 调用/48,046 tokens 不能当修后验证。本轮未进行付费复验，后续仍需有界授权；内部名可见已被用户接受。
- 本地提交包含自然输入脚本/守卫、测试状态标签与 demo 验收口径、两轮脱敏真实记录及此次业务修复、测试、架构/API/质量/历史/学习记录。明确排除最初已存在的 README、docs/.vitepress、docs/agent-skills、docs/index、docs/developer、tests/docs-site、docs/core 和对应并行 history/learning。
