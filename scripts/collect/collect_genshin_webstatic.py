"""Archive official Genshin Webstatic gacha lists/details without changing V1.

Only records observations actually made by this collector. This module does not
derive V1 dates, item IDs or banner versions. No third-party mirror is queried.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
STORE = Path("data/official/genshin/webstatic")
BASE = "https://operation-webstatic.mihoyo.com/gacha_info/hk4e/cn_gf01"
GACHA_ID = re.compile(r"^[a-f0-9]{40}$")
TZ8 = timezone(timedelta(hours=8))
MAX_BYTES = 8 * 1024 * 1024


def fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "PolyxiaBannerData-Webstatic-Collector/1.0"})
    with urlopen(request, timeout=25) as response:
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Webstatic response exceeds 8 MiB")
    obj = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError("Webstatic response must be an object")
    return obj


def _encoded(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path, default: dict | None = None) -> dict:
    if not path.is_file():
        return default.copy() if default is not None else {}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Invalid persisted object: {path}")
    return obj


def _write_if_changed(path: Path, payload: bytes) -> bool:
    if path.is_file() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as stream:
            stream.write(payload)
            tmp_path = Path(stream.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return True


def _save_versioned(path: Path, data: dict, history_dir: Path) -> bool:
    """Persist latest complete JSON; archive its previous bytes before replacement."""
    payload = _encoded(data)
    if path.is_file():
        old = path.read_bytes()
        if old == payload:
            return False
        _write_if_changed(history_dir / f"{_sha(old)}.json", old)
    return _write_if_changed(path, payload)


def _validate_list(data: dict) -> list[dict]:
    if data.get("retcode") != 0:
        raise ValueError(f"Webstatic list retcode: {data.get('retcode')}")
    items = (data.get("data") or {}).get("list")
    if not isinstance(items, list) or not items or len(items) > 60:
        raise ValueError("Webstatic list must contain 1..60 entries")
    unique: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Malformed Webstatic banner entry")
        gid = item.get("gacha_id")
        if not isinstance(gid, str) or not GACHA_ID.fullmatch(gid):
            raise ValueError(f"Invalid gacha_id: {gid!r}")
        if type(item.get("gacha_type")) is not int or not isinstance(item.get("begin_time"), str) or not isinstance(item.get("end_time"), str):
            raise ValueError(f"Incomplete banner list entry: {gid}")
        if gid in unique and unique[gid] != item:
            raise ValueError(f"Conflicting entries for {gid}")
        unique[gid] = item
    return list(unique.values())


def _detail_ready(detail: dict, listed_type: int) -> bool:
    if not isinstance(detail.get("title"), str) or not detail["title"].strip():
        return False
    if detail.get("gacha_type") != listed_type:
        return False
    five, four = detail.get("r5_up_items"), detail.get("r4_up_items")
    if five is not None and (not isinstance(five, list) or not all(isinstance(x, dict) and x.get("item_name") for x in five)):
        return False
    if four is not None and (not isinstance(four, list) or not all(isinstance(x, dict) and x.get("item_name") for x in four)):
        return False
    if listed_type in (301, 400):
        return isinstance(five, list) and len(five) == 1 and isinstance(four, list) and len(four) == 3
    if listed_type == 302:
        return isinstance(five, list) and len(five) == 2 and isinstance(four, list) and len(four) == 5
    if listed_type == 500:
        return isinstance(five, list) and len(five) > 0 and not four
    if listed_type in (100, 200):
        return True
    return False


def collect(root: Path = ROOT, *, fetcher=fetch_json, observed_at: str | None = None) -> dict:
    """Collect independently; never write to public/v1 or existing notice paths."""
    observed_at = observed_at or datetime.now(TZ8).isoformat(timespec="seconds")
    store = root / STORE
    checkpoint_path = store / "checkpoint.json"
    checkpoint = _load(checkpoint_path, {"format": "genshin-webstatic-checkpoint-v1", "list": {}, "banners": {}})
    checkpoint.setdefault("list", {})
    banners = checkpoint.setdefault("banners", {})

    index_url = f"{BASE}/gacha/list.json"
    listing = fetcher(index_url)
    entries = _validate_list(listing)  # Do not replace a valid index with a bad response.
    list_payload_hash = _sha(_encoded(listing))
    old_list_sha = checkpoint["list"].get("sha256")
    _save_versioned(store / "list.json", listing, store / "history" / "list")
    checkpoint["list"].setdefault("firstSeenAt", observed_at)
    if old_list_sha != list_payload_hash:
        checkpoint["list"]["changedAt"] = observed_at
    checkpoint["list"].update({"sha256": list_payload_hash, "url": index_url})
    results = {"listChanged": old_list_sha != list_payload_hash, "discovered": 0,
               "detailsChanged": 0, "detailsReady": 0, "errors": []}

    for item in entries:
        gid = item["gacha_id"]
        url = f"{BASE}/{gid}/zh-cn.json"
        if gid not in banners:
            banners[gid] = {"firstSeenAt": observed_at}
            results["discovered"] += 1
        entry = banners[gid]
        entry.update({"gachaType": item["gacha_type"], "beginTime": item["begin_time"],
                      "endTime": item["end_time"], "detailUrl": url})
        if "op_gacha_type" in item:
            entry["opGachaType"] = item["op_gacha_type"]

        try:
            detail = fetcher(url)
            if not isinstance(detail, dict) or not detail.get("title") or detail.get("gacha_type") != item["gacha_type"]:
                raise ValueError("Detail title or type is missing/inconsistent")
            ready = _detail_ready(detail, item["gacha_type"])
            changed = _save_versioned(store / "details" / f"{gid}.json", detail,
                                      store / "history" / "details" / gid)
            if changed:
                entry["detailChangedAt"] = observed_at
                results["detailsChanged"] += 1
            entry["detailSha256"] = _sha(_encoded(detail))
            entry["detailPath"] = (STORE / "details" / f"{gid}.json").as_posix()
            entry["title"] = detail["title"]
            entry.setdefault("detailFirstSeenAt", observed_at)
            if ready:
                entry.setdefault("detailReadyAt", observed_at)
                results["detailsReady"] += 1
            else:
                results["errors"].append(f"{gid}: detail is not complete for type {item['gacha_type']}")
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            results["errors"].append(f"{gid}: {exc}")

    _write_if_changed(checkpoint_path, _encoded(checkpoint))
    results["totalListed"] = len(entries)
    results["totalArchived"] = len(banners)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = collect(args.root.resolve())
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Webstatic collection failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
