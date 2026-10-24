#!/usr/bin/env python3
"""将原神简体中文公告整合候选与人工配置导入 v1。

业务输入：data/derived/genshin/v1-candidates/*.json、manual/genshin_<版本>.json。
public/v1/genshin.json 仅作为目标及去重依据；不访问网络或重新读取公告。

默认只预览；确认后使用 --write。既有卡池绝不被公告候选覆盖，
只允许 manual.existing 按内部 ID 更新。写入成功后逐条标记 completed。
manifest 由既有 Action 负责。
"""
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
from scripts.release.genshin_manual_versions import load_manual_versions, is_pending, complete

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = Path("data/derived/genshin/v1-candidates")
MANUAL = Path("manual")
V1 = Path("public/v1/genshin.json")
CANDIDATE_FORMAT = "genshin-v1-candidate-zh-CN-v1"
CN_TZ = timezone(timedelta(hours=8))
NORMAL_TYPES = ("character_event", "character_event_2", "weapon_event", "chronicled")
ORDER = {name: i for i, name in enumerate(NORMAL_TYPES)}


def load(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"{path}: JSON 根必须为对象")
    return result


def fail(message: str) -> None:
    raise ValueError(message)


def slot(row: dict) -> tuple:
    """单期每种祈愿只有一个正式卡池；特殊池额外用 variant 区分。"""
    return (row.get("gameVersion"), row.get("phase"),
            row.get("poolType"), row.get("variant") if row.get("poolType") == "chronicled" else None)


def candidate_slot(row: dict) -> tuple:
    return (row["version"], row["phase"], row["poolType"],
            row.get("variant") if row["poolType"] == "chronicled" else None)


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        fail(f"缺少有效的 +08:00 时间：{value!r}")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"无效时间：{value!r}") from exc
    if result.utcoffset() != timedelta(hours=8):
        fail(f"时间必须为 UTC+08:00：{value!r}")
    return result


def load_candidates(folder: Path, rejected: list[dict] | None = None) -> list[dict]:
    items: list[dict] = []
    slots: set[tuple] = set()
    duplicate_slots: set[tuple] = set()
    posts: set[str] = set()
    for path in sorted(folder.glob("v1-candidate_zh-CN_*.json")):
        try:
            row = load(path)
            pid = row.get("postId")
            source_key = row.get('sourceKey') or pid
            manual_candidate = isinstance(source_key, str) and source_key.startswith('manual-')
            if (row.get("format") != CANDIDATE_FORMAT or row.get("game") != "genshin"
                    or row.get("locale") != "zh-CN" or row.get("status") != "ready_candidate"
                    or not isinstance(source_key, str)
                    or not (re.fullmatch(r'\d+', source_key) or re.fullmatch(r'manual-[0-9a-f]{20}', source_key))
                    or (not manual_candidate and pid != source_key)
                    or path.stem != f"v1-candidate_zh-CN_{source_key}"):
                fail(f"{path}: 不是可发布的原神简体中文单篇候选")
            draft = row.get("v1Draft")
            if not isinstance(draft, dict) or row.get("poolType") not in NORMAL_TYPES:
                fail(f"{path}: v1Draft 或 poolType 无效")
            key = candidate_slot(row)
            if (draft.get("gameVersion"), draft.get("phase"), draft.get("poolType"),
                    draft.get("variant") if draft.get("poolType") == "chronicled" else None) != key:
                fail(f"{path}: 候选元数据与 v1Draft 身份不一致")
            if source_key in posts or key in slots:
                if key in slots:
                    duplicate_slots.add(key)
                fail(f"{path}: 公告 ID 或卡池槽位重复：{key}")
            provenance = row.get("provenance") or {}
            if (provenance.get('noticeSourceKey', pid) != source_key
                    or (not manual_candidate and str(provenance.get('noticePostId')) != pid)):
                fail(f"{path}: 缺少与公告 ID 一致的来源证据")
            if any("id" == k for k in draft):
                fail(f"{path}: 候选不得提前分配内部 ID")
            posts.add(source_key)
            slots.add(key)
            items.append(row)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            if rejected is None:
                raise
            rejected.append({"file": path.name, "error": str(exc)})
    if duplicate_slots:
        for item in list(items):
            if candidate_slot(item) in duplicate_slots:
                items.remove(item)
                if rejected is not None:
                    rejected.append({"postId": item["postId"],
                                     "error": "存在重复卡池槽位，全部相关候选暂停发布"})
    return items


