# scripts：数据抓取、整理、v1 发布与仓库同步

> **Public P2 迁移说明（2026-10-24）**：本文件保留自 Private 开发仓库，后文涉及旧 1-2 跨库同步、持久 `posts/*.json`、历史 Actions 时序的内容仅作旧流程参考，**不代表 Public 的现役部署**。Public 正式迁移目标为单仓执行 0-1、1-1、2-1/2-2、3-1/3-2，不再同步库间 v1；公告完整原文及图片不进入 Public Git，采集时仅临时使用。生产工作流当前只暂存于 `deploy/production/workflows/`，未启用；P3 仍需验证缺少原文时的人工恢复路径。以 [`P2 迁移报告`](../deploy/migration/P2-staging-report.md) 和 [`生产暂存说明`](../deploy/production/README.md) 为准。

本目录集中管理 **CastoriceWishBannerData（私有仓库）** 的公告采集、解析、候选整合、v1 导入、数据校验与发布辅助脚本。本文以当前 `main` 分支的实际 GitHub Actions 和脚本行为为准，供仓库开发与运维使用，不属于同步到公开仓库的 API 文档。

> 当前已实现 **原神简体中文公告增量自动采集与 v1 自动发布**；原神与星穹铁道的既有 v1 数据均参与 Manifest 校验和公开同步。**星铁的 3-1/3-2 自动化代码已在 PR #16 建立，但尚未合并 main；合并之前不可宣称已正式启用。**

## 1. 正式工作流总览

```text
[米游社原神公告 type=1 / type=3]        [人工公告 JSON：真实帖子 / 缺帖]
                │                              │
                ▼                              │
  2-1_原神公告每日自动采集与解析 ◄─────────────┘
      │ 发现新公告 → 保存原始 JSON → 单篇解析
      │ 祈愿公告临时下载图片并用 Tesseract 识别时间
      │ 版本更新 + 祈愿预告 + 祈愿公告按单池整合
      │ 保存候选、检查点、诊断报告；v1 仅安全预览
      ▼
  data/derived/genshin/v1-candidates/         [人工版本 JSON]
                │                              │
                ▼                              ▼
  2-2_原神每日V1数据自动发布 ◄──────── manual/genshin_<版本>.json
      │ 逐池校验、隔离异常、追加新池、按 ID 修改旧池
      │ 同一次 Git 提交写入 v1 和人工 completed 状态
      ▼
  public/v1/genshin.json
      │ 正式 v1 有变化时显式触发；直接人工修改 v1 也可触发
      ▼
  1-1_V1 Manifest自动更新
      │ 校验数据 → 更新 public/v1/manifest.json
      ▼
  1-2_公开仓库数据自动同步
      │ 验证完整公开数据、rsync public/ 与 schemas/
      ▼
  sirarikako/PolyxiaBannerData（公开仓库）
```

**另一路触发**：`public/`（排除两个游戏 v1 JSON 的直接 push）或 `schemas/` 发生符合条件的变更，可以触发 `1-2`，但仍必须通过完整校验。`1-1` 同时处理原神与星铁的已有 v1 数据，不负责抓公告。

### GitHub Actions 对照

| 编号与显示名 | Workflow 文件（仓库根目录的 `.github/workflows/`） | 主要触发方式 | 是否修改正式数据 |
| --- | --- | --- | --- |
| **1-1_V1 Manifest自动更新** | [refresh-v1-manifest.yml](../.github/workflows/refresh-v1-manifest.yml) | v1 JSON 等指定文件推送到 `main`，或手动触发；2-2 在 v1 变化后显式触发 | 只更新 `public/v1/manifest.json` |
| **1-2_公开仓库数据自动同步** | [sync-public-data.yml](../.github/workflows/sync-public-data.yml) | 1-1 成功完成；符合路径条件的 `public/` / `schemas/` 推送；或手动触发 | 将已校验的 `public/`、`schemas/` 同步到公开库 |
| **2-1_原神公告每日自动采集与解析** | [genshin-notices-zh-cn-daily-preview.yml](../.github/workflows/genshin-notices-zh-cn-daily-preview.yml) | 每天 UTC 10:17（北京时间 18:17）正常采集；18:27、18:37、18:47、18:57 条件重试 pending；`main` 上缺帖人工 JSON 变更时只重新整合；或手动触发 | 保存原始公告、衍生候选、报告与检查点；**不写正式 v1** |
| **2-2_原神每日V1数据自动发布** | [genshin-v1-auto-publish.yml](../.github/workflows/genshin-v1-auto-publish.yml) | 2-1 的 `collect-and-preview` 作业实际成功完成；`main` 上 `manual/genshin_*.json` 变化；或手动触发 | 校验后写 `public/v1/genshin.json` 和人工完成状态 |
| **Development scripts tests** | [development-scripts-tests.yml](../.github/workflows/development-scripts-tests.yml) | PR、相关脚本/测试文件推送或手动触发 | **只读测试**；不参加正式发布依赖链 |

