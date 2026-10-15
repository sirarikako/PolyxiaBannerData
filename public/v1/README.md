# 卡池情报数据 · v1

本目录提供统一格式的游戏卡池（祈愿／跃迁）**元数据**，用于客户端查询历史与当前卡池、识别卡池类别及对应的 UP／可定轨物品。数据不包含玩家的个人抽卡记录、保底进度或个人定轨结果。

## 当前已发布内容

| 游戏 | 服务器 | 收录范围 | 数据文件 |
| --- | --- | --- | --- |
| 原神（`genshin`） | 国服官服（`cn_official`） | 已录入的历史、当前和已公告卡池；含常驻与新手祈愿 | [genshin.json](./genshin.json) |
| 崩坏：星穹铁道（`starrail`） | — | **尚未发布** | — |

以 [manifest.json](./manifest.json) 的 `games` 列表为准：只有列出的游戏才代表已经发布。未出现的游戏或服务器不应视为已覆盖。

### 原神已收录的卡池类型

以下为 **2026-10-15（UTC+8）数据快照**，与当时的 `manifest.json` 一致。后续自动更新可能使数量变化，最新总数请读取 `games.genshin.bannerCount`。

| `poolType` | 卡池类型 | 记录数 |
| --- | --- | ---: |
| `character_event` | 角色活动祈愿 | 107 |
| `character_event_2` | 角色活动祈愿-2 | 81 |
| `weapon_event` | 武器活动祈愿（神铸赋形等） | 106 |
| `chronicled` | 集录祈愿、溯光祈愿 | 7 |
| `standard` | 常驻祈愿（奔行世间） | 1 |
| `beginner` | 新手祈愿（初行者推荐祈愿） | 1 |
| **合计** | | **303** |

原神记录包含从 1.0 版本开始的活动卡池，以及当前数据中已经收录的后续版本与「月之」系列版本。**实际覆盖范围、每期卡池和开放时间均以 [genshin.json](./genshin.json) 为准**，不应仅凭本页推断某一版本或服务器完全无缺项。

在 `chronicled` 类型下，`variant` 用于区分：
- `chronicled`：集录祈愿；
- `special_recollection`：溯光祈愿。

两者共用同一 `poolType`，各自的定轨上限由 `fatePointLimit` 记录。

### 原神内部卡池 ID 分配

普通活动池使用 `gi-000001`～`gi-099999`，常驻祈愿「奔行世间」使用 `gi-100001`，新手祈愿「初行者推荐祈愿」使用 `gi-100002`。早期发布的 `gi-000302`、`gi-000303` 已退役，今后不会重新分配。外部缓存或关联如使用旧 ID，应迁移至新 ID；`gachaTypes` 不变。

## 发布文件

| 路径 | 用途 |
| --- | --- |
| [manifest.json](./manifest.json) | 发布入口；包含 `schemaVersion`、`generatedAt`，以及各已发布游戏的文件路径、SHA-256 校验值和卡池记录数 |
| [genshin.json](./genshin.json) | 原神卡池数据；包含 `game`、`schemaVersion`、`generatedAt` 和 `banners` 数组 |

对应的 JSON Schema：
- [卡池数据结构](../../schemas/public/v1/banner-data.schema.json)
- [Manifest 结构](../../schemas/public/v1/manifest.schema.json)

## 每条卡池记录包含什么

| 字段 | 含义 |
| --- | --- |
| `id` | 本仓库内部稳定卡池 ID；**不是**玩家抽卡记录 ID |
| `gameVersion`、`phase` | 所属游戏版本和版本内期数（1～9）；不适用或未确认时可为 `null` |
| `category`、`poolType` | 用于展示的卡池分类、进一步细分的卡池类型 |
| `variant` | 原神集录大类的子类型：集录祈愿或溯光祈愿（仅相关卡池） |
| `names` | 按语言代码保存的卡池名称，目前已发布原神数据提供 `zh-CN` |
| `featured.fiveStar`、`featured.fourStar` | 五星、四星 UP 物品；**集录／溯光的五星列表是可选定轨目标名单，不表示全部同时固定 UP** |
| `featured.*[].itemId`、`type`、`names` | 物品 ID、角色或武器等类型、多语言名称；未核实的 ID 可为 `null` |
| `gachaTypes.raw`、`gachaTypes.uigf` | 已核实的官方原始抽卡类型及 UIGF 规范类型；原始类型尚未核实时 `raw` 可为 `null` |
| `regions` | 按服务器记录的 `server`、`startAt`、`endAt` |
| `fatePointLimit` | 原神武器活动池或集录大类的命定值上限；仅在适用时出现 |
| `sources` | 信息出处及可追溯链接 |
| `images`、`gachaIds` | 可选字段；`gachaIds` 仅适用于已核实官方卡池 ID 的星铁记录 |

### 使用时需注意

1. **时间统一为 UTC+8**：采用 ISO 8601 格式，例如 `2026-10-13T18:00:00+08:00`。区间的 `startAt` 包含起点，`endAt` 不包含终点。常驻／新手池无统一结束时间时，`endAt` 为 `null`。
2. **同一池可能有多个服务器时间**：`regions` 只列出已有可信数据的服务器；当前原神文件仅包含 `cn_official`，不能把国服时间直接当成其他服务器时间。
3. **区分空数组与 `null`**：UP／可定轨名单为 `null` 表示未知，`[]` 表示确认没有这一类固定 UP；尤其不要把常驻池的空 `featured` 列表理解为无法抽到五星或四星。
4. **抽卡类型并非单池唯一标识**：`gachaTypes.uigf` 用于标准化抽卡记录类别，例如原神角色活动祈愿-2 的官方 `raw=400` 映射为 UIGF `301`；不能仅用它确定具体是哪一期卡池。
5. **集录／溯光与普通 UP 不同**：`featured.fiveStar` 是当期允许选择的目标范围；数据不记录某位玩家最终选择了谁。
6. **客户端更新建议**：先获取 `manifest.json`，读取对应游戏的 `path`，下载 JSON 后校验 `sha256`，再替换本地缓存。`schemaVersion` 是接口结构的主版本，`generatedAt` 是数据生成时间。

本目录以公开数据的稳定结构和可追溯性为目标；如需确认某条历史记录，请结合其 `sources` 查阅原始公告。
