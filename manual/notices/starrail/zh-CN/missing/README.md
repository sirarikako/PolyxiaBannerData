# 星铁公告人工补齐使用说明

**范围：星铁简体中文米游社；由本仓库正式 3-1／3-2 流程处理。**

## 一、完全缺少官方帖子

使用 `manual/notices/starrail/zh-CN/missing/<身份>.json`，格式 `starrail-missing-warp-v1`。每个独立池一个文件。

最低填写：`identity.version`、`phase`（首次开放期）、`poolType`、`bannerName`，`data.featured.fiveStar`、`fourStar`，`data.time.startAt`、`endAt`，以及 `evidence.summary`。不能伪造 `postId`。

- 常规角色/光锥池：一名五星、三名四星；已知结束时间必须填写 UTC+08:00 的独占结束时刻。
- 长期联动角色/光锥池：一名五星、`fourStar: []`，没有确定结束时间时允许 `endAt: null`。
- 星铁同版本、同期、同池种、同卡池名仍可能有不同五星 UP，系统会同时比较完整五星 UP 名单，不能只靠池名去重。

Schema：`schemas/manual/starrail-missing-warp.schema.json`。

## 二、已有真实官方帖子但解析不足

路径：`manual/notices/starrail/zh-CN/miyoushe/<文章ID>.json`，格式 `starrail-notice-manual-v1`。当次执行必须能取得对应真实官方原文；无法重新取得原文就使用上述 missing 格式。

`banners[]` 每项填写 `identity`（版本、首次期数、池种、池名），和只需补充/核对的 `data.featured`、`data.time`。同名多池时可通过 `identity.fiveStarName` 唯一定位。

Fate 等联动公告正文缺少版本号与首次期数时，自动解析会正常等待，需在真实文章人工数据中确认该身份；程序不会根据发布时间猜测版本或期数。

Schema：`schemas/manual/starrail-notice-manual.schema.json`。

## 三、合并、比对与发布

自动缺失字段可由人工填补；双方都有值时比较，关键冲突阻断受影响候选。已发布的 V1 不会被重放覆盖，如确需修订使用版本级 `manual/starrail_<版本>.json` 的 `existing`（指定正式内部 ID）。

版本级人工的 `upcoming` 仅在首次追加前合并，处理完成后随同正式 V1 在同一次 Git 提交中标记 `completed`。原始公告采集不会直接写正式 V1。

候选由 3-1 生成，经 3-2 在本仓库安全导入；正式数据提交后由本仓库 1-1 更新 Manifest，校验成功才算发布完成。

请勿将虚构示例 JSON 提交为真实人工来源。