> GitHub `workflow_run` 依赖的是上表的 **Action 显示名**，不是 YAML 文件名。修改名称时必须同步调整依赖方。2-2 显式执行 `gh workflow run refresh-v1-manifest.yml` 使用的是 **文件名**，改显示名时无需改此命令。

## 2. 原神简体中文抓取与解析（2-1）

### 2.1 发现与保存官方公告

入口：`collect/collect_genshin_notices_zh_cn.py`。

- 来源：米游社原神公告列表 `getNewsList`，`gids=2`，`type=1`（公告）与 `type=3`（预告）两个栏目；单篇详情使用 `getPostFull`。
- 增量机制：首次建立列表基线，以后使用重叠文章 ID 锚点查找新公告；两栏独立维护进度。2-1 正常采集调用时使用 `--max-pages 15`。
- **当天限次重试**：18:17 正常采集结束后，18:27、18:37、18:47、18:57 四个调度点由 2-1 自身调度，只有存在**可自动重试**的 `checkpoint.pending` 才进入后续作业；定时重试使用 `--retry-only`，只处理可自动重试的 pending，不请求两栏公告列表、不推进锚点。没有可自动重试 pending 时跳过采集 Job（即使 pending 中还有不能自动重试的条目）；OCR/解析需要人工复核的 `manualReview` 不参与重试。GitHub 定时启动可能延迟，并非精确计时器。
- 只识别脚本支持的 **版本更新、活动祈愿预告、祈愿公告**；其他文章不会自动生成 v1 候选。
- 成功取得的单篇完整原文保存在 `data/announcements/genshin/zh-cn/miyoushe/posts/<文章ID>.json`。
- 采集状态、待重试队列、待人工复核情况持久化在 `data/derived/genshin/notice-discovery/`，避免每次从零开始。

### 2.2 三类单篇解析器

采集器会按文章类型调用下面三个模块，分别生成 JSON；各解析器只针对指定文章，不承担列表发现或正式 v1 发布。

| 文章类型 | 解析脚本（`scripts/transform/`） | 主要提取内容 | 默认输出位置 |
| --- | --- | --- | --- |
| 版本更新 | `build_genshin_version_update_zh_cn.py` | 版本、维护开始时间、新角色/武器等 | `data/derived/genshin/version-updates/version-update_zh-CN_<版本>.json` |
| 祈愿预告 | `build_genshin_wish_preview_zh_cn.py` | 版本、期数、起止时间、预告 UP 范围 | `data/derived/genshin/wish-previews/wish-preview_zh-CN_<版本>-phase-<期数>.json` |
| 祈愿公告 | `build_genshin_wish_notice_zh_cn.py` | 池名、池种、五星/四星 UP、可选范围、时间与 OCR 证据 | `data/derived/genshin/wish-notices/wish-notice_zh-CN_<文章ID>.json` |

**祈愿公告图片处理：**

1. `collect/download_genshin_notice_images_zh_cn.py` 从这篇公告的官方图片 URL 下载到 Action 的 `TemporaryDirectory`，同时生成临时图片索引。
2. `transform/recognize_genshin_wish_image_zh_cn.py` 使用本地 Tesseract OCR 识别图片中的起止时间；物品名称仍以公告正文为依据。
3. 本轮识别结束后，临时图片和图片索引被清除。**图片不会随本流程提交到 Git，也不会同步到公开仓库。** 解析后的时间、状态与必要的来源证据保存在祈愿公告 JSON。
4. `collect/run_genshin_wish_notice_with_images_zh_cn.py` 是指定单篇祈愿公告的辅助运行入口，不是每日 Action 直接调用的总入口。

