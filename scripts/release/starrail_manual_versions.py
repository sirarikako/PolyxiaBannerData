"""星铁版本级人工配置：upcoming 只补新池，existing 只定向修改正式内部 ID。"""
from __future__ import annotations

import json
from pathlib import Path
import re

FORMAT = "starrail-v1-overrides-v1"
IMMUTABLE = {"id", "gameVersion", "phase", "poolType", "category"}
EDITABLE = {"names", "featured", "regions", "gachaTypes", "gachaIds", "sources", "images"}
PATCH_KEYS = {"set", "itemIds", "addSources"}

def check(ok, message):
    if not ok:
        raise ValueError(message)

def load_versions(folder: Path, rejected=None):
    files, upcoming, existing = [], [], []
    seen_up, seen_old = set(), set()
    if folder.exists() and not folder.is_dir():
        raise ValueError("人工配置路径不是目录")
    for path in sorted(folder.glob("starrail_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            version = data.get("version")
            check(data.get("format") == FORMAT and data.get("game") == "starrail"
                  and data.get("locale") == "zh-CN" and isinstance(version, str)
                  and path.name == "starrail_" + version + ".json",
                  f"{path}: 格式、版本、文件名不一致")
            check(not (set(data) - {"format", "game", "locale", "version", "upcoming", "existing"})
                  and isinstance(data.get("upcoming"), list) and isinstance(data.get("existing"), list),
                  f"{path}: 顶层结构错误")
            local_up, local_old = [], []
            for group in ("upcoming", "existing"):
                for i, entry in enumerate(data[group]):
                    label = f"{path.name}/{group}[{i}]"
                    check(isinstance(entry, dict)
                          and not (set(entry) - (PATCH_KEYS | {"status", "appliedId", "completedAt", "match", "id"}))
                          and (set(entry) & PATCH_KEYS), f"{label}: 补丁字段非法")
                    check(entry.get("status", "pending") in {"pending", "completed"}, f"{label}: status 非法")
                    check(isinstance(entry.get("set", {}), dict)
                          and not (set(entry.get("set", {})) - EDITABLE), f"{label}: set 存在不可编辑字段")
                    ids = entry.get("itemIds", {})
                    check(isinstance(ids, dict) and all(
                        isinstance(k, str) and k and (v is None or
                        isinstance(v, str) and re.fullmatch(r"[1-9]\d*", v))
                        for k, v in ids.items()), f"{label}: itemIds 非法")
                    check(isinstance(entry.get("addSources", []), list), f"{label}: addSources 非数组")
                    if entry.get("status") == "completed":
                        check(isinstance(entry.get("appliedId"), str)
                              and re.fullmatch(r"hsr-\d{6}", entry["appliedId"])
                              and isinstance(entry.get("completedAt"), str),
                              f"{label}: completed 缺少应用记录")
                    ref = {"file": path, "data": data, "entry": entry, "version": version,
                           "group": group, "index": i}
                    if group == "existing":
                        bid = entry.get("id")
                        check(isinstance(bid, str) and re.fullmatch(r"hsr-\d{6}", bid)
                              and "match" not in entry, f"{label}: existing 必须且只能按 id")
                        if entry.get("status", "pending") == "pending":
                            check(bid not in seen_old, f"{label}: 重复 existing 目标")
                        local_old.append(ref)
                    else:
                        match = entry.get("match")
                        check(isinstance(match, dict)
                              and {"phase", "poolType", "bannerName"} <= set(match)
                              and not (set(match) - {"phase", "poolType", "bannerName", "version", "fiveStarName"})
                              and type(match["phase"]) is int and 1 <= match["phase"] <= 9
                              and match["poolType"] in {"character_event", "light_cone_event", "collab_character", "collab_light_cone"}
                              and isinstance(match["bannerName"], str) and match["bannerName"]
                              and match.get("version", version) == version
                              and ("fiveStarName" not in match or isinstance(match["fiveStarName"], str)
                                   and bool(match["fiveStarName"]))
                              and "id" not in entry,
                              f"{label}: upcoming 必须唯一定位版本/期数/池种/名称")
                        ref["identity"] = (version, match["phase"], match["poolType"],
                                           match["bannerName"], match.get("fiveStarName"))
                        if entry.get("status", "pending") == "pending":
                            check(ref["identity"] not in seen_up, f"{label}: 重复 upcoming 目标")
                        local_up.append(ref)
            for ref in local_up:
                if ref["entry"].get("status", "pending") == "pending":
                    check(ref["identity"] not in seen_up,
                          f"{path.name}: 重复 upcoming 身份")
                    seen_up.add(ref["identity"])
            for ref in local_old:
                if ref["entry"].get("status", "pending") == "pending":
                    seen_old.add(ref["entry"]["id"])
            files.append({"path": path, "data": data})
            upcoming.extend(local_up)
            existing.extend(local_old)
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            if rejected is None:
                raise
            rejected.append({"file": path.name, "error": str(exc)})
    return {"files": files, "upcoming": upcoming, "existing": existing}

def complete(ref, bid, stamp):
    entry = ref["entry"]
    entry["status"] = "completed"
    entry["appliedId"] = bid
    entry["completedAt"] = stamp

def is_pending(ref):
    return ref["entry"].get("status", "pending") == "pending"
