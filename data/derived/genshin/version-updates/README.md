# 原神简体中文版本更新结构化数据

本目录按版本保存从米游社「版本更新说明」提取的结构化 JSON，例如 `version-update_zh-CN_7.1.json`。数据供卡池候选整合使用，**不是独立发布的卡池记录**。

- 转换脚本：`scripts/transform/build_genshin_version_update_zh_cn.py`。
- 输入：当次 Runner 临时取得的官方完整文章 JSON，可通过 `--input` 显式指定。
- 输出：版本号、维护开始时间、预计维护时长、新角色/武器与来源核验信息。
- 同名结果内容不同时，需要 `--force` 才能覆盖；此解析器不直接修改正式 v1 或 Manifest。

示例（须先取得真实官方文章 JSON）：

```bash
python -m scripts.transform.build_genshin_version_update_zh_cn --post-id 78335167 --input /path/to/78335167.json
```

正式 2-1 工作流自动取得所需文章，并只持久化结构化结果；完整正文不提交本仓库。公告中预计的维护结束时间不是实际开服时间，也不能单凭版本更新公告推定 UP 名单。早期文章格式可能不同，解析缺项须人工核验。
