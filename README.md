<p align="center">
  <img src="assets/Polyxia_Color_500px.png" alt="Polyxia">
</p>

# PolyxiaBannerData

原神（Genshin Impact）与崩坏：星穹铁道（Honkai: Star Rail）的公开卡池情报与 JSON Schema 仓库。

Public, versioned gacha-banner metadata for Genshin Impact and Honkai: Star Rail.

## 数据接口 / Public data

以下为对外提供的正式数据。卡池接口版本为 `v1`，客户端可通过 GitHub Raw 直接读取 JSON。

| 数据 | 接口或文档 | 用途 |
| --- | --- | --- |
| 发布清单（Manifest） | [manifest.json](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/manifest.json) | 数据生成时间、游戏文件路径及 SHA-256 校验信息 |
| 原神卡池 | [genshin.json](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/genshin.json) | 原神祈愿卡池的类型、UP、开放时间等元数据 |
| 星铁卡池 | [starrail.json](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/starrail.json) | 星铁跃迁卡池的类型、UP、开放时间等元数据 |
| 物品 ID 对照表 | [文件列表与格式说明](public/item-mappings/README.md) | 原神／星铁物品名称与 ItemID 的对应关系，支持简中、繁中、英文、日文 |
| JSON Schema | [卡池数据](schemas/public/v1/banner-data.schema.json) · [Manifest](schemas/public/v1/manifest.schema.json) | 对接时校验 JSON 数据格式 |

完整字段、卡池类型与空值含义参见 [v1 数据使用说明](public/v1/README.md)。

客户端建议固定使用所需版本（例如 `v1`），先读取 Manifest，再按其 `games.*.path` 获取对应游戏文件，并通过 `sha256` 判断数据是否发生变化。

## 数据更新 / Maintenance

本仓库使用 GitHub Actions 采集、校验并发布正式数据。对外服务以 `public/` 目录中的文件及 `schemas/public/` 中的格式定义为准；其余处理过程数据不作为稳定接口。

开发与回归测试在私有仓库进行，验证通过后再部署至本公开仓库。

## 使用说明 / Notes

本仓库并非 HoYoverse 官方项目。这里提供的是卡池元数据，不包含玩家个人抽卡记录或保底进度；UIGF 抽卡记录与本项目数据用途不同。

本项目使用了 [Dimbreath](https://github.com/DimbreathBot/TurnBasedGameData) 的数据，并曾在初期卡池统计中参考 [Paimon.moe](https://github.com/MadeBaruna/paimon-moe) 和 [Firefly](https://github.com/Natrium0521/Firefly) 的数据，特此感谢。

## License

Except for the [title image](assets/Polyxia_Color_500px.png), this project is released under [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/).

The title image is licensed under [CC BY-ND 4.0](https://creativecommons.org/licenses/by-nd/4.0/). You may redistribute it unchanged with credit to [this repository](https://github.com/sirarikako/PolyxiaBannerData).

Third-party content remains subject to the rights of its respective owners.
