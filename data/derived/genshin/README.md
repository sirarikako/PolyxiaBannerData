# 原神派生数据目录说明

本目录保存从**原神米游社简体中文官方公告**提取、关联和校验得到的内部 JSON，以及增量采集状态。这里是从原始公告到 v1 发布的**中间处理层**，不是对外提供的正式卡池数据；正式数据位于 [`public/v1/genshin.json`](../../../public/v1/genshin.json)。

## 各文件夹的用途

| 文件夹 | 主要用途 | 典型文件 / 内容 | 在现役流程中的作用 |
| --- | --- | --- | --- |
| [`notice-discovery/`](notice-discovery/) | 记录米游社公告列表的**增量发现状态**和采集结果 | `notice-discovery_zh-CN_checkpoint.json`（两类列表的锚点、待处理 `pending`、已完成 `completed`、人工复核状态等）；`notice-discovery_zh-CN_report.json`（本轮报告） | 每日采集会读取并更新，**不能当作普通临时文件删除**，否则可能导致重复采集或丢失待处理状态 |
| [`version-updates/`](version-updates/) | 保存按版本解析的**版本更新说明**，包括版本号、维护开始时间和新增角色、武器 | `version-update_zh-CN_7.1.json` | 为后续整合提供版本和维护时间依据；**不是单独的卡池公告** |
| [`wish-previews/`](wish-previews/) | 保存按版本、期数解析的**活动祈愿预告**，包含该期的时间和 UP 范围 | `wish-preview_zh-CN_7.1-phase-2.json` | 用于识别卡池所属版本/期数、核对时间；预告通常汇总整期，**不能单凭预告推定每个池子的完整名单** |
| [`wish-notices/`](wish-notices/) | 保存逐篇解析的**正式祈愿公告**，包含池名、池种、UP 名单、时间及图片 OCR 识别证据 | `wish-notice_zh-CN_78782590.json`（文件名使用公告文章 ID） | 按单个祈愿池整合的核心输入；需要图中文字时在 Action 临时下载并 OCR，**不在仓库存放下载的图片** |
| [`v1-candidates/`](v1-candidates/) | 将版本更新、祈愿预告、祈愿公告及公告级人工补充**逐池整合**为接近 v1 结构的候选数据 | `v1-candidate_zh-CN_78782590.json`，含 `status`、`v1Draft`、来源和证据 | 供 v1 导入器读取；只有符合发布条件的候选才可进入发布步骤。**候选不等于已发布，内部 ID 由正式导入流程处理** |
| [`v1-readiness/`](v1-readiness/) | 保存整合过程的**就绪性与最终诊断报告**，包括缺失、冲突、人工比较、待关注项目 | `v1-readiness_zh-CN.json`（逐篇匹配状态）；`v1-final-review_zh-CN.json`（最终安全预览和通知判断） | 用于检查哪些单池可继续处理、哪些需要人工复核，以及生成 GitHub Issue 通知；**不是正式卡池数据** |

各目录如有自己的 README，可打开查看更详细的字段说明或原始用途；其中早期文档提到的临时 Action 可能已经退役，应以当前 [`scripts/README.md`](../../../scripts/README.md) 和实际工作流为准。

## 数据如何流转

```text
米游社公告列表（type=1 / type=3）
  ├─ data/announcements/genshin/       ← 当次 Runner 临时原文和图片（不提交 Git）
  └─ notice-discovery/                  ← 持久增量检查点及采集报告
       ├─ version-updates/             ← 持久版本更新说明
       ├─ wish-previews/               ← 持久祈愿预告
       └─ wish-notices/                ← 持久单篇祈愿公告结构化结果
                      │
                      ▼
               v1-candidates/          ← 按单池关联、人工补缺/比对
                      │
                      ├─ v1-readiness/  ← 就绪性、异常、最终预览与通知依据
                      ▼
               v1 导入与正式校验
                      ▼
               public/v1/genshin.json  ← 正式数据
```

- **2-1 原神公告每日自动采集与解析**：更新采集状态及本目录中的派生结果；原始公告仅在 Runner 临时使用；可以预览或在临时副本测试 v1 导入，**不修改正式 v1**。
- **2-2 原神每日 V1 数据自动发布**：读取可用的 `v1-candidates/` 及版本人工设定，合法时向正式 v1 **追加新池**或按内部 ID **更新已有池**；随后由本仓库独立工作流刷新 Manifest。
- **人工数据不放在本目录**：公告级补充/比较位于 `manual/notices/genshin/zh-CN/miyoushe/<文章ID>.json`，版本级新旧池修改位于 `manual/genshin_<版本>.json`。本目录记录的是处理后的结果、比对证据和状态。
- **文件名约定**：`zh-CN` 为简体中文；版本更新按版本命名、预告按版本加期数命名、祈愿公告及单池候选按文章 ID 命名。不能因为文件已经存在就认定它已发布。

## 维护注意事项

1. **不要手动重置或删除** `notice-discovery/` 的 checkpoint；遇到待处理、网络失败或人工复核事项时，应保留相关状态与证据。
2. 重新解析或修正公告应经过对应脚本和检查流程；不要直接把 `wish-notices/`、`wish-previews/` 或 `v1-candidates/` 下的 JSON 当作正式发布数据。
3. 原始公告和图片仅在当次 Runner 临时使用，不作为本仓库持久化输入。
4. 本目录的结构化数据与扫描状态由本仓库生产工作流直接保存。

更多执行命令、工作流触发关系和故障处理参见 [`scripts/README.md`](../../../scripts/README.md)。

## 缺少官方文章时的人工来源（已接入）

已确定允许在**官方真实帖子仍缺失**时使用 `manual/notices/genshin/zh-CN/missing/<逻辑身份>.json` 提供人工来源，生成满足安全校验的 v1 新池候选；采用 `genshin-missing-notice-v1`、`identity`、`data`、`evidence`，而不是虚构 postId；人工只在 `identity` 填写一次版本/期数/池种，稳定 `sourceKey`、文件名和候选身份字段将由程序自动派生。三类模板与完整说明见 [人工示例](../../../manual/templates/README.md) 及 [missing 规则](../../../manual/notices/genshin/zh-CN/missing/README.md)。

当前整合时，缺帖候选应以逻辑身份防止与后来恢复的官方公告重复建池；已经人工先发布的 v1 不因为官方出现就自动被覆盖。官方取得后，下载 pending 结束，但继续核对官方、人工、正式 v1 三方数据；关键冲突经 Issue 人工审查，其他池不受影响。**仅有集录/溯光等特殊池的祈愿预告可不填写 `data.up`；普通角色/武器池仍须核对整期五星 UP，最终由整合器结合其他卡池判断。**

现役整合器也读取 `missing/` 人工来源；实际发布仍须通过候选、冲突和 Schema 校验，不能直接将人工内容当作官方原文。
