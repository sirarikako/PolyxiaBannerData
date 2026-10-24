# P3 — 不持久化公告原文：兼容性测试与实施记录

**状态（2026-10-24）：P3 离线兼容、两篇真实官方文章读取及原神实际 OCR 已验收通过；Public 生产工作流全链运行、正式写入/Issue 真实交互与切换权限仍未实测，属于 P4 生产切换门槛。禁止在此阶段启用生产。**

## 不变的迁移边界

- 旧公告全文 `data/announcements/**/posts/*.json` 永远不迁移到 Public。
- 未来新公告详情只临时存在本次 GitHub Actions Runner 中；`.gitignore` 和采集工作流的 `git add -A -- data/derived/<game>` 不允许提交全文。
- 已完成公告的 `data/derived/**`、checkpoint、人工数据保持完整；不重新扫描 500 多篇旧文章。
- Private `main` 仍是唯一生产入口；Public `main` 和现行正式 v1、Manifest 不因本阶段修改。

## P3 代码兼容

| 功能 | 改动 | 失效保护 |
| --- | --- | --- |
| 原神 `index_additional()` | 已经经历真实原文核实、且 `manualRecovered` 与 `completed.resolution=manual_verified` 状态一致时，允许使用已保存的标题、文章 ID 和官方 URL 重建人工候选 | 缺少原文及可信 checkpoint 时**生成来源错误**，不再静默跳过/伪造官方来源 |
| 星铁 `load_real()` | 允许使用已保存、格式/游戏/ID/标题/官方 URL 一致的 `warp-notice` 或 `collab-notice` 解析文件证明真实来源 | 没有 raw 和可信结构化文件时拒绝生成官方候选 |
| `recover_manual_raw_zh_cn.py` | 仅对人工文件引用而无可信来源的真实文章 ID 发送官方详情 API 请求，验证 ID、游戏、标题、官方标记，原文仅保存在本次 Runner 忽略目录 | HTTP/格式/身份错误立即阻断恢复；返回/日志仅含 ID 和错误类型，不回写 checkpoint 或 v1 |
| 原神 2-1 / 星铁 3-1 | 在整合前暂存调用一次上述临时补抓；原神额外监听 `missing/**` 及 `miyoushe/**` 两种人工公告 push，不迁移旧全文 | 原神来源补抓失败会进入最终诊断，并阻止自动关闭历史 Issue；星铁失败使任务报错，不触发发布 |
| 原神最终报告/Issue 守卫 | `GENSHIN_MANUAL_SOURCE_CODE` 纳入最终诊断及完整成功判定 | 补抓失败的作业不允许将旧 Issue 自动结清 |
| 工作流定时单测 | 暂存阶段读取 `deploy/production/workflows/`；正常生产也可读取 `.github/workflows/` | **绝不为测试把六个生产工作流部署到真实 Actions 路径** |

## 离线回归

- `tests/test_p3_no_persisted_raw.py`：已核实 checkpoint 无原文重建、人工未核实失败阻断、临时按 ID 获取、跨游戏/ID/标题不一致、网络超时状态保护、星铁结构化证明、Issue 不误关闭、日志报告不含原始正文。
- 扩大只读 CI 检查原神采集与 OCR 场景、人工整合、通知、星铁采集、调度时序、v1 与 Manifest。
- 普通 CI 的回归测试在隔离临时目录与模拟详情响应上运行，**不请求真实米游社公告、不上传原文、不执行正式 `--write`**。真实联网探针另行通过一次性开关执行，完成后已删除触发开关；后续普通 CI 不会重复联网。
- `tests/test_p3_no_raw_end_to_end.py` 复制本次迁移的真实原神 `78782590` / 星铁 `79023863` 结构化数据，在没有 `posts/` 的全新临时根目录里验证人工文件匹配和星铁连续两轮候选重整合。
- `tests/test_p3_public_artifact_guard.py` 自动审查六份暂存生产工作流的 Git 提交、Artifact 上传路径、人工触发路径以及真实探针已关闭；不允许上传原始公告正文、图片目录或宽泛的工作目录。
- P3 常规 CI [#40050611444](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40050611444) **success：177 passed + 64 subtests passed**，涵盖 v1/Manifest 检查、编译及上述保护。

## 实际 GitHub Runner 官方源验证（已通过）

- 一次性触发提交：`d8d8564db4717e621105e419d73e07d3e7588165`，只读 [Actions #40050197969](https://github.com/sirarikako/PolyxiaBannerData/actions/runs/40050197969)，结论 **success / P3_LIVE_RESULT=PASS**。
- 原神真实文章 `78782590`：官方详情 API 返回成功，文章身份/标题、卡池类型及 UP 解析匹配保存的结构化结果；**2 张真实图片下载成功，本地 Tesseract OCR 返回 `recognized`，起止时间与已知历史结果完全相同**。
- 星铁真实文章 `79023863`：官方详情 API 返回成功，身份、标题、版本和期数与结构化结果匹配，解析 **4 个跃迁卡池**。
- 原文只在运行时内存中存在，图片在 Python `TemporaryDirectory` 中下载及识别，退出即清理；没有上传原文/图片 Artifact、没有 Git push、没有改 v1 / Manifest / checkpoint、没有创建 Issue。
- **一次性 `p3-live-once.flag` 已在提交 `1951bf83a899d515ca79d0cbf379bc3773025787` 删除**；只读 CI 中保留显式 opt-in 检查门槛，普通运行不访问官网。

## P4 前剩余门槛（不能以 P3 成功代替）

1. 两篇旧样本的成功结果**不能保证**未来每次新公告都可以联网，也没有人为触发真实限流/验证码；这类异常在 P3 离线测试中覆盖，发生时应安全停机而非绕过。
2. 未在 Public `main` 启用完整 2-1→2-2 / 3-1→3-2 发布链，也未真实创建、编辑、关闭公开 Issue 或发布新的 Artifact。已做**只读静态安全检查和离线通知模拟**，正式联动验收与生产 Token 权限应在 P4 切换计划中按受控步骤进行。
3. P4 仍需以最新 Private `main` 更新增量状态、停旧作业、核对未解决的 manual / pending；在仅有一方生产运行的前提下，安装六份 workflow 并观察首次运行，避免双写。
4. Public P3 暂存分支目前 **281 个 Git 文件**，其中 `data/` 156、`scripts/` 40、`tests/` 44；**0 个旧 `posts/`**。唯一实际在 `.github/workflows/` 的工作流仍是只读迁移 CI。

## 生产切换禁令

本 P3 只在 Public `staging/p2-polyxia-production` 中开发与运行**只读回归**。未修改两个仓库的 `main`，未关闭 Private 旧作业，未安装 Public 新调度，未合并 Draft PR。