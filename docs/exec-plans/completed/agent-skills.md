# 共享 Agent Skill 渐进加载

## 目标、范围与风险

- 用户授权：为当前 LearnGraph Lite 增加 Skill 支持；本地实现、检查与本次问题修复连续推进，不调用付费模型。
- 目标：规划和节点学习复用同一技能机制，摘要进入上下文，正文通过受限 read_skill 或当前输入中的 $skill-name 加载。
- 包含：可信仓库目录、YAML frontmatter、安全启动快照、场景过滤、有界加载、两份内置技能、使用元数据、历史协议处理、离线测试及说明。
- 不包含：新 Agent 引擎、脚本执行、自动下载/安装、第三方技能目录、资源文件读取、管理 UI、内层路线/题目/学习包生成指导。
- 保持现有 Runner、工具授权、目标/节点作用域、确认发布、私有答案和共享预算边界；Skill 是方法指南，不授予能力。
- 工作区已有规划功能的未提交改动；不恢复、不覆盖、不提交这些既有改动。
- 风险：历史工具结果携带旧技能正文；通过 PreparedRun 可选历史投影钩子替换正文、保留调用与结果配对。文件与内容只在显式装配时读取，运行中不访问任意路径。

## 进度与决定

- [x] 定义技能数据、加载端口、受限读取工具与本轮状态。
- [x] 增加安全 YAML 文件适配器和 goal-planning / concept-teaching 技能。
- [x] 在业务 app factory、PlanningContext 和 LearningContext 接入；保持普通 echo fixture 独立。
- [x] 处理旧 Skill 工具结果与使用元数据的持久/公共 DTO。
- [x] 测试加载、隔离、显式调用、预算、历史协议、HTTP/SQLite；运行 CI 与离线评估。
- [x] 更新使用说明、架构、开源复用、history 和学习记录，归档计划。
- 2026-10-15：采用 nanobot 的元数据→正文渐进披露思想，不复制源码或安装其产品。使用 PyYAML 安全解析，不自研 YAML 解析器。
- 2026-10-15：metadata.learngraph.modes 只缩小技能展示范围；默认可用于当前支持的交互场景。宿主仍决定本轮工具集合。每份正文最多 8 KiB，每轮最多加载 2 份，摘要总量最多 8 KiB。
- 2026-10-15：底层 build_learning_loop 保留可选 skills 注入，便于无文件依赖的内核/用例测试；real 和业务 fixture app factory 默认装配仓库内置技能。

## 验收与交接

- 新增 application/skills.py、infrastructure/file_skills.py、两份 skills/*/SKILL.md，以及 test_skills.py（34）、test_file_skills.py（15）、test_skill_integration.py（8），合计 57 个新增测试。
- 修改两个 Context、bootstrap、PreparedRun/Loop 可选历史钩子及 HTTP SkillUsage DTO；两个旧 HTTP 模型测试显式预期新增 read_skill，不放松原有工具白名单断言。
- 依赖：PyYAML 6.0.3，已核验安装包 metadata/LICENSE（MIT），uv.lock 仅新增该包；技能文件内容无外部源码复制。
- 初轮 219 Python 中一个旧 HTTP 工具集合断言失败，补准确预期后全通过。只读审查发现事件合成输入被误当成显式技能选择、Unicode 单词边界漏中文相邻标记；先新增两个 RED 回归，再按输入来源和 ASCII ID 边界修复，两类回归在最终 CI 通过。
- 最终代码验证：npm.cmd run ci 退出码 0（221 Python、19 Node、Python import boundaries、文档/仓库/Actions 检查），npm.cmd run eval:offline 20/20，git diff --check 通过。
- Windows symbolic-link 用例因系统权限不可用跳过；四类真实 Windows junction 拒绝及模拟解析逃逸/错误脱敏用例通过。有限关闭测试仍打印既有预期取消栈，Starlette TestClient 仍有既有弃用警告；不影响退出码与验收。
- 新增 docs/agent-skills.md、学习记录和 history；同步 README、架构、正式规格与复用记录；计划已归档。npm.cmd run check:docs、npm.cmd run check:repo 退出码 0，新增文档本地引用/计划归档与 git diff --check 通过。
- 未执行付费真实模型、前端 build/E2E 或内容质量对照；本次没有前端改动，不把 fixture 证明写成模型选择/质量提升证据。
- 官方入口新增技能文件后需重启；同一进程的技能内容为启动快照。
- 内层结构化生成上下文独立，第一版不声称技能能改变正式题目、路线或学习包生成内容。
