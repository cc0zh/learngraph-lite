# Windows 使用说明

## 环境与命令

使用 Node.js 22.12+（含 npm）、Python 3.13+、uv 和 Git。打包与完整 Node 工具测试使用系统 `tar`；先确认工具可用：

```powershell
node --version
npm.cmd --version
git --version
tar --version
uv --version
```

不需要 Bash、rsync 或 Perl。基础 Node 仓库检查仅用标准库，但 React 应用/构建和浏览器测试需要 npm 依赖：先运行 `npm.cmd ci` 与 `uv sync --locked --group dev`。通过 `npm.cmd run dev` 启动无 Key 业务 UI；`dev:api` 只是独立 echo 协议 fixture，查询/取消/SSE 示例见 [API 手册](api-guide.md)。浏览器安装与完整验证见[测试指南](demo/stage-review-real-testing.md)。

从仓库根目录执行：

```powershell
npm.cmd run check
npm.cmd run release-package
```

打包输出 `dist/repo-metadata.tgz` 和 `dist/release-manifest.json`。再次执行会更新这两个文件，保留 `dist` 下的其他文件。源码压缩包没有 Git 元数据时，manifest 中的 `git_sha` 为 `unknown`；GitHub Release 流程使用 `GITHUB_SHA`。

## 命令入口

当前应用启动与模型配置以 [README](../README.md) 为准。保留的源码复制工具可通过 `node scripts/create-project.cjs --help` 查看；它不是额外的运行前置，不要求 `npm link` 或全局安装。应用归档与模板兼容边界见 [CI/CD](CICD.md)。

PowerShell 可能优先选择 npm 生成的 `.ps1` 包装器。使用 `npm.cmd`、`code-harness-init.cmd` 可避免执行策略对包装器的限制；cmd 中也可使用。macOS/Linux 使用无后缀命令。

`--into` 不合并已有 package.json；需要独立运行检查时使用 `node scripts/ci.cjs`。

## Windows 上执行 Agent 计划

模板源码仓库的 nono profile 是 macOS/Linux 可选扩展，不随新项目分发，也不适用于 Windows 原生进程。Windows 使用 Codex 自身的 Windows 沙箱，保留 `workspace-write` 边界；首次沙箱设置按客户端提示完成。

已安装并登录 Codex CLI 后，在受信任的项目目录运行以下 PowerShell 命令（把路径换成实际计划）：

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Get-Content -Raw -Encoding UTF8 docs/exec-plans/active/your-plan.md |
  codex.cmd exec --sandbox workspace-write -
```

通过 UTF-8 stdin 传入全文，避免中文编码和长命令行问题。此方式不提供 nono 的快照/回滚；运行前保留 Git 检查点，结束后审查改动。超出沙箱权限的步骤可能失败或需要后续授权，不承诺所有计划都可无人值守完成。不要把 nono 示例中的 `--dangerously-bypass-approvals-and-sandbox` 用到这个原生流程。

依据：[OpenAI, Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox)、[OpenAI, Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security)，核对日期 2026-09-26；本机 `codex exec --help` 也确认了 stdin 和 `--sandbox workspace-write` 参数。本次未启动真实模型任务。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 提示不能加载 npm.ps1 | 改用 `npm.cmd`；全局初始化命令使用 `code-harness-init.cmd` |
| 找不到初始化命令 | 重新执行 `npm.cmd link`，检查 `npm.cmd prefix -g` 输出的目录是否在 PATH，重新打开终端 |
| `git` 或 `tar` 无法运行 | 确认对应程序已安装并在当前终端 PATH 中；初始化需要 Git，打包及完整测试需要 tar |
| 目标与模板目录相互包含 | 选择模板之外的兄弟目录或其他磁盘目录 |
| 已有项目没有 npm scripts | 先运行 `node scripts/ci.cjs`，再按需将模板 scripts 合并到原 package.json |
| Git Bash 可用但 npm 命令仍失败 | npm 已使用 Node.js 入口，检查 Node.js 版本和报错，不需要切换 npm 的 script-shell |
