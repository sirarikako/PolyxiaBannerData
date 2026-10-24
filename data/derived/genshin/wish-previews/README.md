# 原神简体中文祈愿预告候选

本目录保存米游社「活动祈愿预告」按文章解析得到的内部候选 JSON。命名与版本更新公告的 `version-update_zh-CN_7.1.json` 一致，采用「类型_语言_版本-期数」规则，与正式「祈愿公告」区分，不直接发布至 `public/v1/`。

- 解析脚本：`scripts/transform/build_genshin_wish_preview_zh_cn.py`
- 原始正文：`data/announcements/genshin/zh-cn/miyoushe/posts/<post_id>.json` 或 `data/announcements/genshin/zh-cn/miyoushe-account-75276539/posts/<post_id>.json`（与已有米游社归档共用）
- 本目录输出：`wish-preview_zh-CN_<version>-phase-<n>.json`，例如 `wish-preview_zh-CN_7.1-phase-2.json`。
- 若以后新增按期生成的正式祈愿公告候选，应采用 `wish-announcement_zh-CN_<version>-phase-<n>.json`，不要覆盖预告。
- 第一期开头为「版本更新后」时，只保留 `time.startRaw` 和 `time.startCondition`，不猜测实际开服时刻。
- `time.startAt` / `time.endAt` 是按米游社简体中文国服时间解释的原文时刻（UTC+08:00），不是转换为排他结束时间；正式 v1 仍需单独核验。
- 未能从正文找到的四星或图片中信息保持空数组，记录到 `review.warnings`；不以配对顺序推断每个角色池或武器池的归属。

手动按文章采集并转换：

```bash
python -m scripts.transform.build_genshin_wish_preview_zh_cn --post-id 78879329
python -m unittest discover -s tests -p 'test_build_genshin_wish_preview.py' -v
```

若两种米游社归档均无缓存，首次执行会访问文章详情接口并保存原始响应；如果已有归档，则默认离线重用。若详情接口要求验证或限制频率，程序停止而非绕过。现有临时手动 Action `.github/workflows/TEMP-genshin-wish-preview-zh-cn-test.yml` 会离线核对 5 个版本的 10 篇真实归档，并在全部测试通过后将候选 JSON 提交到本目录，同时上传短期 Artifact；不设定时任务、不修改 `public/v1/` 或公开数据。没有获取到真实原文的文章不应生成模拟数据。
