# 可选执行记录

默认在 execution plan 中记录进度和最终验收，见 `docs/PLANS_GUIDE.md`。

只有长时间执行、过程细节过多或需要独立交接时，才在 `docs/exec-runs/<plan-slug>/` 拆出材料：

- `execution-process.md`：详细过程与问题，按需采用 `templates/execution-process.md`。
- `execution-summary.md`：独立验收与交接，按需采用 `templates/execution-summary.md`。

无需同时创建两份。计划只链接拆出的内容，history 只作为任务索引，不重复维护相同事实。

无人值守任务也遵循这一规则，但必须在计划或验收记录中写清完成项、失败与权限阻塞。工作权限沿用 `AGENTS.md`，不因记录形式变化而扩大授权。

此目录中的已有任务记录属于模板维护资料，初始化新项目时只复制本说明与 `templates/`。
