# P1 — Polyxia 生产工作流暂存（尚未启用）

本目录准备供 P2 / P4 部署到 **Public `sirarikako/PolyxiaBannerData`** 的正式 GitHub Actions 工作流。

**注意：** 当前六个 YAML 位于 `deploy/production/workflows/`，不是 `.github/workflows/`。Private 仍以旧工作流执行正式调度，本次 P1 不修改任何仓库的 `main`，不启用新的生产定时任务。

## 工作流改动

| 文件 | 功能 | P1 改动 |
|---|---|---|
| `official-item-mappings-daily.yml` | 0-1，每日北京时间 13:17 | 不再向另一个仓库同步；删除无用 actions 写权限 |
| `refresh-v1-manifest.yml` | 1-1，正式 Manifest 刷新 | 不再触发旧的 1-2；删除无用 actions 写权限 |
| `genshin-notices-zh-cn-daily-preview.yml` | 2-1，14:17/27/37/47/57 | 原样暂存，不改公告下载、OCR、posts 或 checkpoint |
| `genshin-v1-auto-publish.yml` | 2-2，原神 v1 发布 | workflow_run 限定上游为本仓库 main 且成功采集 |
| `starrail-notices-zh-cn-daily-preview.yml` | 3-1，15:17/27/37/47/57 | 原样暂存，不改公告下载、posts 或 checkpoint |
| `starrail-v1-auto-publish.yml` | 3-2，星铁 v1 发布 | workflow_run 限定上游为本仓库 main 且成功采集 |

不部署旧 `sync-public-data.yml`（1-2）。

最终独立生产链：0-1 直接更新本仓库映射；2-1 → 2-2 → 显式 `workflow_dispatch` 1-1；3-1 → 3-2 → 显式 `workflow_dispatch` 1-1。不能仅依赖机器人 `GITHUB_TOKEN` push 触发下游普通 push 工作流。

## P2 / P4 部署前置条件

1. 审查全部拟公开 `posts/*.json` 的内容、相关使用条款与版权、隐私字段，未经确认不得直接写入公开 Git 历史。
2. 检查现有 Issue 通知与 Artifact，在 Public 中是否会暴露不应公开的人工证据、原文或诊断信息；需要时先调整隐私边界。
3. 在 Public 的临时分支准备 `scripts/`、`tests/`、`manual/`、按 P0 筛选规则得到的 `data/`、依赖与这些暂存工作流；现有 `public/`、`schemas/`、人工 completed 状态不得简单被旧文件覆盖。
4. **不能仅把六个 YAML 放进 Public 的 main。** 必须先完成隔离回归测试，再于 P4 停止 Private 旧调度、等待旧运行结束、重新核对 P0 之后的 checkpoint、候选与正式 v1 增量。确保不会双写。
5. Public 正式部署时才将这六个 YAML 复制为 `.github/workflows/<同名>.yml`。检查 GITHUB_TOKEN 内容/Issue/Actions 写入权限（按需授权），无需旧跨库 `CASTORICEBANNERDATA_TOKEN`。
6. 启用定时之前，验证人工 missing + 真实文章补充组合、pending/OCR 异常、v1 与 Manifest 哈希、Issue 通知，以及 2-1/3-1 的实际工作结果。

## 静态回归

```bash
python -m pytest -q tests/test_p1_production_workflows_staged.py
```

此测试检验暂存文件清单、定时、权限、旧同步移除、发布源校验与生产采集原样保留。它不能替代 P2/P4 的真实 Actions 端到端测试。

P0 报告保存在 `backup/p0-20261023-pre-production-migration` 分支下的 `docs/migration/polyxia-production/`。
