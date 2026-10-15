# PolyxiaBannerData

原神（Genshin Impact）与崩坏：星穹铁道（Honkai: Star Rail）的公开卡池情报与 JSON Schema 数据仓库。

Public versioned gacha banner metadata and JSON Schemas for Genshin Impact and Honkai: Star Rail.

## 数据目录 / Data layout

| 路径 | 说明 |
| --- | --- |
| [`public/v1/`](public/v1/) | 正式发布的 v1 卡池数据与 Manifest |
| [`public/v1/manifest.json`](public/v1/manifest.json) | 数据文件索引及校验信息 |
| [`public/v1/genshin.json`](public/v1/genshin.json) | 原神卡池情报 |
| [`schemas/public/v1/`](schemas/public/v1/) | v1 数据格式的 JSON Schema |

客户端应固定请求其支持的接口版本，例如 `public/v1/`。数据更新不代表接口格式版本升级；不兼容的结构变更将使用新的版本目录。

## 获取数据 / Access

可通过 GitHub Raw URL 获取公开数据：

- [Manifest](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/manifest.json)
- [Genshin Impact](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/genshin.json)

相关 JSON 文件及后续游戏数据请以 [Manifest](public/v1/manifest.json) 中的记录为准。

## 更新与维护 / Updates

此仓库是只读发布镜像。卡池资料在私有维护仓库中采集、整理并验证后，通过 GitHub Actions 自动同步 `public/` 和 `schemas/` 到此仓库。

请勿直接修改这两个目录：下一次同步会覆盖其中的更改，包括删除源仓库中已经移除的文件。

更新内容涉及原始资料采集、内部脚本和人工校正记录时，不会将这些内部目录同步到公开仓库。

## 数据使用提示 / Notes

- 本仓库收录的是**卡池元数据**，不是个人抽卡记录。
- 公开数据格式与 UIGF 抽卡记录格式用途不同。
- 请以 Manifest 和 Schema 判断文件结构及字段含义。
- 此仓库不是 HoYoverse 官方项目。
