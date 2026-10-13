# M4B 声明式学习页与事件解释离线切片

## 用户诉求

继续按 docs/从零构建功能文档.md 实现 LearnGraph Lite，推进声明式交互学习页、固定组件、用户事件回流和解释任务幂等，避免任意 HTML/JS 执行。

## 本次结果

- 新增 LessonPackage、LessonComponent、LessonEvent 领域模型。
- 限定组件类型为 choice_card、stepper、comparison_table。
- 拒绝 Markdown 中 script/iframe，以及组件 props 或事件 payload 中 on*、script、html、dangerouslySetInnerHTML 等可执行字段。
- 新增 LessonService，保存 lesson package、ACK 用户事件、复用 LearningService 提交正式选择题答案。
- 解释任务按 event_id + slot 建立逻辑幂等关系；重复请求返回同一 run_id，失败后可按新 request_id 重试。
- 测试覆盖事件不改变成绩、重复事件 ACK、正式作答复用、解释 run 幂等和失败可见。

## 设计动机

学习页内容应该是可校验的 Markdown + JSON，而不是可执行代码。用户交互先作为结构化事件进入后端，只有明确的正式作答走评分通道；普通点击和步骤事件只能触发解释或记录，不能伪造成绩。

## 关键文件

- src/learngraph_lite/domain/lessons.py
- src/learngraph_lite/application/lessons.py
- tests/test_lessons.py
- docs/exec-plans/active/learngraph-lite-implementation.md

## 验证

- python scripts/run-python-tests.py：通过，25 Python tests passed。
- python scripts/check-python-boundaries.py：通过。
- npm.cmd run ci：通过，包含 25 个 Python 测试和 19 个 Node 模板工具测试。

## 未完成项

- React 固定组件渲染器未实现。
- HTTP/SSE 路由未实现。
- 资料型学习页的前端引用展示仍待 M5 组合验证。
