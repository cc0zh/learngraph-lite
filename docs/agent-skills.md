# 应用 Agent 的 Skill

Skill 是可按需加载的流程指南，不是新 Agent、业务资料、权限或可执行插件。规划与节点学习共用一套加载机制，沿用原来的 AgentLoop / AgentRunner。

## 本页解决什么问题

- 模型怎样按需选择 Skill，用户怎样显式指定？
- 如何新增指南，它适用于哪些交互模式？
- Skill 为什么不能扩大工具权限或代替业务校验？

执行与恢复的整体流程见[Agent 机制](core/agent-loop.md)，其他能力见[核心机制总览](core/index.md)。

## 当前支持

- real 和业务 fixture app factory 默认从 `src/learngraph_lite/skills/` 加载启动快照；独立 echo fixture 不加载。
- `goal-planning` 适用于 planning；`concept-teaching` 适用于 runner、teaching 和 explanation。
- system 只包含可用技能的名称与描述。模型自行判断是否调用 `read_skill(skill_id)`，正文经工具结果进入上下文。
- 规划/节点聊天当前输入中的 `$skill-name` 可直接加载对应正文，只作用于本轮；中文可紧邻标记，如 `请用$concept-teaching解释当前概念`。
- explanation 的输入来自已保存学习包事件，不扫描其中的 `$skill-name`；仍可按需使用摘要和读取工具。历史、资料、目标字段、结构化答案不触发显式加载。
- 未知 `$skill-name` 保留为普通文本；已知但不适用于当前模式的显式技能会使本轮在模型调用前失败，不修改业务状态。

这是一种模型上下文的渐进披露，不是每轮重新读取文件。新增或修改技能后需要重启后端；运行中始终使用已验证的只读快照。

## 新增一份 Skill

创建 `src/learngraph_lite/skills/misconception-check/SKILL.md`：

```markdown
---
name: misconception-check
description: 用户混淆相邻概念或要求检查理解时使用，通过反例和比较澄清误区。
metadata:
  learngraph:
    modes: [runner, teaching]
---
# 检查概念误区

1. 先确认用户混淆的两个概念，不把猜测当成已知事实。
2. 用相同例子比较它们的适用条件，再提供一个反例。
3. 用一个简短问题检查理解，依据回答调整解释。
4. 正式练习和判分仍使用本轮已有的应用工具，不声称已保存或已掌握。
```

名称必须与目录名一致，最多 64 字符，仅使用小写 ASCII 字母、数字和单个分隔连字符。description 应说明何时使用；详细方法放正文。省略 `metadata.learngraph.modes` 时默认适用于四个交互模式；推荐明确缩小范围。合法模式只有 planning、runner、teaching、explanation。

然后重启应用，并在相应对话中输入：

```text
请用$misconception-check解释这两个概念有什么区别
```

无需注册新工具、修改路由或创建数据库表。模式元数据只控制技能展示，不改变工具白名单。自然选择依赖真实模型的判断；fixture 和离线测试仅证明加载/协议契约，不证明模型必然选择或解释质量提升。

## 限额与可信边界

| 项目 | 限制 |
| --- | --- |
| SKILL.md 文件 | 最多 16 KiB，严格 UTF-8（允许 BOM），YAML 使用 safe_load |
| 描述 | 非空，最多 1024 字符 |
| 正文 | 非空，最多 8 KiB UTF-8 bytes |
| 目录 | 最多 32 个有效技能，只扫描直接子目录 |
| 每模式摘要 | JSON 摘要最多 8 KiB，超限明确拒绝，不静默隐藏技能 |
| 每轮加载 | 最多 2 个不同技能，显式和工具加载共用限额 |

这些限额不能替代现有每次请求输入预算；必要上下文加正文仍超限时，模型调用被拒绝。read_skill 计入工具预算，后续模型调用仍计入父 run 的共享预算。重复加载不会重复记 usage，但重复工具结果仍占上下文与工具调用额度。

只允许维护者审核后放入仓库目录的技能。上传资料不会被当成 Skill。目录/SKILL.md 的 symlink、Windows junction/reparse point 和解析逃逸被拒绝；工具只接受技能 ID，不接受文件路径。不存在的目录提供空 catalog，已存在的非法目录/配置使启动失败，诊断不返回正文或绝对路径。

本版不执行 scripts、不读取 references/assets、不支持 always、自动安装或第三方技能市场。兼容元数据不授予能力。技能方法不能覆盖业务作用域、版本校验、人工确认/发布、私有答案隔离或输出 schema。

## 使用记录与历史

实际加载且本轮 `completed` 后，run 的 `output.skill_usage` 保存以下元数据，并通过 GET/SSE 返回；失败、取消或预算耗尽的回合不保证保存此字段：

```json
{
  "skill_usage": [
    {"skill_id": "concept-teaching", "content_hash": "<正文 SHA256>", "activation": "tool"}
  ]
}
```

activation 为 tool 或 explicit。hash 是正文原始 UTF-8 bytes 的 SHA256，描述/模式不参与该摘要；它用于辨认正文，不是权限凭证或完整配置版本。没加载技能时不新增此字段。元数据不含正文、服务器路径，也不并入资料 citation_map。

已完成回合的完整工具协议保存在 run 中；当前不保存失败、取消或未完成回合的完整协议。下一轮恢复历史时，应用层历史投影只替换旧 read_skill 的 tool 正文为历史提示，保留 assistant tool_calls、tool_call_id 和其他工具结果。旧持久记录保持原样；本轮使用技能需要重新选择/加载，不能把历史正文当成当前有效指令。

## 实现和验证入口

- `src/learngraph_lite/application/skills.py`：技能定义、提供者端口、本轮过滤/加载/usage、历史处理。
- `src/learngraph_lite/infrastructure/file_skills.py`：安全文件解析和启动快照。
- `PlanningContext.prepare()` / `LearningContext.prepare()`：组合基础契约、摘要、局部工具及结果。
- `PreparedRun.prepare_history`：可选历史投影，Loop 不内嵌技能业务。
- `bootstrap.py`：官方入口装配；底层 build_learning_loop 可选择注入 catalog，未注入时保留原行为。
- `tests/test_skills.py`、`tests/test_file_skills.py`、`tests/test_skill_integration.py`：加载/隔离/预算/历史、HTTP/SQLite 和事件来源回归。

运行 `npm.cmd run ci` 与 `npm.cmd run eval:offline`（非 Windows 使用 npm）。本版只指导交互 Agent；路线、练习、学习包的内层结构化生成使用独立消息，不自动继承外层技能。后续若要指导生成，必须显式传入适用于该用例的技能上下文，同时保持 schema、来源与保存校验。
