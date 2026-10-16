# 卡池情报数据 · v1

本目录提供《原神》与《崩坏：星穹铁道》的公开卡池（祈愿／跃迁）元数据，包括卡池类型、名称、UP／可定轨物品、开放时间及数据来源。不包含玩家个人抽卡记录、保底进度或个人定轨结果。

## 收录内容

| 游戏 | 服务器 | 卡池类型 | 数据文件 |
| --- | --- | --- | --- |
| 原神（`genshin`） | 国服官服（`cn_official`） | 角色活动祈愿、角色活动祈愿-2、武器活动祈愿、集录祈愿、溯光祈愿、常驻祈愿、新手祈愿 | [genshin.json](./genshin.json) |
| 崩坏：星穹铁道（`starrail`） | 国服官服（`cn_official`） | 角色活动跃迁、光锥活动跃迁、联动角色跃迁、联动光锥跃迁、常驻跃迁、新手跃迁 | [starrail.json](./starrail.json) |

原神的集录祈愿与溯光祈愿共用 `poolType: "chronicled"`，通过 `variant` 区分（`chronicled` / `special_recollection`）。实际已发布游戏与卡池范围以数据文件和 [manifest.json](./manifest.json) 为准。

## 发布文件

| 文件 | 包含的数据 |
| --- | --- |
| [manifest.json](./manifest.json) | 发布清单、接口版本、生成时间、各游戏数据文件路径及 SHA-256 校验值 |
| [genshin.json](./genshin.json) | 原神卡池元数据 |
| [starrail.json](./starrail.json) | 星铁卡池元数据 |

对应的 JSON Schema：[卡池数据结构](../../schemas/public/v1/banner-data.schema.json) · [Manifest 结构](../../schemas/public/v1/manifest.schema.json)。

## 卡池记录字段

| 字段 | 内容 |
| --- | --- |
| `id` | 仓库分配的稳定卡池 ID，不是个人抽卡记录 ID |
| `gameVersion`、`phase` | 游戏版本及卡池首次开放的版本内期数 |
| `category`、`poolType` | 展示分类及具体卡池类型 |
| `variant` | 原神集录祈愿或溯光祈愿的子类型（适用时） |
| `names` | 按语言代码保存的卡池名称 |
| `featured.fiveStar`、`featured.fourStar` | 五星、四星 UP 物品；集录／溯光的五星列表为可选定轨目标 |
| `featured.*[].itemId`、`type`、`names` | 物品 ID、角色／武器／光锥类型及多语言名称 |
| `gachaTypes.raw`、`gachaTypes.uigf` | 官方原始抽卡类型及 UIGF 规范类型 |
| `gachaIds` | 已核实的星铁官方卡池 ID（可选） |
| `regions` | 各服务器的 `server`、`startAt`、`endAt`；时间统一使用 UTC+8 |
| `fatePointLimit` | 原神相关卡池的定轨命定值上限（适用时） |
| `sources` | 数据来源及可追溯链接 |
| `images` | 按语言保存的卡池图片链接（可选） |

`featured` 中的 `null` 表示信息未知，空数组表示确认没有对应的固定 UP；`regions.endAt` 在没有确定结束时间的常驻、新手或部分长期联动池中可为 `null`。

## 内部卡池 ID 分配规则

`banners[].id` 是本仓库的卡池唯一标识，与官方 `gachaIds`、`gachaTypes` 及玩家抽卡记录 ID 不同。

| 游戏 | 卡池类别 | ID 规则 |
| --- | --- | --- |
| 原神 | 普通活动池 | `gi-000001`～`gi-099999`，顺序递增 |
| 原神 | 常驻祈愿「奔行世间」 | 固定 `gi-100001` |
| 原神 | 新手祈愿「初行者推荐祈愿」 | 固定 `gi-100002` |
| 星铁 | 普通活动池 | `hsr-000001`～`hsr-099999`，顺序递增 |
| 星铁 | 常驻跃迁「群星跃迁」 | 固定 `hsr-100001` |
| 星铁 | 新手跃迁「始发跃迁」 | 固定 `hsr-100002` |
| 星铁 | 长期联动池 | 从 `hsr-100003` 起按首次登场顺序递增；跨期、跨版本持续开放的同一池只分配一个 ID |
