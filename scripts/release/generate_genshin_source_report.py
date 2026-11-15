"""Generate observational source provenance for Genshin candidates and Webstatic.

Never changes V1 or chooses a source for V1. Times mean first observer-run,
not the upstream's actual publication or first availability.
"""
from __future__ import annotations
import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.collect.collect_genshin_webstatic import (
    ROOT, STORE, _load, _write_if_changed, _encoded,
)

TZ8 = timezone(timedelta(hours=8))
SOURCE = Path("data/derived/genshin")
TRACE = SOURCE / "source-traces/observations.json"
REPORT = Path("data/BANNER_SOURCE_STATUS.md")
TAGS = re.compile(r"<[^>]*>")
QUOTED = re.compile(r'「([^」]+)」|"([^"]+)"')
TYPE = {100: "beginner", 200: "standard", 301: "character_event",
        400: "character_event_2", 302: "weapon_event", 500: "chronicled"}


def _title(value):
    clean = TAGS.sub("", value or "")
    hit = QUOTED.search(clean)
    return (hit.group(1) or hit.group(2)) if hit else clean.strip()


def _items(detail, field):
    value = detail.get(field)
    if value is None:
        return [] if field == "r4_up_items" and detail.get("gacha_type") == 500 else None
    if not isinstance(value, list):
        return None
    result = []
    for item in value:
        if not isinstance(item, dict):
            return None
        kind = {"角色": "character", "武器": "weapon",
                "Character": "character", "Weapon": "weapon"}.get(
                    item.get("item_type_cn") or item.get("item_type"))
        if not kind or not isinstance(item.get("item_name"), str):
            return None
        result.append((item["item_name"], kind))
    return sorted(result)


def _featured(banner, star):
    value = (banner.get("featured") or {}).get(star)
    if not isinstance(value, list):
        return None
    return sorted((x.get("names", {}).get("zh-CN"), x.get("type")) for x in value)


def _associate(v1, checkpoint, details_path):
    """Only accept unique combination of name, type, UP and start date."""
    found = defaultdict(list)
    for gid, meta in checkpoint.get("banners", {}).items():
        if not meta.get("detailReadyAt"):
            continue
        path = details_path / (gid + ".json")
        if not path.is_file():
            continue
        detail = _load(path)
        pool = TYPE.get(detail.get("gacha_type"))
        five, four = _items(detail, "r5_up_items"), _items(detail, "r4_up_items")
        if pool is None or five is None or four is None:
            continue
        matches = [x for x in v1
                   if x.get("poolType") == pool
                   and x.get("names", {}).get("zh-CN") == _title(detail.get("title"))
                   and _featured(x, "fiveStar") == five
                   and _featured(x, "fourStar") == four
                   and (x.get("regions") or [{}])[0].get("startAt", "")[:10] == meta.get("beginTime", "")[:10]]
        if len(matches) == 1:
            found[matches[0]["id"]].append(gid)
    return found


def _actual_fields(candidate):
    """Attribute actual candidate input fields, including P3 Webstatic supplements."""
    p = candidate.get("provenance") or {}
    notice = "miyoushe:" + str(p.get("noticePostId") or "manual")
    preview = "miyoushe:" + str(p.get("previewPostId") or "manual")
    version = "miyoushe:" + str(p.get("versionUpdatePostId") or "manual")
    ev = candidate.get("timeEvidence") or {}
    draft = candidate.get("v1Draft") or {}
    start = [notice] if (draft.get("regions") or [{}])[0].get("startAt") else [version, preview, notice]
    end = [notice + ":image-ocr"] if ev.get("endTimeSource") == "ocr" else (
        ["manual"] if ev.get("endTimeSource") == "manual" else [notice])
    fields = {
        "gameVersion": [version, preview],
        "phase": [preview],
        "names.zh-CN": [notice],
        "poolType": [notice],
        "gachaTypes.raw": ["pool-type-rule"],
        "gachaTypes.uigf": ["uigf-rule"],
        "featured.fiveStar": [notice],
        "featured.fourStar": [notice],
        "featured.itemId": ["official-item-mapping"],
        "regions.startAt": start,
        "regions.endAt": end,
    }
    extra = candidate.get("webstaticAugmentation") or {}
    gid = extra.get("gachaId")
    if gid:
        official = "webstatic:" + str(gid)
        for field in extra.get("usedFields", []):
            if field not in ("names.zh-CN", "featured.fiveStar", "featured.fourStar"):
                continue
            mode = (extra.get("fieldModes") or {}).get(field)
            fields[field] = ([notice, official] if mode == "mixed" else [official])
    if draft.get("variant"):
        fields["variant"] = [notice]
    if "fatePointLimit" in draft:
        fields["fatePointLimit"] = ["verified-current-project-rule"]
    return fields


