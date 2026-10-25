# 原神 v1 人工设定（按游戏_版本拆分）

人工文件按 `游戏_版本.json` 命名，直接放在 `manual/` 根目录，例如：

```text
manual/
├── genshin_7.1.json
├── genshin_7.2.json                 # 需要配置时自行创建
├── genshin_月之八.json             # 版本名称可使用中文
└── archive/
    └── genshin_旧版本.json         # 人工归档，只在全部完成后移动
```

原神与星铁分别使用 `genshin_<version>.json`、`starrail_<version>.json`，由各自的正式导入器处理。以下先以原神为例。

每个文件必须含 `format: "genshin-v1-overrides-v2"`、`game: "genshin"`、`locale: "zh-CN"`、与文件名一致的 `version`、`upcoming` 和 `existing` 数组。

- **upcoming**：新池尚无内部编号时，按 `phase` + `poolType` 匹配。可再加 `variant`、`bannerName` 或祈愿公告 `postId` 精确定位；版本直接从文件名和 `version` 获得，`match.version` 可省略。仅用于新池追加，绝不自动修改已有池。
- **existing**：已发布卡池使用唯一内部 `id` 定向更新；内部 ID 必须属于这个文件指定的版本。没有该 ID 或放错版本立即报错。

两组条目均可使用 `set`（对象递归合并；一般数组整体替换，`regions` 根据 `server` 合并）、`itemIds`（中文 UP 名称到 ID 字符串/null）、`addSources`（追加来源并去重）。不可在 `set` 修改内部 ID、版本、期数和池种。

## 处理状态

- `status: "pending"`：待处理。**省略 status 与 pending 等价。**
- `status: "completed"`：已处理。导入器不再运行此条人工设定；`appliedId` 记录对应的 v1 内部编号，`completedAt` 记录处理时间。
- **预览（默认）**只计算将新增、将修订、将完成的条目，不改 v1 或人工文件。
- **正式运行 `--write`**：先校验并写入 v1，成功后将完成的条目自动标为 `completed`。尚未匹配新公告的 `upcoming` 继续 `pending`，即使同文件其他池已导入。
- 整个版本所有条目都 `completed` 时，可手动把文件移到 `manual/archive/` 备份；导入器不扫描子目录。不要自动移动尚有 `pending` 的文件。
- 某次写入 v1 后若人工状态更新前中断，重试时只在原本预设的值**已完整存在**于该池时补记 `completed`，绝不因此重新覆盖旧池。已经 `completed` 的条目若想重新修订，必须确认之后显式重新设为 `pending` 或添加新的人工条目。
- 对已经存在但尚未合并人工值的卡池，`upcoming` 不会反向覆盖它；需要将设定转为 `existing` 按内部 ID 修改。

## 配置示例（仅说明，不能当成真实数据发布）

例如 `manual/genshin_7.2.json`：

```json
{
  "format": "genshin-v1-overrides-v2",
  "game": "genshin",
  "locale": "zh-CN",
  "version": "7.2",
  "upcoming": [
    {
      "status": "pending",
      "match": {"phase": 1, "poolType": "character_event", "bannerName": "示例祈愿"},
      "itemIds": {"示例角色": "12345678"},
      "set": {"names": {"ja-JP": "例の祈願"}}
    }
  ],
  "existing": []
}
```

已有卡池的人工修改请放在**该池所属版本**文件的 `existing`，比如：

```json
{
  "status": "pending",
  "id": "gi-000299",
  "set": {"names": {"en-US": "Example Name"}}
}
```

## 使用

```bash
python -m scripts.transform.assemble_genshin_wish_candidates_zh_cn
python -m scripts.release.import_genshin_v1_zh_cn
python -m scripts.release.import_genshin_v1_zh_cn --write
python -m scripts.release.validate_v1 --datasets-only
```

`--manual <目录>` 可指定另一个人工版本目录。输入公告候选必须是已整合的 `ready_candidate`，第一期“版本更新后”需要在候选时间证据里带版本维护开始时刻。脚本不会联网，也不更新 `manifest.json`；后者仍由现有 Action 自动维护。

本目录属于本公开仓库生产流水线的人工输入。真实 `public/v1/` 未经人工确认前不要用虚构数据测试 `--write`；模拟测试只在临时副本上运行。

## 公告级人工数据

公告级人工数据按[公告专用说明](notices/README.md)分为两套互不混淆的格式：真实帖子存在时用 `manual/notices/genshin/zh-CN/miyoushe/<文章ID>.json`（`genshin-notice-manual-v1`）；官方帖子完全缺失时，使用独立的 `manual/notices/genshin/zh-CN/missing/<逻辑身份>.json`（`genshin-missing-notice-v1`）。后者不伪造 postId，人工仅在 `identity` 填写一次版本、期数、池种（及变种），并填写所需业务 `data`；`sourceKey`、文件名和候选的身份字段均约定由后续程序派生，不需要也不允许在人工 JSON 手写 `sourceKey`。

公告人工只负责补缺、官方恢复后的自动核对和来源证据，**与本目录 `upcoming/existing` 严格区分**；正式 v1 已有池只允许通过 `existing` 按内部 ID 修改。无帖子人工源满足条件后可先生成 v1 候选、发布后保持网络 pending 继续等待官方核对，这是已确认方案。现役整合器已经接入缺帖人工来源，仍须通过候选完整性、来源冲突和正式发布校验；创建人工文件本身不代表发布成功。

## 自动发布与通知

每日安全预览成功后，由独立的 `2-2_原神每日V1数据自动发布` Action 导入已持久化的合法候选与此目录的待处理版本人工 JSON。用户向 `main` 提交 `manual/genshin_*.json` 也会触发同一发布入口；`existing` 不要求出现新的公告。

正式工作流采用 `--isolate-invalid --write`：坏候选或版本人工文件记录到发布结果并通过 Issue 通知，但不妨碍其他合法卡池更新。关键公告字段冲突阻断对应候选；非关键差异仅触发 Issue 提醒。两个来源的差异一律记录，不能用 `upcoming` 覆盖已经发布的卡池。

新数据与 `completed` 状态必须在本公开仓库同一次 Git 提交成功后才视为正式写入；随后由本仓库的 1-1 工作流刷新 Manifest。异常修复后可由后续运行自动关闭对应 Issue。


## 星铁版本人工配置

星铁另用 `manual/starrail_<版本>.json`，格式 `starrail-v1-overrides-v1`（`game=starrail`、`locale=zh-CN`）。`upcoming` 必须通过 `match.phase`、`poolType`、`bannerName` 定位新池；同版本同期同名但五星不同可加 `match.fiveStarName`。`existing` 必须明确正式内部 `hsr-xxxxxx` ID，仅用于旧池人工定向修订。两组均可写 `set`、`itemIds`、`addSources`，每条状态为 pending/completed。

公告人工来源（真实帖子或缺帖）由 `manual/notices/starrail/zh-CN/missing/README.md` 说明；不能与版本级人工混用。公开结构参考 `schemas/manual/starrail-v1-overrides.schema.json`。正式导入成功后在本仓库同一次提交保存 V1 与人工完成状态，再由 1-1 刷新 Manifest。
