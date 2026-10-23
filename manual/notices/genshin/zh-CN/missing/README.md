# 无官方帖子时的原神人工公告来源

当官方帖子尚未发布、没有在列表中被发现，或临时下载失败导致**无法取得可核实的文章 ID／原始 JSON**时，允许人工提供独立的 `missing` 来源，**不伪造 `postId`**。已通过逐池整合器读取本目录并进行 V1 候选安全校验；仅通过校验的候选才能交由正式发布工作流处理。

## 路径与对应关系

每条逻辑公告一文件，按版本、期数和池种定位，而不是按未存在的文章 ID 定位：

| 公告种类 | 文件名约定 | 业务身份 |
| --- | --- | --- |
| 版本更新 | `version-update_<版本>.json` | `version` |
| 祈愿预告 | `wish-preview_<版本>-phase-<期数>.json` | `version + phase` |
| 单池祈愿公告 | `wish-notice_<版本>-phase-<期数>-<池种>.json` | `version + phase + poolType` |
| 集录／溯光 | `wish-notice_<版本>-phase-<期数>-chronicled-<variant>.json` | 同上另加 `variant` |

例如 `wish-notice_7.1-phase-2-character_event_2.json`。**文件名和 `sourceKey` 均应由程序根据 `noticeType` + `identity` 自动推导，不作为人工填写项**；用户只选择公告类型并填写一次 `identity`。现有逐池整合器已经支持该能力；手工提交时仍建议遵循上表的文件名约定，以便审查和维护。同一逻辑身份不得因重试、人工改动或后续恢复官方公告而生成第二条等价来源。

## 文件结构

- `format`：固定 `genshin-missing-notice-v1`（与真实文章人工 `genshin-notice-manual-v1` 不同）。
- `noticeType`：`version_update`、`wish_preview` 或 `wish_notice`。
- `identity`：必须能从版本、期数、池种定位该条公告，不放虚构的 `postId`。
- `sourceKey`：**不需要在人工 JSON 填写**。程序根据 `noticeType + identity` 自动生成稳定内部来源键，候选发布后以 `provider=manual` 与非官方的 `externalId` 标识人工来源，避免伪造帖子 ID。
- `data`：参照当前三种官方解析结果所需的最低业务字段，不能写 `source`、`review`、`imageTimeRecognition` 或自称官方已解析成功的证据。
- `evidence.summary`：人工核对的依据、范围和结论；`evidence.references` 可列出可信来源的说明和 URL，没有可靠链接就不要填写/拼造 URL。

Schema：[`schemas/manual/genshin-missing-notice.schema.json`](../../../../../schemas/manual/genshin-missing-notice.schema.json)（本仓库内部相对路径）；模板：[`manual/templates/missing/`](../../../../../manual/templates/missing/)。

## 三种公告最低补充信息

1. **版本更新**：`identity.version`、`data.maintenance.startAt`。版本名称、新角色和新武器属于可选。
2. **祈愿预告**：`identity.version + phase`、`data.time.endAt`，以及可用来核对目标卡池的整期五星 UP 名单。武器池应包含对应两把五星武器；集录/溯光按最终整合规则核对。
3. **单池祈愿公告**：`identity.version + phase + poolType`、`data.bannerName`、`data.time.endAt` 以及真实 `startAt` 或第一期的 `startCondition=after_version_update`。角色池 1 五星角色+3 四星角色，武器池 2 五星武器+5 四星武器；集录/溯光需 `variant` 和完整 `selectable`（至少包含五星角色和五星武器）。

所有公告结束时间均使用公告写的 `+08:00` 分钟，**不要提前加一分钟**；v1 独占结束边界在生成时计算。

### 派生字段与当前实现

程序使用 `noticeType + identity` 自动派生稳定的内部 `sourceKey`，格式为 `manual-` 加 20 位 SHA-256 十六进制摘要；人工 JSON 不填写此字段。发布候选的 `sources` 使用 `provider=manual` 和由相同身份派生的 `externalId`，不得冒充米游社文章 ID 或 URL。

版本、期数、池种和变种只保存在 `identity` 中，整合时按公告类型补入派生结果；不需要在 `data` 中重复填写。整合器当前已经读取 `missing/*.json`，执行人工 Schema 校验、官方来源核对、关键差异检查，并将符合条件的新池候选交由 2-2 的正式发布校验。未知 ItemID 可先为 `null`，不得虚构 ID；资料不齐全的候选继续等待，不得猜测补齐。

## 人工先发布、官方后补的处理

1. 人工 `missing` 来源可先生成候选并经 2-2 追加正式 v1（如合法且未发布）；这**不表示官方公告已经取得**，也**不能删除既有网络重试 pending**。
2. 采集器继续按正常发现/临时网络 pending 计划下载真实官方公告；当前日定时为 18:17 主采集与 18:27、18:37、18:47、18:57 条件重试。不存在文章 ID 的纯缺帖不应凭空制造网络 `pending`，等待正常公告发现即可。
3. 恢复官方文章后，用真实 `postId` 解析，按 `identity` 把官方来源和原人工来源识别为**同一个卡池**；不得把新的 `postId` 当作另一个新池。保留人工来源/证据，记录自动、人工、已发布 v1 三方比较结果。
4. 官方恢复成功即结束相应**下载 pending**。人工与官方数据一致时标记已核对；有差异时归入差异复核，不因已有人工作成 v1 就忽略正式官方结果。
5. **关键冲突**（版本、期数、池种、UP 名单、起止时间、确定的 ItemID 等）：受影响池停止自动修订并创建/更新 GitHub Issue，**已发布正式 v1 原样保留、不自动覆盖/回滚**，其他正常池仍可发布。**非关键差异**通过 Issue 提醒，不阻断其他池。
6. 对已发布池的修正只走 `manual/genshin_<版本>.json` 的 `existing`，用正式内部 ID 定向修订；`upcoming` 与恢复的官方候选都不能反向修改已发布池。
7. Issue 需记录原人工来源、真实文章 ID/URL、差异字段及人工/官方/现有 v1 的值、关键性和处理结论；确认解决后写明最终采用结果、修改范围及验证结论并关闭。若官方长期恢复失败，保留人工已发布状态，同时按既定通知策略提醒官方来源仍未核实，不能将缺帖错误假装已解决。

**使用提醒**：新增人工文件并不等于已发布。须经过 2-1 的公告整合检查、2-2 的正式 V1 校验及发布；官方后来恢复且数据冲突时，已发布 V1 不会自动覆盖，需通过 Issue 人工复核。
