# Database Directory

这里预留给数据库文件与后续数据库相关配置。

当前项目为了兼容现有运行方式，默认 SQLite 仍使用 `data/fzg.db`。
如果你想把数据库文件迁到这里，可以在环境变量中显式设置：

```env
DATABASE_URL=sqlite:///database/fzg.db
```

