# 原神公告原始资料

中文米游社公告将保存到 `zh-cn/miyoushe/`，包含 `pages/`（原始列表与分页游标）、`posts/`（全文原始 JSON）、`index.json`、`checkpoint.json` 和 `collection-report.json`。

使用仓库的手动工作流 `Archive Chinese Miyoushe announcements (manual only)` 进行第一次采集和断点续采。不要与其他游戏或正式 `public/v1/` 卡池接口混合。

繁體中文 HoYoverse 官网祈願公告单独保存到 `zh-tw/hoyoverse/`，使用手动工作流 `Archive Genshin HoYoverse Traditional Chinese wish notices (manual only)`。其原始时间文本按 `Asia/Shanghai`（UTC+08:00）解释。详见 `docs/archive/hoyoverse-genshin-zh-tw-archive.md`。

繁體中文 HoYoverse 官网列表的逐批原始分页快照保存在 `zh-tw/hoyoverse/snapshots/<采集批次>/000001.json` 等文件中；`index.json`、`checkpoint.json`、`collection-report.json` 仍位于 `zh-tw/hoyoverse/` 根目录，数据内容未经去重或重写。

米游社公告解析产生的 `banner-candidates.json` 统一归入 `data/derived/genshin/miyoushe-zh-cn/`，原始公告目录只保留来源材料。
