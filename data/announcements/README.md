# 游戏公告原始数据归档

所有原始公告严格按 **游戏 → 语言 → 来源** 隔离，不写入 `public/v1/`，也不自动把原始公告当作已经核验的卡池数据。

```text
data/announcements/
├── genshin/
│   └── zh-cn/
│       └── miyoushe/
│           ├── pages/                # 分页列表的原始 API 响应和请求参数
│           ├── posts/                # 完整正文原始 JSON，按 post_id 命名
│           ├── end-probe.json        # 如 API 没有正确 is_last，保存空页复核证据
│           ├── index.json           # 去重公告索引与原始详情文件状态
│           ├── checkpoint.json      # 便于查看的采集进度；真正断点由 pages/ 重建
│           └── collection-report.json
└── starrail/                         # 星穹铁道，单独预留；尚未采集
```

## 手动采集

GitHub Actions 工作流：**Archive Chinese Miyoushe announcements (manual only)**。没有自动定时触发。

触发时选择 `stage`：

- `list`（默认）：只采集 / 恢复全部历史公告列表，不请求正文；列表结束后，即使还有正文缺口，此阶段也可以成功结束。
- `banner-details`：**推荐的下一阶段**。只补抓标题匹配祈愿/概率UP/神铸赋形的公告，按发布时间从旧到新优先处理；已保存的完整正文自动跳过。使用 `max_detail_requests=25` 作为单次请求预算，达到上限后保存进度，下一次继续；这个模式的 Actions 成功仅表示本批安全执行，不代表所有候选正文已完成。每次执行前仍会检查原始历史列表已完成。
- `version-details`：新增的正式版本公告正文补抓模式。筛选游戏本体的版本更新说明、更新维护通知/预告、维护时间调整或版本延期，兼容 2020 年的“某月某日维护更新说明/通知”；**不包含**《云·原神》客户端、编辑器/千星沙箱、启动器、充值系统、测试服或已知问题反馈。按时间从旧到新补抓，自动跳过已有完整正文。建议每次最多 25 篇。
- `details`：读取已有历史列表，跳过有效正文，补采全部缺失详情；遇到米游社验证码 `retcode=1034` 或 HTTP 429 则暂停，不轮换域名绕过限制。
- `all`：先列表再详情；完整正文缺失会令该阶段保持未完成。

手动运行与离线测试：

```bash
python -m unittest discover -s tests -p 'test_collect_miyoushe_announcements.py' -v
python -u -m scripts.collect.collect_miyoushe_announcements --stage list
python -u -m scripts.collect.collect_miyoushe_announcements --stage banner-details --max-detail-requests 25
python -u -m scripts.collect.collect_miyoushe_announcements --stage version-details --max-detail-requests 25
python -u -m scripts.collect.collect_miyoushe_announcements --stage details
python -m unittest discover -s tests -p 'test_analyze_miyoushe_banner_notices.py' -v
python -m scripts.transform.analyze_miyoushe_banner_notices
```

**列表分页：**以 `gids=2, type=1, page_size=20` 从原神中文公告栏目取列表。保存 `last_id` 和原始响应。若 API 给出 `is_last=true`，以此为明确的分页结束证据；针对实际观察到的最后一页仅有 15 条、下一页为空但 `is_last=false` 的情况，必须满足 **上一页少于20条、已有2020年前数据、同一游标连续两次空结果**，才将列表标为*推定耗尽*。该复核过程保存为 `end-probe.json`，不伪装成 API 自行声明结束。其他空页仍视为异常。

**跨批次断点：**已保存的 `pages/*.json` 是可信数据；启动时按页重新核验游标链、原神游戏 ID，再结合可核验的 `end-probe.json` 判断结束。历史已保存正文无需重新下载。分页游标类似偏移量，公告插入、删除或后端变动可能影响跨时段一致性；`collection-report.json.listQuality` 记录去重及时间顺序异常，不能仅靠结束标记保证绝无缺页。

**执行与安全：**约每 50 个新文件或每 120 秒产生并推送 GitHub 检查点；程序有 90 分钟软限制、Actions 110 分钟作业限制，单请求 15 秒、最多 3 次重试。中断时只有已推送的文件保证不会丢失。正文请求节流，每次请求间隔约 2 秒，遇到验证码 / 限流即暂停，不能保证最终能完成全部详情。

