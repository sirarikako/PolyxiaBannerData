# 原神简体中文祈愿预告结构化数据

本目录保存米游社「活动祈愿预告」按版本、期数解析的结构化 JSON，例如 `wish-preview_zh-CN_7.1-phase-2.json`。这些文件是候选整合的输入，**不直接发布到** `public/v1/`。

- 解析脚本：`scripts/transform/build_genshin_wish_preview_zh_cn.py`。
- 输入：真实官方文章 JSON，由生产 2-1 工作流当次临时取得；也可通过 `--input` 指定本地文件。
- 文件命名：`wish-preview_zh-CN_<version>-phase-<n>.json`。
- 第一期开头为「版本更新后」时，保留原始条件，不猜测具体开服时刻。
- 时间按照国服公告原文的 UTC+08:00 解释；不能直接替代 v1 的独占结束边界。
- 公告没有明确给出的名单或图片信息不得通过配对顺序猜测，缺项须留待其他公告或人工核对。

手动转换（需要真实输入文件）：

```bash
python -m scripts.transform.build_genshin_wish_preview_zh_cn --post-id 78879329 --input /path/to/78879329.json
```

完整官方文章只在当次执行临时使用，不作为公开仓库持久文件保存。生产扫描、候选合并与发布见 [脚本说明](../../../scripts/README.md)。