def generate(root=ROOT, *, observed_at=None):
    observed_at = observed_at or datetime.now(TZ8).isoformat(timespec="seconds")
    path = root / TRACE
    state = _load(path, {"format": "genshin-source-observations-v1",
                         "sources": {}, "banners": {}})
    source_seen = state.setdefault("sources", {})
    banners = state.setdefault("banners", {})
    v1 = _load(root / "public/v1/genshin.json", {"banners": []}).get("banners", [])
    if not isinstance(v1, list):
        raise ValueError("Invalid V1 banner array")
    slots = defaultdict(list)
    for b in v1:
        slots[(b.get("gameVersion"), b.get("phase"), b.get("poolType"), b.get("variant"))].append(b)

    # Observe all persisted structured sources, including ones that have not
    # yet assembled into a publishable candidate.
    for kind, folder, glob_pattern in (
        ("version_update", "version-updates", "version-update_zh-CN_*.json"),
        ("wish_preview", "wish-previews", "wish-preview_zh-CN_*.json"),
        ("wish_notice", "wish-notices", "wish-notice_zh-CN_*.json"),
    ):
        for data_file in sorted((root / SOURCE / folder).glob(glob_pattern)):
            data = _load(data_file)
            origin = data.get("source") or {}
            post_id = str(origin.get("postId") or "")
            if not post_id:
                continue
            key_source = "miyoushe:" + post_id
            item = source_seen.setdefault(key_source, {
                "kind": kind, "firstObservedAt": observed_at,
            })
            item.setdefault("file", data_file.relative_to(root).as_posix())
            if origin.get("publishedAt"):
                item.setdefault("sourcePublishedAt", origin["publishedAt"])
            item["availableFields"] = sorted(
                key for key, value in data.items()
                if key in ("version", "phase", "bannerName", "poolType",
                           "up", "selectable", "time", "maintenance", "newCharacters",
                           "newWeapons") and value is not None
            )

    for candidate_file in sorted((root / SOURCE / "v1-candidates").glob("v1-candidate_zh-CN_*.json")):
        candidate = _load(candidate_file)
        if candidate.get("status") != "ready_candidate" or not isinstance(candidate.get("v1Draft"), dict):
            continue
        draft = candidate["v1Draft"]
        slot = (candidate.get("version"), candidate.get("phase"),
                candidate.get("poolType"), candidate.get("variant"))
        options = [b for b in slots.get(slot, [])
                   if b.get("names", {}).get("zh-CN") == draft.get("names", {}).get("zh-CN")]
        v1id = options[0]["id"] if len(options) == 1 else None
        key = v1id or ("candidate:" + str(candidate.get("sourceKey") or candidate_file.stem))
        entry = banners.setdefault(key, {"firstObservedAt": observed_at})
        entry.setdefault("candidateReadyObservedAt", observed_at)
        entry.update({
            "status": "published" if v1id else "ready_candidate",
            "linkedV1Id": v1id,
            "candidateFile": candidate_file.relative_to(root).as_posix(),
            "fieldSources": _actual_fields(candidate),
            "sourceRefs": candidate.get("provenance") or {},
        })
        entry.setdefault("sourceFirstObservedAt", {})
        for kind, key_name in (("version_update", "versionUpdatePostId"),
                               ("wish_preview", "previewPostId"),
                               ("wish_notice", "noticePostId")):
            post_id = entry["sourceRefs"].get(key_name)
            if post_id:
                origin = "miyoushe:" + str(post_id)
                observed = source_seen.setdefault(origin, {
                    "kind": kind, "firstObservedAt": observed_at})
                entry["sourceFirstObservedAt"][kind] = observed["firstObservedAt"]

    web = _load(root / STORE / "checkpoint.json", {"banners": {}})
    matched = _associate(v1, web, root / STORE / "details")
    for bid, ids in matched.items():
        # Never silently attach multiple Webstatic configs to the same V1 pool.
        entry = banners.setdefault(bid, {"firstObservedAt": observed_at})
        contributed = sorted(
            field for field, origins in (entry.get("fieldSources") or {}).items()
            if any("webstatic:" + gid in origins for gid in ids)
        )
        entry["webstatic"] = {
            "gachaIds": ids, "unique": len(ids) == 1,
            "firstSeenAt": min(web["banners"][id]["firstSeenAt"] for id in ids),
            "detailsReadyAt": min(web["banners"][id]["detailReadyAt"] for id in ids),
            "role": "used_in_candidate" if contributed else "independent_comparison_only",
            "contributedFields": contributed,
        }

    _write_if_changed(path, _encoded(state))
    journal = _load(root / SOURCE / "source-traces/publication-events.json", {"events": []})
    _write_if_changed(root / REPORT, render(state, journal).encode("utf-8"))
    return {"tracked": len(banners), "matchedWebstatic": len(matched),
            "sourcesObserved": len(source_seen), "report": REPORT.as_posix()}


def render(state, journal=None):
    created_at = {}
    for event in (journal or {}).get("events", []):
        if event.get("action") == "created":
            created_at.setdefault(event.get("v1Id"), event.get("recordedAt"))
    lines = [
        "# 原神来源追踪",
        "",
        "本报告是采集观测记录。首次观测不等于官方发布日期；旧候选首次扫描不代表历史首次可用。",
        "Webstatic 目前只独立校验，不参与 V1 组装。字段来源详见 observations.json。",
        "",
        "| 卡池 | 状态 | 公告首次观测 | Webstatic 详情就绪 | V1 新增记录 | 公告 postId |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    count = 0
    for bid, record in sorted(state.get("banners", {}).items(), reverse=True):
        if bid.startswith("candidate:"):
            continue
        post = record.get("sourceRefs", {}).get("noticePostId", "—")
        first = record.get("sourceFirstObservedAt", {}).get("wish_notice", "—")
        ready = record.get("webstatic", {}).get("detailsReadyAt", "—")
        lines.append(f"| {bid} | {record.get('status', 'observed')} | {first} | {ready} | {created_at.get(bid) or '—'} | {post} |")
        count += 1
        if count >= 30:
            break
    if not count:
        lines.append("| — | 暂无新数据 | — | — | — | — |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(generate(args.root.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
