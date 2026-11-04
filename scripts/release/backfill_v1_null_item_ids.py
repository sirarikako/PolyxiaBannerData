#!/usr/bin/env python3
"""仅从现有官方名称对照表回填已发布 v1 中为 null 的 ItemID。

不访问网络，不更改已有非 null ID，不修正名称或重新生成卡池。
运行方式：python -m scripts.release.backfill_v1_null_item_ids [--write] [--report FILE]
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "genshin": ("public/v1/genshin.json", "public/item-mappings/genshin/zh-CN.json"),
    "starrail": ("public/v1/starrail.json", "public/item-mappings/starrail/zh-CN.json"),
}


def items_in(data: dict):
    for banner in data.get("banners", []):
        for field in ("featured", "selectable"):
            group = banner.get(field) or {}
            if not isinstance(group, dict):
                continue
            for entries in group.values():
                if not isinstance(entries, list):
                    continue
                for item in entries:
                    if isinstance(item, dict) and "itemId" in item:
                        yield banner, item


def fill_dataset(data: dict, mapping: dict) -> dict:
    """原地仅回填 null；不确定名称/已有 ID 冲突只记录，不写入。"""
    known = defaultdict(set)
    for _, item in items_in(data):
        item_id = item.get("itemId")
        name = (item.get("names") or {}).get("zh-CN")
        if item_id is not None and name:
            known[(name, item.get("type"))].add(str(item_id))

    filled, unresolved, conflicts = [], [], []
    for banner, item in items_in(data):
        if item.get("itemId") is not None:
            continue
        name = (item.get("names") or {}).get("zh-CN")
        key = (name, item.get("type"))
        value = mapping.get(name) if isinstance(name, str) else None
        where = {"bannerId": banner.get("id"), "name": name, "type": item.get("type")}
        if type(value) is not int or value <= 0:
            unresolved.append(where)
            continue
        candidate = str(value)
        known_ids = known[key]
        if known_ids and known_ids != {candidate}:
            conflicts.append({**where, "mappingId": candidate, "existingIds": sorted(known_ids)})
            continue
        item["itemId"] = candidate
        filled.append({**where, "itemId": candidate})
        known_ids.add(candidate)
    return {"filled": filled, "unresolved": unresolved, "conflicts": conflicts}


def write_atomic(path: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".itemid-backfill-", suffix=".tmp",
                                     delete=False) as stream:
        temp = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run(root: Path, write: bool = False) -> dict:
    report = {"mode": "write" if write else "dry-run", "games": {}}
    for game, (v1_rel, map_rel) in FILES.items():
        v1_path, map_path = root / v1_rel, root / map_rel
        data = json.loads(v1_path.read_text(encoding="utf-8"))
        mapping = json.loads(map_path.read_text(encoding="utf-8"))
        if data.get("game") != game or not isinstance(mapping, dict):
            raise ValueError(f"{game}: v1/game 或物品映射格式不正确")
        result = fill_dataset(data, mapping)
        report["games"][game] = result
        if write and result["filled"]:
            from scripts.release.validate_v1 import validate_publishable_dataset
            data["generatedAt"] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
            validate_publishable_dataset(data)
            write_atomic(v1_path, data)
    report["totalFilled"] = sum(len(x["filled"]) for x in report["games"].values())
    report["totalConflicts"] = sum(len(x["conflicts"]) for x in report["games"].values())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = run(args.root.resolve(), write=args.write)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