### 2.3 逐池整合与人工核对

入口：`transform/assemble_genshin_wish_candidates_zh_cn.py`。

- 读取上述三类已保存的解析 JSON，不再次联网抓取公告。
- 官方来源优先按 **祈愿公告 OCR 结束时间**关联预告，再按 **版本号**关联版本更新公告；不是靠五星角色名称推断期数，也不用等整期所有卡池出现才处理。
- `transform/genshin_notice_manual_zh_cn.py` 读取真实帖子人工文件 `manual/notices/genshin/zh-CN/miyoushe/<文章ID>.json`，自动结果缺失时补充，双方都有值时比较。
- `transform/genshin_missing_notices_zh_cn.py` 读取 `manual/notices/genshin/zh-CN/missing/*.json`，校验 Schema，按 `noticeType + identity` 派生稳定人工来源键，并在整合时与可能恢复的官方来源匹配、比较；不伪造官方文章 ID。
- **关键差异**（版本、期数、池种、UP、时间等）阻断受影响的候选；**非关键差异**只记录并通知。缺少其他必要公告时保持 `waiting`，不因正常等待建立 Issue。
- 只有完整且通过核对的单池候选标为 `ready_candidate`；已发布池不由重新解析的候选自动覆盖。

输出：

- `data/derived/genshin/v1-candidates/v1-candidate_zh-CN_<来源键>.json`：逐池 v1 候选；官方来源键为文章 ID，纯人工缺帖来源键由身份派生。
- `data/derived/genshin/v1-readiness/v1-readiness_zh-CN.json`：逐池匹配状态、来源、缺失、冲突、人工比对详情。
- `scripts/release/report_genshin_v1_preview_zh_cn.py` 生成 `data/derived/genshin/v1-readiness/v1-final-review_zh-CN.json`：最终安全预览与通知诊断。
- `scripts/collect/reconcile_genshin_manual_review_zh_cn.py` 在人工恢复成功后整理公告采集 checkpoint 状态；**不写正式 v1**。

2-1 还会调用导入器进行 **只读预览**，并在 `/tmp/` 的临时副本测试写入。调试报告会随 Actions Artifact 上传；**正式 `public/v1/genshin.json` 始终保持不变**。

## 3. 原神 v1 导入与发布（2-2）

入口：`release/import_genshin_v1_zh_cn.py`。

| 输入 | 用途 |
| --- | --- |
| `data/derived/genshin/v1-candidates/*.json` | 只读取合法 `ready_candidate`，按版本/期数/池种等去重、分配内部 ID、追加新池 |
| `manual/genshin_<版本>.json` | 版本级人工配置：`upcoming` 补充尚未发布的新池，`existing` 根据内部 ID 定向更新已有池 |
| `public/v1/genshin.json` | 已发布数据、现有 ID、去重与修改目标 |

处理规则：

1. 工作流从最新 `main` 重新计算，不重新联网抓公告，也不重新 OCR。
2. 使用 `--isolate-invalid --write` 隔离不合法的单池候选/人工配置，允许其他合法项继续；最终依然执行全量 v1 校验与合约测试。
3. **`upcoming` 仅在新池首次追加前合并**。已有池不被公告候选反向覆盖；需要补充已有池时改用 `existing`。
4. 成功应用的版本人工条目标记 `completed`，记录 `appliedId` 和 `completedAt`；未匹配的 `upcoming` 保持 `pending`。所有完成条目可按 `manual/README.md` 所述自行归档到 `manual/archive/`。
5. v1 数据与本轮人工完成状态由 **同一次 Git Commit** 提交到私有仓库 `main`；若推送遇到并发提交，重新读取并计算，绝不强制覆盖。
6. 只有 `public/v1/genshin.json` **实际变化**时，2-2 才显式启动 `1-1` 刷新 Manifest。`completed` 表示人工设定已应用到私有 v1，**不代表公开仓库同步成功**。

异常通过 `release/notify_genshin_v1_publication.py` 管理对应的 GitHub Issue，报告作为 Actions Artifact 保存（`genshin-v1-publish-report`，默认保留 30 天）。直接执行导入器不加 `--write` 时只返回预览，不会修改文件。

