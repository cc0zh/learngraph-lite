# 声明式学习页的事件边界

## 是什么

声明式学习页把 Agent 生成内容限制在 Markdown 和版本化 JSON 组件里。前端只渲染固定组件，用户点击、选择和请求解释会变成结构化事件发回服务端。

## 为什么需要

如果 Agent 直接生成 HTML 或 JavaScript，学习页就会变成不受控执行环境，调试和验收都很难。声明式组件让交互能力和业务状态分离：组件负责展示，事件负责表达用户动作，正式成绩仍由练习服务判分。

## 怎么想

- LessonPackage 保存 node_id 和 graph_content_revision，用于后续判断内容是否过期。
- 组件只允许有限 kind，例如 choice_card、stepper、comparison_table。
- Event ACK 使用 event_id 幂等，重复提交返回同一业务事件。
- 解释任务使用 source_event_id + slot 建立逻辑幂等，网络重试不会创建多个初始 run。
- 普通学习页事件不改变 mastery；正式作答必须调用练习评分用例。

## 常见陷阱

- 不要把 onClick、script、html 这类字段透传给前端。
- 不要把选择卡事件直接当作正式成绩，除非它走 Exercise 提交流程。
- request_id 只能解决传输重试，业务幂等还需要 source_event_id 和 slot。
- 失败重试和显式重新解释语义不同，不能都映射到同一个无限复用的 key。
