# 原神简体中文版本更新说明（内部候选）

本目录保存从米游社完整版本更新说明生成的结构化候选 JSON，每个版本一个文件（如 `version-update_zh-CN_7.1.json`）。文件名前缀 `version-update` 代表版本更新，`zh-CN` 代表简体中文。

- 原始公告归档位于 `data/announcements/genshin/zh-cn/miyoushe/posts/`。
- 转换脚本：`scripts/transform/build_genshin_version_update_zh_cn.py`。
- 从仓库根目录执行：`python -m scripts.transform.build_genshin_version_update_zh_cn --post-id 78335167`。
- 默认离线读取 `posts/78335167.json` 并保存 `version-update_zh-CN_7.1.json`。可用 `--input` / `--output` 指定路径；若目标内容不同，须显式使用 `--force` 才覆盖。
- 输出包含版本号、版本名、维护开始时间、**预计**维护时长与结束时间、新增角色属性、新增武器及其获取方式、公告来源和复核提示。
- 预计维护结束时间仅根据公告估算，不代表实际开服时间；版本公告不用于断言某个卡池的 UP 名单或起止时间。
- `review.status=pending_manual_review` 表示这是未经逐条人工复核的候选数据，不能直接发布。
- 不负责自动发现或联网采集，不更改 `public/v1/`、`schemas/`、Manifest，也不触发新的采集 Action。
- 长期作为人工指定公告 ID 的版本信息提取工具保留；以后如果设计自动发现，只需要调用现有转换入口，不需要迁移目录。

**已知限制：** 只接受标题含数字版本号或「月之N」版本号且符合「版本更新说明」规则的公告；旧版本标题、章节和武器标注形式可能不同，提取为空时应查看警告并人工核对，不得把空列表直接当作确无新增物品。完整 HTML 的折叠栏目是必要输入，不能只使用有可能缺失这些栏目内容的 `structured_content`。
