# PolyxiaBannerData

原神（Genshin Impact）与崩坏：星穹铁道（Honkai: Star Rail）的公开卡池情报与 JSON Schema 仓库。

Public, versioned gacha-banner metadata for Genshin Impact and Honkai: Star Rail.

## 数据接口 / Public data

| 数据 | 用途 |
| --- | --- |
| [Manifest](public/v1/manifest.json) | 文件清单与校验信息 |
| [原神 v1](public/v1/genshin.json) | 原神卡池 |
| [星铁 v1](public/v1/starrail.json) | 星铁卡池 |
| [JSON Schema](schemas/public/v1/) | v1 数据格式 |

GitHub Raw 可直接读取：
- [Manifest](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/manifest.json)
- [Genshin](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/genshin.json)
- [Star Rail](https://raw.githubusercontent.com/sirarikako/PolyxiaBannerData/main/public/v1/starrail.json)

客户端应固定支持的 API 版本（如 `v1`），并按 Manifest 的记录使用文件。

## 生产和维护 / Production

**本仓库已独立执行卡池采集、解析、发布及 Manifest 更新。** 旧 Private → Public 的 1-2 跨仓库同步已取消，`CastoriceWishBannerData` 保留为 Private 开发仓库，不执行生产。

- `.github/workflows/`：六份正式生产 Action（0-1、1-1、2-1/2-2、3-1/3-2）及只读安全测试
- `scripts/`：采集、OCR、结构化整合与发布代码，参阅 [脚本说明](scripts/README.md)
- `data/derived/`：持久保存的结构化公告、checkpoint、候选与诊断
- `manual/`：人工补充与版本修正
- `tests/`：发布合约、无原文恢复、防止数据泄露的测试

**完整公告原文与 OCR 图片只在 GitHub Actions Runner 当次临时使用，不提交 Public Git。** 不允许将 `data/announcements/**/posts/`、图片或旧归档 JSON 加入 Git/公开 Artifact；但结构化结果及来源核验状态仍会写入 `data/derived/`。

- [原神结构化数据目录](data/derived/genshin/README.md)
- [P4 切换验收记录](deploy/migration/P4-production-cutover-report.md)

## 使用说明 / Notes

本仓库不是 HoYoverse 官方项目，提供的是卡池元数据，不是个人抽卡记录；抽卡记录 UIGF 与这里的元数据用途不同。
