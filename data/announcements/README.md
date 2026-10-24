# 官方公告临时缓存

Public 生产在 GitHub Actions Runner 内临时使用 `data/announcements/<game>/zh-cn/miyoushe/posts/<postId>.json` 等来源正文。**这些原始 JSON 和 OCR 图片不提交 Git，也不上传公开 Artifact。**

长期保存的是 `data/derived/` 中的结构化公告、扫描 checkpoint、候选与诊断；正式接口在 `public/v1/`。

旧历史归档文件及完整官方文章仍留 Private 开发库。禁止在 Public 提交 `posts/`、`images/`、历史分页/索引 JSON；旧归档器的 `--commit-progress` 在 Public 也被代码禁止。

- [原神](genshin/README.md)
- [星铁](starrail/README.md)
- [现役发布流程](../../scripts/README.md)
