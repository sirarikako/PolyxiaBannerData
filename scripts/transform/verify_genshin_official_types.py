"""Verify Genshin raw gacha types from archived official Webstatic evidence.

Raw comes only from verified official gacha_type. UIGF uses an independently
reviewed mapping for existing V1 pool categories. Never use op_gacha_type as raw.
Unknown/mismatched official types prevent candidate publication; no network I/O.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from scripts.collect.collect_genshin_webstatic import STORE, _encoded, _load, _sha

CN = timezone(timedelta(hours=8))
TAG = re.compile(r"<[^>]*>")
TITLE = re.compile(r"「([^」]+)」")
RAW_TO_POOL = {301: "character_event", 400: "character_event_2",
               302: "weapon_event", 500: "chronicled"}
UIGF_BY_RAW = {301: "301", 400: "301", 302: "302", 500: "500"}
UIGF_BY_POOL = {"character_event": "301", "character_event_2": "301",
                "weapon_event": "302", "chronicled": "500"}


def normalized_title(value):
    if not isinstance(value, str):
        return ""
    text = TAG.sub("", value).strip()
    hit = TITLE.search(text)
    return (hit.group(1) if hit else text).strip()


def at_cn(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace(" ", "T"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=CN)).astimezone(CN)
    except ValueError:
        return None


def official_records(root: Path) -> list[dict]:
    """Return only complete, SHA-consistent list/detail pairs, including unknown raw types."""
    try:
        checkpoint = _load(root / STORE / "checkpoint.json", {"banners": {}})
        banners = checkpoint.get("banners", {})
        if not isinstance(banners, dict):
            return []
        records = []
        for gid, meta in sorted(banners.items()):
            if not re.fullmatch(r"[0-9a-f]{40}", gid) or not isinstance(meta, dict):
                continue
            path = root / STORE / "details" / (gid + ".json")
            if not path.exists() or not isinstance(meta.get("detailSha256"), str):
                continue
            try:
                data = _load(path)
                raw = meta.get("gachaType")
                if type(raw) is not int or type(data.get("gacha_type")) is not int:
                    continue
                if data["gacha_type"] != raw or _sha(_encoded(data)) != meta["detailSha256"]:
                    continue
                detail_op, list_op = data.get("op_gacha_type"), meta.get("opGachaType")
                if detail_op is not None and list_op is not None and detail_op != list_op:
                    continue
                name = normalized_title(data.get("title"))
                begin, end = at_cn(meta.get("beginTime")), at_cn(meta.get("endTime"))
                if not name or begin is None or end is None:
                    continue
                records.append({"gachaId": gid, "raw": raw,
                                "op": detail_op if detail_op is not None else list_op,
                                "name": name, "begin": begin, "end": end,
                                "detail": data,
                                "sha256": meta["detailSha256"],
                                "url": meta.get("detailUrl")})
            except (ValueError, OSError, TypeError, AttributeError):
                continue
        return records
    except (ValueError, OSError, TypeError, AttributeError):
        return []


def _official_five(detail):
    items = detail.get("r5_up_items")
    if not isinstance(items, list):
        return set()
    return {i.get("item_name") for i in items if isinstance(i, dict) and isinstance(i.get("item_name"), str)}


def _notice_five(notice):
    pool = notice.get("poolType")
    if pool == "chronicled":
        items = (notice.get("selectable") or {})
    else:
        items = notice.get("up") or {}
    result = []
    for field in ("fiveStarCharacters", "fiveStarWeapons"):
        for x in items.get(field) or []:
            n = x.get("name") if isinstance(x, dict) else x
            if isinstance(n, str) and n.strip():
                result.append(n.strip())
    return set(result)


def find_match(*, pool_type: str, name: str, start, end,
               five_names: set[str], records: list[dict]) -> tuple[dict | None, str]:
    """Match by time and title, or by a nonempty five-star roster when title is missing.

    *Never* restrict the search by assumed raw type: that would hide novel raw
    codes and category conflicts instead of warning about them.
    """
    finish = at_cn(end)
    opened = at_cn(start)
    if finish is None:
        return None, "unavailable"
    potential = []
    for rec in records:
        if abs(rec["end"] - finish) > timedelta(seconds=59):
            continue
        if opened is not None and abs(rec["begin"] - opened) > timedelta(minutes=90):
            continue
        if name:
            if rec["name"] != normalized_title(name):
                continue
        elif not five_names or not five_names.issubset(_official_five(rec["detail"])):
            continue
        potential.append(rec)
    if not potential:
        return None, "unavailable"
    if len(potential) != 1:
        return None, "ambiguous"
    return potential[0], "matched"


def verify_notice(notice: dict, records: list[dict], *, preferred_gacha_id: str | None = None) -> dict:
    pool = notice.get("poolType")
    fallback = UIGF_BY_POOL.get(pool)
    result = {"status": "unavailable", "raw": None,
              "uigf": [fallback] if fallback else None}
    if not fallback:
        return {"status": "unsupported_pool_type", "raw": None, "uigf": None}
    time = notice.get("time") or {}
    record, match_status = find_match(
        pool_type=pool, name=notice.get("bannerName") or "",
        start=time.get("startAt"), end=time.get("endAt"),
        five_names=_notice_five(notice), records=records)
    if record is not None and preferred_gacha_id and record["gachaId"] != preferred_gacha_id:
        match_status, record = "ambiguous", None
    if record is None:
        result["status"] = match_status
        return result
    raw = record["raw"]
    result.update({"gachaId": record["gachaId"],
                   "detailSha256": record["sha256"], "url": record["url"],
                   "officialRaw": raw, "opGachaType": record["op"]})
    if raw not in RAW_TO_POOL:
        result["status"] = "unknown_official_gacha_type"
        result["uigf"] = None
        return result
    if RAW_TO_POOL[raw] != pool:
        result["status"] = "official_gacha_type_pool_conflict"
        result["uigf"] = None
        return result
    if raw == 500 and record["op"] is not None:
        # Verified existing operator subtypes; don't guess future new variants.
        op_variant = {500: "chronicled", 5001: "special_recollection"}.get(record["op"])
        if op_variant is None:
            result["status"] = "unknown_official_op_gacha_type"
            result["uigf"] = None
            return result
        if op_variant != notice.get("variant"):
            result["status"] = "official_special_variant_conflict"
            result["uigf"] = None
            return result
    result.update({"status": "verified", "raw": [str(raw)],
                   "uigf": [UIGF_BY_RAW[raw]]})
    return result


def backfill_raw(banners: list[dict], records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Fill *only* null raw of existing V1, with uniquely matched official evidence.

    Existing non-null values are never touched. Can run after 1-2 archives
    arrive, even when the banner was published earlier from notices.
    """
    updated, conflicts = [], []
    for row in banners:
        if row.get("poolType") not in UIGF_BY_POOL:
            continue
        existing = (row.get("gachaTypes") or {}).get("raw")
        if existing is not None:
            continue
        region = next((r for r in (row.get("regions") or []) if r.get("server") == "cn_official"), None)
        if region is None:
            continue
        ending = at_cn(region.get("endAt"))
        if ending is None:
            continue
        # V1 exclusive endAt is Webstatic's minute-inclusive endAt + 1 minute.
        expected = ending - timedelta(minutes=1)
        found, status = find_match(
            pool_type=row["poolType"], name=(row.get("names") or {}).get("zh-CN") or "",
            start=region.get("startAt"), end=expected.isoformat(),
            five_names={i.get("names", {}).get("zh-CN") for i in
                        (row.get("featured") or {}).get("fiveStar", [])
                        if isinstance(i, dict)}, records=records)
        if status != "matched":
            if status == "ambiguous":
                conflicts.append({"id": row["id"], "reason": "ambiguous_official_gacha_type"})
            continue
        raw = found["raw"]
        if RAW_TO_POOL.get(raw) != row["poolType"] or raw not in UIGF_BY_RAW:
            conflicts.append({"id": row["id"], "gachaId": found["gachaId"],
                              "officialRaw": raw, "reason": "unverified_official_gacha_type"})
            continue
        if raw == 500 and found["op"] is not None and (
            {500: "chronicled", 5001: "special_recollection"}.get(found["op"])
            != row.get("variant")
        ):
            conflicts.append({"id": row["id"], "gachaId": found["gachaId"],
                              "reason": "unverified_official_special_variant"})
            continue
        if (row.get("gachaTypes") or {}).get("uigf") != [UIGF_BY_RAW[raw]]:
            conflicts.append({"id": row["id"], "gachaId": found["gachaId"],
                              "reason": "uigf_mapping_conflict"})
            continue
        # Extra guard: the normal fixed 5-star UP must match official exactly.
        if raw in (301, 400, 302):
            actual_five = {i.get("names", {}).get("zh-CN") for i in row.get("featured", {}).get("fiveStar", [])}
            if not actual_five or actual_five != _official_five(found["detail"]):
                conflicts.append({"id": row["id"], "gachaId": found["gachaId"],
                                  "reason": "five_star_roster_conflict"})
                continue
        row["gachaTypes"]["raw"] = [str(raw)]
        source = {"provider": "webstatic", "externalId": found["gachaId"], "url": found["url"]}
        if source not in row.get("sources", []):
            row.setdefault("sources", []).append(source)
        updated.append({"id": row["id"], "gachaId": found["gachaId"],
                        "raw": str(raw), "detailSha256": found["sha256"]})
    return updated, conflicts
