# 异步解析：ready 必须和索引一起提交

后台任务中的“完成”是一个数据承诺：用户看到 ready 后，应当能读取原文并检索到它。如果先写 ready，再保存 chunk/索引，进程在两步之间退出，就会留下无法使用却显示成功的资料。

把所有可见结果放进一个事务：先按当前状态更新，再保存全文、chunk 和 FTS，最后 commit。任何一步失败都 rollback。SQLite 的 BEGIN IMMEDIATE 提前取得写入资格，让状态检查和后续写入之间不能插入另一条删除操作；模型或 PDF 解析本身应在事务外执行，避免长时间占用写锁。

```sql
BEGIN IMMEDIATE;
UPDATE document_uploads SET status = 'ready', reason = NULL
WHERE document_id = ? AND status = 'parsing';
-- 仅 rowcount == 1 时保存全文、chunk、FTS。
COMMIT;
```

状态条件还解决“晚到结果”：用户删除资料后，旧 worker 的 UPDATE 找不到记录，不能重新插入文档。恢复流程把 parsing 改成 failed/interrupted，旧任务也不能覆盖恢复状态。这个条件只适用于当前单进程模型；多进程或跨重启继续运行的 worker 需要独立 attempt ID，否则新任务再次进入 parsing 时无法区分新旧执行者。

重启恢复和失败重试承担不同责任。启动只把未完成任务标为 interrupted，让用户知道结果不确定；reparse 再从持久化原 bytes 执行解析。原 bytes 没变，内容 revision 不变；ready 的重试直接返回现有结果。不能用“每重试一次 revision 加一”掩盖缺少内容版本模型。

验证要观察失败后对外可见的状态，而非只检查调用顺序：在保存索引后注入异常，确认 ready、全文和 chunks 一起回滚；暂停绑定校验，交错执行删除，确认不会留下孤立绑定；删除解析中的资料后放行 worker，确认内容不会复活。引用存在性与语义支持仍是另一类问题，事务只能保证可定位数据的一致性。

自检：若 FTS 写入失败，用户看到什么状态？若解析完成之前删除，哪个条件阻止结果复活？若多个进程共享数据库，启动恢复会不会把别人的活跃任务标为失败？

对应变更：[资料上传与检索 HTTP](../../histories/2026-10/20261013-1920-document-import-http.md)。
