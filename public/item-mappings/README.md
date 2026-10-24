# 物品 ID 对照表

本目录按游戏和语言提供「**物品名称 → 物品 ID**」的 JSON 对照表，可用于将抽卡记录中的 `item_id` 与物品名称关联。

## 数据文件

| 游戏 | 语言 | 文件 |
| --- | --- | --- |
| 原神 | 简体中文（`zh-CN`） | [genshin/zh-CN.json](./genshin/zh-CN.json) |
| 原神 | 繁体中文（`zh-TW`） | [genshin/zh-TW.json](./genshin/zh-TW.json) |
| 原神 | 英文（`en-US`） | [genshin/en-US.json](./genshin/en-US.json) |
| 原神 | 日文（`ja-JP`） | [genshin/ja-JP.json](./genshin/ja-JP.json) |
| 崩坏：星穹铁道 | 简体中文（`zh-CN`） | [starrail/zh-CN.json](./starrail/zh-CN.json) |
| 崩坏：星穹铁道 | 繁体中文（`zh-TW`） | [starrail/zh-TW.json](./starrail/zh-TW.json) |
| 崩坏：星穹铁道 | 英文（`en-US`） | [starrail/en-US.json](./starrail/en-US.json) |
| 崩坏：星穹铁道 | 日文（`ja-JP`） | [starrail/ja-JP.json](./starrail/ja-JP.json) |

## 数据格式

文件是普通 JSON 对象：**键为物品名称，值为物品 ID（整数）**。条目按 ID 的数值从小到大排列，不包含额外的元数据。

例如，原神对照表中的条目：

```json
{
  "风鹰剑": 11501,
  "温迪": 10000022
}
```

## 使用方法

读取对应游戏和语言的 JSON 文件后，可以通过名称查询 ID，也可以建立反向字典，通过 ID 查询名称。

以下为 Python 示例（以原神为例）：

```python
import json

with open("genshin/zh-CN.json", encoding="utf-8") as f:
    name_to_id = json.load(f)

# 通过名称查询 ID
item_id = name_to_id.get("温迪")

# 通过 ID 查询名称
id_to_name = {id_: name for name, id_ in name_to_id.items()}
item_name = id_to_name.get(10000022)
```

**注意：** 原神与星铁的物品 ID 应分别使用对应游戏的对照表；对照表不代表游戏完整物品库，未查到的物品不能直接判定为无效。

三种国际服语言使用官方国际服名称，非自动翻译。各语言文件中的名称可能不同，但对应的 ItemID 仍按同游戏同一物品关联。**同名不同 ID 属于合法情况**；由于格式仅允许一个名称对应一个整数 ID，同名的多个物品无法全部用这一格式表达，保留既有已发布的名称映射，不覆盖原条目。
