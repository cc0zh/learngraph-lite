# 模型返回后，更新最新状态中的一部分

模型调用可能持续数秒。若调用前读出状态，调用后把整份旧状态写回，期间其他请求写入的事件会被覆盖。这不是模型质量问题，而是读改写的并发问题；单纯给最终 save 加锁也不能让旧快照变新。

正确顺序是：先在事务外获取模型候选，再进入短事务读取最新状态、复验版本和取消状态、只修改此次负责的字段。生成学习包时，在最新包集合上计算下一个版本，并一起写入包与 operation；ACK 则只增加首次事件。两者竞争时，后进入事务的一方能看到前一方的结果。

```python
# 旧快照会覆盖模型调用期间的新事件。
old = repository.state(goal_id)
answer = call_model()
old.explanation_runs[key] = answer.run_id
repository.save(goal_id, old)

# 在最新状态上更新解释关联，保留期间的 ACK。
answer = call_model()
repository.mutate(goal_id, lambda latest: latest.explanation_runs.setdefault(key, answer.run_id))
```

内存实现需要锁与快照副本，异常时不提交；SQLite 可用 BEGIN IMMEDIATE 串行化短写事务。不要把网络调用放进数据库写事务，否则慢模型会阻塞普通 ACK。测试应让两个请求在模型返回处同步，检查版本、事件都保留，并检查异常后的状态未变化。

这只解决同仓库丢更新。跨资料/规划/学习仓库的复验后变更仍有窄窗口；解释事件与首个 run 的原子关联也需独立设计，不能用一次 mutate 宣称全部解决。

关联：[本次变更](../../histories/2026-10/20261013-2020-lesson-generation-http.md)。