## 4. Manifest 与公开仓库同步（1-1、1-2）

### 4.1 1-1：刷新 Manifest

- 入口：`release/refresh_v1_manifest.py`。
- 输入：`public/v1/genshin.json`、`public/v1/starrail.json` 及已有 `public/v1/manifest.json`。
- `release/validate_v1.py --datasets-only` 先验证数据，计算对应 JSON 的 SHA-256 和卡池数量，再更新 `public/v1/manifest.json`（必要时刷新 `generatedAt`）。
- 随后执行 `validate_v1 --public` 和 `tests/test_v1.py`，通过后单独提交 Manifest。
- 直接修改 `public/v1/genshin.json` 或 `public/v1/starrail.json` 并推送到 `main`，同样可以触发 1-1。**不要手动在同一提交里更新 Manifest。**

### 4.2 1-2：同步公开仓库

- Action 文件：[sync-public-data.yml](../.github/workflows/sync-public-data.yml)。
- 从私有仓库最新 `main` 检出源，重新验证完整的 `public/v1/manifest.json`、所有公开 v1 数据与 Schema。
- 通过密钥 `CASTORICEBANNERDATA_TOKEN` 访问公开仓库 `sirarikako/PolyxiaBannerData`。
- 仅对 **`public/` 和 `schemas/`** 两个目录使用 `rsync -a --delete` 同步至公开仓库的同名目录；没有变化就不提交。
- `manual/`、`data/`、`scripts/`、`archive/`、`.github/` 不属于公开同步范围；这份 README **不会**同步到公开仓库。
- 公开数据同步是发布链的最后一环；若此步骤失败，私有 v1 可能已经提交成功，必须查看同步 Action 的结果，不应把前一阶段成功视为公开发布完成。

## 5. 脚本职责速查

下面按相对 `scripts/` 的路径列出当前文件。带“辅助/历史”的脚本**不在现有 2-1 → 2-2 主要日常调用链中**，不应误认为需要每天分别执行。

| 脚本 | 角色 |
| --- | --- |
| `collect/collect_genshin_notices_zh_cn.py` | **2-1 入口**；增量列表、原文、状态与三个解析器的调度 |
| `collect/download_genshin_notice_images_zh_cn.py` | 仅为祈愿公告临时下载图片、验证并生成临时索引 |
| `collect/reconcile_genshin_manual_review_zh_cn.py` | 处理已用人工数据恢复的公告 checkpoint 状态 |
| `collect/notify_genshin_notice_problems.py` | 公告/OCR/整合异常的 Issue 通知、去重及结清 |
| `collect/run_genshin_wish_notice_with_images_zh_cn.py` | 指定单篇祈愿公告的图片下载和解析辅助入口 |
| `collect/collect_miyoushe_announcements.py` | **历史/辅助**全量归档采集器；不等同于 2-1 增量采集 |
| `transform/build_genshin_version_update_zh_cn.py` | 版本更新公告单篇解析 |
| `transform/build_genshin_wish_preview_zh_cn.py` | 祈愿预告单篇解析 |
| `transform/build_genshin_wish_notice_zh_cn.py` | 祈愿公告单篇解析 |
| `transform/recognize_genshin_wish_image_zh_cn.py` | 本地图片时间 OCR |
| `transform/genshin_notice_manual_zh_cn.py` | 真实帖子公告级人工数据读取、补缺和差异分类 |
| `transform/genshin_missing_notices_zh_cn.py` | 无真实帖子时的人工公告读取、Schema 校验、身份派生、官方恢复后的合并与比较 |
| `transform/assemble_genshin_wish_candidates_zh_cn.py` | **2-1 候选整合入口**；按单池合并生成 v1 候选 |
| `transform/select_miyoushe_version_notices.py` | 公告标题分类辅助（也由历史采集工具复用） |
| `transform/analyze_miyoushe_banner_notices.py` | **历史/辅助**公告候选只读审查，不直接发布 |
| `release/genshin_manual_versions.py` | 版本级人工 JSON 格式、匹配和完成状态工具 |
| `release/import_genshin_v1_zh_cn.py` | **2-2 导入入口**；预览、逐池隔离、v1 写入和人工状态 |
| `release/report_genshin_v1_preview_zh_cn.py` | 汇总最终只读诊断和通知依据 |
| `release/notify_genshin_v1_publication.py` | 正式导入异常的 Issue 通知 |
| `release/validate_v1.py` | Schema、业务字段、跨池关系及 Manifest 校验 |
| `release/refresh_v1_manifest.py` | **1-1 入口**；计算 SHA-256、条数，维护 Manifest |

