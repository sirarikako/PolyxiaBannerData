#!/usr/bin/env python3
"""每日匿名读取官方物品目录并补齐两游戏简体中文 ItemID 对照表。

策略：四类各自国服优先；网络/响应/完整性失败时回退国际服；默认预览。
同名不同 ID 允许（现有 name->one ID 不覆盖；保留既有选择），
同一游戏内同 ID 不同名称为阻断性错误。永不删除已有映射、修改 v1 或 manifest。

python -m scripts.release.refresh_official_item_mappings
python -m scripts.release.refresh_official_item_mappings --write
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
MAPPING_FOLDER = Path("public/item-mappings")
CN_HOST = "https://api-takumi.mihoyo.com"
INTL_HOST = "https://sg-public-api.hoyolab.com"
# 门槛是2026-10已经实测的目录量的保守下限，只防止把局部响应当完整物品库。
MIN_IDS = {
    "genshin-characters": 100, "genshin-weapons": 200,
    "starrail-characters": 90, "starrail-lightcones": 150,
}
CATEGORIES = (
    ("genshin-characters", "genshin"),
    ("genshin-weapons", "genshin"),
    ("starrail-characters", "starrail"),
    ("starrail-lightcones", "starrail"),
)
PAGE_LIMIT = 20
PAGE_SIZE = 100


class CatalogUnavailable(Exception):
    """请求不通、服务端拒绝或目录数据不完整，可尝试备用服务器。"""


class MappingConflict(Exception):
    """同 ID 不同名称是业务冲突，不能通过切换来源悄悄掩盖。"""


def _name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize("NFC", value.strip())
    return value if value else None


def _id(value: object) -> int | None:
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,15}", str(value)):
        return None
    return int(value)


def row_pair(entry: object, *, identity: object = None) -> tuple[int, str] | None:
    if not isinstance(entry, dict):
        return None
    for nested in ("avatar", "equipment", "weapon"):
        child = entry.get(nested)
        if isinstance(child, dict):
            nested_pair = row_pair(child)
            if nested_pair:
                return nested_pair
    for field in ("item_name", "name", "name_mi18n"):
        name = _name(entry.get(field))
        if name is not None:
            break
    else:
        return None
    for field in ("item_id", "id", "avatar_id", "weapon_id"):
        item_id = _id(entry.get(field))
        if item_id is not None:
            return item_id, name
    item_id = _id(identity)
    return (item_id, name) if item_id is not None else None


def parse_catalog(value: object, category: str) -> list[tuple[int, str]]:
    """配置列表或数字键字典；不同元素形态的同 ID 同名条目仅去重。"""
    if isinstance(value, list):
        candidates = [(None, entry) for entry in value]
    elif isinstance(value, dict):
        candidates = list(value.items())
    else:
        raise CatalogUnavailable(f"{category}: 不是目录列表或对象")
    output: dict[int, str] = {}
    for identity, entry in candidates:
        pair = row_pair(entry, identity=identity)
        if not pair:
            continue
        item_id, name = pair
        if item_id in output and output[item_id] != name:
            raise MappingConflict(f"{category}: 同 ID 不同名称 {item_id}: {output[item_id]!r} / {name!r}")
        output[item_id] = name
    if not output:
        raise CatalogUnavailable(f"{category}: 没有可用的名称/ItemID 记录")
    return sorted(output.items())


def request_json(url: str, *, method: str = "GET", payload: dict | None = None,
                 is_international: bool = False, lang: str = "zh-cn") -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "CastoriceWishBannerData-ItemMappings/1.0 (+daily; no account data)",
        "x-rpc-lang": lang,
        "Referer": ("https://act.hoyolab.com/" if is_international else
                    "https://act.mihoyo.com/"),
    }
    req = Request(url, method=method, headers=headers,
                  data=json.dumps(payload or {}).encode("utf-8") if method == "POST" else None)
    try:
        with urlopen(req, timeout=15) as response:
            raw = response.read(5_000_001)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise CatalogUnavailable(f"请求失败: {type(exc).__name__}") from exc
    if len(raw) > 5_000_000:
        raise CatalogUnavailable("响应超过 5MB")
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CatalogUnavailable("接口没有返回有效 JSON") from exc
    if not isinstance(obj, dict):
        raise CatalogUnavailable("接口 JSON 根节点不是对象")
    code = obj.get("retcode", obj.get("code"))
    if code not in (None, 0, "0"):
        raise CatalogUnavailable(f"接口拒绝：code={code}")
    if not isinstance(obj.get("data"), dict):
        raise CatalogUnavailable("接口没有 data 对象")
    return obj["data"]


def _config_catalog(key: str, *, is_international: bool,
                    requester: Callable[..., dict], lang: str = "zh-cn") -> list[tuple[int, str]]:
    if key.startswith("genshin"):
        if is_international:
            url = f"{INTL_HOST}/event/simulatoros/config?{urlencode({'lang': lang})}"
            data = requester(url, is_international=True, **({"lang": lang} if lang != "zh-cn" else {}))
        else:
            url = f"{CN_HOST}/event/platsimulator/config?gids=2&game=hk4e"
            data = requester(url, method="POST", payload={})
        field = "all_avatar" if key.endswith("characters") else "all_weapon"
    else:
        if is_international:
            endpoint = "avatar" if key.endswith("characters") else "equipment"
            rows = []
            fingerprints: set[tuple[tuple[int, str], ...]] = set()
            for page in range(1, PAGE_LIMIT + 1):
                query = urlencode({
                    "game": "hkrpg", "lang": lang, "tab_from": "TabAll",
                    "page": page, "size": PAGE_SIZE,
                })
                data = requester(f"{INTL_HOST}/event/rpgcalc/{endpoint}/list?{query}",
                                 is_international=True, **({"lang": lang} if lang != "zh-cn" else {}))
                batch = data.get("list")
                if not isinstance(batch, list):
                    raise CatalogUnavailable(f"{key}: 国际服分页缺少 data.list")
                pairs = parse_catalog(batch, key) if batch else []
                marker = tuple(pairs)
                if marker in fingerprints and marker:
                    raise CatalogUnavailable(f"{key}: 重复分页，目录不完整")
                fingerprints.add(marker)
                rows.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
                total = data.get("total")
                if type(total) is int and page * PAGE_SIZE >= total:
                    break
                if page == PAGE_LIMIT:
                    raise CatalogUnavailable(f"{key}: 分页超出 {PAGE_LIMIT} 页")
            return parse_catalog(rows, key)
        data = requester(f"{CN_HOST}/event/rpgsimulator/config?game=hkrpg")
        field = "avatar" if key.endswith("characters") else "equipment"

    if field not in data:
        raise CatalogUnavailable(f"{key}: 缺少 data.{field}")
    return parse_catalog(data[field], key)


def get_category(key: str, requester: Callable[..., dict] = request_json) -> tuple[list[tuple[int, str]], str, str | None]:
    try:
        cn = _config_catalog(key, is_international=False, requester=requester)
        if len(cn) < MIN_IDS[key]:
            raise CatalogUnavailable(f"国服仅取得 {len(cn)} 个 ID（低于 {MIN_IDS[key]} 最低门槛）")
        return cn, "cn", None
    except CatalogUnavailable as exc:
        reason = str(exc)
    # ID/名称结构冲突不属于可通过回退隐藏的网络故障，故不在上方捕获。
    try:
        international = _config_catalog(key, is_international=True, requester=requester)
        if len(international) < MIN_IDS[key]:
            raise CatalogUnavailable(f"国际服仅取得 {len(international)} 个 ID（低于 {MIN_IDS[key]} 最低门槛）")
        return international, "international", reason
    except CatalogUnavailable as exc:
        raise CatalogUnavailable(f"国服失败: {reason}；国际服失败: {exc}") from exc


def load_mapping(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MappingConflict(f"{path}: 现有映射必须为对象")
    mapping: dict[str, int] = {}
    for name, value in data.items():
        item_id = _id(value)
        if not isinstance(name, str) or not name or item_id is None:
            raise MappingConflict(f"{path}: 现有映射条目无效 {name!r}")
        mapping[name] = item_id
    return mapping


def merge_game(mapping: dict[str, int], catalogs: list[tuple[str, list[tuple[int, str]]]]) -> tuple[dict[str, int], dict]:
    merged = dict(mapping)
    by_id: dict[int, str] = {}
    # 先验证原有映射中的反向键唯一
    for name, item_id in mapping.items():
        if item_id in by_id and by_id[item_id] != name:
            raise MappingConflict(f"现有映射同 ID 不同名称 {item_id}: {by_id[item_id]!r} / {name!r}")
        by_id[item_id] = name
    pair_by_id: dict[int, str] = {}
    same_name_other_id = 0
    added = []
    for category, items in catalogs:
        for item_id, name in items:
            if item_id in pair_by_id and pair_by_id[item_id] != name:
                raise MappingConflict(f"官方目录同 ID 不同名称 {item_id}: {pair_by_id[item_id]!r} / {name!r}")
            pair_by_id[item_id] = name
            if item_id in by_id and by_id[item_id] != name:
                raise MappingConflict(f"官方与已有对照表同 ID 不同名称 {item_id}: {by_id[item_id]!r} / {name!r}")
            if name in merged:
                if merged[name] != item_id:
                    # 一个名称在现有公共 name->单值格式中不能保存多个 ID；
                    # 视为合法同名，保留原映射，不任意替换 ID。
                    same_name_other_id += 1
                continue
            # 原有反向表无此 ID，才允许新名称进入。
            merged[name] = item_id
            by_id[item_id] = name
            added.append({"name": name, "itemId": item_id, "source": category})
    merged = dict(sorted(merged.items(), key=lambda pair: (pair[1], pair[0])))
    return merged, {"added": added, "allowedSameNameDifferentId": same_name_other_id,
                    "sourceUniqueIds": len(pair_by_id)}


def _atomic_write(path: Path, contents: str) -> None:
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".mapping-", suffix=".tmp", delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(contents)
        os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def refresh(root: Path = ROOT, *, write: bool = False,
            requester: Callable[..., dict] = request_json) -> dict:
    catalogs_by_game: dict[str, list[tuple[str, list[tuple[int, str]]]]] = defaultdict(list)
    details: list[dict] = []
    # 游戏分别隔离：一个游戏存在 ID/名称冲突不能阻止另一个游戏补齐数据。
    source_conflicts: dict[str, list[str]] = defaultdict(list)
    for category, game in CATEGORIES:
        try:
            items, source, fallback_reason = get_category(category, requester)
            catalogs_by_game[game].append((category, items))
            details.append({"category": category, "source": source,
                            "uniqueItemIds": len(items), "fallbackReason": fallback_reason})
        except CatalogUnavailable as exc:
            details.append({"category": category, "source": "unavailable", "error": str(exc)})
        except MappingConflict as exc:
            source_conflicts[game].append(str(exc))
            details.append({"category": category, "source": "conflict", "error": str(exc)})

    output: dict[str, tuple[Path, dict]] = {}
    reports: dict[str, dict] = {}
    blocked: dict[str, list[str]] = {}
    for game in ("genshin", "starrail"):
        path = root / MAPPING_FOLDER / game / "zh-CN.json"
        old = load_mapping(path)
        problems = list(source_conflicts.get(game, []))
        if not problems:
            try:
                new, report = merge_game(old, catalogs_by_game.get(game, []))
            except MappingConflict as exc:
                problems.append(str(exc))
        if problems:
            blocked[game] = problems
            reports[game] = {"oldCount": len(old), "newCount": len(old),
                             "newEntries": 0, "allowedSameNameDifferentId": 0,
                             "sourceUniqueIds": 0, "blocked": True}
            continue
        reports[game] = {
            "oldCount": len(old), "newCount": len(new),
            "newEntries": len(report["added"]),
            "allowedSameNameDifferentId": report["allowedSameNameDifferentId"],
            "sourceUniqueIds": report["sourceUniqueIds"], "blocked": False,
        }
        if new != old:
            output[game] = (path, new)

    # 所有项目都已校验完才动手，冲突游戏保持原文件完全不变。
    if write:
        for path, data in output.values():
            _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {
        "mode": "write" if write else "dry-run",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalogs": details, "games": reports,
        "blockedGames": blocked, "updatedGames": sorted(output),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true", help="通过校验后写入 item-mappings（默认只预览）")
    parser.add_argument("--with-locales", action="store_true", help="同时更新繁中、英文、日文（与简中独立校验）")
    parser.add_argument("--report", type=Path, help="可选：输出报告 JSON（不保存 API 原始响应）")
    args = parser.parse_args(argv)
    report = refresh(args.root.resolve(), write=args.write)
    if args.with_locales:
        from scripts.release.refresh_official_item_mappings_locales import refresh_locales
        report["localized"] = refresh_locales(args.root.resolve(), write=args.write)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(encoded, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    return 2 if report["blockedGames"] or report.get("localized", {}).get("blockedLocales") else 0


if __name__ == "__main__":
    raise SystemExit(main())
