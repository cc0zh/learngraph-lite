# 安装与首次运行

本页目标：不配置模型 Key，先在本机运行工作台，并能指出前端、API 和数据库的位置。所有命令在仓库根目录执行。

## 准备环境

| 工具 | 要求与用途 |
| --- | --- |
| Node.js / npm | Node 22.12+；前端与文档站 |
| Python / uv | Python 3.13+；后端、锁定依赖和测试 |
| SQLite FTS5 | Python 的 SQLite 必须支持全文检索 |
| Git | 分支、代码审查与本地变更管理 |
| tar | 完整 Node 工具测试和源码打包需要；日常启动不需要 |

Windows PowerShell 使用 `npm.cmd`、`npx.cmd`，避免执行策略阻止 `.ps1` 包装器；macOS/Linux 改为 `npm`、`npx`。系统问题见 [Windows 指南](../WINDOWS.md)。

```powershell
node --version
uv --version
git --version
npm.cmd ci
uv sync --locked --group dev
uv run --locked python -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table probe using fts5(text)'); print('FTS5 OK')"
```

使用锁文件安装，不先升级依赖。上面的 FTS5 探针只操作内存数据库。

## 启动无 Key 工作台

```powershell
npm.cmd run dev
```

该命令通过 `scripts/dev.cjs` 同时启动 Vite 与 SQLite 业务 fixture API：

| 服务 | 地址 |
| --- | --- |
| Web | <http://127.0.0.1:5173> |
| 业务 API 健康检查 | <http://127.0.0.1:8000/api/health> |
| 业务 API schema | <http://127.0.0.1:8000/docs> |

页面应显示 **Fixture · 示例模式**。fixture 是确定性演示模型，用来理解流程和复现测试，不代表真实供应商的推理或教学质量。数据库默认 `.local/fixture.sqlite3`，刷新和重启不会清空业务积累。

不要用 `dev:api` 替代这个后端：它是独立的内存 echo 协议演示，不能支持完整工作台。单独启动业务 API 用 `dev:api:business`，单独启动前端用 `dev:web`。

## 走一遍最小学习流程

1. 打开工作台，点击“创建目标”，输入想学习的主题后发送。切换创建模式本身不创建目标。
2. 根据规划对话补充信息，阅读目标审核卡。由你明确确认目标，再审核并发布图谱；Agent 不能替你确认或发布。
3. 在右侧浏览节点，点击“开始学习此节点”建立独立学习对话。仅浏览其他节点不会切换当前对话作用域。
4. 在“对话／学习内容”之间切换，体验教材与练习。正式提交答案后观察反馈；阅读和事件 ACK 不计成绩。
5. 从工作台“我的资料”或当前目标/节点资料入口查看资料管理；图谱管理中查看草稿、来源与待审核提案。
6. 刷新页面，确认目录、已保存产物和 run 状态恢复。若写入结果不确定，先查询，再使用界面的显式恢复操作，不重新发送一个新请求碰运气。

当前页面入口统一为 `/`，通过查询参数选择目标、会话与工具。旧 `/library`、`/goals/:id/plan`、`/goals/:id/learn` 和资料书签只做只读导航转换，不是仍独立维护的页面。当前入口以 `frontend/src/main.tsx`、`workbench/navigation.ts` 为准。

## 第一次验证

```powershell
npm.cmd run check
```

这会执行仓库、Python、Node 门禁与前端构建，不调用供应商；浏览器回归需要另外安装 Chromium，见[测试与验证](testing.md)。只编辑 Markdown 时先运行 `npm.cmd run check:docs`；验证站点呈现还需文档构建。

停止服务用 Ctrl+C。后续接入 real、切换数据库和排查端口问题，见[运行模式与配置](configuration.md)与[排错](troubleshooting.md)。接下来阅读[核心概念](concepts.md)。
