# 原神临时公告源

原神 2-1 从米游社简体中文 type=1/type=3 增量发现新文章，当次下载 `zh-cn/miyoushe/posts/<postId>.json` 并解析；祈愿公告图片在 Runner 中临时 OCR。**原文和图片不进入 Public Git**。

持久化结果在 `data/derived/genshin/`：`notice-discovery/` 保存 checkpoint，`version-updates/`、`wish-previews/`、`wish-notices/` 保存结构化公告，`v1-candidates/` 和 `v1-readiness/` 用于发布及异常复核。Private 旧全量归档和繁体快照不在本仓库执行。

见 [结构化数据说明](../../derived/genshin/README.md)。