**历史全量归档工具** `collect_miyoushe_announcements.py` 的输出集中在 `data/announcements/genshin/zh-cn/miyoushe/`（如 `index.json`、`collection-report.json`、`checkpoint.json`，以及原文和历史页记录）；它和每日增量采集在 `data/derived/genshin/notice-discovery/` 使用的 checkpoint **不是同一个文件**。

## 6. 主要数据文件与保存位置

所有位置均从仓库根目录计算，而不是从 `scripts/` 当前目录计算。

| 位置 | 归属 | 内容和保存策略 |
| --- | --- | --- |
| `data/announcements/genshin/zh-cn/miyoushe/posts/<文章ID>.json` | 私有采集数据 | 米游社单篇官方原文，持久保存 |
| `data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json` | 私有采集状态 | 增量进度、`pending`、`manualReview`、`completed` 等，持续维护 |
| `data/derived/genshin/notice-discovery/notice-discovery_zh-CN_report.json` | 私有采集报告 | 本轮发现、完成与失败情况 |
| `data/derived/genshin/version-updates/` | 私有解析数据 | 版本更新 JSON |
| `data/derived/genshin/wish-previews/` | 私有解析数据 | 祈愿预告 JSON |
| `data/derived/genshin/wish-notices/` | 私有解析数据 | 祈愿公告 JSON（包括 OCR 状态/证据） |
| `data/derived/genshin/v1-candidates/` | 私有候选数据 | 按文章 ID 或人工来源键拆分的 v1 待发布候选 |
| `data/derived/genshin/v1-readiness/` | 私有诊断数据 | `v1-readiness_zh-CN.json` 与 `v1-final-review_zh-CN.json` |
| `manual/notices/genshin/zh-CN/miyoushe/<文章ID>.json` | 人工输入 | 针对真实米游社文章的人工补缺与比较 |
| `manual/notices/genshin/zh-CN/missing/*.json` | 人工输入 | 官方帖子缺失时按逻辑身份提供三类公告，生成候选并在恢复后核对 |
| `manual/genshin_<版本>.json` | 人工输入与状态 | v1 新池补充 `upcoming` / 旧池修改 `existing`，逐条标记完成 |
| `public/item-mappings/genshin/zh-CN.json` | 公开映射 | 解析时匹配原神简中物品名称与 itemId；缺失值不凭空推测 |
| `public/v1/genshin.json` | 正式公开源数据 | 2-2 自动导入后更新，或经过审查人工修正 |
| `public/v1/starrail.json` | 正式公开源数据 | 现有星铁 v1，参与 Manifest/同步；目前不由原神采集脚本更新 |
| `public/v1/manifest.json` | 正式公开元数据 | 由 1-1 计算并提交 |
| `schemas/` | 正式公开 Schema | 校验使用，并由 1-2 同步 |
| Actions 运行器的 `/tmp/` 与 Artifact | 临时产物 | 临时下载图片、预览副本、发布/采集调试报告；不作为 Git 永久文件 |

仓库可能仍包含 `data/derived/genshin/` 下早期整理的历史目录；它们不是这条正式增量采集与自动发布链的输入约定。判断是否在用，请以当前 workflow 调用链及脚本常量为准。

## 7. 通知、失败恢复和操作注意事项

