# 数据采集、候选整合与生产发布

本仓库独立执行正式采集与发布；代码及工作流的开发、回归测试在私有仓库完成，验证后部署到此处。

## GitHub Actions

| 编号 | `.github/workflows/` 文件 | 功能 |
| --- | --- | --- |
| 0 | `manual-version-refresh-sequential.yml` | 版本更新时手动顺序执行 |
| 1-1 | `official-item-mappings-daily.yml` | 每日更新官方 ItemID |
| 2-1 | `refresh-v1-manifest.yml` | 校验/刷新 v1 Manifest |
| 3-1 | `genshin-notices-zh-cn-daily-preview.yml` | 原神公告扫描、OCR、候选和问题通知 |
| 3-2 | `genshin-v1-auto-publish.yml` | 原神正式 v1 导入发布 |
| 4-1 | `starrail-notices-zh-cn-daily-preview.yml` | 星铁公告扫描、候选和问题通知 |
| 4-2 | `starrail-v1-auto-publish.yml` | 星铁正式 v1 导入发布 |
| 5-1 | `banner-status-report.yml` | 独立汇总公开仓库结构化公告、预告、候选和 V1 至 `data/BANNER_STATUS.md` |
| 1-2 | `genshin-webstatic-source-observer.yml` | 原神官方 Webstatic 数据每日自动采集、原始 JSON 归档及来源追踪，不修改 V1 |

正式正常扫描时间按 UTC：1-1 为 05:17（UTC+8 13:17），1-2 为 22:17、06:07、10:07（北京时间 06:17、14:07、18:07），原神 3-1 为 06:17、06:27/37/47/57（UTC+8 14:17 开始），星铁 4-1 为 07:17、07:27/37/47/57（UTC+8 15:17 开始）；以正式 workflow 的 cron 为准，GitHub 定时可能延迟。

`5-1` 仅按时或手动汇总既有数据，不执行抓取、OCR、候选整合或 V1 发布；首轮部署脚本时也触发生成。

日常采集可通过 `workflow_run` 触发 `3-2/4-2`；手动总控 `0` 则直接顺序调用并等待发布任务。v1 有变化时，发布工作流显式触发 `2-1` 更新 Manifest。

## 数据生命周期

| 路径 | 保存策略 |
| --- | --- |
| `public/v1/`、`public/item-mappings/` | Public 正式数据，持久化 |
| `data/derived/genshin/notice-discovery/`、`data/derived/starrail/notice-discovery/` | 扫描锚点、pending、人工复核、报告，**不要清空 checkpoint** |
| `data/derived/genshin/version-updates/`、`wish-previews/`、`wish-notices/` | 原神公告的结构化结果 |
| `data/derived/genshin/v1-candidates/`、`v1-readiness/` | 发布候选、冲突及就绪诊断 |
| `data/derived/starrail/` 下解析结果、`v1-candidates/`、`v1-readiness/` | 星铁结构化公告与发布候选 |
| `manual/` | 公告级、缺帖和版本级人工数据 |
| `data/announcements/**/posts/`、OCR 图片 | 仅 Runner 内临时存在，**不提交 Public** |

结构化 `source.rawFile` 只标记当次临时来源路径，不保证下次 checkout 仍可读取；定位真实来源应使用 `postId`、官方 URL 与核验证据。

## 现役脚本与异常处理

- `scripts/collect/collect_genshin_notices_zh_cn.py`：增量扫描、pending、正文提取，网络故障可从第一页换官方备用列表接口重扫；429 和验证码不绕过。
- `scripts/collect/collect_starrail_notices_zh_cn.py`：星铁增量扫描、来源异常分类。
- `scripts/collect/recover_manual_raw_zh_cn.py`：只在必要时按官方 postId 临时补抓人工来源，不提交原文。
- `scripts/transform/assemble_genshin_wish_candidates_zh_cn.py`、`assemble_starrail_warp_candidates_zh_cn.py`：将结构化公告和人工数据整合为候选。
- `scripts/release/import_genshin_v1_zh_cn.py`、`import_starrail_v1_zh_cn.py`：逐池核对后发布；`validate_v1.py` 与 `refresh_v1_manifest.py` 负责合约与索引。
- `scripts/collect/collect_miyoushe_announcements.py` 是历史归档辅助模块，现役模块仍复用它的 HTTP 和验证逻辑。`--commit-progress` / `git_commit()` 在 Public/未知 Git 来源中被代码禁止，不能恢复旧归档 Git 提交流程。

缺帖人工补充模板和 Schema 参阅 [manual 说明](../manual/README.md)。获取不到官方文章时应保留既有候选、checkpoint 与正式 v1，进入 pending/人工复核，而不是把失败视作“没有新公告”。图片 OCR 只在当次 Runner 内运行，不保存完整图片。

## 生产数据安全与开发测试边界

Public `main` 不包含 `tests/`、`requirements-dev.txt` 或测试用 Actions，也不会在生产任务中执行 pytest/unittest。

正式发布流程仍执行：

- `python -m scripts.release.validate_v1 --datasets-only`：独立验证发布数据。
- `python -m scripts.release.refresh_v1_manifest`：生成临时或正式 Manifest。
- `python -m scripts.release.validate_v1 --public`：核对 Schema、Manifest 与数据哈希。
- 发布范围、原神 3-1 保证 v1 不变、checkpoint/人工复核/Issue/Artifact 原文保护等生产守卫。

代码或 Actions 变更先完成私有仓库中的开发与验证，再部署到本仓库；不应绕过验证直接修改正式运行逻辑。

## 1-2 原神官方卡池数据每日自动采集（P1/P2）

新 Action 不替代 3-1 公告扫描，也不参与 3-2 的 V1 数据组装。它保存 `data/official/genshin/webstatic/` 下的官方列表、简体中文详情及变更历史，并生成 `data/BANNER_SOURCE_STATUS.md` 和 `data/derived/genshin/source-traces/observations.json`。

3-2 在新增／人工修订 V1 成功后，同一提交写入 `data/derived/genshin/source-traces/publication-events.json`，记录每个新卡池实际组装字段的来源（不将只参与比对的 Webstatic 标记成发布来源）。采集器的首次观测时间不代表官方发布时间。具体规则见 [Webstatic 来源追踪说明](../docs/GENSHIN_WEBSTATIC_SOURCES.md)。


## P3 原神官方 Webstatic 参与候选补全

3-1 在现有公告、预告、版本和时间证据已经关联后，读取 1-2 已归档的官方详情。
仅对能够唯一匹配、完整且无冲突的普通角色/武器池补全缺失的池名或 UP 名单。
不额外请求 API，不跳过 OCR/人工复核，不处理特殊池/版本/时间，已有公告值不覆盖。
实际补全字段会进入候选 webstaticAugmentation、来源追踪和发布审计；
冲突仅记录在 v1-readiness 的 webstatic 状态与 warning 中，保留原发布规则。
细节见 docs/GENSHIN_WEBSTATIC_SOURCES.md。
