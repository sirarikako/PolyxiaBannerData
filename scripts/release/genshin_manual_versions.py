"""按游戏_版本拆分的原神人工覆盖文件。只读取 manual 根目录下 genshin_*.json。

每一条人工修改有 pending/completed 状态；completed 不重新参与合并。
manual/archive/ 下的文件不被扫描，用户可将全完成的版本移入归档。
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re

FORMAT = "genshin-v1-overrides-v2"
PATCH_KEYS = {"set", "itemIds", "addSources"}
ENTRY_KEYS = PATCH_KEYS | {"match", "id", "status", "completedAt", "appliedId"}
MATCH_KEYS = {"version", "phase", "poolType", "variant", "bannerName", "postId"}
EDITABLE = {"names", "gachaTypes", "featured", "regions", "sources", "images", "fatePointLimit"}
POOL_TYPES = ("character_event", "character_event_2", "weapon_event", "chronicled")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_patch(entry: dict, label: str) -> None:
    check(isinstance(entry, dict) and not (set(entry) - ENTRY_KEYS),
          f"{label}: 不支持的人工配置字段")
    check(bool(PATCH_KEYS & set(entry)), f"{label}: 需包含 set、itemIds 或 addSources")
    check(entry.get("status", "pending") in ("pending", "completed"),
          f"{label}: status 只能是 pending 或 completed")
    if "completedAt" in entry:
        check(isinstance(entry["completedAt"], str) and entry["completedAt"],
              f"{label}: completedAt 必须是非空字符串")
    if "appliedId" in entry:
        check(isinstance(entry["appliedId"], str) and re.fullmatch(r"gi-\d{6}", entry["appliedId"]) is not None,
              f"{label}: appliedId 无效")
    fields = entry.get("set", {})
    check(isinstance(fields, dict) and not (set(fields) - EDITABLE),
          f"{label}: set 只能包含可编辑 v1 字段")
    ids = entry.get("itemIds", {})
    check(isinstance(ids, dict) and all(
        isinstance(k, str) and bool(k.strip())
        and (v is None or (isinstance(v, str) and re.fullmatch(r"[1-9]\d*", v) is not None))
        for k, v in ids.items()), f"{label}: itemIds 必须为“名称: 正整数ID字符串/null”")
    sources = entry.get("addSources", [])
    check(isinstance(sources, list) and all(isinstance(x, dict) for x in sources),
          f"{label}: addSources 必须是来源对象数组")


def load_manual_versions(folder: Path, rejected: list[dict] | None = None) -> dict:
    """返回文件与条目引用。不触碰文件系统内容；状态只在调用方成功写入后落盘。"""
    files: list[dict] = []
    upcoming: list[dict] = []
    existing: list[dict] = []
    seen_existing: set[str] = set()
    seen_upcoming: set[tuple[str, str]] = set()

    if folder.exists() and not folder.is_dir():
        raise ValueError(f"{folder}: --manual 必须为目录")
    for path in sorted(folder.glob("genshin_*.json")):
        old_files, old_upcoming, old_existing = len(files), len(upcoming), len(existing)
        old_seen_existing, old_seen_upcoming = seen_existing.copy(), seen_upcoming.copy()
        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                raise ValueError(f"{path}: JSON 读取失败: {exc}") from exc
            check(isinstance(data, dict), f"{path}: JSON 根必须是对象")
            version = data.get("version")
            check(isinstance(version, str) and bool(version) and path.name == f"genshin_{version}.json",
                  f"{path}: 文件名必须为 genshin_<version>.json，且与 version 字段一致")
            check(data.get("format") == FORMAT and data.get("game") == "genshin"
                  and data.get("locale") == "zh-CN"
                  and not (set(data) - {"format", "game", "locale", "version", "upcoming", "existing"}),
                  f"{path}: 文件格式/游戏/语言无效")
            check(isinstance(data.get("upcoming"), list) and isinstance(data.get("existing"), list),
                  f"{path}: upcoming/existing 必须是数组")
            files.append({"path": path, "data": data})
            for group in ("upcoming", "existing"):
                for idx, entry in enumerate(data[group]):
                    label = f"{path.name}/{group}[{idx}]"
                    validate_patch(entry, label)
                    ref = {"file": path, "data": data, "version": version,
                           "group": group, "index": idx, "entry": entry}
                    active = entry.get("status", "pending") == "pending"
                    if group == "existing":
                        bid = entry.get("id")
                        check(isinstance(bid, str) and re.fullmatch(r"gi-\d{6}", bid) is not None,
                              f"{label}: 必须填写原神内部 ID")
                        check("match" not in entry, f"{label}: existing 不允许 match")
                        if active:
                            check(bid not in seen_existing, f"{label}: 重复的 pending 内部 ID")
                            seen_existing.add(bid)
                        existing.append(ref)
                    else:
                        matcher = entry.get("match")
                        check(isinstance(matcher, dict) and not (set(matcher) - MATCH_KEYS)
                              and {"phase", "poolType"} <= set(matcher) and "id" not in entry,
                              f"{label}: match 需要 phase、poolType，不得预设内部 ID")
                        check("version" not in matcher or matcher["version"] == version,
                              f"{label}: match.version 必须与文件版本相同")
                        check(type(matcher["phase"]) is int and 1 <= matcher["phase"] <= 9
                              and matcher["poolType"] in POOL_TYPES,
                              f"{label}: match 期数或 poolType 不正确")
                        if "variant" in matcher:
                            check(matcher["poolType"] == "chronicled"
                                  and matcher["variant"] in ("chronicled", "special_recollection"),
                                  f"{label}: variant 无效")
                        for field in ("bannerName", "postId"):
                            if field in matcher:
                                check(isinstance(matcher[field], str) and bool(matcher[field]),
                                      f"{label}: {field} 必须是非空字符串")
                        if "postId" in matcher:
                            check(re.fullmatch(r"\d+", matcher["postId"]) is not None,
                                  f"{label}: postId 必须为数字字符串")
                        normalized = {**matcher, "version": version}
                        stamp = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
                        if active:
                            check((version, stamp) not in seen_upcoming,
                                  f"{label}: 重复的 pending 预设匹配条件")
                            seen_upcoming.add((version, stamp))
                        ref["match"] = normalized
                        upcoming.append(ref)
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            if rejected is None:
                raise
            del files[old_files:]
            del upcoming[old_upcoming:]
            del existing[old_existing:]
            seen_existing, seen_upcoming = old_seen_existing, old_seen_upcoming
            rejected.append({"file": path.name, "group": "manual", "error": str(exc)})
    return {"files": files, "upcoming": upcoming, "existing": existing}


def complete(entry_ref: dict, applied_id: str, timestamp: str) -> None:
    entry_ref["entry"]["status"] = "completed"
    entry_ref["entry"]["completedAt"] = timestamp
    entry_ref["entry"]["appliedId"] = applied_id


def is_pending(ref: dict) -> bool:
    return ref["entry"].get("status", "pending") == "pending"
