# 原神简体中文公告增量发现

正式采集脚本：`scripts/collect/collect_genshin_notices_zh_cn.py`；对应生产 Action 为 `genshin-notices-zh-cn-daily-preview.yml`（2-1）。

## 数据来源与扫描

扫描米游社原神公告的两个分栏：

- https://www.miyoushe.com/ys/home/28?type=1
- https://www.miyoushe.com/ys/home/28?type=3

脚本从官方列表发现新文章，识别版本更新、祈愿预告及祈愿公告，并调用对应解析器。增量扫描依靠已知文章的重叠锚点；达到分页上限仍无法确认重叠时，不推进相应 checkpoint。首次启动仅建立当前列表基线，不自动追溯历史公告。

## 持久化结果

- `notice-discovery_zh-CN_checkpoint.json`：分栏锚点、待重试 `pending`、已处理 `completed` 与人工复核状态。
- `notice-discovery_zh-CN_report.json`：扫描报告。
- `../version-updates/`、`../wish-previews/`、`../wish-notices/`：解析后的结构化公告。
- `../v1-candidates/`、`../v1-readiness/`：卡池候选与发布前诊断。

**完整官方文章 JSON 与 OCR 图片仅在当次 Runner 临时下载，不提交本仓库，也不上传公开 Artifact。** 祈愿公告需要时下载图片并进行 OCR；图片识别失败、解析冲突或脚本异常进入人工复核，临时网络问题保留在 `pending`。

## 手动调用

```bash
python -m scripts.collect.collect_genshin_notices_zh_cn
python -m scripts.collect.collect_genshin_notices_zh_cn --max-pages 10
```

不要删除或重置正式 checkpoint。2-1 可生成候选和安全预览，但不修改正式 v1；正式发布由独立 2-2 Action 完成。具体运行与异常处理见 [生产脚本说明](../../../scripts/README.md)。
