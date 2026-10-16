# 稳定性与恢复

本文件维护本地单用户、单 SQLite、单 API 进程的恢复操作；不是高可用部署方案。实现结构见[架构](ARCHITECTURE.md)，请求字段见[API 手册](api-guide.md)。

## 启动与健康

- 依赖、模型与分库配置见 [README](../README.md)。fixture 不请求供应商；real 缺配置启动失败。
- `GET /api/health` 检查服务响应，`GET /api/model/status` 只检查装配模式/配置，不证明供应商认证或连通。
- 同一数据库不得并行启动两个 API；业务 fixture 默认 `.local/fixture.sqlite3`，real 默认 `.local/learngraph.sqlite3`，E2E 用独立库。修改 LEARNGRAPH_DATABASE_PATH 时保留该边界。

## 故障处理

| 场景 | 当前行为与恢复方式 |
| --- | --- |
| POST 未送达或响应丢失 | 客户端保留完整输入和 request_id，先 GET run/会话；用户再显式同 ID 重发，不通过刷新猜测重做 |
| 429 准入限流 | 保留原命令与 ID；查询后显式恢复，不把它当输入错误清空，也不自动循环重试 |
| 确定性 409/422 拒绝 | 展示冲突/无效输入，保留草稿供修改；读取最新版本后重新审核，不盲重发旧写入 |
| SSE 断线 | 不取消任务；按 cursor 重连，先 snapshot，再补有界事件。超出窗口依快照恢复，不承诺无限 token 重放 |
| failed/cancelled/budget_exceeded/interrupted | 需要用户显式 retry：新 request_id + 原 retry_of_run_id，保留 root/session/作用域/原输入；completed 不可 retry |
| 刷新、导航或重启 | 只读取已保存状态，不自动发模型请求；启动把遗留 queued/running 标 interrupted，显式恢复未完成任务 |
| 终态持久化失败 | live 状态 interrupted 并停止新准入，不报告未保存结果成功；先修复存储问题，再重启把 durable 遗留状态转 interrupted |
| 发布/提案响应丢失 | 先只读核对当前版本与决定；不得假设没有写入并自动再发布/再接受 |
| 文档解析中断 | 启动将遗留任务标 failed/interrupted；显式 reparse 复用原 bytes，ready 不重跑。删除后晚到解析不得复活资料 |

普通重复请求仍返回原 attempt；解释事件 `(goal,event,slot)` 的业务复用返回最近 attempt，额外 request_id 不保存为别名。具体契约勿混用，见 API 手册。

## 取消、超时与关闭

- 全局最多两个 run，同 session 一个。取消先提交公开终态、唤醒订阅者并设置协作标志；阻塞线程实际退出前仍占用名额，晚到结果不覆盖终态。
- 本地 Uvicorn 给活跃 HTTP/SSE 连接最多 2 秒 graceful shutdown，然后 lifespan 停止准入、取消并等待 worker，再关闭 SDK。其他启动器也需有限的连接等待；Ctrl+C 不等同于可硬杀供应商调用。
- 默认共享六次模型调用、八步、十二次工具调用、每次 12,000 估算输入 token 与 120 秒协作 deadline。usage 汇总不是实际累计 token 硬上限；SDK 网络 timeout 不是 run 硬截止，无独立 tool timeout 或阻塞调用硬中断。
- 关闭测试可能出现 graceful timeout/CancelledError 日志，TestClient 当前也有 httpx 弃用警告；退出码与断言结果必须一并记录，不把有警告写成失败，也不承诺无告警。

## 数据一致性与证据

提案接受以同一 SQLite 短事务更新 planning/learning/proposal；初次 publish 与 ensure_goal 仍为两次写入，启动只补缺失学习状态、不覆盖已有成绩。生成保存前会复验来源，但资料与业务保存之间仍有并发窄窗口。不存在通用迁移平台或完整图谱/资料版本仓库，升级前应另行制定兼容与备份要求；不要通过删除日常数据库解决版本冲突。

公开 run/SSE 提供状态、工具活动、usage 与公共结果，不输出隐藏思维链。完整协议与 Skill usage 当前只保证保存 completed 回合，不能据失败 run 缺这些字段推断没有调用过模型。

离线/真实验证步骤见[测试指南](demo/stage-review-real-testing.md)，当前证据见[质量与验收](QUALITY_SCORE.md)，遗留项见[技术债](exec-plans/tech-debt-tracker.md)。CI/CD 与源码归档见 [CICD.md](CICD.md)。
