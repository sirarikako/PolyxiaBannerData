"""独立生成 data/BANNER_STATUS.md：只读查看公告解析、候选和 V1 的逐版本状态。"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

GAMES = {"genshin": "原神", "starrail": "星铁"}
ROLE_TYPES = {"character_event", "character_event_2", "collab_character_event"}
GEAR_TYPES = {"weapon_event", "light_cone_event", "collab_light_cone_event"}
VERSION_IN_TIME = re.compile(r"(\d+\.\d+|月之[一二三四五六七八九十]+)\s*版本")
MAX_NAMES = 3


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc


def pool_kind(pool_type):
    if pool_type in ROLE_TYPES or (isinstance(pool_type, str) and "collab_character" in pool_type):
        return "role"
    if pool_type in GEAR_TYPES or (isinstance(pool_type, str) and "collab_light_cone" in pool_type):
        return "gear"
    return "other"


def version_of(row):
    value = row.get("version") or row.get("gameVersion")
    if value:
        return str(value)
    time = row.get("time") or {}
    match = VERSION_IN_TIME.search(str(time.get("startRaw") or ""))
    return match.group(1) if match else "未归版本"


def featured_names(row, category):
    draft = row.get("v1Draft") or {}
    featured = row.get("featured") or draft.get("featured") or {}
    items = featured.get("fiveStar")
    if isinstance(items, list):
        return [str((obj.get("names") or {}).get("zh-CN") or obj.get("itemId") or "?")
                if isinstance(obj, dict) else str(obj)
                for obj in items]
    up = row.get("up") or {}
    key = "fiveStarCharacters" if category == "role" else "fiveStarWeapons"
    return [str(obj.get("name") or "?") if isinstance(obj, dict) else str(obj)
            for obj in (up.get(key) or [])]


def path_link(root, path, label):
    relative = path.relative_to(root).as_posix()
    return f"[{label}](../{quote(relative, safe='/')})"


def hsr_match_key(version, record):
    """用版本、池种、名称及五星名单匹配同一期的持久化 V1。"""
    featured = record.get("featured") or {}
    five = featured.get("fiveStar") or []
    names = tuple(sorted(
        str((item.get("names") or {}).get("zh-CN") or item.get("itemId") or "")
        if isinstance(item, dict) else str(item)
        for item in five
    ))
    name = (record.get("names") or {}).get("zh-CN") or record.get("bannerName") or ""
    return (str(version or ""), str(record.get("poolType") or ""), str(name), names)


def hsr_published_phase(record, version, published_by_id, published_by_key):
    """已有 V1 的实际期数优先于跨期跃迁公告的顶部 phase。"""
    existing_id = record.get("existingId") or record.get("existingV1Id")
    published = published_by_id.get(existing_id)
    if published and str(published.get("gameVersion")) == str(version):
        return published.get("phase")
    key = hsr_match_key(version, record)
    matches = published_by_key.get(key, [])
    if len(matches) == 1:
        return matches[0].get("phase")
    return None


def make_group():
    return {"updates": [], "previews": [], "notices": defaultdict(list),
            "candidates": defaultdict(list), "v1": defaultdict(list), "dates": []}


def add(groups, version, phase, source, category, path, record):
    group = groups[(version, phase)]
    group[source][category].append((path, record))
    regions = record.get("regions") or []
    date = regions[0].get("startAt") if regions and isinstance(regions[0], dict) else None
    date = date or (record.get("time") or {}).get("startAt")
    date = date or (record.get("source") or {}).get("publishedAt")
    if date:
        group["dates"].append(str(date))


def collect(root, game):
    groups = defaultdict(make_group)
    v1_file = root / f"public/v1/{game}.json"
    # 原始公告没有期数时，从已发布 V1 的来源文章精确关联，不凭日期或 UP 名称猜测。
    published_sources = {}
    published_conflicts = set()
    published_by_id = {}
    published_by_key = defaultdict(list)
    for banner in read_json(v1_file).get("banners", []):
        if not banner.get("gameVersion"):
            continue
        add(groups, str(banner["gameVersion"]), banner.get("phase"), "v1",
            pool_kind(banner.get("poolType")), v1_file, banner)
        if game == "starrail":
            published_by_id[banner.get("id")] = banner
            published_by_key[hsr_match_key(banner.get("gameVersion"), banner)].append(banner)
        if game == "genshin" and isinstance(banner.get("phase"), int):
            identity = (str(banner["gameVersion"]), banner["phase"])
            for source in banner.get("sources") or []:
                if not isinstance(source, dict) or source.get("provider") != "miyoushe":
                    continue
                match = re.fullmatch(
                    r"https?://(?:www\.)?miyoushe\.com/ys/article/(\d+)(?:[/?#].*)?",
                    str(source.get("url") or ""),
                )
                if not match:
                    continue
                post_id = match.group(1)
                if post_id in published_sources and published_sources[post_id] != identity:
                    published_conflicts.add(post_id)
                else:
                    published_sources[post_id] = identity
    for post_id in published_conflicts:
        published_sources.pop(post_id, None)

    base = root / "data/derived" / game

    # 原始祈愿公告的 version/phase 可能为 null；关联结果保存在 readiness。
    # 使用确切的公告文件路径映射，绝不通过时间/角色名字猜测期数。
    associations = {}
    ambiguous = set()
    if game == "genshin":
        readiness = base / "v1-readiness/v1-readiness_zh-CN.json"
        if readiness.exists():
            for item in read_json(readiness).get("notices", []):
                file_name = item.get("noticeFile")
                version, phase = item.get("version"), item.get("phase")
                if not file_name or not version or not isinstance(phase, int):
                    continue
                identity = (str(version), phase)
                if file_name in associations and associations[file_name] != identity:
                    ambiguous.add(file_name)
                else:
                    associations[file_name] = identity
            for file_name in ambiguous:
                associations.pop(file_name, None)

    notice_folder = "wish-notices" if game == "genshin" else "warp-notices"
    for file in sorted((base / notice_folder).glob("*.json")):
        record = read_json(file)
        if isinstance(record.get("banners"), list):
            for banner in record["banners"]:
                combined = {**banner, "version": record.get("version"),
                            "phase": record.get("phase"), "source": record.get("source")}
                version = version_of(combined)
                if game == "starrail":
                    published_phase = hsr_published_phase(
                        combined, version, published_by_id, published_by_key
                    )
                    if published_phase is not None:
                        combined["phase"] = published_phase
                add(groups, version, combined.get("phase"), "notices",
                    pool_kind(combined.get("poolType")), file, combined)
        else:
            associated = associations.get(file.relative_to(root).as_posix())
            if not associated:
                post_id = str((record.get("source") or {}).get("postId") or "")
                associated = published_sources.get(post_id)
            version = record.get("version") or (associated[0] if associated else None) or version_of(record)
            phase = record.get("phase")
            if phase is None and associated:
                phase = associated[1]
            add(groups, str(version), phase, "notices",
                pool_kind(record.get("poolType")), file, record)

    if game == "genshin":
        for file in sorted((base / "v1-candidates").glob("*.json")):
            candidate = read_json(file)
            draft = candidate.get("v1Draft") or {}
            add(groups, version_of(candidate), candidate.get("phase"), "candidates",
                pool_kind(candidate.get("poolType") or draft.get("poolType")), file, draft)
        for file in sorted((base / "wish-previews").glob("*.json")):
            record = read_json(file)
            groups[(version_of(record), record.get("phase"))]["previews"].append((file, record))
        for file in sorted((base / "version-updates").glob("*.json")):
            record = read_json(file)
            version = version_of(record)
            if version == "未归版本":
                version = file.stem.removeprefix("version-update_zh-CN_")
            keys = [key for key in groups if key[0] == version]
            for key in keys or [(version, None)]:
                groups[key]["updates"].append((file, record))
    else:
        readiness = base / "v1-readiness/v1-readiness_zh-CN.json"
        if readiness.exists():
            for candidate in read_json(readiness).get("rows", []):
                draft = candidate.get("v1Draft") or {}
                version = version_of(candidate)
                actual_phase = hsr_published_phase(
                    candidate, version, published_by_id, published_by_key
                )
                if actual_phase is None:
                    actual_phase = hsr_published_phase(
                        {**draft, "bannerName": candidate.get("bannerName")},
                        version, published_by_id, published_by_key
                    )
                phase = actual_phase if actual_phase is not None else candidate.get("phase")
                add(groups, version, phase, "candidates",
                    pool_kind(candidate.get("poolType") or draft.get("poolType")), readiness, draft)
    return groups


def stage_cell(root, records, singular_label, plural_label=None, show_names=False, category=None):
    if not records:
        return "—"
    paths = list(dict.fromkeys(file for file, _ in records))
    target = paths[0] if len(paths) == 1 else paths[0].parent
    count = len(records)
    label = singular_label if count == 1 else (plural_label or f"{count}条")
    cell = "✅ " + path_link(root, target, label)
    if show_names:
        names = sorted({name for _, row in records for name in featured_names(row, category)})
        if names:
            cell += " · " + "、".join(names[:MAX_NAMES])
            if len(names) > MAX_NAMES:
                cell += f" 等{len(names)}个"
    return cell


def notice_cell(root, records, game, category):
    if game == "starrail":
        # 一篇星铁跃迁公告内可以同时列多个池，不能把池数显示成文章数。
        articles = len({path for path, _ in records})
        label = f"{articles}篇"
        value = stage_cell(root, records, label, label, True, category)
        if records:
            value += f" · {len(records)}池"
        return value
    return stage_cell(root, records, "1篇", f"{len(records)}篇", True, category)


def brief_preview(root, previews):
    if not previews:
        return "—"
    file, _ = previews[0]
    count = len(previews)
    info = []
    for _, record in previews:
        up = record.get("up") or {}
        for key, abbr in (("fiveStarCharacters", "角"), ("fiveStarWeapons", "武")):
            names = {str(x.get("name")) if isinstance(x, dict) else str(x)
                     for x in up.get(key, [])}
            info.append((abbr, names))
    role = set().union(*(names for kind, names in info if kind == "角"))
    gear = set().union(*(names for kind, names in info if kind == "武"))
    suffix = f" · 角{len(role)}/武{len(gear)}" if role or gear else ""
    return "✅ " + path_link(root, file if count == 1 else file.parent, f"{count}篇") + suffix


def count_cell(root, group, source, game):
    records = sum((group[source][key] for key in ("role", "gear", "other")), [])
    if not records:
        return "—"
    if source == "v1":
        return "✅ " + path_link(root, root / f"public/v1/{game}.json", f"{len(records)}池")
    paths = list(dict.fromkeys(file for file, _ in records))
    target = paths[0] if len(paths) == 1 else paths[0].parent
    return "✅ " + path_link(root, target, f"{len(records)}池")


def note(group, phase, game):
    notices = group["notices"]
    role, gear = len(notices["role"]), len(notices["gear"])
    reasons = []
    if phase is None and (role or gear or group["previews"]):
        reasons.append("期数未关联")
    if role and not gear:
        reasons.append("武器/光锥公告待确认")
    elif gear and not role:
        reasons.append("角色公告待确认")
    if (role or gear) and not any(group["v1"].values()):
        reasons.append("尚未进入正式V1")
    return "⚠️ " + "；".join(reasons) if reasons else "—"


def sort_key(item):
    (version, phase), group = item
    num = re.fullmatch(r"(\d+)\.(\d+)", version)
    numbers = (int(num[1]), int(num[2])) if num else (0, 0)
    return (max(group["dates"], default=""), numbers, version, phase if isinstance(phase, int) else 99)


def table(root, game, rows):
    result = ["| 版本 | 期 | 版本更新公告 | 卡池预告 | 角色池公告 | 武器/光锥公告 | 候选 | V1 | 提示 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for (version, phase), group in rows:
        updates = stage_cell(root, group["updates"], "已解析", "多篇")
        previews = brief_preview(root, group["previews"]) if game == "genshin" else "不适用"
        role = notice_cell(root, group["notices"]["role"], game, "role")
        gear = notice_cell(root, group["notices"]["gear"], game, "gear")
        parts = [version, str(phase) if phase is not None else "待归期", updates, previews, role, gear,
                 count_cell(root, group, "candidates", game), count_cell(root, group, "v1", game),
                 note(group, phase, game)]
        result.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ") for x in parts) + " |")
    return "\n".join(result)


def render(root):
    lines = ["# 公告识别与卡池数据状态一览", "",
             "本报告由独立只读程序根据仓库已保存的结构化 JSON 自动生成，不抓取公告、不执行 OCR、不修改候选或 V1。", "",
             "✅ 表示当前仓库有对应解析结果；— 表示未见保存的结构化记录（不等于官方未发布公告）。",
             "数字可以点击查看对应 JSON 或目录；候选是组装结果，V1 是正式数据。", "",
             "同版本按期展示，尚未匹配期数的公告标记为待归期；历史版本缺少阶段记录不自动报错。", ""]
    for game, title in GAMES.items():
        groups = collect(root, game)
        ordered = sorted(groups.items(), key=sort_key, reverse=True)
        versions = list(dict.fromkeys(key[0] for key, _ in ordered))
        recent = set(versions[:10])
        visible = [item for item in ordered if item[0][0] in recent]
        older = [item for item in ordered if item[0][0] not in recent]
        lines.extend([f"## {title}", "", table(root, game, visible), ""])
        if older:
            lines.extend([f"<details><summary>展开历史版本（另 {len(versions) - len(recent)} 个版本）</summary>",
                          "", table(root, game, older), "", "</details>", ""])
    lines.extend(["---", "",
                  "说明：原神有版本更新、卡池预告和卡池公告三个独立来源；星铁不使用卡池预告。",
                  "当前星铁没有单独持久化的版本更新公告结构化文件，因此此列不会臆写已解析。",
                  "星铁跃迁公告可能同时包含持续开放的上一期卡池；报告以已发布 V1 的精确池身份核对实际期数。",
                  "角色和武器公告不对称仅提示核查，不代表官方必须同时存在两类池；常驻、新手池不按版本列出。", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output or root / "data/BANNER_STATUS.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(root), encoding="utf-8")
    print(f"已生成：{output}")


if __name__ == "__main__":
    main()
