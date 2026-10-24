#!/usr/bin/env python3
"""Validate v1 data: JSON Schema + cross-field rules + published manifest digests."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SERVERS = {"cn_official", "cn_channel", "asia", "europe", "america", "tw_hk_mo"}
MAP = {
    "genshin": {
        "100": ("100", "beginner", "beginner"),
        "200": ("200", "standard", "standard"),
        "301": ("301", "character_event", "character"),
        "400": ("301", "character_event_2", "character"),
        "302": ("302", "weapon_event", "weapon"),
        "500": ("500", "chronicled", "chronicled"),
    },
    "starrail": {
        "1": ("1", "standard", "standard"),
        "2": ("2", "beginner", "beginner"),
        "11": ("11", "character_event", "character"),
        "12": ("12", "light_cone_event", "light_cone"),
        "21": ("21", "collab_character", "character"),
        "22": ("22", "collab_light_cone", "light_cone"),
    },
}
PERMANENT = {"beginner", "standard"}
# Some Star Rail collaboration pools have an announced start but no fixed end date.
OPEN_ENDED_POOLS = PERMANENT | {"collab_character", "collab_light_cone"}
POOL_MAP = {game: {pool: (uigf, cat) for uigf, pool, cat in mapping.values()} for game, mapping in MAP.items()}
EVENT_POOLS = {"character_event", "character_event_2", "weapon_event", "light_cone_event", "collab_character", "collab_light_cone"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schema(data, name):
    path = ROOT / "schemas" / "public" / "v1" / (name + ".schema.json")
    schema = load(path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=lambda e: list(map(str, e.absolute_path)),
    )
    if errors:
        first = errors[0]
        raise ValueError(f"{name} schema invalid at {list(first.absolute_path)}: {first.message}")


def validate_dataset(dataset):
    validate_schema(dataset, "banner-data")
    game = dataset["game"]
    seen = set()
    for banner in dataset["banners"]:
        bid = banner["id"]
        if bid in seen:
            raise ValueError(f"duplicate banner.id: {bid}")
        seen.add(bid)
        raw, uigf = banner["gachaTypes"]["raw"], banner["gachaTypes"]["uigf"]
        if len(uigf) != 1 or (raw is not None and len(raw) != 1):
            raise ValueError(f"{bid}: exactly one uigf and zero/one raw type required")
        if (uigf[0], banner["category"]) != POOL_MAP[game][banner["poolType"]]:
            raise ValueError(f"{bid}: poolType/category/uigf mapping mismatch")
        if raw is not None and (uigf[0], banner["poolType"], banner["category"]) != MAP[game][raw[0]]:
            raise ValueError(f"{bid}: raw gacha type mapping mismatch")
        chronicled = game == "genshin" and banner["poolType"] == "chronicled"
        if ("variant" in banner) != chronicled:
            raise ValueError(f"{bid}: variant required exactly for genshin chronicled pools")
        if game == "genshin" and "gachaIds" in banner:
            raise ValueError(f"{bid}: genshin must omit gachaIds")
        if "fatePointLimit" in banner and not (game == "genshin" and banner["poolType"] in {"weapon_event", "chronicled"}):
            raise ValueError(f"{bid}: fatePointLimit only allowed for genshin weapon/chronicled")
        if banner["poolType"] in PERMANENT and banner["phase"] is not None:
            raise ValueError(f"{bid}: permanent pools require phase null")
        servers = set()
        for region in banner["regions"]:
            if region["server"] in servers:
                raise ValueError(f"{bid}: duplicate region {region['server']}")
            servers.add(region["server"])
            start = datetime.fromisoformat(region["startAt"])
            end = region["endAt"]
            if end is None and banner["poolType"] not in OPEN_ENDED_POOLS:
                raise ValueError(f"{bid}: endAt null only allowed for permanent or Star Rail collaboration pools")
            if end is not None and datetime.fromisoformat(end) <= start:
                raise ValueError(f"{bid}: invalid region time range")
        for grade in ("fiveStar", "fourStar"):
            for entry in banner["featured"][grade] or []:
                if entry["type"] == "light_cone" and game != "starrail":
                    raise ValueError(f"{bid}: light_cone only belongs to starrail")
    return len(seen)


def validate_publishable_dataset(dataset):
    count = validate_dataset(dataset)
    if not count:
        raise ValueError("refusing empty game dataset")
    for banner in dataset["banners"]:
        bid = banner["id"]
        if "cn_official" not in {r["server"] for r in banner["regions"]}:
            raise ValueError(f"{bid}: cn_official schedule required for public release")
        if banner["poolType"] not in PERMANENT and (banner["phase"] is None or banner["gameVersion"] is None):
            raise ValueError(f"{bid}: version and phase required for limited public banner")
        featured = banner["featured"]
        if banner["poolType"] in EVENT_POOLS and (not featured["fiveStar"] or featured["fourStar"] is None):
            raise ValueError(f"{bid}: complete fiveStar and fourStar UP lists required")
        if banner["poolType"] == "chronicled" and not featured["fiveStar"]:
            raise ValueError(f"{bid}: complete selectable fiveStar list required")
        if not any(src.get("url") or src.get("externalId") for src in banner["sources"]):
            raise ValueError(f"{bid}: source must have URL or externalId")
        if any(str(src["provider"]).lower() in {"fixture", "test", "example", "synthetic"} or
               src.get("externalId") == "synthetic-do-not-publish" for src in banner["sources"]):
            raise ValueError(f"{bid}: synthetic data must not be published")
    validate_published_consistency(dataset)
    return count


def validate_published_consistency(dataset):
    """发布数据的跨记录一致性检查；不约束允许不完整信息的测试夹具。"""
    game = dataset["game"]
    banners = dataset["banners"]
    item_ids = {}
    named_items = {}
    official_gacha_ids = {}
    ordinary_ids = []
    special_ids = []
    expected_counts = {
        "character_event": (1, 3),
        "character_event_2": (1, 3),
        "weapon_event": (2, 5),
        "light_cone_event": (1, 3),
        "collab_character": (1, 0),
        "collab_light_cone": (1, 0),
    }
    expected_types = {
        "character_event": "character",
        "character_event_2": "character",
        "weapon_event": "weapon",
        "light_cone_event": "light_cone",
        "collab_character": "character",
        "collab_light_cone": "light_cone",
    }
    reserved = {"standard": 100001, "beginner": 100002}
    special_pool_types = {"collab_character", "collab_light_cone"}
    for banner in banners:
        bid, pool = banner["id"], banner["poolType"]
        number = int(bid.split("-")[1])
        if number < 1:
            raise ValueError(f"{bid}: banner ID number must be positive")
        if pool in reserved:
            if number != reserved[pool]:
                raise ValueError(f"{bid}: incorrect reserved ID for {pool}")
        elif game == "starrail" and pool in special_pool_types:
            if number < 100003:
                raise ValueError(f"{bid}: collaboration pool requires reserved special ID")
            special_ids.append(number)
        else:
            if not 1 <= number <= 99999:
                raise ValueError(f"{bid}: ordinary pool ID out of range")
            ordinary_ids.append(number)

        five, four = banner["featured"]["fiveStar"], banner["featured"]["fourStar"]
        if pool in expected_counts:
            expected = expected_counts[pool]
            actual = (len(five or []), len(four or []))
            if actual != expected:
                raise ValueError(f"{bid}: incorrect featured counts {actual}, expected {expected}")
        elif pool == "chronicled" and four != []:
            raise ValueError(f"{bid}: chronicled fourStar must be [] (no fixed four-star UP)")
        elif pool in PERMANENT and (five != [] or four != []):
            raise ValueError(f"{bid}: permanent featured lists must be empty")

        within_banner = set()
        for grade in ("fiveStar", "fourStar"):
            for item in banner["featured"][grade] or []:
                item_id = item["itemId"]
                item_type = item["type"]
                if pool in expected_types and item_type != expected_types[pool]:
                    raise ValueError(f"{bid}: incorrect featured item type {item_type}")
                name = item["names"].get("zh-CN")
                # 同名不同 ID、同 ID 不同名称或类型均需人工核实，不能自动改写。
                if item_id is None:
                    continue
                if item_id in within_banner:
                    raise ValueError(f"{bid}: duplicate featured itemId {item_id}")
                within_banner.add(item_id)
                identity = (item_type, name)
                if item_id in item_ids and item_ids[item_id] != identity:
                    raise ValueError(f"{bid}: conflicting itemId {item_id}")
                item_ids[item_id] = identity
                if name:
                    name_key = (item_type, name)
                    if name_key in named_items and named_items[name_key] != item_id:
                        raise ValueError(f"{bid}: same item name has different itemIds: {name}")
                    named_items[name_key] = item_id

        for gacha_id in banner.get("gachaIds", []):
            if gacha_id in official_gacha_ids:
                raise ValueError(f"{bid}: duplicate gachaId {gacha_id} in {official_gacha_ids[gacha_id]}")
            official_gacha_ids[gacha_id] = bid

    # 从 1 开始无断号，但允许按时间后续追加，不能写死当前记录总数。
    if sorted(ordinary_ids) != list(range(1, len(ordinary_ids) + 1)):
        raise ValueError(f"{game}: ordinary banner IDs must be contiguous from 1")
    if game == "starrail" and sorted(special_ids) != list(range(100003, 100003 + len(special_ids))):
        raise ValueError("starrail: collaboration banner IDs must be contiguous from 100003")


def validate_manifest(manifest, folder):
    validate_schema(manifest, "manifest")
    for game, meta in manifest["games"].items():
        raw = (folder / meta["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != meta["sha256"]:
            raise ValueError(f"{game}: sha256 mismatch")
        dataset = json.loads(raw.decode("utf-8"))
        if dataset["game"] != game:
            raise ValueError(f"{game}: game mismatch")
        if validate_publishable_dataset(dataset) != meta["bannerCount"]:
            raise ValueError(f"{game}: bannerCount mismatch")
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate public v1")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixtures", action="store_true")
    mode.add_argument("--public", action="store_true")
    mode.add_argument("--datasets-only", action="store_true", help="Verify published game JSON without requiring an already refreshed Manifest")
    args = parser.parse_args()
    folder = ROOT / ("tests/fixtures/v1" if args.fixtures else "public/v1")
    if args.fixtures:
        for game in ("genshin", "starrail"):
            dataset = load(folder / f"{game}.json")
            if dataset["game"] != game:
                raise ValueError(f"{game}: game mismatch")
            print(f"{game}: {validate_dataset(dataset)} fixture banners OK")
    elif args.datasets_only:
        for game in ("genshin", "starrail"):
            dataset = load(folder / f"{game}.json")
            if dataset["game"] != game:
                raise ValueError(f"{game}: game mismatch")
            print(f"{game}: {validate_publishable_dataset(dataset)} published banners validated")
    else:
        manifest = load(folder / "manifest.json")
        validate_manifest(manifest, folder)
        print("manifest: published games verified")
    print("v1: PASS")


if __name__ == "__main__":
    main()
