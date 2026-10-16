# 运行模式与配置

先判断自己要验证什么，再选择启动入口。不要把配置成功、协议连通与内容质量混成一种“成功”。

## 三种入口

| 入口 | 模型 / 数据 | 适用场景 |
| --- | --- | --- |
| `npm.cmd run dev` | 确定性业务 fixture / SQLite | 本地业务开发与无 Key 体验 |
| `npm.cmd run dev -- --real` | 真实供应商 / SQLite | 经授权的真实内容体验，可能收费 |
| `npm.cmd run dev:api` | echo fixture / 内存 run | 独立 run、工具协议、取消与 SSE 示例 |

前两项同时启动 Web 与 API；独立业务 API 用 `dev:api:business` 或 `dev:api:real`。不要让两个 API 进程同时使用同一个 SQLite 文件。启动入口与依赖装配位于 `src/learngraph_lite/bootstrap.py`。

## 模型配置

后端显式创建 real gateway 时读取根目录 `.env`；已设置的进程环境变量优先。fixture 工厂不会因存在 Key 而切换到 real。

```dotenv
MODEL_API_KEY=<你的 API Key>
MODEL_NAME=<模型名>
# MODEL_BASE_URL=https://供应商地址/v1
```

`.env` 不提交。只使用有授权的资料；真实运行会把选中的业务上下文和检索片段发送给供应商。

| 变量 | 默认 / 行为 |
| --- | --- |
| `MODEL_API_KEY` | real 必需；未设置时可用 `OPENAI_API_KEY` |
| `MODEL_NAME` | real 必需，无默认模型 |
| `MODEL_BASE_URL` | 可选；未设置用 SDK 的 OpenAI endpoint |
| `MODEL_TIMEOUT_SECONDS` | 30；SDK 网络操作超时，不是 run 硬截止时间 |
| `MODEL_MAX_OUTPUT_TOKENS` | 4096；以 `max_tokens` 发送，并非累计 token 硬预算 |
| `LEARNGRAPH_DATABASE_PATH` | fixture 为 `.local/fixture.sqlite3`；real 为 `.local/learngraph.sqlite3` |

模型需要支持 Chat Completions、原生 function tool calling 与 `max_tokens`。不保证所有“OpenAI 兼容”供应商都可用；缺少 Key/模型名启动会失败，不静默退回 fixture。

`GET /api/model/status` 的 `configured: true` 只说明配置已装配，不能证明认证、连通性或生成质量。付费协议 smoke 和示例见 [API 手册](../api-guide.md)，执行前单独确认费用与数据授权。

## 数据和恢复

业务仓库保存目标、图谱、资料原文件与索引、题目和作答、学习包、提案、会话元数据和 run。浏览器 localStorage 还保存草稿与未确认命令标识；它不是数据库备份。

- 不让 fixture 和 real 共用日常数据库；实验使用新的 `.local/` 路径。
- 启动只为已发布且缺少学习状态的目标补初始化，不重置既有成绩。
- 重启把遗留 queued/running run 标记为 interrupted，不自动调用模型继续。
- 备份和迁移必须先停止相关写入，按 [可靠性手册](../RELIABILITY.md)操作；不要直接修改或删除日常数据库来修界面问题。

## Web、文档站与测试端口

业务 Web/API 默认 5173/8000；文档站独立使用 4173，预览使用 4174，不需要 Python 或 API。

浏览器业务回归默认也用 5173/8000，但拒绝复用已有服务。需要与日常开发并行时，同时设置 `LEARNGRAPH_E2E_WEB_PORT`、`LEARNGRAPH_E2E_API_PORT` 和新的 `LEARNGRAPH_E2E_DATABASE_PATH`，详见[测试指南](testing.md)。

所有本地服务绑定 loopback。Host 白名单和浏览器同源写检查不是登录或公网访问控制；不要通过监听公网、隧道或反向代理把当前应用当作多人服务。