- **正常等待**：`unmatched_end_time`、`waiting_identity_preview`、`waiting_version_update` 等公告尚未关联完整时不建立 Issue；没有新候选、待未来新池的 `upcoming` 未匹配，也不作为异常。已有 v1 数据不会因等待而自动改写。
- **临时网络问题**：保留 `checkpoint.pending`；北京时间每天 18:17 正常执行，18:27、18:37、18:47、18:57 最多四次有条件检查。2-1 的重试 cron 直接使用 `retry_only` 模式，不扫描新帖；无可重试 pending 时 2-1 只做轻量检查并跳过处理 Job，2-2 也会检查上游作业结果并跳过发布。GitHub 定时触发有可能延迟。累计多次失败后由最终诊断提醒。
- **OCR/解析失败及关键字段冲突**：暂停受影响的单篇，保留证据；必要时使用公告级人工 JSON 补充，修复后重建候选。
- **非关键人工差异**：候选可以继续发布，但通过 Issue 留下人工核对记录。
- **Issue 与邮件**：只有 OCR/解析错误、关键冲突、连续失败等需要关注的问题才通知。通知脚本按公告/发布问题去重；新问题由 Actions 机器人创建并指派仓库所有者，有实际变化时评论，问题消失且检查可信时自动关闭。Issue 通知能否投递邮件取决于 GitHub 个人通知设置；**Action 本身真正失败**则沿用 GitHub 的工作流失败通知。
- **私有 vs 公开成功**：2-2 成功仅表明已在私有 v1 生成有效提交；应继续确认 `1-1` 与 `1-2` 成功。
- **严禁**通过修改 checkpoint、伪造公告或预览文件，将未核实的卡池当作正式发布数据。正式自动发布不会自动从未知第三方来源猜测新 itemId。
- 修改 `workflow_run` 工作流显示名、Manifest 调用文件名、发布目录或公开仓库目标时，必须检查整个触发链及相应测试。

## 8. 从仓库根目录执行的只读检查示例

```bash
# 整合已有原神公告，但不写候选或报告
python -m scripts.transform.assemble_genshin_wish_candidates_zh_cn --check-only

# 预览 v1 的新增、修订、异常隔离结果；不写正式 v1
python -m scripts.release.import_genshin_v1_zh_cn --isolate-invalid

# 验证 v1 数据（不要求 Manifest 已刷新）
python -m scripts.release.validate_v1 --datasets-only

# 正式公开数据与 Manifest 完整一致性验证
python -m scripts.release.validate_v1 --public

# 开发脚本回归（不执行正式发布）
python -m pytest -q tests --ignore=tests/test_v1.py
```

**不要把 `--write` 加到本地试验命令中直接修改真实 `public/v1/`。** 正式变更应经 2-2 或经过审核的明确修订流程提交。关于人工配置格式，请参见 [manual/README.md](../manual/README.md) 与 [manual/notices/README.md](../manual/notices/README.md)；关于公开接口仅参见 [public/v1/README.md](../public/v1/README.md)。

## 9. 无官方帖子时的人工公告补齐（已接入）

此功能已由 `transform/genshin_missing_notices_zh_cn.py` 和逐池整合器接入现有 2-1 → 2-2 链路，具备独立 Schema 校验与隔离端到端测试。**已验证的是功能与安全边界；正式新卡池的实际公告更新仍需在后续真实运行中观察。**

| 场景 | 人工文件位置 | 格式及识别依据 |
| --- | --- | --- |
| 已有真实米游社帖子，个别 OCR/字段缺失 | `manual/notices/genshin/zh-CN/miyoushe/<文章ID>.json` | `genshin-notice-manual-v1`，真实 `postId` |
| 官方尚未发布帖子、文章不可获取、没有可核实的真实文章 ID | `manual/notices/genshin/zh-CN/missing/*.json` | `genshin-missing-notice-v1`，`noticeType + identity` |

**格式与填写规范：**三类缺帖模板见 [manual/templates/missing/](../manual/templates/missing/)，Schema 见 [schemas/manual/genshin-missing-notice.schema.json](../schemas/manual/genshin-missing-notice.schema.json)，字段细节与文件名约定见 [missing README](../manual/notices/genshin/zh-CN/missing/README.md)。

- 版本更新只需 `identity.version`；预告需要版本与期数；单池祈愿公告需要版本、期数、池种，集录/溯光再指定 `variant`。此外应按模板提供对应最低业务信息及 `evidence.summary` 核实依据。
- 人工在 `identity` 中填写一次身份字段；`data` 不重复这些身份字段。程序由 `noticeType + identity` 自动派生 `sourceKey` 与人工 `externalId`（两者**不是**必须相等），不填写虚构的 `postId` 或官方 URL。
- 仅涉及集录/溯光的纯特殊池预告可不写 `data.up`；常规角色/武器池仍需可核实的五星 UP 信息。缺字段、Schema 无效或业务冲突时，不能把不完整候选发布为正式 v1。

