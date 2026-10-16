# 异步测试：等待这次事件，不要只认一段文本

重试前后若使用同一句模拟回答，点击“重试”后断言文本可见，可能立即读到**上一次**结果。此时网络请求还没进入拦截器，紧接着访问 `submissions[1].request_id` 就会偶发报错；表面像业务不稳定，实际是测试没有同步到本次事件。

## 怎么判断等待条件是否可靠

问一句：**如果刚才的按钮根本没有生效，这个断言仍可能通过吗？** 若可能，它就不能证明按钮触发了本次操作。

错误的做法：

```typescript
await retry.click();
await expect(lastMessage).toContainText('模拟回答已完成'); // 旧消息也包含它
expect(submissions[1].request_id).not.toBe(originalId);
```

更可靠的做法是把业务事件和它的结果分开验证：

```typescript
await retry.click();
await expect.poll(() => submissions.length).toBe(2);
await expect(lastMessage).toContainText('重试后的回答已完成');
expect(submissions[1]).toMatchObject({ retry_of_run_id: failedRunId });
expect(submissions[1].request_id).not.toBe(originalId);
```

先证明新请求发生，再证明新结果呈现，最后检查身份关系。失败 fixture 不应冒充成功文本；不同 attempt 的结果应能区分。

## 不要用重跑替代修复

固定 sleep 会依赖机器速度；开启自动 retries 则可能掩盖错误等待条件。应保留首轮失败事实，修好观测点，再执行相关回归。只有证据指向环境瞬断时才记为环境问题，不能把所有偶发失败都归给环境。

本次案例与验收索引：[版本收敛计划](../../exec-plans/completed/version-consolidation.md)。
