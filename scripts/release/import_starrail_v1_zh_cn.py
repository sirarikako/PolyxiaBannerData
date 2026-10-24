#!/usr/bin/env python3
"""星铁候选 -> 正式 V1，默认只读。仅读取持久化候选和版本级人工配置。"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile

from scripts.release.validate_v1 import validate_publishable_dataset
from scripts.release.starrail_manual_versions import load_versions, complete, is_pending

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = Path("data/derived/starrail/v1-candidates")
MANUAL = Path("manual")
V1 = Path("public/v1/starrail.json")
FORMAT = "starrail-v1-candidate-zh-CN-v1"
TZ8 = timezone(timedelta(hours=8))
POOL_ORDER = {"character_event": 0, "light_cone_event": 1,
              "collab_character": 2, "collab_light_cone": 3}
SPECIAL = {"collab_character", "collab_light_cone"}
TYPE_CODE = {"character_event": "11", "light_cone_event": "12",
             "collab_character": "21", "collab_light_cone": "22"}

def load(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON 根必须是对象")
    return data

def identity(row):
    # 同版本同期、同名、同池种的五星 UP 仍可能不同。
    stars = tuple(sorted(x.get("names", {}).get("zh-CN") for x in
                         (row.get("featured", {}).get("fiveStar") or [])))
    return (row.get("gameVersion"), row.get("phase"), row.get("poolType"),
            (row.get("names") or {}).get("zh-CN"), stars)

def identity_candidate(row):
    return identity(row["v1Draft"])

def timestamp(value):
    try:
        dt = datetime.fromisoformat(value)
        if dt.utcoffset() != timedelta(hours=8):
            raise ValueError("时区不是 +08:00")
        return dt
    except (ValueError, TypeError) as exc:
        raise ValueError(f"时间格式非法：{value!r}") from exc

def atomic_json(path, obj):
    content = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".starrail-", suffix=".tmp", delete=False) as fh:
            fh.write(content)
            temp = Path(fh.name)
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()

def apply_fields(target, patch, label):
    for key, value in patch.items():
        if key == "regions":
            if not isinstance(value, list):
                raise ValueError(f"{label}: regions 不是数组")
            existing = target.get("regions", [])
            region_index = {r["server"]: r for r in existing}
            if len(existing) != len(region_index):
                raise ValueError(f"{label}: regions 原数据重复")
            used = set()
            for region in value:
                if not isinstance(region, dict) or not isinstance(region.get("server"), str):
                    raise ValueError(f"{label}: region 必须包含 server")
                srv = region["server"]
                if srv in used:
                    raise ValueError(f"{label}: 同次补丁重复 server")
                used.add(srv)
                if srv in region_index:
                    apply_fields(region_index[srv], {k: v for k, v in region.items() if k != "server"}, label)
                else:
                    existing.append(deepcopy(region))
            target["regions"] = existing
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            apply_fields(target[key], value, label + "." + key)
        else:
            target[key] = deepcopy(value)

def patch_banner(banner, entry, label, *, new=False):
    apply_fields(banner, entry.get("set", {}), label)
    for name, requested in entry.get("itemIds", {}).items():
        matches = [item for grade in ("fiveStar", "fourStar")
                   for item in banner.get("featured", {}).get(grade, [])
                   if item.get("names", {}).get("zh-CN") == name]
        if len(matches) != 1:
            raise ValueError(f"{label}: ItemID 名称 {name} 没有唯一匹配的 UP 物品")
        prior = matches[0].get("itemId")
        if new and prior is not None and requested is not None and str(prior) != str(requested):
            raise ValueError(f"{label}: 人工 ItemID 与已确认自动 ID 冲突")
        matches[0]["itemId"] = requested
    for item in entry.get("addSources", []):
        if not isinstance(item, dict):
            raise ValueError(f"{label}: addSources 必须由来源对象组成")
        sources = banner.setdefault("sources", [])
        if item not in sources:
            sources.append(deepcopy(item))

def read_candidates(folder, rejected):
    valid, by_identity, by_source = [], {}, set()
    if folder.exists() and not folder.is_dir():
        raise ValueError("候选目录格式非法")
    for path in sorted(folder.glob("v1-candidate_zh-CN_*.json")):
        try:
            row = load(path)
            key = row.get("sourceKey")
            if (row.get("format") != FORMAT or row.get("game") != "starrail"
                    or row.get("locale") != "zh-CN" or row.get("status") != "ready_candidate"
                    or not isinstance(key, str)
                    or re.fullmatch(r"(?:\d+-[a-f0-9]{12}|manual-[a-f0-9]{20})", key) is None
                    or path.name != f"v1-candidate_zh-CN_{key}.json"):
                raise ValueError("非可发布的星铁候选")
            draft = row.get("v1Draft")
            if not isinstance(draft, dict) or "id" in draft:
                raise ValueError("候选禁止自带内部 ID")
            if (identity(draft) != identity_candidate(row)
                    or row["poolType"] not in POOL_ORDER):
                raise ValueError("候选版本/期数/池种/名称不一致")
            if (draft.get("category") != ("character" if row["poolType"] in
                        {"character_event", "collab_character"} else "light_cone")
                    or (draft.get("gachaTypes") or {}).get("uigf") != [TYPE_CODE[row["poolType"]]]):
                raise ValueError("候选类别与 UIGF 类型不一致")
            sources = draft.get("sources") or []
            if key.startswith("manual-"):
                if not any(s.get("provider") == "manual" and
                           s.get("externalId") == "starrail-" + key.removeprefix("manual-")
                           for s in sources):
                    raise ValueError("人工缺帖来源身份与来源证据不一致")
            else:
                pid = key.split("-")[0]
                if not any(s.get("provider") == "miyoushe" and
                           s.get("url") == f"https://www.miyoushe.com/sr/article/{pid}"
                           for s in sources):
                    raise ValueError("真实文章来源与文章 ID 不一致")
            stamp = timestamp(draft["regions"][0]["startAt"])
            end = draft["regions"][0]["endAt"]
            if end is None and row["poolType"] not in SPECIAL:
                raise ValueError("普通活动池不允许未知结束时间")
            if end is not None and stamp >= timestamp(end):
                raise ValueError("卡池开始时间不得晚于结束时间")
            if key in by_source:
                raise ValueError("来源键重复")
            by_source.add(key)
            ident = identity_candidate(row)
            by_identity.setdefault(ident, []).append(row)
            valid.append(row)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            rejected.append({"file": path.name, "error": str(exc)})
    blocked = {ident for ident, entries in by_identity.items() if len(entries) > 1}
    for ident in sorted(blocked):
        rejected.append({"identity": ident, "error": "业务身份重复，相关候选全部隔离"})
    return [row for row in valid if identity_candidate(row) not in blocked]

def import_v1(root=ROOT, *, write=False, candidate_dir=CANDIDATES, manual_dir=MANUAL,
              v1_path=V1, isolate_invalid=True):
    def resolve(path):
        p = Path(path)
        return p if p.is_absolute() else root / p
    file = resolve(v1_path)
    current = load(file)
    if current.get("game") != "starrail" or not isinstance(current.get("banners"), list):
        raise ValueError("目标不是星铁 V1")
    result = deepcopy(current)
    rejected = []
    candidates = read_candidates(resolve(candidate_dir), rejected)
    manual = load_versions(resolve(manual_dir), rejected)
    records = result["banners"]
    by_id = {x["id"]: x for x in records}
    if len(by_id) != len(records):
        raise ValueError("当前 V1 存在重复 ID")
    existing = {identity(b): b for b in records}
    if len(existing) != len(records):
        raise ValueError("当前 V1 存在重复业务身份")
    original_ids = set(by_id)
    current_special = {(b["poolType"], b["names"]["zh-CN"], identity(b)[4]): b
                       for b in records if b["poolType"] in SPECIAL}
    next_special = max([int(b["id"][4:]) for b in records
                        if b["poolType"] in SPECIAL] or [100002]) + 1
    next_num = max([int(b["id"][4:]) for b in records
                    if re.fullmatch(r"hsr-\d{6}", b["id"])
                    and int(b["id"][4:]) < 100000] or [0]) + 1
    ready_up = [r for r in manual["upcoming"] if is_pending(r)]
    ready_old = [r for r in manual["existing"] if is_pending(r)]
    def applies(ref, ident):
        match = ref["identity"]
        return match[:4] == ident[:4] and (len(match) < 5 or
                match[4] is None or match[4] in ident[4])
    ambiguous = set()
    for ref in ready_up:
        found = [row for row in candidates if applies(ref, identity_candidate(row))]
        if len(found) > 1:
            ambiguous.add(id(ref))
            rejected.append({"file": ref["file"].name, "match": ref["identity"],
                             "error": "同名卡池匹配多个候选，请增加 match.fiveStarName"})
    applied, appended, skipped, updated, pending = [], [], [], [], []
    stamp = datetime.now(TZ8).isoformat(timespec="seconds")
    candidates.sort(key=lambda row: (timestamp(row["v1Draft"]["regions"][0]["startAt"]),
                                      row["phase"], POOL_ORDER[row["poolType"]], row["bannerName"]))
    used = set()
    def verify(probe):
        validate_publishable_dataset(probe)
    def valid_after(candidate):
        try:
            verify(result)
            return True
        except (ValueError, KeyError, TypeError) as exc:
            if not isolate_invalid:
                raise
            rejected.append({"identity": candidate, "error": str(exc)})
            return False
    for row in candidates:
        ident = identity_candidate(row)
        match = [ref for ref in ready_up if id(ref) not in ambiguous and applies(ref, ident)]
        old = existing.get(ident)
        if old is None and row["poolType"] in SPECIAL:
            old = current_special.get((row["poolType"], row["bannerName"], ident[4]))
        # 第二道防线：即使候选文件绕过上游组装，也不能把同一期、
        # 同种类和同五星的已发布池仅因展示名称不同而重新新增。
        if old is None and ident[4]:
            same_up = [b for b in records if b["gameVersion"] == row["version"] and
                       b["phase"] == row["phase"] and b["poolType"] == row["poolType"]
                       and identity(b)[4] == ident[4]]
            if same_up:
                rejected.append({"identity": ident,
                                 "existingIds": [b["id"] for b in same_up],
                                 "error": "同版本同期同五星已发布，但池名不同；禁止自动追加"})
                continue
        if old is None and row["poolType"] not in SPECIAL and row["phase"] is not None:
            fresh_region = row["v1Draft"]["regions"][0]
            prior = [b for b in records
                     if b["gameVersion"] == row["version"] and
                     b["phase"] is not None and b["phase"] < row["phase"] and
                     b["poolType"] == row["poolType"] and identity(b)[3:] == ident[3:] and
                     any(r["server"] == "cn_official" and
                         r["startAt"] == fresh_region["startAt"] and
                         r["endAt"] == fresh_region["endAt"] for r in b["regions"])]
            if len(prior) > 1:
                rejected.append({"identity": ident, "error": "跨期存在多个相同卡池，必须人工复核"})
                continue
            if prior:
                old = prior[0]
        if old is not None:
            skipped.append({"id": old["id"], "identity": ident, "reason": "already_exists"})
            if match:
                trial = deepcopy(old)
                try:
                    patch_banner(trial, match[0]["entry"], str(ident))
                    if trial == old and (match[0]["file"], match[0]["index"]) not in used:
                        applied.append((match[0], old["id"]))
                        used.add((match[0]["file"], match[0]["index"]))
                    else:
                        pending.append({"identity": ident, "reason": "published_pool_not_overwritten"})
                except (ValueError, KeyError, TypeError) as exc:
                    rejected.append({"identity": ident, "error": str(exc)})
            continue
        if len(match) > 1:
            rejected.append({"identity": ident, "error": "多个 upcoming 同时匹配该卡池"})
            continue
        if match and (match[0]["file"], match[0]["index"]) in used:
            rejected.append({"identity": ident, "error": "同一人工设定匹配多个新池"})
            continue
        special = row["poolType"] in SPECIAL
        allocated = next_special if special else next_num
        if (not special and allocated >= 100000) or (special and allocated >= 1000000):
            rejected.append({"identity": ident, "error": "内部 ID 已超出安全范围"})
            continue
        try:
            fresh = deepcopy(row["v1Draft"])
            fresh["id"] = f"hsr-{allocated:06d}"
            if match:
                patch_banner(fresh, match[0]["entry"], str(ident), new=True)
            records.append(fresh)
            if not valid_after(ident):
                records.pop()
                continue
            existing[ident] = fresh
            by_id[fresh["id"]] = fresh
            appended.append({"id": fresh["id"], "identity": ident})
            if special:
                next_special += 1
                current_special[(row["poolType"], row["bannerName"], ident[4])] = fresh
            else:
                next_num += 1
            if match:
                applied.append((match[0], fresh["id"]))
                used.add((match[0]["file"], match[0]["index"]))
        except (ValueError, KeyError, TypeError) as exc:
            if records and records[-1].get("id") == f"hsr-{allocated:06d}":
                records.pop()
            if not isolate_invalid:
                raise
            rejected.append({"identity": ident, "error": str(exc)})
    for ref in ready_old:
        bid = ref["entry"]["id"]
        original = by_id.get(bid)
        if bid not in original_ids or original is None:
            rejected.append({"id": bid, "error": "existing 不允许修改本轮才新增的池"})
            continue
        if original["gameVersion"] != ref["version"]:
            rejected.append({"id": bid, "error": "existing 版本与卡池原版本不符"})
            continue
        changed = deepcopy(original)
        try:
            patch_banner(changed, ref["entry"], bid)
            idx = next(i for i, b in enumerate(records) if b["id"] == bid)
            before = records[idx]
            records[idx] = changed
            if not valid_after(bid):
                records[idx] = before
                continue
            by_id[bid] = changed
            if changed != before:
                updated.append(bid)
            applied.append((ref, bid))
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            rejected.append({"id": bid, "error": str(exc)})
    for ref in ready_up:
        if not any(x is ref for x, _ in applied):
            if not any(x["identity"] == ref["identity"] for x in pending):
                pending.append({"identity": ref["identity"], "reason": "waiting_for_candidate"})
    for ref, bid in applied:
        complete(ref, bid, stamp)
    if result["banners"] != current["banners"]:
        result["generatedAt"] = stamp
    verify(result)
    summary = {"appended": appended, "updatedExistingIds": updated,
               "skipped": skipped, "completedManual": [
                   {"file": ref["file"].name, "group": ref["group"],
                    "index": ref["index"], "appliedId": bid} for ref, bid in applied],
               "pendingManual": pending, "rejected": rejected, "v1Changed": result != current}
    if write:
        if result != current:
            atomic_json(file, result)
        for source in manual["files"]:
            entry = source["data"]
            prior = load(source["path"])
            if entry != prior:
                atomic_json(source["path"], entry)
    return summary

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--isolate-invalid", action="store_true")
    parser.add_argument("--candidate-dir", type=Path, default=CANDIDATES)
    parser.add_argument("--manual", type=Path, default=MANUAL)
    parser.add_argument("--v1", type=Path, default=V1)
    args = parser.parse_args()
    print(json.dumps(import_v1(write=args.write, candidate_dir=args.candidate_dir,
                               manual_dir=args.manual, v1_path=args.v1,
                               isolate_invalid=args.isolate_invalid), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