### 运行、恢复及数据保护

1. **人工文件触发整合**：`missing/*.json` 推送到 `main` 后，2-1 不重新联网抓取，而是使用持久化的官方公告与人工文件重新整合；2-1 成功后 2-2 按正常安全校验处理合格候选。人工文件本身不直接修改正式 v1。
2. **人工可先于官方发布**：必要公告信息满足条件时可以生成 `ready_candidate`，由 2-2 向正式 v1 追加**尚未存在**的池。已经存在的池不因再次回放或人工缺帖候选而被覆盖；修订只能在 `manual/genshin_<版本>.json` 的 `existing` 指明正式内部 ID。
3. **pending 与缺帖分开**：网络下载失败仍保留可重试的 `checkpoint.pending`；纯缺帖但尚无官方文章 ID 时不虚构 pending。每日正常发现和现有条件重试机制继续工作；人工成功发布并不清理尚未解决的真实网络故障。
4. **官方后来恢复**：使用真实文章 ID 解析后按可核实的业务身份关联人工来源并比较，不能把同一个卡池当作第二个新池。官方、人工与已发布 v1 的关键差异保留证据并进行 Issue 复核；已有 v1 不自动回滚或反向覆盖，其他正常池仍可发布。
5. **等待与通知**：仅因缺少预告、版本更新或结束时间未匹配而处于普通 `waiting` 时不建立 Issue。确有 OCR 错误、关键差异、非法来源或累计重试失败时才按既有规则通知，同一问题去重；人工修复且最终检查可信后自动关闭相应 Issue。

相关隔离测试：`tests/test_genshin_missing_notices_zh_cn.py`、`tests/test_genshin_manual_postmerge_integration.py`。这些测试不会写正式 V1、Manifest 或公开仓库。


## 10. 星铁简体中文公告与自动发布（PR #16）

星铁没有原神祈愿预告的关联步骤，采用公告一览（米游社 `gids=6,type=1`）→ 版本更新／活动跃迁／联动跃迁分别解析 → 按单池组装 → 3-2 导入 → 现有 1-1／1-2 同步。**星铁完全采用文本解析，不安装 OCR。**

- **3-1**：`.github/workflows/starrail-notices-zh-cn-daily-preview.yml`。北京时间 18:21 主采集，18:31／18:41／18:51／19:01 有 pending 才重试。首次只建立最新列表锚点，不自动全量重放历史。只持久化 `data/announcements/starrail/`、`data/derived/starrail/` 及候选，不写正式 v1。
- **3-2**：`.github/workflows/starrail-v1-auto-publish.yml`。只读已持久化 ready 候选以及 `manual/starrail_<版本>.json`，逐池校验、连续分配普通/联动内部 ID，人工状态与 V1 同 Git Commit。只有真实 V1 变化才显式启动 Manifest。
- **人工**：真实帖子 `manual/notices/starrail/zh-CN/miyoushe/<文章ID>.json`，完全缺帖 `manual/notices/starrail/zh-CN/missing/*.json`，分别使用 `schemas/manual/starrail-notice-manual.schema.json` 和 `starrail-missing-warp.schema.json`；版本级改动用 `schemas/manual/starrail-v1-overrides.schema.json`。
- **长期联动**：4 星 UP 必须为空数组，`endAt=null`，普通池与联动池使用不同的内部 ID 空间；正文无法推定版本与首次期数时保持等待并要求人工确认。公告候选不反向改写旧池。
- **异常**：待采集网络 pending 独立保存，解析错误由 Issue 指派所有者，正常等待不重复提醒；最终公开发布仍需 Manifest/公开同步。
- **验收**：`Development scripts tests` 运行隔离回归；`3-TEMP_星铁真实公告只读回放` 对官方样本做隔离全链路回放。该临时工作流已在验证后归档到 `.github/workflow-archive/2026-10/`，不参与正式每日任务。

此章描述 PR 中的新实现；合并并成功完成首次真实 Action 验证之前，不保证生产已运行。