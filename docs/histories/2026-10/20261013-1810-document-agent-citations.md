# Agent 资料检索与回答引用

- 用户诉求：继续开发面向 Agent 应用简历作品的 LearnGraph Lite；参考成熟开源实现、保持适当规模，增长并收敛测试，同步文档并适时提交。
- 结果：节点 Agent 接入绑定范围内检索/读取工具，每轮稳定来源编号、回答未验证引用标记、HTTP/SSE 来源表与原文重新定位；SQLite demo 覆盖资料回答与空召回。参考 LlamaIndex 的来源编号分工，不复制源码或引入框架。
- 设计与验收：[总执行计划的资料引用切片](../../exec-plans/active/learngraph-lite-implementation.md)。当前只完成该切片，总目标保持 active；真实供应商、上传/PDF、生成产物 grounding 与 React 尚未完成。
