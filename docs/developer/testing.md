# 测试与验证

验证应回答“这次改动可能破坏什么”，而不是每次都执行全部付费流程。当前已验证范围统一见[质量与验收](../QUALITY_SCORE.md)，本页不维护累计用例数。

## 根据改动选择检查

| 改动 | 最小相关验证 | 交付前补充 |
| --- | --- | --- |
| Markdown 内容、导航 | `npm.cmd run check:docs` | `npm.cmd run docs:build`；人工检查命令和口径 |
| 文档主题、搜索或配置 | `check:docs`、`docs:build` | `npm.cmd run test:docs` 和桌面/手机走查 |
| 领域或应用逻辑 | 定向 Python 测试 | `npm.cmd run check`；按影响加浏览器/离线评估 |
| API / SSE / 恢复 | 相关 HTTP 和持久化 Python 测试 | `check` 与恢复浏览器回归 |
| React 业务交互 | `npm.cmd run check:web` | `check` 与相应 fixture/mock E2E |
| 提示词 / Skill / 模型协议 | 对应离线协议与场景测试 | 真实质量需单独授权评估，离线通过不能代替 |

所有命令从仓库根目录运行。Windows 用 `.cmd`；macOS/Linux 去掉后缀。

## 默认离线门禁

```powershell
npm.cmd run check
```

- `ci`：文档骨架/本地 Markdown 链接、仓库与 Action 固定版本、CJS 语法、Python import 边界、Python 和 Node 测试。
- `check:web`：TypeScript 检查与业务前端 production build。
- `check`：上面两者；不包含业务浏览器 E2E、文档站构建或离线评估。
- `docs:build`：所有文档页面的编译与站内死链检查，独立于基础门禁，在 GitHub CI 单独执行。

仓库 Python 使用自带加载器，**不是 pytest**。可先定向执行一个模块中的 `test_*` 函数，例如：

```powershell
uv run --locked python -c "import runpy; m=runpy.run_path('tests/test_learning_domain.py'); tests=[f for n,f in m.items() if n.startswith('test_') and callable(f)]; [f() for f in tests]; print(len(tests), 'tests passed')"
```

完整 Python 回归仍用 `npm.cmd run test:py`。新增测试需符合 `scripts/run-python-tests.py` 的发现方式：顶层、无需 fixture 参数的 `test_*` 函数。

## 业务浏览器回归

首次安装 Chromium，然后运行相关场景：

```powershell
npx.cmd playwright install chromium
npm.cmd run test:e2e -- --list
npm.cmd run test:e2e -- --grep "workbench:"
```

完整回归用 `npm.cmd run test:e2e`。Linux 首次安装常需 `npx playwright install --with-deps chromium`。

业务 E2E 会自行启动 fixture API/Vite，拒绝复用日常服务；默认端口 8000/5173，数据库 `.local/e2e.sqlite3`。并行开发时，在独立终端指定独立资源：

```powershell
$env:LEARNGRAPH_E2E_API_PORT = '8017'
$env:LEARNGRAPH_E2E_WEB_PORT = '5187'
$env:LEARNGRAPH_E2E_DATABASE_PATH = '.local/my-change-e2e.sqlite3'
npm.cmd run test:e2e
```

不要对日常数据库运行清理/种子脚本。断言应检查实际工具、保存产物和请求身份，而不只等一段相同的“成功”文本；恢复用例要区分旧结果与本次重试。

## 文档站回归

```powershell
npm.cmd run docs:build
npm.cmd run test:docs
```

文档测试使用独立 Playwright 配置与静态预览，只启动文档服务，不启动 API、不读模型配置。覆盖桌面导航、中文搜索、相对链接、窄屏菜单与溢出。测试前安装 Chromium；预览端口 4174 必须空闲。

## 离线评估和真实调用

`npm.cmd run eval:offline` 使用确定性样例评估，不说明真实模型的内容正确率、引用语义或供应商稳定性。

`smoke:real`、`smoke:p0:real`、`smoke:p0:browser:real` 和带 `--real` 的 demo 会调用供应商并可能收费，不属于默认验证，不因为存在 `.env` 就执行。真实测试需明确数据/费用授权，使用独立数据库；操作步骤与历史适用边界见[阶段验收指南](../demo/stage-review-real-testing.md)。

交付时报告实际执行的命令、结果和未测项。不要用历史真实旅程替代当前默认工作台、Agent/Skill 或 P1 内容质量验收。
