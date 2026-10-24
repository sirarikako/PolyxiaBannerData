# P4 — 生产切换与首次验收（2026-10-24）

**状态：Private 生产停用，Public 生产已启用。首次生产入口测试完成；自然定时、自然 workflow_run 和实际新增卡池发布仍待日常观察。**

## 数据与工作流

- Private `sirarikako/CastoriceWishBannerData`：[PR #32](https://github.com/sirarikako/CastoriceWishBannerData/pull/32) 停用了原 0-1、1-1、2-1、2-2、3-1、3-2、1-2 共 7 份工作流。已确认没有自动触发器，手动入口有 `if: false`；历史与 519 份公告原文仍留 Private。
- Public `sirarikako/PolyxiaBannerData`：[PR #1](https://github.com/sirarikako/PolyxiaBannerData/pull/1) 合并数据、脚本、状态，[PR #2](https://github.com/sirarikako/PolyxiaBannerData/pull/2) 启用 6 份独立生产工作流。不再运行跨库 1-2 同步。
- Public Git 中 **0 个 `posts/*.json`**；公告原文与 OCR 图片只在 Runner 临时保存，`data/derived/**` 继续持久提交。
- 正式 `public/v1/genshin.json`、`starrail.json`、`manifest.json` 与两款游戏 `public/item-mappings/*/zh-CN.json` 的 Git Blob SHA 均与停用后的 Private 对照一致。切换前检查 Private 无正在运行或排队的旧生产作业。

## 真实 Actions 验收记录

| 验收项 | 运行 | 结果 |
| --- | --- | --- |
| GITHUB_TOKEN contents/actions/issues 写入与调度 | [#40053122455](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40053122455) | 成功；测试 Issue #3 已关闭 |
| 0-1 ItemID | [#40053248546](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40053248546) | success |
| 1-1 Manifest | [#40053248545](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40053248545) | success |
| 3-1 星铁公告 | [#40053310695](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40053310695) | success |
| 3-2 星铁 V1 | [#40053478053](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40053478053) | success，正式数据无新变更 |
| 2-1 原神首次 | [#40053309273](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40053309273) | 两次主列表 HTTP 超时，checkpoint 未丢失，Issue #4 |
| 官方双入口分页等价性 | [#40057185154](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40057185154) | type=1/3 前两页各 40 条、游标、末页状态一致 |
| 原神安全备用源修复 | [PR #5](https://github.com/sirarikako/PolyxiaBannerData/pull/5) / [CI #40057324289](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40057324289) | 已合并，186 项测试 + 64 项子测试通过 |
| 2-1 原神修复后 | [#40057430398](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40057430398) | success；type=1 新帖 0、type=3 新资讯 5，新增需提取 0，pending/review 为 0；Issue #4 自动关闭 |
| 2-2 原神 V1 | [#40057545900](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40057545900) | success，正式 v1 未出现意外变更 |

## 网络回退边界

原神主源为 `bbs-api-static.miyoushe.com/painter/wapi/getNewsList`，备用源为 `api-takumi.mihoyo.com/post/wapi/getNewsList`。**仅**明确的传输异常/5xx 允许从第一页面重新读取备用源，同次扫描不混用游标。429、验证码、403/404、无效响应不触发回退。两源均不可用时停止并保留 checkpoint，不把故障当作空公告列表。

首次修复后 2-1 主源已经恢复，故未在正式生产中真实触发备用路径；备用实际连通性、两页等价性和离线回退逻辑分别通过验证。

## 后续正常运营观察（不能提前宣称完成）

1. 首次自然 `schedule`：当前 0-1、1-1 push 触发和手动生产入口已通过，但 GitHub 自然定时尚待观察。
2. 2-1→2-2 / 3-1→3-2 的自然 `workflow_run`：本次 2-1/3-1 由一次性 `GITHUB_TOKEN` 工作流调度，GitHub 防递归行为可能导致没有下游事件。两款游戏的 2-2/3-2 分别人工验证通过，仍需检查首次真实上游自动触发。
3. 下一次真实新增卡池需要确认 `data/derived` 候选 → 新 v1 → Manifest 哈希/数量 → 公开 Issue 通知。首轮测试没有可新增的卡池。
4. 官方持续超时、验证码、限流不得绕过或强行反复请求；保留状态与故障 Issue。

测试结束后，`staging/p4-token-probe` 下的六份一次性测试工作流均已删除；不会在 Public `main` 执行。Private 七份旧生产必须继续保持关闭，**不要在 Public 仍运行时直接恢复 Private 或旧跨库 1-2 同步**。
