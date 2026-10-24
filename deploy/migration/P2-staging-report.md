# P2 — PolyxiaBannerData 迁移验收（未切换）

**2026-10-24 最终决定：旧公告全文 `data/announcements/**/posts/*.json` 不迁移，也不得将新取得的完整正文提交 Public Git。** 已从 P2 目标范围移除 519 篇旧正文，此项不再是迁移缺口。Runner 可临时取得需要解析的官方文章和 OCR 图片，但只将结构化结果持久化到仓库。

## 仓库与基线

- Private 开发库：`sirarikako/CastoriceWishBannerData`。P0 基线 main：`acad003dd790d267eb32ab5cd1ea6b81dc9b1ade`，P1/P2 来源为 Draft PR #30/#31。
- Public 生产目标：`sirarikako/PolyxiaBannerData`。P0 基线 main：`c9b7a6a40036b11aad1a9c690440cb5cd8a7bc2b`。
- 本次仅暂存于 Public `staging/p2-polyxia-production` / Draft PR #1；未修改双方 `main`，不能提前合并或启动生产。
- 仍由 Private `main` 唯一执行正式生产；P4 切换前必须按**当时最新** Private `main` 重新校验增量。

## data 范围：来源 817 文件全部分类

| 数据分类 | 文件数 | 最终处理 |
| --- | ---: | --- |
| 当前 checkpoint、解析、候选、报告及相关 README | **156** | **迁移** |
| 旧完整公告原文 `posts/*.json` | **519** / 10,838,343 bytes | **明确不迁移，今后也不提交 Public Git** |
| 历史图片、旧索引、归档、审核数据等 | **142** | 依原方案排除 |
| **Private 来源 data 合计** | **817** | **817/817 已归类** |

最初讨论的 675 个 `data/` 文件包含现在明确排除的 519 篇正文。**最终 P2 的 `data/` 目标为 156 文件**；因目录说明更新，当前暂存字节数为 522,255 bytes。没有待补的旧公告。未来任何 raw 文章需要只在本轮 Runner 临时使用，不得先提交后删除（公开 Git 历史仍可见）。

## P2 暂存清单与 SHA 审计（2026-10-24）

| 目录 | 文件数 | 备注 |
| --- | ---: | --- |
| `data/` | 156 | 结构化及状态文件 |
| `scripts/` | 39 | 采集、解析、整合、发布模块 |
| `tests/` | 40 | 现役回归、fixture 与 P2 守护测试 |
| `manual/` | 13 | 当前人工配置与模板，排除旧归档 |
| `deploy/production/` | 7 | 六个**未启用**的 workflow + README |
| `requirements-dev.txt` | 1 | 依赖 |

Public P2 分支共 **275 个 Git 文件**，与 Private P2 来源逐 Git Blob SHA 校验：

- **265 个同路径 Blob SHA 完全一致**。
- **7 个有意修改**：`.gitignore`、仓库根 README、公告目录 README、`scripts/README.md`、生产暂存 README、原神/星铁两份采集 workflow。
- **3 个独立新增**：只读 P2 CI、本报告及 `tests/test_p2_public_staging.py`。
- Public 原有 `public/` 7 个文件和 `schemas/` 8 个文件 **15/15 完全未改**；根 README 仅在本暂存分支调整迁移说明，Public `main` 不变。

## 安全隔离和自动验证

- 六份生产调度 workflow 只放在 `deploy/production/workflows/`，不在 `.github/workflows/` 中启用。
- 唯一实际运行的 `.github/workflows/p2-staging-validate.yml` 是只读 PR CI，`contents: read`，不具备生产调度、Git push、正式发布或联网 OCR 采集能力。
- Public `.gitignore` 忽略完整公告正文与历史图片；暂存的原神 2-1、星铁 3-1 的 `git add` 只包含各自的 `data/derived/`，不提交 raw `posts`。
- 不迁移旧 1-2 `sync-public-data.yml`。未来的 0-1、1-1 在本库执行，2-2/3-2 校验本仓库上游并触发本仓库 Manifest。
- `tests/test_p2_public_staging.py` 使用 `git ls-files` 检查实际跟踪文件，排除 raw 文章、旧索引、归档及内部文件，检查唯一只读 CI、六份生产工作流隔离以及 `git add` 的范围。
- [P2 CI #40046959940](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40046959940) 在安全测试修正提交 `7f490ecf4430c2e633de0c8451d745026228fd8c` 上 **success**。后续文档修订提交以最新 CI 结果为准。

## 不保存旧原文时的代码依赖（P3 前置）

P2 基线 checkpoint：原神 `pending=0`、`manualReview=0`、`manualRecovered=0`；星铁 `pending=0`、`manualReview=0`。已完成来源对应的结构化数据保留，旧 raw 文件不需要为本次迁移补齐。正常新公告采集可在本轮 Runner 获取并解析详情。

但**这不等于 P3 生产兼容已通过**：

1. 原神 `scripts.transform.genshin_notice_manual_zh_cn.index_additional()` 对部分 `manualRecovered` / 解析失败的真实文章需本地 raw；当人工文件 push 触发 2-1 而网络采集被跳过时，缺少 raw 会导致恢复来源被跳过。
2. 星铁 `scripts.transform.starrail_notice_manual_zh_cn.load_real()` 要求真实 `postId` 对应 raw 文件存在；没有持久旧公告时，人工重整合可能失败，包括长期联动确认。
3. P3 要验证并修正按 `postId` 临时补抓、真实来源验证、接口限流/删除、候选保留及错误状态；覆盖人工 missing、旧结构化结果、OCR 临时图片、Issue 和 Artifact 是否泄漏不应公开的数据。

这些是 **P3 正式运行前测试要求**，不是要求复制旧全文到 Public 的理由。

## 后续门槛

- **P2**：范围确认、156 文件迁移、SHA/排除项核对、只读 CI 验证完成；保持 Draft PR，生产仍未切换。
- **P3**：完成无持久全文模式的集成回归与必要代码修正，并审核公开 Issue、Artifact 诊断的内容边界。
- **P4**：以最新 Private main 校验数据增量；停止 Private 定时并等待现有任务结束，避免双写；必要权限与实际流程确认后再在 Public 启用六份生产工作流、正式独立发布。切换前不可将暂存 workflow 复制至 `.github/workflows/`。
