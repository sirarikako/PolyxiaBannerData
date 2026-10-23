# 原神公告人工 JSON 模板

本目录的 JSON 均为**格式示例，不参与当前脚本输入或发布**。示例使用已知版本数据说明字段含义，**不代表对应版本真实缺少公告**；正式人工核对时务必替换数据、来源依据和目标路径。

## 1. 已取得真实帖子（现有流程）

| 模板 | 对应解析输出 | 例子 postId |
| --- | --- | --- |
| `notices/version-update.template.json` | `data/derived/genshin/version-updates/version-update_zh-CN_7.1.json` | 78335167 |
| `notices/wish-preview.template.json` | `data/derived/genshin/wish-previews/wish-preview_zh-CN_7.1-phase-2.json` | 78879329 |
| `notices/wish-notice.template.json` | `data/derived/genshin/wish-notices/wish-notice_zh-CN_78782590.json` | 78782590 |

复制到 `manual/notices/genshin/zh-CN/miyoushe/<真实文章ID>.json`，保留 `format=genshin-notice-manual-v1` 和真实 `postId`，只填写实际需要补充或核对的 `data` 字段。必须已有真实帖子原文；不能使用虚构的 ID 让采集器误以为有官方公告。

Schema：`schemas/manual/genshin-notice-manual.schema.json`。

## 2. 完全缺失帖子（逐池候选整合）

| 模板 | 正式人工 JSON 计划位置 | 逻辑身份 |
| --- | --- | --- |
| `missing/version-update.template.json` | `manual/notices/genshin/zh-CN/missing/version-update_<版本>.json` | 版本 |
| `missing/wish-preview.template.json` | `manual/notices/genshin/zh-CN/missing/wish-preview_<版本>-phase-<期数>.json` | 版本＋期数 |
| `missing/wish-preview-special-only.template.json` | 与普通预告相同的文件命名规则（**仅演示，无需同时保存两份**） | 全期仅特殊池，省略 `data.up` |
| `missing/wish-notice.template.json` | `manual/notices/genshin/zh-CN/missing/wish-notice_<版本>-phase-<期数>-<poolType>.json` | 版本＋期数＋池种 |

**集录/溯光** 在文件名与 `identity` 里再加 `variant` 区分，例如 `wish-notice_7.1-phase-1-chronicled-special_recollection.json`。

缺帖模板固定用 `genshin-missing-notice-v1`，**不填写 `postId`、`sourceKey`**；人工必填 `noticeType`、`identity`、`data`、`evidence.summary`。程序由 `identity` 派生内部 `sourceKey`，在正式 V1 来源中使用 `provider=manual` 标识，不伪造米游社帖子 ID。

Schema：`schemas/manual/genshin-missing-notice.schema.json`。完整字段和恢复流程：`manual/notices/genshin/zh-CN/missing/README.md`。

## 共通注意

- 三类公告都只需提供最终构成可发布候选的**必要字段**；其他字段若有已解析值由整合器沿用。缺帖情况的最低字段要求请看 `manual/notices/README.md`。
- 对于常规角色池/武器池，预告仍应提供整期五星 UP 汇总；**只有集录/溯光等特殊池且无常规 UP 时，才可省略 `data.up`**。Schema 允许省略，但后续整合器还必须依据整期卡池类型判定是否能发布；特殊池模板不代表 7.1 的真实卡池情况。
- `data.time.endAt` 为公告原始 `+08:00` 分钟，不是正式 v1 中加 1 分钟的独占截止时刻。
- UP、selectable 名单为该字段的**完整名单**；自动比对忽略名单顺序。不能把未知写成虚构值。
- 无帖人工来源可先发布 v1，但不能因此清除临时网络下载 `pending`；官方补发/恢复后必须按逻辑身份核对。官方与人工出现关键差异时，保留已发布 v1、不自动覆盖，交由 Issue 人工复核。
- **当前仅标准、示例及文档已准备；现有 2-1／2-2 未接入 `missing`，创建模板目标文件本身不会触发正式发布。**
