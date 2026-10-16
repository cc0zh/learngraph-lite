# 参与协作

这个仓库是为 Agent-first 开发准备的，但这些规则对人和 Agent 都一样适用。

## 基本协作方式

新加入的开发者先看[开发者文档总览](docs/index.md)，从首次运行、概念与调用链进入业务；维护文档站见[文档维护指南](docs/developer/documentation.md)。

- 从 `AGENTS.md` 开始，再按任务类型去读对应文档。
- 仓库级知识要落在版本化文件里，不要只存在聊天记录、口头同步或工单评论里。
- 如果行为变了，就一起更新代码、文档、测试和 release/history 记录。
- 遇到跨度大、风险高、会分多轮推进的任务，先在 `docs/exec-plans/active/` 下建 execution plan。

## 发起 Pull Request 之前

- 文档变更运行 `npm run check:docs` 与 `npm run docs:build`，人工核对引用与口径；导航、搜索和主题变化补 `npm run test:docs`。代码变更运行 `npm run check`，按影响补浏览器回归与 `eval:offline`，范围见[测试指南](docs/demo/stage-review-real-testing.md)。`ci` 只是基础门禁，不包含前端/文档构建或 E2E；收费 smoke 需另行授权，不因提 PR 自动执行。
- 如果本次改动涉及代码或仓库流程，补齐或更新对应 history。
- 如果变更对用户可感知，补齐 release note。
- 确认示例、脚本、说明文档和当前实现一致。

## Review 默认要求

- 优先拆成范围清晰的小 PR。
- 明确写出风险点、迁移影响和后续待办。
- 如果上下文复杂，直接链接对应 plan、spec 或 history，不要依赖评审者自己猜。