def matches(matcher: dict, candidate: dict) -> bool:
    values = {
        "version": candidate["version"],
        "phase": candidate["phase"],
        "poolType": candidate["poolType"],
        "variant": candidate.get("variant"),
        "bannerName": candidate.get("bannerName"),
        "postId": candidate.get("postId"),
    }
    return all(values.get(key) == value for key, value in matcher.items())


def merge_map(target: dict, patch: dict, where: str) -> None:
    """普通对象递归合并；列表整体替换。唯一例外：regions 根据 server 合并。"""
    for name, value in patch.items():
        if name == "regions":
            if not isinstance(value, list):
                fail(f"{where}.regions: 必须为服务器对象数组")
            original = target.get("regions", [])
            if not isinstance(original, list):
                fail(f"{where}.regions: 目标格式无效")
            region_by_server = {r.get("server"): r for r in original}
            if len(region_by_server) != len(original):
                fail(f"{where}.regions: 已有服务器重复")
            used: set[str] = set()
            for region in value:
                if not isinstance(region, dict) or not isinstance(region.get("server"), str):
                    fail(f"{where}.regions: 缺少 server")
                server = region["server"]
                if server in used:
                    fail(f"{where}.regions: 同一次补丁重复服务器 {server}")
                used.add(server)
                if server in region_by_server:
                    merge_map(region_by_server[server], {k: v for k, v in region.items() if k != "server"},
                              f"{where}.regions[{server}]")
                else:
                    original.append(deepcopy(region))
                    region_by_server[server] = original[-1]
            target["regions"] = original
        elif isinstance(value, dict) and isinstance(target.get(name), dict):
            merge_map(target[name], value, f"{where}.{name}")
        else:
            target[name] = deepcopy(value)


def apply_patch(banner: dict, entry: dict, label: str, *, compare_item_ids: bool = False) -> None:
    merge_map(banner, entry.get("set", {}), label)
    for name, item_id in entry.get("itemIds", {}).items():
        matches_list = [
            item for grade in ("fiveStar", "fourStar")
            for item in (banner.get("featured", {}).get(grade) or [])
            if item.get("names", {}).get("zh-CN") == name
        ]
        if len(matches_list) != 1:
            fail(f"{label}: itemIds.{name} 未唯一匹配到 UP 物品")
        current_id = matches_list[0].get("itemId")
        if compare_item_ids and current_id is not None and item_id is not None and str(current_id) != str(item_id):
            fail(f"{label}: itemIds.{name} 人工 ID {item_id} 与已确认自动 ID {current_id} 冲突")
        matches_list[0]["itemId"] = item_id
    sources = banner.setdefault("sources", [])
    for source in entry.get("addSources", []):
        if source not in sources:
            sources.append(deepcopy(source))


def complete_start(candidate: dict, banner: dict) -> None:
    """第一期公告写“版本更新后”时，使用候选记录的版本维护开始时间。"""
    evidence = candidate.get("timeEvidence") or {}
    region = next((r for r in banner.get("regions", []) if r.get("server") == "cn_official"), None)
    if region is None:
        fail(f"{candidate['postId']}: 缺少国服时间")
    if region.get("startAt") is None:
        if evidence.get("startCondition") != "after_version_update" or candidate["phase"] != 1:
            fail(f"{candidate['postId']}: 缺少准确开池时间，且不是第一期版本更新后")
        maintenance = evidence.get("versionMaintenanceStartAt")
        region["startAt"] = _time(maintenance).isoformat(timespec="seconds")
    _time(region["startAt"])
    _time(region["endAt"])


def sort_candidate(candidate: dict) -> tuple:
    draft = candidate["v1Draft"]
    region = next((r for r in draft.get("regions", []) if r.get("server") == "cn_official"), {})
    start = region.get("startAt") or (candidate.get("timeEvidence") or {}).get("versionMaintenanceStartAt")
    return (_time(start), candidate["phase"], ORDER[candidate["poolType"]], str(candidate.get('sourceKey') or candidate.get('postId')))


