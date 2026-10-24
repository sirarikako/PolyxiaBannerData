#!/usr/bin/env python3
"""国际服多语言 ItemID 增量更新：每个游戏与语言独立校验、独立写入。

仅支持 zh-TW/en-US/ja-JP。简中更新继续由 refresh_official_item_mappings 负责。
任何单语言两类目录缺失、数据冲突、疑似简中回退或覆盖不足均拒绝写该文件。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

from scripts.release.refresh_official_item_mappings import (
    ROOT, MAPPING_FOLDER, MIN_IDS, CatalogUnavailable, MappingConflict,
    _atomic_write, _config_catalog, load_mapping, merge_game, request_json,
)

LANGUAGES = {"zh-TW": "zh-tw", "en-US": "en-us", "ja-JP": "ja-jp"}
CATEGORIES = {
    "genshin": ("genshin-characters", "genshin-weapons"),
    "starrail": ("starrail-characters", "starrail-lightcones"),
}
# 本次实测三种语言均达 100%。95% 仅是最低门槛，不表示物品库绝对完整。
MIN_BASELINE_COVERAGE = 0.95
MAX_IDENTICAL_NAME_RATIO = 0.85


def locale_catalog(category: str, language: str, *,
                   requester: Callable[..., dict] = request_json,
                   min_ids: dict[str, int] = MIN_IDS) -> list[tuple[int, str]]:
    """复用简中现役更新器的解析和分页逻辑，只向国际服请求目标语言。"""
    rows = _config_catalog(category, is_international=True,
                           requester=requester, lang=language)
    if len(rows) < min_ids[category]:
        raise CatalogUnavailable(
            f"{category}: {language} 仅返回 {len(rows)} 个 ItemID，低于最低门槛 {min_ids[category]}"
        )
    return rows


def build_locale(root: Path, game: str, locale: str, *,
                 requester: Callable[..., dict] = request_json,
                 min_ids: dict[str, int] = MIN_IDS) -> tuple[dict, dict[str, int] | None]:
    """返回状态及安全的候选映射；错误时不更改任何数据。"""
    if game not in CATEGORIES or locale not in LANGUAGES:
        raise ValueError(f"不支持游戏/语言: {game}/{locale}")
    file_path = root / MAPPING_FOLDER / game / f"{locale}.json"
    old = load_mapping(file_path) if file_path.exists() else {}
    report = {
        "game": game, "locale": locale, "file": str(MAPPING_FOLDER / game / f"{locale}.json"),
        "status": "blocked", "oldCount": len(old), "newCount": len(old),
        "newEntries": 0, "catalogs": [],
    }
    grouped = []
    for category in CATEGORIES[game]:
        try:
            records = locale_catalog(category, LANGUAGES[locale],
                                     requester=requester, min_ids=min_ids)
        except CatalogUnavailable as exc:
            report["catalogs"].append({"category": category, "source": "unavailable", "error": str(exc)})
            continue
        except MappingConflict as exc:
            report["catalogs"].append({"category": category, "source": "conflict", "error": str(exc)})
            continue
        grouped.append((category, records))
        report["catalogs"].append({"category": category, "source": "international",
                                   "uniqueItemIds": len(records)})
    if len(grouped) != len(CATEGORIES[game]):
        report["status"] = "conflict" if any(
            c["source"] == "conflict" for c in report["catalogs"]) else "unavailable"
        report["reason"] = "；".join(
            c.get("error", "") for c in report["catalogs"] if c["source"] != "international"
        )
        return report, None

    try:
        merged, info = merge_game(old, grouped)
    except MappingConflict as exc:
        report["status"] = "conflict"
        report["reason"] = str(exc)
        return report, None

    zhcn = load_mapping(root / MAPPING_FOLDER / game / "zh-CN.json")
    baseline_ids = {item_id: name for name, item_id in zhcn.items()}
    localized_ids = {item_id: name for name, item_id in merged.items()}
    overlap = set(baseline_ids) & set(localized_ids)
    coverage = len(overlap) / len(baseline_ids) if baseline_ids else 0.0
    identical = sum(baseline_ids[item_id] == localized_ids[item_id] for item_id in overlap)
    ratio = identical / len(overlap) if overlap else 1.0
    report.update({
        "baselineCount": len(baseline_ids), "coveredIds": len(overlap),
        "baselineCoverage": round(coverage, 4), "identicalNameRatio": round(ratio, 4),
        "allowedSameNameDifferentId": info["allowedSameNameDifferentId"],
        "newCount": len(merged), "newEntries": len(info["added"]),
    })
    if coverage < MIN_BASELINE_COVERAGE:
        report["status"] = "incomplete"
        report["reason"] = f"已知简中 ItemID 覆盖不足: {coverage:.2%}"
        return report, None
    if ratio > MAX_IDENTICAL_NAME_RATIO:
        report["status"] = "suspicious-language"
        report["reason"] = f"名称与简中高度一致: {ratio:.2%}，可能忽略语言参数"
        return report, None
    report["status"] = "ready"
    return report, merged


def refresh_locales(root: Path = ROOT, *, write: bool = False,
                    requester: Callable[..., dict] = request_json,
                    min_ids: dict[str, int] = MIN_IDS,
                    games: tuple[str, ...] = ("genshin", "starrail"),
                    locales: tuple[str, ...] = ("zh-TW", "en-US", "ja-JP")) -> dict:
    reports = []
    updates: dict[str, tuple[Path, dict[str, int]]] = {}
    blocked: dict[str, str] = {}
    unavailable: dict[str, str] = {}
    for game in games:
        for locale in locales:
            key = f"{game}/{locale}"
            result, merged = build_locale(
                root, game, locale, requester=requester, min_ids=min_ids)
            reports.append(result)
            if result["status"] != "ready":
                target = unavailable if result["status"] == "unavailable" else blocked
                target[key] = result.get("reason", result["status"])
                continue
            path = root / MAPPING_FOLDER / game / f"{locale}.json"
            existing = load_mapping(path) if path.exists() else None
            if existing != merged:
                updates[key] = (path, merged)

    if write:
        for path, data in updates.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {
        "mode": "write" if write else "dry-run",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "languages": list(locales), "results": reports, "updatedLocales": sorted(updates),
        "blockedLocales": blocked, "unavailableLocales": unavailable,
    }
