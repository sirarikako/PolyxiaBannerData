#!/usr/bin/env python3
"""用 Dimbreath GachaBasicInfo 安全补齐星铁 V1 中缺失的 gachaIds。

仅根据已确认的五星 itemId、GachaType 和已发布同类卡池的先后顺序匹配；
无法唯一匹配时保留空值。默认只读，--write 才修改 V1。
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import Request, urlopen

from scripts.release.validate_v1 import validate_publishable_dataset

ROOT = Path(__file__).resolve().parents[2]
V1_PATH = Path("public/v1/starrail.json")
SOURCE_URL = (
    "https://raw.githubusercontent.com/DimbreathBot/TurnBasedGameData/"
    "main/ExcelOutput/GachaBasicInfo.json"
)
GACHA_TYPES = {
    "character_event": "AvatarUp",
    "light_cone_event": "WeaponUp",
    "collab_character": "CollaborationAvatarUp",
    "collab_light_cone": "CollaborationWeaponUp",
    "standard": "Normal",
    "beginner": "Newbie",
}
PREFAB_ITEM = re.compile(r"(?:Avatar|LightCone)Gacha_(\d+)\.prefab$", re.IGNORECASE)
VERSION = re.compile(r"(\d+)\.(\d+)")


def banner_slot(banner):
    """只使用明确的版本/期数；绝不根据公告发布日期推算期数。"""
    version, phase = banner.get("gameVersion"), banner.get("phase")
    match = VERSION.fullmatch(version) if isinstance(version, str) else None
    if match is None or type(phase) is not int or phase < 1:
        return None
    return int(match.group(1)), int(match.group(2)), phase


def source_index(records):
    """拒绝结构异常或重复 GachaID，避免静默覆盖不可信上游数据。"""
    if not isinstance(records, list):
        raise ValueError("GachaBasicInfo 根必须是数组")
    indexed = {}
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("GachaBasicInfo 记录必须是对象")
        gacha_id = row.get("GachaID")
        kind, prefab = row.get("GachaType"), row.get("PrefabPath")
        if type(gacha_id) is not int or gacha_id <= 0 or not isinstance(kind, str) or not isinstance(prefab, str):
            raise ValueError("GachaBasicInfo 存在无效的 GachaID/GachaType/PrefabPath")
        if gacha_id in indexed:
            raise ValueError(f"GachaBasicInfo 重复 GachaID: {gacha_id}")
        match = PREFAB_ITEM.search(prefab)
        indexed[gacha_id] = (kind, match.group(1) if match else None)
    if not indexed:
        raise ValueError("GachaBasicInfo 没有可用记录")
    return indexed


def five_star_id(banner):
    five = (banner.get("featured") or {}).get("fiveStar") or []
    if len(five) != 1 or not isinstance(five[0], dict):
        return None
    item = five[0].get("itemId")
    if isinstance(item, str) and item.isdecimal() and int(item) > 0:
        return str(int(item))
    if type(item) is int and item > 0:
        return str(item)
    return None


def complete_gacha_ids(banners, upstream):
    """原地补齐 banners；返回可审计报告，不修改已有的非空 gachaIds。"""
    lookup = source_index(upstream)
    known, occupied, problems, missing = [], set(), [], []
    for banner in banners:
        kind = GACHA_TYPES.get(banner.get("poolType"))
        ids = banner.get("gachaIds") or []
        if not kind:
            continue
        if ids:
            for raw_id in ids:
                try:
                    gid = int(raw_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{banner.get('id')}: 已有 GachaID 非法") from exc
                if str(gid) != str(raw_id) or gid not in lookup:
                    raise ValueError(f"{banner.get('id')}: 已有 GachaID {raw_id} 不在上游")
                source_kind, source_item = lookup[gid]
                expected_item = five_star_id(banner)
                if source_kind != kind or (expected_item and source_item != expected_item):
                    raise ValueError(f"{banner.get('id')}: 已有 GachaID {gid} 与上游池种或五星不符")
                if gid in occupied:
                    raise ValueError(f"GachaID {gid} 已被多个 V1 卡池使用")
                occupied.add(gid)
                if banner_slot(banner):
                    known.append((banner_slot(banner), kind, gid))
        else:
            missing.append((banner, kind))

    proposals = {}
    for banner, kind in missing:
        bid = banner.get("id")
        slot, item_id = banner_slot(banner), five_star_id(banner)
        if slot is None or item_id is None:
            problems.append({"id": bid, "reason": "missing_version_phase_or_five_star_item_id"})
            continue
        lower = max((gid for other_slot, other_kind, gid in known
                     if other_kind == kind and other_slot < slot), default=0)
        upper = min((gid for other_slot, other_kind, gid in known
                     if other_kind == kind and other_slot > slot), default=float("inf"))
        matches = [
            gid for gid, (source_kind, source_item) in lookup.items()
            if source_kind == kind and source_item == item_id
            and gid not in occupied and lower < gid < upper
        ]
        if len(matches) != 1:
            problems.append({"id": bid, "reason": "ambiguous" if matches else "not_found",
                             "candidateIds": [str(i) for i in sorted(matches)]})
            continue
        proposals[bid] = (banner, matches[0])

    collisions = Counter(gid for _, gid in proposals.values())
    filled = []
    for bid, (banner, gid) in proposals.items():
        if collisions[gid] != 1:
            problems.append({"id": bid, "reason": "same_gacha_id_for_multiple_banners",
                             "candidateIds": [str(gid)]})
            continue
        banner["gachaIds"] = [str(gid)]
        filled.append({"id": bid, "gachaIds": [str(gid)]})
    return {"verifiedExisting": len(occupied), "filled": filled,
            "unresolved": problems, "sourceCount": len(lookup)}


def atomic_save(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".hsr-gacha-",
            suffix=".tmp", delete=False
        ) as handle:
            json.dump(content, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_upstream(source_json=None, *, timeout=20):
    if source_json is not None:
        return json.loads(Path(source_json).read_text(encoding="utf-8"))
    request = Request(SOURCE_URL, headers={"User-Agent": "PolyxiaBannerData-GachaIdSync/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def run(v1_path, source_json=None, *, write=False, timeout=20):
    original = json.loads(Path(v1_path).read_text(encoding="utf-8"))
    if original.get("game") != "starrail" or not isinstance(original.get("banners"), list):
        raise ValueError("目标文件不是星铁 V1")
    # 先检查本地数据；所有已知池都带有编号时，不请求第三方服务。
    missing = [banner for banner in original["banners"]
               if banner.get("poolType") in GACHA_TYPES and not banner.get("gachaIds")]
    if not missing:
        return {"source": str(source_json or SOURCE_URL), "sourceAvailable": None,
                "skipped": True, "skipReason": "no_missing_gacha_ids",
                "missingCount": 0, "verifiedExisting": 0,
                "filled": [], "unresolved": [], "v1Changed": False, "written": False}
    result = deepcopy(original)
    try:
        source = load_upstream(source_json, timeout=timeout)
        report = complete_gacha_ids(result["banners"], source)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        # 第三方数据不可用时不影响公告发布；也绝不清空已有 ID。
        return {"source": str(source_json or SOURCE_URL), "sourceAvailable": False,
                "sourceError": str(exc), "skipped": False, "missingCount": len(missing),
                "verifiedExisting": 0, "filled": [], "unresolved": [],
                "v1Changed": False, "written": False}
    changed = result["banners"] != original["banners"]
    if changed:
        result["generatedAt"] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        validate_publishable_dataset(result)
        if write:
            atomic_save(Path(v1_path), result)
    return {"source": str(source_json or SOURCE_URL), "sourceAvailable": True,
            "skipped": False, "missingCount": len(missing), **report,
            "v1Changed": changed, "written": bool(changed and write)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1", type=Path, default=ROOT / V1_PATH)
    parser.add_argument("--source-json", type=Path, help="使用本地 GachaBasicInfo JSON，便于离线测试")
    parser.add_argument("--write", action="store_true", help="验证后实际修改 V1；默认只预览")
    parser.add_argument("--report", type=Path, help="将报告写入单独的 JSON 文件")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    report = run(args.v1, args.source_json, write=args.write, timeout=args.timeout)
    if args.report:
        atomic_save(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["skipped"]:
        print("星铁所有已知卡池均已有 GachaID，跳过 Dimbreath 请求。")
    elif report["sourceAvailable"] is False:
        print("::warning::Dimbreath GachaBasicInfo 不可用，保留现有 gachaIds。")


if __name__ == "__main__":
    main()
