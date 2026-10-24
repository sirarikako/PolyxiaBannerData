# P3 — 不持久化公告原文：兼容性测试与实施记录

**状态：P3 已开始。离线修正与回归进行中，尚未完成真实联网/OCR/发布验证，禁止启用生产。**

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
| 原神 2-1 / 星铁 3-1 | 在整合前暂存调用一次上述临时补抓，无需迁移旧全文 | 原神来源补抓失败会进入最终诊断，并阻止自动关闭历史 Issue；星铁失败使任务报错，不触发发布 |
| 原神最终报告/Issue 守卫 | `GENSHIN_MANUAL_SOURCE_CODE` 纳入最终诊断及完整成功判定 | 补抓失败的作业不允许将旧 Issue 自动结清 |
| 工作流定时单测 | 暂存阶段读取 `deploy/production/workflows/`；正常生产也可读取 `.github/workflows/` | **绝不为测试把六个生产工作流部署到真实 Actions 路径** |

## 离线回归

- `tests/test_p3_no_persisted_raw.py`：已核实 checkpoint 无原文重建、人工未核实失败阻断、临时按 ID 获取、跨游戏/ID/标题不一致、网络超时状态保护、星铁结构化证明、Issue 不误关闭、日志报告不含原始正文。
- 扩大只读 CI 检查原神采集与 OCR 场景、人工整合、通知、星铁采集、调度时序、v1 与 Manifest。
- 所有测试在隔离临时目录与模拟详情响应上运行，**不请求真实米游社公告，不上传原始原文，不执行正式 `--write`**。暂存工作流未安装到 `.github/workflows/`。

## P3 尚未验收的真实运行场景

1. 在**单独、受控的测试 Runner** 上，对原神、星铁各一个现存公告调用真实 API，检查限流/验证码、身份校验、临时文件清理；原神再对包含图片的公告执行真实 Tesseract OCR，不把正文、图片或 Debug 数据上传到公开 Artifact。
2. 使用无 `posts/` 的全新 Runner 模拟：原神 `manualRecovered` 持久重整合；原神和星铁人工文件 push 自动恢复；来源 404、429、403/验证、图像失败时保留 checkpoint 与已有候选，不误发布。
3. 审查 Public Issue 的详细错误描述、人工差异和公开 Artifact：不得包含完整 raw 文章或敏感凭据；业务比较保留必要的字段差异。
4. 最终检查六个生产 workflow 的触发链、Token 权限、不会双写，以及 P4 切换窗口。P3 实测完成以前不安装生产计划任务。

## 生产切换禁令

本 P3 只在 Public `staging/p2-polyxia-production` 中开发与运行**只读回归**。未修改两个仓库的 `main`，未关闭 Private 旧作业，未安装 Public 新调度，未合并 Draft PR。