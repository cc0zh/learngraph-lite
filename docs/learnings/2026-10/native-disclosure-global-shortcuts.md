# 原生 disclosure 遇上全局快捷键

## 先区分“冒泡”与“默认动作”

`summary` 原生支持 Enter / Space 展开 `details`，本不需要自写键盘逻辑。但页面上的图谱库可能在 `window` 监听 Space，用于激活平移。如果监听器调用 `preventDefault()`，它取消的不只是滚动，也包括已经聚焦的 summary 的原生激活动作。

症状很有迷惑性：Enter 和鼠标正常，Space 没反应；把同样的 HTML/CSS 放进空白页面又正常。问题不在隐藏了三角标记，而在另一个区域的全局监听器。当前 ReactFlow 依赖的 `useKeyPress` 排除了 button/link 的部分情况，却没有把 summary 当作同样的交互控件。

## 局部隔离，保留原生行为

在受影响 summary 上阻止 Space 冒泡到全局监听器即可：

```tsx
<summary onKeyDown={event => {
  if (event.key === ' ') event.stopPropagation();
}}>
  处理步骤
</summary>
```

这里**不要**调用 `preventDefault()`：我们正是要保留浏览器的原生开合动作。也不应手动反转 `details.open`，否则会与原生激活发生双重切换；更不需要关闭整个图谱的键盘支持。

仅隔离已确认冲突的键，不无差别吞掉所有键盘事件。这种局部补丁依赖全局监听器位于冒泡阶段；如果第三方库改为捕获阶段，需要重新核对监听时序，不能机械复用。

## 回归要包含那个“旁边的控件”

- 在真实含图谱的工作台验证，而不只测孤立 summary。
- 用 `summary.press('Space')` / `press('Enter')`，检查 `details.open` 与步骤可见性；不要用 JS 直接设置 open 来代替键盘测试。
- 展开、收起、刷新保持只读；折叠后错误与重试仍可见，草稿与会话范围不变。
- 同时测目录 disclosure：同一个全局监听器可能影响多个位置。

从[本次 UI 组件适配](../../histories/2026-10/20261017-1430-editorial-ui-refresh.md)提炼。对应代码在 `frontend/src/components.tsx`、`frontend/src/workbench/Workbench.tsx`，回归在 `frontend/tests/enso-components.spec.ts`。
