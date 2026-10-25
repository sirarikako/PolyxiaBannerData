# PolyxiaBannerData

<p align="center">
  <img src="assets/Polyxia_250px.png" alt="Polyxia">
</p>

原神（Genshin Impact）与崩坏：星穹铁道（Honkai: Star Rail）的公开卡池情报与 JSON Schema 仓库。

Public, versioned gacha-banner metadata for Genshin Impact and Honkai: Star Rail.

## 数据接口 / Public data

| 数据 | 用途 |
| --- | --- |
| [Manifest](public/v1/manifest.json) | 文件清单与校验信息 |
| [原神 v1](public/v1/genshin.json) | 原神卡池 |
| [星铁 v1](public/v1/starrail.json) | 星铁卡池 |
| [JSON Schema](schemas/public/v1/) | v1 数据格式 |
| [物品 ID 对照表](public/item-mappings/README.md) | 按游戏与语言查询物品名称和 ID |

GitHub Raw 可直接读取：
- [Manifest](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/manifest.json)
- [Genshin](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/genshin.json)
- [Star Rail](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/starrail.json)

客户端应固定支持的 API 版本（如 `v1`），并按 Manifest 的记录使用文件。

## 生产与维护 / Production

本仓库**独立运行**公告采集、解析、卡池数据发布、物品 ID 更新和 Manifest 校验，不依赖其他仓库同步生成的数据。

- `.github/workflows/`：六份正式生产 Actions（0-1、1-1、2-1/2-2、3-1/3-2）。
- `scripts/`：采集、OCR、候选整合、校验与发布代码；参见[生产脚本说明](scripts/README.md)。
- `data/derived/`：结构化公告、增量 checkpoint、候选和诊断数据。
- `manual/`：人工补充、核对及版本修正。
- `public/` 与 `schemas/public/`：供客户端使用的正式数据及其格式定义。

**开发与回归测试在私有仓库进行；验证通过后将代码和工作流变更部署到本仓库。** 本仓库的生产 Actions 仍会执行正式数据校验和发布安全检查。

完整官方公告原文与 OCR 图片仅在当次 GitHub Actions Runner 临时使用，不提交本仓库，也不上传公开 Artifact。长期保留的中间结果位于 `data/derived/`。

## 使用说明 / Notes

本仓库并非 HoYoverse 官方项目。这里提供的是卡池元数据，不包含玩家个人抽卡记录或保底进度；UIGF 抽卡记录与本项目数据用途不同。
