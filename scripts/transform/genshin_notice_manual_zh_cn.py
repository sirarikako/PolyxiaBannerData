"""原神简中按公告 ID 的单套人工数据：补缺、比对，不静默覆盖自动结果。

manual/notices/genshin/zh-CN/miyoushe/<postId>.json
{"format":"genshin-notice-manual-v1","postId":"123","data":{"time":{"endAt":"..."}}}
自动缺失或 null 时用人工；自动有值时只对比，关键差异阻断，普通差异仅通知。
人工内容不能伪造官方来源、OCR 结果或解析元数据。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any

MANUAL_ROOT = Path("manual/notices/genshin/zh-CN/miyoushe")
FORMAT = "genshin-notice-manual-v1"
ALLOWED = {
    "version_update": {"version", "versionName", "maintenance", "newCharacters", "newWeapons"},
    "wish_preview": {"version", "phase", "time", "up", "additionalWishes"},
    "wish_notice": {"bannerName", "officialWishType", "poolType", "variant",
                    "time", "up", "selectable", "rules"},
}
TIME_FIELDS = {"startAt", "endAt", "startCondition", "startRaw", "endRaw"}
LIST_FIELDS = {"fiveStarCharacters", "fourStarCharacters", "fiveStarWeapons", "fourStarWeapons",
               "fiveStarCharacters", "fiveStarWeapons"}
_MISSING = object()


def read_manual(path: Path, post_id: str, kind: str) -> dict:
    if not re.fullmatch(r"\d+", post_id) or kind not in ALLOWED:
        raise ValueError("不支持的公告 ID 或公告类型")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or not {"format", "postId", "data"}.issubset(data) or set(data) - {"format", "postId", "data", "note", "evidence"}
            or data["format"] != FORMAT or data["postId"] != post_id
            or not isinstance(data["data"], dict) or not data["data"]):
        raise ValueError(f"{path}: 人工 JSON 格式或公告 ID 错误")
    if "note" in data and not isinstance(data["note"], str):
        raise ValueError(f"{path}: note 必须是字符串")
    if "evidence" in data and not isinstance(data["evidence"], dict):
        raise ValueError(f"{path}: evidence 必须是对象")
    unknown = set(data["data"]) - ALLOWED[kind]
    if unknown:
        raise ValueError(f"{path}: 不允许人工修改源标识或不属于该公告的字段：{sorted(unknown)}")
    if "time" in data["data"]:
        time = data["data"]["time"]
        if not isinstance(time, dict) or not time or set(time) - TIME_FIELDS:
            raise ValueError(f"{path}: time 只能包含时间字段")
    if "time" in data["data"]:
        for field in ("startAt", "endAt"):
            value = data["data"]["time"].get(field)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f"{path}: time.{field} 必须是 +08:00 时间字符串")
            try:
                dt = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{path}: time.{field} 不是 ISO 时间") from exc
            if dt.utcoffset() != timedelta(hours=8) or dt.second or dt.microsecond:
                raise ValueError(f"{path}: time.{field} 必须使用 +08:00 且精确到分钟")
    if "phase" in data["data"] and (
            type(data["data"]["phase"]) is not int or not 1 <= data["data"]["phase"] <= 9):
        raise ValueError(f"{path}: phase 必须是 1 到 9 的整数")
    if "up" in data["data"] or "selectable" in data["data"]:
        for key in ("up", "selectable"):
            groups = data["data"].get(key)
            if groups is None:
                continue
            if not isinstance(groups, dict) or set(groups) - LIST_FIELDS:
                raise ValueError(f"{path}: {key} 的字段不正确")
            for name, items in groups.items():
                if not isinstance(items, list) or not all(
                    (isinstance(x, str) and x.strip()) or
                    (isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].strip())
                    for x in items
                ):
                    raise ValueError(f"{path}: {key}.{name} 必须是名称数组或含 name 的对象数组")
    return data["data"]


def normalize(value: Any, field: str = "") -> Any:
    """只对名单消除顺序及对象额外属性的影响；时间统一瞬时表达由上游定义。"""
    if isinstance(value, list) and field in LIST_FIELDS:
        names = []
        for item in value:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                names.append(item["name"])
            else:
                # 自动解析出的坏结构也是冲突证据，不能导致整合器自身崩溃。
                return value
        return sorted(names)
    return value


def merge_data(auto: dict, human: dict) -> tuple[dict, list[dict], list[str], list[str]]:
    result = deepcopy(auto)
    differences: list[dict] = []
    filled: list[str] = []
    matched: list[str] = []

    def walk(target: dict, proposed: dict, prefix: str = "") -> None:
        for name, human_value in proposed.items():
            # 人工 null 表示尚未提供，不应拿未知值覆盖或冲突自动数据。
            if human_value is None:
                continue
            key = f"{prefix}.{name}" if prefix else name
            auto_value = target.get(name, _MISSING)
            if isinstance(human_value, dict) and (
                    isinstance(auto_value, dict) or auto_value is _MISSING or auto_value is None):
                if not isinstance(auto_value, dict):
                    target[name] = {}
                walk(target[name], human_value, key)
            elif auto_value is _MISSING or auto_value is None:
                target[name] = deepcopy(human_value)
                filled.append(key)
            elif normalize(auto_value, name) == normalize(human_value, name):
                matched.append(key)
            else:
                differences.append({"field": key, "automatic": deepcopy(auto_value),
                                    "manual": deepcopy(human_value)})
    walk(result, human)
    return result, differences, filled, matched


def is_blocking_difference(kind: str, field: str) -> bool:
    """按最终卡池安全性划分人工与自动解析差异。

    名称（仅显示）、原文描述和其他语言名称属于提醒；
    身份、UP 清单、时间和物品 ID 属于阻断。
    """
    if field.endswith("itemId") or ".itemId" in field:
        return True
    critical = {
        "version_update": ("version", "maintenance.startAt"),
        "wish_preview": ("version", "phase", "time.startAt", "time.endAt",
                         "time.startCondition", "up", "additionalWishes"),
        "wish_notice": ("poolType", "variant", "officialWishType",
                        "time.startAt", "time.endAt", "time.startCondition",
                        "up", "selectable"),
    }
    return any(field == name or field.startswith(name + ".")
               for name in critical.get(kind, ()))


def classify_differences(kind: str, differences: list[dict]) -> tuple[list[dict], list[dict]]:
    blocking, warning = [], []
    for entry in differences:
        (blocking if is_blocking_difference(kind, str(entry.get("field") or "")) else warning).append(entry)
    return blocking, warning


def apply(root: Path, kind: str, post_id: str, auto: dict) -> dict:
    path = root / MANUAL_ROOT / f"{post_id}.json"
    if not path.is_file():
        return {"data": deepcopy(auto), "differences": [],
                "blockingDifferences": [], "warningDifferences": [], "filled": [],
                "matched": [], "manualFile": None}
    manual = read_manual(path, post_id, kind)
    effective, differences, filled, matched = merge_data(auto, manual)
    blocking, warning = classify_differences(kind, differences)
    return {"data": effective, "differences": differences,
            "blockingDifferences": blocking, "warningDifferences": warning,
            "filled": filled, "matched": matched,
            "manualFile": path.relative_to(root).as_posix()}


def partial_from_raw(root: Path, post_id: str, kind: str, raw_path: Path) -> dict:
    """解析器完全退出时，仅用本地真实原文保存来源身份，其余依赖人工补齐。"""
    source_file = raw_path.relative_to(root).as_posix()
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    post = payload["data"]["post"]["post"]
    if (str(post.get("post_id")) != post_id
            or post.get("game_id") not in (None, "", 0, "0", 2, "2")
            or (post.get("post_status") or {}).get("is_official") is False):
        raise ValueError(f"{raw_path}: 原始文章身份不符，禁止使用人工数据伪造公告")
    return {"game": "genshin", "locale": "zh-CN", "noticeType": kind,
            "source": {"postId": post_id,
                       "title": post.get("subject"),
                       "url": f"https://www.miyoushe.com/ys/article/{post_id}",
                       "rawFile": source_file},
            "review": {"warnings": []}}


def index_additional(root: Path, existing: list[dict], kind: str) -> list[dict]:
    """仅为已经抓取到真实原文、但解析脚本未生成 JSON 的文章创建补丁候选。"""
    checkpoint = root / "data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json"
    if not checkpoint.is_file():
        return []
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    known = {str(r.get("data", {}).get("source", {}).get("postId")) for r in existing if "data" in r}
    candidates = []
    # 完全解析失败、后来靠人工恢复的公告，需在每次整合时继续按真实原文重建。
    # 不能因为它已不在 manualReview 就把候选误删。
    tracked = dict(state.get("manualRecovered") or {})
    tracked.update(state.get("manualReview") or {})
    for pid, entry in tracked.items():
        if pid in known or entry.get("kind") != kind:
            continue
        manual = root / MANUAL_ROOT / f"{pid}.json"
        raw = root / "data/announcements/genshin/zh-cn/miyoushe/posts" / f"{pid}.json"
        if pid in (state.get("manualRecovered") or {}) and not manual.is_file():
            candidates.append({"path": raw.relative_to(root).as_posix(),
                               "error": "已经用人工文件恢复的公告缺少原人工 JSON", "postId": pid})
            continue
        if not manual.is_file() or not raw.is_file():
            continue
        try:
            base = partial_from_raw(root, pid, kind, raw)
            if entry.get("title") and entry["title"] != base["source"]["title"]:
                raise ValueError("原始文章标题与发现时的标题不同，禁止人工恢复错误来源")
            patched = apply(root, kind, pid, base)
            data = patched["data"]
            if kind == "version_update":
                filename = f"version-update_zh-CN_{data.get('version', 'unknown')}.json"
                folder = "version-updates"
            elif kind == "wish_preview":
                filename = f"wish-preview_zh-CN_{data.get('version', 'unknown')}-phase-{data.get('phase', 'unknown')}.json"
                folder = "wish-previews"
            else:
                filename, folder = f"wish-notice_zh-CN_{pid}.json", "wish-notices"
            candidates.append({"path": f"data/derived/genshin/{folder}/{filename}",
                               "evidenceFile": raw.relative_to(root).as_posix(),
                               **patched, "fallback": True})
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
            candidates.append({"path": raw.relative_to(root).as_posix(),
                               "error": f"无法使用人工数据恢复解析：{exc}", "postId": pid})
    return candidates
