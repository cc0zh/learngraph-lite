# sqlite3 的 with connection 不等于关闭连接

## 是什么

Python 标准库 `sqlite3.Connection` 可以作为 context manager 使用，但它管理的是事务提交和回滚，不负责关闭连接。需要释放文件句柄时，应显式调用 `close()`，或用 `contextlib.closing(connection)` 包住连接生命周期。

## 为什么需要

在 Windows 上，未关闭的 SQLite 连接会继续占用 `.db` 文件。测试如果把数据库建在 `TemporaryDirectory` 下，即使用例逻辑已经结束，目录清理也可能因为文件被占用而失败。这个问题在类 Unix 系统上不一定以同样方式暴露，所以跨平台测试更容易踩坑。

## 怎么用

推荐把“关闭连接”和“事务边界”分开表达：

```python
from contextlib import closing

with closing(sqlite3.connect(path)) as connection:
    with connection:
        connection.execute("insert into table_name(id) values (?)", (item_id,))
```

外层 `closing` 保证离开作用域时关闭连接；内层 `with connection:` 保证写操作在成功时提交、异常时回滚。只读查询也可以只用 `closing`。

## 核心要点

- `with sqlite3.connect(path) as connection:` 不会在退出时自动关闭连接。
- 临时文件、测试数据库和 Windows 环境更容易暴露连接未关闭问题。
- repository adapter 应把连接生命周期封装起来，不把 connection 泄漏给应用层。
- 事务管理和资源释放是两个不同职责，代码里最好分别表达。