def _store_atomic(path: Path, content: str) -> None:
    """在原目录写临时文件，再原子替换单个 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".manual-v1-", suffix=".tmp", delete=False) as fh:
            tmp_path = Path(fh.name)
            fh.write(content)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


def import_v1(root: Path = ROOT, *, write: bool = False,
              candidate_dir: Path = CANDIDATES, manual_path: Path = MANUAL,
              v1_path: Path = V1, isolate_invalid: bool = False) -> dict:
    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else root / path

    v1_file = resolve(v1_path)
    current = load(v1_file)
    if current.get("game") != "genshin" or not isinstance(current.get("banners"), list):
        fail(f"{v1_file}: 不是原神 v1 数据")
    result = deepcopy(current)
    banners = result["banners"]
    rejected: list[dict] = []
    candidates = load_candidates(resolve(candidate_dir), rejected if isolate_invalid else None)
    valid_candidates = []
    for candidate in candidates:
        try:
            sort_candidate(candidate)
            valid_candidates.append(candidate)
        except (ValueError, KeyError, TypeError) as exc:
            if not isolate_invalid:
                raise
            rejected.append({"postId": candidate.get("postId"), "error": str(exc)})
    candidates = valid_candidates
    manual = load_manual_versions(resolve(manual_path), rejected if isolate_invalid else None)
    original_by_id = {b["id"]: b for b in banners}
    if len(original_by_id) != len(banners):
        fail("现有 v1 存在重复内部 ID")
    occupied = {slot(b): b["id"] for b in banners}
    if len(occupied) != len(banners):
        fail("现有 v1 存在重复的版本/期数/卡池类型槽位")

    active_upcoming = [r for r in manual["upcoming"] if is_pending(r)]
    active_existing = [r for r in manual["existing"] if is_pending(r)]
    used_preset: set[tuple[Path, int]] = set()
    completed_refs: list[tuple[dict, str]] = []
    actions: list[dict] = []
    skip: list[dict] = []
    pending: list[dict] = []
    next_id = max((int(b["id"].split("-")[1]) for b in banners
                   if re.fullmatch(r"gi-0\d{5}", b["id"])), default=0) + 1

    def label(ref: dict) -> str:
        return f"{ref['file'].name}/{ref['group']}[{ref['index']}]"

    def use(ref: dict, bid: str) -> None:
        marker = (ref["file"], ref["index"])
        if marker in used_preset:
            fail(f"{label(ref)}: 同一 upcoming 预设匹配多个新卡池")
        used_preset.add(marker)
        completed_refs.append((ref, bid))

    for candidate in sorted(candidates, key=sort_candidate):
        try:
            key = candidate_slot(candidate)
            matched = [ref for ref in active_upcoming if matches(ref["match"], candidate)]
            if len(matched) > 1:
                fail(f"{candidate['postId']}: 同时匹配多个 upcoming 人工预设")
            if key in occupied:
                bid = occupied[key]
                skip.append({"postId": candidate["postId"], "id": bid, "reason": "already_exists"})
                if matched:
                    # 断点续跑：上轮已写入 v1、但还没写 completed 时，只在验证补丁
                    # 已全部反映到该已有池后补记完成；绝不因此修改现有池。
                    ref = matched[0]
                    simulated = deepcopy(original_by_id[bid])
                    apply_patch(simulated, ref["entry"], label(ref))
                    if simulated == original_by_id[bid]:
                        use(ref, bid)
                    else:
                        pending.append({"file": ref["file"].name, "index": ref["index"],
                                        "match": ref["match"], "reason": "existing_pool_not_overwritten"})
                continue
            data = deepcopy(candidate["v1Draft"])
            complete_start(candidate, data)
            if matched:
                ref = matched[0]
                if (ref["file"], ref["index"]) in used_preset:
                    fail(f"{candidate['postId']}: 同一 upcoming 预设匹配多个新卡池")
                apply_patch(data, ref["entry"], label(ref), compare_item_ids=True)
            if next_id > 99999:
                fail("原神普通活动池 ID 已超出范围")
            data["id"] = f"gi-{next_id:06d}"
            if isolate_invalid:
                probe = deepcopy(result)
                probe["banners"].append(data)
                validate_publishable_dataset(probe)
            banners.append(data)
            occupied[key] = data["id"]
            next_id += 1
            if matched:
                use(matched[0], data["id"])
            actions.append({"id": data["id"], "postId": candidate["postId"],
                            "name": data.get("names", {}).get("zh-CN"), "manual": bool(matched)})
        except (ValueError, KeyError, TypeError) as exc:
            if not isolate_invalid:
                raise
            rejected.append({"postId": candidate.get("postId"), "phase": candidate.get("phase"),
                             "poolType": candidate.get("poolType"), "error": str(exc)})
            continue

    updates: list[str] = []
    for ref in active_existing:
        try:
            entry = ref["entry"]
            bid = entry["id"]
            old = original_by_id.get(bid)
            if old is None:
                fail(f"{label(ref)}: 找不到已发布内部 ID {bid}")
            if old.get("gameVersion") != ref["version"]:
                fail(f"{label(ref)}: {bid} 所属版本不是 {ref['version']}，拒绝跨版本更新")
            before = deepcopy(old)
            updated = deepcopy(old)
            apply_patch(updated, entry, label(ref))
            if isolate_invalid and updated != before:
                probe = deepcopy(result)
                probe["banners"] = [
                    deepcopy(updated) if b["id"] == bid else b for b in probe["banners"]
                ]
                validate_publishable_dataset(probe)
            old.clear()
            old.update(updated)
            if old != before:
                updates.append(bid)
            completed_refs.append((ref, bid))
        except (ValueError, KeyError, TypeError) as exc:
            if not isolate_invalid:
                raise
            rejected.append({"file": ref["file"].name, "group": "existing",
                             "id": ref["entry"].get("id"), "error": str(exc)})

    for ref in active_upcoming:
        if (ref["file"], ref["index"]) not in used_preset and not any(
                a["file"] == ref["file"].name and a["index"] == ref["index"] for a in pending):
            pending.append({"file": ref["file"].name, "index": ref["index"],
                            "match": ref["match"], "reason": "waiting_for_new_candidate"})

    changed = bool(actions or updates)
    if changed:
        validate_publishable_dataset(result)
    # 默认预览不改 v1，也不改人工设定状态。
    if write:
        stamped = datetime.now(CN_TZ).isoformat(timespec="seconds")
        if changed:
            result["generatedAt"] = stamped
            validate_publishable_dataset(result)
            _store_atomic(v1_file, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        # 先成功写入 v1，才标记 completed。若意外中断，可按相同补丁安全重试。
        touched: set[Path] = set()
        for ref, bid in completed_refs:
            complete(ref, bid, stamped)
            touched.add(ref["file"])
        for obj in manual["files"]:
            if obj["path"] in touched:
                _store_atomic(obj["path"], json.dumps(obj["data"], ensure_ascii=False, indent=2) + "\n")

    return {
        "mode": "write" if write else "dry-run", "changed": changed,
        "candidates": len(candidates), "manualFilesScanned": len(manual["files"]),
        "pendingManualEntries": len(active_upcoming) + len(active_existing),
        "completedManual": [{"file": ref["file"].name, "group": ref["group"],
                             "index": ref["index"], "id": bid} for ref, bid in completed_refs],
        "appended": actions, "updatedExistingIds": updates,
        "skippedExisting": skip, "unmatchedUpcoming": pending,
        "rejected": rejected,
        "totalBanners": len(banners), "target": str(v1_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="仓库根目录")
    parser.add_argument("--candidate-dir", type=Path, default=CANDIDATES)
    parser.add_argument("--manual", type=Path, default=MANUAL, help="人工版本目录，扫描 genshin_*.json（忽略 archive 子目录）")
    parser.add_argument("--v1", type=Path, default=V1)
    parser.add_argument("--write", action="store_true", help="校验通过后真正更新 v1（默认预览）")
    parser.add_argument("--isolate-invalid", action="store_true",
                        help="逐池隔离无法发布的条目；保留其他合法修改（仅正式工作流使用）")
    args = parser.parse_args(argv)
    result = import_v1(args.root.resolve(), write=args.write,
                       candidate_dir=args.candidate_dir, manual_path=args.manual,
                       v1_path=args.v1, isolate_invalid=args.isolate_invalid)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
