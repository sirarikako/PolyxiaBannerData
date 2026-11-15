# 1-2 原神官方卡池数据每日自动采集与来源追踪（P1/P2）

## 当前状态

此代码先部署在私有开发仓库。**私有仓库原有生产 Actions 仍禁用**。
正式运行需要验证后将脚本及候选 workflow 迁移到公开生产仓库。
现有米游社公告扫描、OCR、V1 候选选择和发布不变。Webstatic 只采集、归档、对照；
不能因为 Webstatic 返回数据就自动覆盖 V1。

## 数据目录

- data/official/genshin/webstatic/list.json：最近一次成功获取的完整官方列表 JSON。
- data/official/genshin/webstatic/details/{gacha_id}.json：官方简体中文详情，按配置 ID 保存。
- data/official/genshin/webstatic/history/list/{sha256}.json：官方列表旧版本。
- data/official/genshin/webstatic/history/details/{gacha_id}/{sha256}.json：详情旧版本。
- data/official/genshin/webstatic/checkpoint.json：列表和详情首次发现、变更、详情完整时间。
- data/derived/genshin/source-traces/observations.json：候选实际字段来源及已观察的官方独立对照。
- data/derived/genshin/source-traces/publication-events.json：新建／修订 V1 的字段来源审计日志；需在正式导入成功后调用记录器。
- data/BANNER_SOURCE_STATUS.md：最近卡池来源状态摘要。

Webstatic 返回 JSON 归其权利人所有；即使保存在代码仓库，也**不因 Polyxia 项目许可证获得 CC0 许可**。

## 执行

1. python -m scripts.collect.collect_genshin_webstatic
2. python -m scripts.release.generate_genshin_source_report
3. V1 正式发布后，使用导入脚本输出的 JSON 调用：
   python -m scripts.release.record_genshin_publication_sources --report /tmp/genshin-v1-publish.json

步骤 3 必须与 V1 的提交在**同一 Git commit / push**中执行；如果需要重试发布，则重新计算 V1 和追踪记录。
开发期不会主动启用该步骤。参考 deployment/workflows/genshin-webstatic-source-observer.yml
为公开库可部署的 `1-2_原神官方卡池数据每日自动采集` 工作流草案，原私有工作流保持退役。

## 数据来源规则

- firstSeenAt / firstObservedAt：采集器**第一次看到**信息的时间，不是官方真正发布的时间。
- detailReadyAt：首次观测到满足当前卡池类型完整度规则的官方详情时间，
  **并不表示整条 V1 已经可以发布**；版本、期数、时间等可能仍缺失。
- fieldSources：当前公告组装器实际采用的来源，不将 Webstatic 仅用于对比的字段冒充为使用来源。
- Webstatic 关联仅在类型、中文正式名称、UP 名单和开放日期均吻合且唯一时建立。
- Webstatic 详情的负数 item_id 不用于 V1 itemId。
- 历史资料首次扫描不能倒推其真实可用时间；需要从功能启用后持续观察。

## 预期生产迁移

- 将三个脚本与独立 workflow 候选部署到公开仓库（workflow 放在 .github/workflows）。
- 原 3-1、3-2 不需要停用，原 V1 校验方式保持不变。
- 在 3-2 导入成功、提交前，增加 publication-sources 记录动作，
  并把 publication-events.json 与 public/v1/genshin.json 一起提交。
- 手动总控 0 继续原样调用原公告和 V1 发布链路。Webstatic 观测独立运行。
- 如果官方请求失败，保留已有归档，记录不完整信息，不允许损坏 V1。

## 测试

python -m pytest -q tests/test_genshin_webstatic_source_observer.py


## P3：将官方数据安全补齐到候选

从 1-2 的本地存档读取 Webstatic 详情后，3-1 的候选整合器可在原有公告/预告/版本均已关联、
OCR 时间证据有效的情况下，仅为普通角色池（301、400）与武器池（302）
补足缺少的名称和五星、四星 UP。不开新网络请求，不改变现有公告采集量。

安全前提：官方详情哈希验证通过；类型、结束时间相符；有开始时间时允许已知的
一小时差；官方五星在对应预告名单中；同一类型和时间只能匹配一个 gacha_id；
公告已有名单只能是官方列表的子集，冲突不覆盖。人工覆盖字段不自动补齐。

P3 不填时间、版本、期数、itemId，也不处理类型 500 的集录／溯光池。
没有单篇公告或 OCR 时间失败时仍按原流程等待；Webstatic API 失败/存档损坏不影响 3-1。

成功补齐后，候选的 webstaticAugmentation 记录确切的官方 gachaId、
SHA-256、补齐字段及单独/混合来源；V1 sources 才添加 provider=webstatic。
若只是独立核对，不将其标为已参与生成。字段冲突写入 3-1 readiness
的 webstatic 对照结果，并附非阻断警告 webstatic_source_conflict。


## P3 后续：官方 raw 与独立 UIGF

- 全部新原神普通活动池和集录／溯光池，先与 1-2 存档的官方 Webstatic 详情按卡池名、时间唯一匹配，并校验详情 SHA-256。
- raw 仅从匹配的官方 gacha_type 生成；未取得官方确证时保持 null。op_gacha_type 只用于特殊池子类型检查，不能当 raw。
- UIGF 按独立确认的映射：官方 301→UIGF 301、400→301、302→302、500→500。没有官方 raw 时，也按已知 poolType 的 UIGF 分类规则保留规范值。
- 如果官方出现未知 raw（如 501）、未知特殊 op_gacha_type，或官方类型与公告分类矛盾，**仅阻断该候选**并记录 readiness 冲突，通过现有 3-1 问题通知机制报告；不得擅自套用 500。
- 若候选在 Webstatic 更新前就已发布，其 raw 可以先为 null。以后 1-2 采集到验证通过的官方资料时，3-2 仅回填以前为 null 的正式 V1 raw，并要求标题、起止时间、分类、UIGF 和普通池五星名单一致；已非 null 的 raw 永不覆盖。
- 具体来源记录在候选 gachaTypeEvidence、webstaticAugmentation、P2 fieldSources、3-2 rawBackfilled/rawConflicts 及 publication-events 的 raw_backfilled 事件中。
- 原有版本、期数、公告采集、图片 OCR、特殊池角色/武器可选名单都不改变。
