"""Safely supplement Genshin notice candidates using archived official Webstatic details.

P3 deliberately does not replace missing articles, preview/version sources, OCR
time evidence, special-pool rules, or existing V1 banners. It only fills absent
name/UP roster entries on a *uniquely* matched normal banner. Conflicts never
overwrite announcement/manual values.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from pathlib import Path

from scripts.collect.collect_genshin_webstatic import STORE, _detail_ready, _encoded, _load, _sha

CN = timezone(timedelta(hours=8))
TITLE = re.compile(r"「([^」]+)」")
TAGS = re.compile(r"<[^>]+>")
POOL_RAW = {"character_event": 301, "character_event_2": 400, "weapon_event": 302}
FIELDS = {
    301: {"fiveStarCharacters": ("r5_up_items", "角色"),
          "fourStarCharacters": ("r4_up_items", "角色")},
    400: {"fiveStarCharacters": ("r5_up_items", "角色"),
          "fourStarCharacters": ("r4_up_items", "角色")},
    302: {"fiveStarWeapons": ("r5_up_items", "武器"),
          "fourStarWeapons": ("r4_up_items", "武器")},
}
OTHER_FIELDS = ("fiveStarCharacters", "fourStarCharacters", "fiveStarWeapons", "fourStarWeapons")


def _stamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN)
        return dt.astimezone(CN)
    except ValueError:
        return None


def _banner_name(title: str) -> str:
    plain = TAGS.sub("", title).strip()
    match = TITLE.search(plain)
    return match.group(1).strip() if match else plain


def _official_names(detail: dict, field: str, expected_type: str) -> list[str] | None:
    source = detail.get(field)
    if not isinstance(source, list):
        return None
    names: list[str] = []
    for item in source:
        if not isinstance(item, dict) or (item.get("item_type_cn") or item.get("item_type")) != expected_type:
            return None
        name = item.get("item_name")
        if not isinstance(name, str) or not name.strip():
            return None
        names.append(name.strip())
    return names if len(set(names)) == len(names) else None


def _read_official(root: Path) -> list[dict]:
    checkpoint = _load(root / STORE / "checkpoint.json", {"banners": {}})
    result = []
    for gid, info in sorted(checkpoint.get("banners", {}).items()):
        if not info.get("detailReadyAt") or not info.get("detailSha256"):
            continue
        detail_path = root / STORE / "details" / (gid + ".json")
        if not detail_path.is_file():
            continue
        try:
            detail = _load(detail_path)
            raw_type = info.get("gachaType")
            if raw_type not in FIELDS or detail.get("gacha_type") != raw_type:
                continue
            if not _detail_ready(detail, raw_type) or _sha(_encoded(detail)) != info["detailSha256"]:
                continue
            end_time = _stamp(info.get("endTime"))
            begin_time = _stamp(info.get("beginTime"))
            if end_time is None or begin_time is None:
                continue
            result.append({"gachaId": gid, "gachaType": raw_type, "detail": detail,
                           "begin": begin_time, "end": end_time,
                           "detailSha256": info["detailSha256"],
                           "url": info.get("detailUrl")})
        except (OSError, ValueError, TypeError):
            continue
    return result


def load_official(root: Path) -> list[dict]:
    """No network; official source is optional and must never break 3-1."""
    try:
        return _read_official(root)
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def _preview_allows(preview: dict, raw_type: int, official: dict[str, list[str]]) -> bool:
    up = preview.get("up") or {}
    field = "fiveStarWeapons" if raw_type == 302 else "fiveStarCharacters"
    entries = up.get(field) or []
    names = [x.get("name") if isinstance(x, dict) else x for x in entries]
    five = official[field]
    if not names or any(not isinstance(n, str) for n in names):
        return False
    if raw_type == 302:
        return sorted(set(names)) == sorted(five)
    return set(five).issubset(set(names))


def _notice_names(notice: dict, field: str) -> list[str] | None:
    up = notice.get("up") or {}
    value = up.get(field) or []
    if not isinstance(value, list):
        return None
    names = [x.get("name") if isinstance(x, dict) else x for x in value]
    if any(not isinstance(name, str) or not name for name in names):
        return None
    return names


def supplement(notice: dict, preview: dict, official: list[dict],
               *, manual_fields: set[str] | None = None) -> tuple[dict, dict]:
    """Return (copy of notice, report). A mismatch preserves the original notice."""
    pool_type = notice.get("poolType")
    raw_type = POOL_RAW.get(pool_type)
    result = {"status": "unavailable", "usedFields": [], "fieldModes": {}, "conflicts": []}
    if raw_type is None:
        result["status"] = "unsupported_pool_type"
        return notice, result

    end = _stamp((notice.get("time") or {}).get("endAt"))
    if end is None:
        return notice, result
    start = _stamp((notice.get("time") or {}).get("startAt"))
    eligible = []
    for record in official:
        if record["gachaType"] != raw_type:
            continue
        # Webstatic and Miyoushe use the same end-minute, but the API's
        # first-phase begin_time can be one hour after V1's maintenance start.
        if abs(record["end"] - end) > timedelta(seconds=59):
            continue
        if start and abs(record["begin"] - start) > timedelta(minutes=90):
            continue
        eligible.append(record)
    if not eligible:
        result["status"] = "no_match"
        return notice, result
    if len(eligible) != 1:
        result["status"] = "ambiguous"
        return notice, result

    item = eligible[0]
    result.update({"status": "matched", "gachaId": item["gachaId"],
                   "detailSha256": item["detailSha256"], "url": item["url"]})
    detail = item["detail"]
    roster = {}
    for field, (source, expected_type) in FIELDS[raw_type].items():
        names = _official_names(detail, source, expected_type)
        if names is None:
            result["status"] = "invalid_official_roster"
            return notice, result
        roster[field] = names
    if not _preview_allows(preview, raw_type, roster):
        result["status"] = "conflict"
        result["conflicts"].append("official_five_star_preview_conflict")
        return notice, result

    proposed = deepcopy(notice)
    proposed_up = proposed.setdefault("up", {})
    if not isinstance(proposed_up, dict):
        result.update(status="conflict", conflicts=["invalid_notice_up"])
        return notice, result

    official_title = _banner_name(detail["title"])
    current_title = notice.get("bannerName")
    if current_title and current_title.strip() != official_title:
        result["conflicts"].append("official_banner_name_conflict")
    # Do not mix character/weapon UP fields; a mismatched existing field is
    # a conflict even when Webstatic could fill the other fields.
    for field in OTHER_FIELDS:
        if field not in roster and _notice_names(notice, field):
            result["conflicts"].append("unexpected_" + field)
    for field, expected in roster.items():
        existing = _notice_names(notice, field)
        if existing is None or len(set(existing)) != len(existing):
            result["conflicts"].append("invalid_" + field)
        elif not set(existing).issubset(set(expected)):
            result["conflicts"].append("official_" + field + "_conflict")
    if result["conflicts"]:
        result["status"] = "conflict"
        return notice, result

    protected = manual_fields or set()
    if not current_title and "bannerName" not in protected:
        proposed["bannerName"] = official_title
        result["usedFields"].append("names.zh-CN")
        result["fieldModes"]["names.zh-CN"] = "webstatic_only"
    for field, expected in roster.items():
        if any(x == "up" or x.startswith("up." + field) or x == "up." + field for x in protected):
            continue
        old = proposed_up.get(field) or []
        existing = {x.get("name") if isinstance(x, dict) else x: x for x in old}
        if set(existing) == set(expected):
            continue
        proposed_up[field] = [existing.get(name, {"name": name}) for name in expected]
        target = "featured.fiveStar" if field.startswith("fiveStar") else "featured.fourStar"
        result["usedFields"].append(target)
        result["fieldModes"][target] = "mixed" if existing else "webstatic_only"

    if result["usedFields"]:
        result["usedFields"] = sorted(set(result["usedFields"]))
        result["status"] = "filled"
        # Only a previously missing UP/name warning can be cleared, and only
        # after the full normal-pool roster passes the normal assembler checks.
        if "featured.fiveStar" in result["usedFields"] or "featured.fourStar" in result["usedFields"]:
            review = proposed.get("review") or {}
            if isinstance(review, dict):
                review["warnings"] = [w for w in review.get("warnings", [])
                                      if w != "正文没有识别出明确的概率 UP 或可定轨物品"]
                proposed["review"] = review
    return proposed, result