**状态语义：**`listComplete` 表示当前接口的历史列表已取得有依据的结束信号且覆盖至 2020-09-30 或更早；`listEndBasis` 用于区分 `api_is_last` 与 `confirmed_empty_after_short_page`。独立的 `complete` 仅在所有归档列表对应的正文文件都保存且有效时为 true。`lastPageReached` 只对应 API 明确返回的 `is_last=true`。尚未尝试的正文在索引中标为 `rawFile=null`，仅实际请求失败才写入 `detailErrors`。

**数据边界：**保留原始时间戳以及转换后的 UTC+8 索引时间；`posts/*.json` 含有正文文本与图片 URL，但没有下载图片、更没有 OCR。米游社列表可能遗漏已删除、隐藏或来源之外的公告。该归档不能直接推定 UP 角色、准确卡池时刻、服务器范围或完整全球官方公告覆盖率。

## 祈愿公告定向分析（仅内部候选，禁止直接发布）

单独的手动 Actions：**Analyze Genshin Miyoushe banner notice candidates (manual only)**。它仅使用已经保存的 `index.json` 与 `posts/<post_id>.json`，无网络请求、无图片下载、无 OCR；结果保存为 `data/derived/genshin/miyoushe-zh-cn/banner-candidates.json`，不再放在原始公告目录内。

- 以标题包含“祈愿”“概率UP”“神铸赋形”等作为候选规则，不保证穷尽所有卡池公告，也不把候选直接当成已核验卡池。
- 提取正文的明确时间**原文及上下文**，只标记为 `bodyTimeMentions`，不自动填入卡池开始/结束时间；公告发表时间仅存为 `publishedAtUtc8`，不能充当活动时间。
- 从五星角色/武器上下文提取名称候选 `fiveStarTextCandidates`，不直接断言所有 UP 项、数量、顺序或卡池类型。
- 保留图片 URL `imageUrls` 和 `imageRecognitionNeeded`；图片实际下载与 OCR 留待后续独立阶段。
- `publishable=false`、`timesVerified=false`、`reviewRequired=true`；绝不写入 `public/v1`。
- `collection-report.json` 新增 `bannerCandidateNotices`、`bannerDetailsSaved`、`bannerDetailsMissing`、`bannerDetailsComplete` 和本轮请求预算字段。

建议操作：先执行一次 **Analyze...**，生成候选及缺口报告；再执行 **Archive...**，选择 `banner-details` 和请求上限 25；之后再次执行 **Analyze...** 更新报告。正文遇到验证码或限流时必须停止，不要通过增加运行频率绕过限制。

## 版本更新与维护公告正文补抓

在现有的 **Archive Chinese Miyoushe announcements (manual only)** 工作流里选 `version-details`（`max_detail_requests=25`）。无需重新采集 78 页列表；复用 `posts/<post_id>.json` 中此前已保存的正文文件。所有原始 JSON 仍储存在同一按游戏/语言/来源隔离的目录中，不覆盖祈愿公告，也不向 `public/v1` 写入内容。

筛选规则由 `scripts/transform/select_miyoushe_version_notices.py` 统一定义，分类：

- `release_notes`：版本更新说明，含早期停服维护更新说明，以及个别标题为“「月之X」更新说明”的正式更新公告。
- `maintenance_notice`：版本更新通知、版本更新维护预告、早期停服维护更新通知。
- `schedule_change`：版本更新时间调整、更新延期通知与补偿、版本持续时间说明等。

采集统计另增 `versionCandidateNotices`、`versionDetailsSaved`、`versionDetailsMissing`、`versionDetailsComplete`、`versionCandidateKinds`；保留标题筛选的候选语义，不能保证站点已经公开的历史公告完全收录。因为它与祈愿公告的筛选相互独立，`bannerDetailsComplete` 不受本轮版本正文补抓影响；`complete` 则继续代表整个 1,550 篇公告正文全部齐备。

版本公告对时间核验非常有用，但**维护预计结束时间不能直接当作卡池开始时间**：不同版本可能延迟开服，需结合公告文字中的条件、卡池独立公告与时区约定作后续人工核验。当前阶段只归档原始数据，尚不进行时间推算。
