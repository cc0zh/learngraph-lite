# 文档文件存在，不代表片段链接可用

## 问题是什么

Markdown 链接 `planning.md#谁决定，保存什么` 的文件确实存在，页面也能构建，但点击后不一定跳到目标段落。链接包含两个契约：文件地址能解析，以及片段能匹配渲染后的元素 ID。只检查第一个，会留下“打开了正确页面，却没有定位”的缺陷。

## 为什么中文标题也会变化

标题会经过站点生成器的 slug 处理，而不是原样成为 ID。本仓库的 VitePress 会进行 Unicode 规范化与标点处理：

```text
标题：谁决定，保存什么
错误：planning.md#谁决定，保存什么
实际：planning.md#谁决定-保存什么
```

全角逗号经规范化后参与连字符替换；大小写、空白和重复标题也可能影响 ID。浏览器地址中看起来相似的两段文字，不一定引用同一个元素。不要另写一套“看起来差不多”的 slug 算法来证明链接正确。

## 怎样验证

分三层检查，各自回答不同问题：

1. **Markdown 文件检查：**相对路径指向正式来源文件。
2. **站点构建：**页面能生成，站内页面地址没有失效。
3. **构建产物和浏览器验证：**解析链接的 `hash`，URL 解码后在目标 HTML 中查找真实 ID，并实际打开代表性链接，确认目标进入视口。

核心断言可以很小：

```javascript
const id = decodeURIComponent(new URL(link).hash.slice(1));
const document = new DOMParser().parseFromString(targetHtml, 'text/html');
const exists = document.getElementById(id) !== null;
```

`tests/docs-site.spec.ts` 使用此思路检查机制入口和调用链的站内片段，并缓存同一目标页面的 HTML，避免为每个锚点重新下载。HTML 解析检查目标是否存在，真实导航检查定位行为；二者都不能替代对章节含义的人工核对。

## 维护时自检

- 新链接的片段来自实际构建 ID，还是照抄标题？
- 修改标题或迁移页面时，谁还在引用旧地址和锚点？
- 测试是否只检查了 HTTP 200，却没有验证定位？

相关操作见[文档维护指南](../../developer/documentation.md)。
