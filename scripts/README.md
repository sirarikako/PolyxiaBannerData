# 数据采集、候选整合与生产发布

本仓库独立执行正式采集与发布；代码及工作流的开发、回归测试在私有仓库完成，验证后部署到此处。

## GitHub Actions

| 编号 | `.github/workflows/` 文件 | 功能 |
| --- | --- | --- |
| 0-1 | `official-item-mappings-daily.yml` | 每日更新官方 ItemID |
| 1-1 | `refresh-v1-manifest.yml` | 校验/刷新 v1 Manifest |
| 2-1 | `genshin-notices-zh-cn-daily-preview.yml` | 原神公告扫描、OCR、候选和问题通知 |
| 2-2 | `genshin-v1-auto-publish.yml` | 原神正式 v1 导入发布 |
| 3-1 | `starrail-notices-zh-cn-daily-preview.yml` | 星铁公告扫描、候选和问题通知 |
| 3-2 | `starrail-v1-auto-publish.yml` | 星铁正式 v1 导入发布 |

正式正常扫描时间按 UTC：0-1 为 05:17（UTC+8 13:17），原神 2-1 为 06:17、06:27/37/47/57（UTC+8 14:17 开始），星铁 3-1 为 07:17、07:27/37/47/57（UTC+8 15:17 开始）；以正式 workflow 的 cron 为准，GitHub 定时可能延迟。

成功的上游采集可以通过 `workflow_run` 触发对应 2-2/3-2；v1 有真实变化时显式 `workflow_dispatch` 1-1。GitHub `GITHUB_TOKEN` 的防递归机制可能影响手动调度测试，不等同于自然上游触发。1-1 在本仓库内维护 Manifest。

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
- 发布范围、原神 2-1 保证 v1 不变、checkpoint/人工复核/Issue/Artifact 原文保护等生产守卫。

代码或 Actions 变更先完成私有仓库中的开发与验证，再部署到本仓库；不应绕过验证直接修改正式运行逻辑。
