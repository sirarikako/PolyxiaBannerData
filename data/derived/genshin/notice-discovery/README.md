# 原神简体中文公告增量发现

长期维护脚本：`scripts/collect/collect_genshin_notices_zh_cn.py`。

仅检查米游社原神公告的两个分栏：
- `https://www.miyoushe.com/ys/home/28?type=1`
- `https://www.miyoushe.com/ys/home/28?type=3`

通过米游社 `getNewsList` API 读取列表，仅对明确匹配「版本更新说明」「活动祈愿预告」「单篇祈愿公告」的新增文章，调用既有的三个单篇提取器。详情从米游社 `getPostFull` 读取或复用本地归档；不会访问第三方来源。

运行：

```bash
python -m scripts.collect.collect_genshin_notices_zh_cn
python -m scripts.collect.collect_genshin_notices_zh_cn --max-pages 10
```

首次运行仅读取两个分栏的最新一页并分别记录基线，**不会追溯当前已存在的历史文章**。后续每次从列表顶部检查，通过连续已知文章 ID 的重叠确认上次扫描位置，发现新增文章后保存至待处理队列。一次发布多篇帖子时，每篇会分别提取。超出页数上限仍找不到重叠时，该分栏不推进检查点，应适当增大 `--max-pages` 再运行。

持久状态文件：`notice-discovery_zh-CN_checkpoint.json`，记录各分栏的近期锚点、`pending` 失败队列和 `completed` 已提取文章。报告：`notice-discovery_zh-CN_report.json`。这些文件将在首次执行时创建。JSON 均使用简体中文标记 `zh-CN`；脚本使用 `zh_cn`。

提取输出保持既有命名与目录：
- `data/derived/genshin/version-updates/version-update_zh-CN_<版本>.json`
- `data/derived/genshin/wish-previews/wish-preview_zh-CN_<版本>-phase-<期数>.json`
- `data/derived/genshin/wish-notices/wish-notice_zh-CN_<文章ID>.json`

完整原始公告 JSON 仍归档于 `data/announcements/genshin/zh-cn/miyoushe/posts/`，结构化 JSON 与 checkpoint 继续保存到私有仓库。**图片只在需要执行祈愿公告提取器时下载到系统临时目录**，供 `build_genshin_wish_notice_zh_cn.py` 的 `--images-dir` 参数读取。完成或失败后都会自动删除临时目录；版本更新和祈愿预告不下载图片，已有结构化 JSON 也不重复下载图片。

临时图片工具：`scripts/collect/download_genshin_notice_images_zh_cn.py`。图片只接受 HTTPS `upload-bbs.miyoushe.com/upload/`，支持 PNG/JPEG/WebP/GIF，最多 60 张，单张最多 20 MiB。临时索引提供 URL、文件名、校验值，**不提交图片或图片索引到 GitHub**。当前祈愿公告解析器只读取并校验图片文件，还没有 OCR/图中文字识别功能，因此不会从图片自动填补卡池时间。


注意：Actions 运行机的文件系统不会在多次执行间自动保留，因此日后启用定时工作流时，必须将 checkpoint JSON、原始公告 JSON 和候选 JSON 持久提交到私有仓库；不提交临时图片或图片索引，并配置同一时刻只有一轮检查。不要把检查点只存为临时 Artifact。列表 API 失败、验证或限流时停止，不伪造空列表或绕过校验。

目前未新增、启用或修改任何 GitHub Actions。长期使用时应定期复查标题分类，新增的公告格式可能需要新增提取器。
