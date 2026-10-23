# P2 — PolyxiaBannerData 生产迁移暂存报告（尚未切换）

**分支：** `staging/p2-polyxia-production`。该分支属于 Public 仓库，**不是**正式 `main`。

源 Private 基线 main：`acad003dd790d267eb32ab5cd1ea6b81dc9b1ade`。
Public 基线 main：`c9b7a6a40036b11aad1a9c690440cb5cd8a7bc2b`。
P1 生产模板来源：Private PR #30 `feature/p1-polyxia-production-workflows`。

## 已迁移并按 Git Blob SHA 校验的目录

| 内容 | 数量 | 说明 |
| --- | ---: | --- |
| `data/` | 156 文件 / 521,780 bytes | 公告增量 checkpoint、解析、候选、就绪报告及 README |
| `scripts/` | 39 文件 | 现役 collect / transform / release，不含 TEMP/experiments/历史重放 |
| `tests/` | 39 文件 | 与 v1 和现役代码相关的回归及 fixture/v1 |
| `manual/` | 13 文件 | 当前人工设置、模板和说明，排除 `manual/archive` |
| `deploy/production/` | 7 文件 | P1 六份正式 workflow 模板及 README；全部不是 Actions 可执行路径 |
| `requirements-dev.txt` | 1 文件 | 保留与现有代码一致的依赖 |

Public 原有 `public/` + `schemas/` 共 15 个 Blob 未改动。只读验证 workflow `p2-staging-validate.yml` 为新增加的 staging CI，不具备内容写入权限。

## 重要：当前 P2 尚未完成全部选定数据迁移

最终用户选择的是：排除 `data/derived/genshin/archive/`、`data/review/`、历史 `images/`、旧 `index.json`、旧 `checkpoint.json`、`collection-report.json`、`end-probe.json`，其余保留，包括官方原始帖子。

固定 P0 基线的完整迁移目标：**675 个 data 文件 / 11,360,123 bytes（约 10.83 MiB）**。

**因公开再发布的授权和内容检查尚未完成，519 个 `data/announcements/**/posts/*.json`（10,838,343 bytes）被暂缓迁移到 Public。** 不可把“暂缓”理解为擅自修改最终目标，也不能先上传后删除：Public Git 历史中的内容仍可能保留。

实际运行必须考虑上述帖子和原神/星铁人工恢复对持久原文的依赖。未经解决，不得开启 2-1、3-1 的真实联网采集，也不得启动正式 v1 写入流程。

## 生产隔离保证

- 现有 Private `main` / Public `main` 未修改，Private 仍是唯一正式数据处理方。
- P1 六个生产 workflow 仅放在 `deploy/production/workflows/`，**未**放在 `.github/workflows/`。
- 唯一新增的 `.github/workflows/p2-staging-validate.yml` 仅运行只读单测/校验，`contents: read`，不推送 Git、不开 Issues、不 OCR、不联网采集、不使用 `--write`。
- 旧 `sync-public-data.yml` 不迁移；生产模板中 0-1 / 1-1 已取消旧跨仓库同步。

## P2/P4 后续验收门槛

1. 处理完整公告原文公开权限/敏感信息问题，决定是否允许进入 Public 版本历史；或在正式改变方案前与用户明确确认变更。
2. CI 通过后审阅迁移候选：所有 scripts/manual/derived/blob SHA 对照源分支一致，不缺少必要脚本、fixture。
3. 验证 v1 与 Manifest；验证人工 missing、按真实 postId 补齐和三方冲突；真实 OCR/公告采集必须在隔离条件下验证。
4. P4 时以**最新** Private main 重做增量校验，停止 Private 写入并等待运行结束后才能切换；两库禁止双写。

## P2 安全补丁：禁止原始公告进入 Public Git 历史

已经在暂存版 2-1/3-1 中移除 `git add -A -- data/announcements/**/posts`，只提交结构化 `data/derived/**`。同时新增 `.gitignore` 忽略原始 `posts/` 与旧图片目录；即使未来 Runner 重新联网抓取，原文也只存在本次 Runner 工作目录，**不会因为旧的 staging 语句而进入 Public**。

此改动**不代表人工恢复问题已解决**：原神 `manualRecovered` 和星铁 `load_real()` 在缺少持久化 `posts` 时可能无法恢复。P3 必须实现并测试按文章 ID 补抓及失败处理，才能允许 P4 实际启用生产调度。

测试新增 `tests/test_p2_public_staging.py`，严格检查完整原文/旧归档不在 Git、暂存工作流不提交原文；此测试由 Public 的只读 CI 执行。
