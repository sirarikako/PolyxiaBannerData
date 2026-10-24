# 原神公告级人工数据（两种来源：真实帖子与缺失帖子）

本目录为长期人工补缺和核对资料，**不是正式 v1 文件**。按 2026-10-18 已确定的方案，支持两种互不混淆的人工来源：

| 场景 | 人工文件位置 | 格式标记 | 是否必须有官方原始帖子 |
| --- | --- | --- | --- |
| **已有真实文章 ID**，但 OCR、解析或字段不完整 | `manual/notices/genshin/zh-CN/miyoushe/<文章ID>.json` | `genshin-notice-manual-v1` | 是；可用已保存原文恢复解析 |
| **尚无真实帖子／取不到文章 ID 或原始 JSON** | `manual/notices/genshin/zh-CN/missing/<逻辑身份>.json` | `genshin-missing-notice-v1` | **否**；只使用人工核对的身份及证据，绝不虚构 postId |

两种来源分别由真实帖子人工读取器和缺帖人工读取器处理。缺帖来源满足字段完整性、公告关联和正式 V1 校验后才能发布；详细格式参见 [缺帖人工来源说明](genshin/zh-CN/missing/README.md)。

## 一、真实帖子人工补缺（当前可用）

文件：`manual/notices/genshin/zh-CN/miyoushe/<文章ID>.json`。真实文章已出现，但部分字段缺失时：

```json
{
  "format": "genshin-notice-manual-v1",
  "postId": "78782590",
  "data": {
    "time": { "endAt": "2026-11-03T14:59:00+08:00" }
  }
}
```

- 只填写需要补充或核对的 `data` 字段，不复制完整自动解析结果。不再分 `override` 与 `verify`：自动无值时采用人工；自动已有值时逐字段比较，一致记匹配，不一致保留自动值并按关键性处理差异。
- 列表可写成 `["角色甲","角色乙"]` 或 `[{"name":"角色甲"}]`；名单是一整项完整列表，不支持按索引合并；比较忽略顺序和自动结果额外属性。自动 `[]` 不等同缺失，人工非空名单与之不一致会报告冲突。
- 时间用原公告的 `+08:00` 分钟，不能直接复制 v1 的独占结束时间。人工 `null` 表示未知／不参与覆盖，`[]` 是明确空名单。
- 禁止从人工字段设置 `source`、`game`、`locale`、`imageTimeRecognition`、`review` 或伪造官方采集证明。
- 文件长期参与补缺与比较，不需要单条 `completed`。OCR/解析失败时仍保留原始解析状态；真实原文已保存且字段足够，才可恢复候选。
- 原始文章未保存时，本类文件不能恢复解析，也不能借 `postId` 伪装已有来源；应采用第二类 `missing` 设计。

相关 Schema：[`genshin-notice-manual.schema.json`](../../schemas/manual/genshin-notice-manual.schema.json)。

## 二、缺失帖子人工补齐

路径：`manual/notices/genshin/zh-CN/missing/`，**以版本、期数、池种等逻辑身份命名**，而不是凭空生成文章 ID。

- 版本更新：`version-update_7.1.json` → `identity.version`。
- 祈愿预告：`wish-preview_7.1-phase-2.json` → `identity.version + phase`。
- 单池祈愿公告：`wish-notice_7.1-phase-2-character_event_2.json` → `identity.version + phase + poolType`，集录/溯光再带 `variant`。

人工 JSON 只填写 `format="genshin-missing-notice-v1"`、`noticeType`、`identity`、`data`、`evidence.summary`（可附 `evidence.references`）。**不写 `postId` 或 `sourceKey`**：程序根据逻辑身份自动生成稳定来源键；候选的人工来源使用 `provider=manual` 和派生的 `externalId`，不能伪造米游社 URL。

### 最低数据（其余自动可取得字段无需人工重复填写）

| 类型 | 最低内容 |
| --- | --- |
| 版本更新 | 版本号、维护开始时间 |
| 祈愿预告 | `identity` 中的版本和期数、`data.time.endAt`；**有常规角色/武器池时**才需要整期五星 UP 汇总。仅集录/溯光等特殊池时可省略 `data.up`（整合器仍须核对整期池型） |
| 正式祈愿公告 | `identity` 中的池种、版本、期数；`data` 中的池名、结束时间、有效开始时间（第一期可用版本更新后）、按池种完整 UP／可选五星名单；池种不重复填写到 `data` |

角色池需要 1 五星角色 + 3 四星角色；武器池需要 2 五星武器 + 5 四星武器；集录/溯光必须说明 `variant` 与完整可选五星角色、武器。未知物品 ID 可以 `null`，绝不能编造。

Schema：[`genshin-missing-notice.schema.json`](../../schemas/manual/genshin-missing-notice.schema.json)；示例：[无帖三类 JSON 模板](../templates/README.md)；完整规则：[missing/README](genshin/zh-CN/missing/README.md)。

## 三、先人工发布，再取得官方帖子：pending、比较和通知

以下是缺帖人工来源与现有自动公告流水线的协作规则：

1. 缺帖人工数据已足够且其他必需数据、发布校验通过时，允许先形成候选，经 2-2 发布正式 v1；不必等帖子实际出现。**人工发布不结清下载 `pending`**。
2. 原本存在的临时下载 `checkpoint.pending` 继续重试；只要没有实际文章 ID，就没有可重试的下载任务，正常公告列表继续发现即可。约定日内 18:17 主采集，18:27、18:37、18:47、18:57 有条件重试。
3. 以后官方公告取得且成功解析，按业务 `identity` 与既有人工源匹配并逐字段核对；成功下载应从 `pending` 移除。**人工一致**则核对完成；**不一致**则记录差异并进入 Issue 流程。
4. 关键差异（版本、期数、池种、时间、UP 等）阻断**受影响池今后的自动改写**，但已发布的 v1 保持不动、不回滚，其他合法卡池不受影响。非关键差异也要 Issue 提醒，但不阻断其他池。
5. **已发布 v1 也要拿来与人工、官方三方比较**，不能因为候选后来转为 conflict 就跳过核对。确认确需修改时，必须在 `manual/genshin_<版本>.json` 的 `existing` 使用正式内部 ID 定向修订，不能由重新出现的官方公告或 `upcoming` 反向覆盖。
6. Issue 保留原来源、官方文章、新旧值、关键性、处理决定以及最终验证结果。冲突处理完成并在 Issue 回复注明结论后再关闭。人工已经填好但官网持续取不到时，不能宣称官方核验成功，也不能因为 v1 已发布就静默吞掉长期下载失败提示。

## 四、当前报告及完成状态

每日安全预览会在逐池整合完成后执行 `scripts.collect.reconcile_genshin_manual_review_zh_cn`：当公告级人工数据确实已生成可用候选，就把该篇文章从 `checkpoint.manualReview` 移入 `completed`，并保留 `resolution: manual_verified`。如果自动解析文件原本完全缺失，还会记录 `checkpoint.manualRecovered`，下次仍从真实原文和人工 JSON 重新生成候选，避免因状态结清而丢失。恢复结果失效（例如对应人工文件被删除）时会重新产生异常报告，不会使用过期候选。
