# CI/CD 说明

当前包含基础仓库门禁、React 构建、fixture 浏览器回归与源码归档；不自动部署，不运行收费模型。

## 本地命令与 GitHub 流水线

| 入口 | 实际范围 |
| --- | --- |
| `npm run ci` | 文档骨架及本地 Markdown 文件链接、仓库卫生、Action pinning、CJS 语法、Python import 边界、Python/Node 测试 |
| `npm run check:web` | TypeScript 类型检查及 Vite production build |
| `npm run docs:build` / `npm run test:docs` | 同源 VitePress 构建与站内死链；独立静态站 Playwright 导航、中文搜索与窄屏回归 |
| `npm run check` | 上述两项，不含浏览器 E2E |
| `npm run test:e2e` | 业务 fixture/mock Playwright，不含 opt-in real-tests |
| `npm run eval:offline` | 确定性评估；不在当前 ci.yml 中自动运行 |
| `.github/workflows/ci.yml` | Windows/Ubuntu/macOS 基础门禁、前端及文档站构建、打包；仅 Ubuntu 安装 Chromium/运行业务和文档 E2E 及 Markdown lint |

Windows PowerShell 使用 `npm.cmd`。本地依赖准备与浏览器安装见 [README](../README.md) 和[测试指南](demo/stage-review-real-testing.md)；Node.js 至少 22.12，Python 至少 3.13。基础 `ci` 的 Node 脚本只用标准库；**前端构建/E2E 必须先安装 npm 锁定依赖**，不能把基础门禁的“无额外依赖”理解成整个应用不需要 npm 安装。

GitHub Actions 使用固定 commit SHA：setup-node 安装 Node 22，setup-python 安装 Python 3.13，uv 0.8.13 执行 `uv sync --locked --group dev`；随后 `npm ci --ignore-scripts` 安装前端与文档依赖。Python 测试由仓库脚本加载，并非 pytest。文档源、独立端口、搜索与维护见[文档维护指南](developer/documentation.md)；CI 构建不代表已部署。

## 供应链与发布

- `supply-chain-security.yml`：PR 依赖变更审查，PR/定时/手动 OSV 扫描。
- `release.yml`：手动生成归档、SBOM、provenance 和 GitHub Release，需要发布授权。
- `scripts/check-action-pinning.cjs`：远端 Action 固定 commit SHA，Docker 引用固定 digest。更多见[供应链安全](SUPPLY_CHAIN_SECURITY.md)。

本地 `npm run release-package` 仅生成 `dist/repo-metadata.tgz` 和 `dist/release-manifest.json`；不生成 SBOM/attestation，不创建 Release。再次执行只更新两项约定文件，不清空其他 dist 文件。源码目录无 Git 元数据时 SHA 为 unknown，GitHub 使用 GITHUB_SHA。

**制品是源码归档，不是已安装环境、桌面安装器或可直接部署的服务。** 当前应用导出保留 frontend、evals、package-lock.json、Python 锁文件与被文档引用的计划/history/学习记录；排除依赖、构建物、本地数据库/证据、凭据和浏览器产物。解包后仍需按 README 安装 Node/Python 依赖及浏览器，再运行检查。

`code-harness-init` 是保留的本地复制工具：当前源仓含 `frontend/package.json` 时复制应用源码及知识记录；普通空模板来源仍使用精简历史及文档 override 规则。不要把它当成已发布的独立通用模板产品；`--into` 不覆盖现有文件，也不合并 package.json。

## 当前限制

- 本地通过不等于已经运行 GitHub 跨平台矩阵、OSV 或签名发布；本次验证证据见[质量与验收](QUALITY_SCORE.md)。
- release 归档不是应用运行制品，尚未设计目标平台的部署或升级/通用 schema 迁移。需要发布时应先明确分发方式，再替换构建制品，而非另开绕过门禁的流程。
- 历史真实 P0 和 fixture 通过不替代当前工作台真实质量验收。默认门禁不读取密钥执行收费任务。
