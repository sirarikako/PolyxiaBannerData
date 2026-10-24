# 星铁公告人工补齐使用说明

**范围：星铁简体中文米游社，正式代码暂位于 PR #16 开发分支。**

## 一、完全缺少官方帖子

使用 `manual/notices/starrail/zh-CN/missing/<身份>.json`，格式 `starrail-missing-warp-v1`。每个独立池一个文件。

最低填写：`identity.version`、`phase`（首次开放期）、`poolType`、`bannerName`，`data.featured.fiveStar`、`fourStar`，`data.time.startAt`、`endAt`，以及 `evidence.summary`。不能伪造 `postId`。

- 常规角色/光锥池：一名五星、三名四星；已知结束时间必须填写 UTC+08:00 的独占结束时刻。
- 长期联动角色/光锥池：一名五星、`fourStar: []`，没有确定结束时间时允许 `endAt: null`。
- 星铁同版本、同期、同池种、同卡池名仍可能有不同五星 UP，系统会同时比较完整五星 UP 名单，不能只靠池名去重。

Schema：`schemas/manual/starrail-missing-warp.schema.json`。

## 二、已有真实官方帖子但解析不足

路径：`manual/notices/starrail/zh-CN/miyoushe/<文章ID>.json`，格式 `starrail-notice-manual-v1`。文章的原始 JSON 必须真实存在于 `data/announcements/starrail/zh-cn/miyoushe/posts/`，无法取得原文就使用上述 missing 格式。

`banners[]` 每项填写 `identity`（版本、首次期数、池种、池名），和只需补充/核对的 `data.featured`、`data.time`。同名多池时可通过 `identity.fiveStarName` 唯一定位。

Fate 等联动公告正文缺少版本号与首次期数时，自动解析会正常等待，需在真实文章人工数据中确认该身份；程序不会根据发布时间猜测版本或期数。

Schema：`schemas/manual/starrail-notice-manual.schema.json`。

## 三、合并、比对与发布

自动缺失字段可由人工填补；双方都有值时比较，关键冲突阻断受影响候选。已发布的 V1 不会被重放覆盖，如确需修订使用版本级 `manual/starrail_<版本>.json` 的 `existing`（指定正式内部 ID）。

版本级人工的 `upcoming` 仅在首次追加前合并，处理完成后随同正式 V1 在同一次 Git 提交中标记 `completed`。原始公告采集不会直接写正式 V1。

候选由 3-1 生成，经 3-2 安全导入，之后仍需要 1-1 Manifest 与 1-2 公开仓库同步全部成功，才能算公开发布完成。

请勿将虚构示例 JSON 提交为真实人工来源。PR 尚未合并时所有上线动作均未生效。
