"""Archive official Honkai: Star Rail Webstatic gacha observations; never update V1.

This collector stores API responses as evidence, not an inferred banner catalog.
The endpoint layout is configurable because Webstatic can change its paths.
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
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
STORE = Path("data/official/starrail/webstatic")
# Candidate path: verify against the page's Network panel before production cutover.
BASE = "https://operation-webstatic.mihoyo.com/gacha_info/hkrpg/prod_gf_cn"
TZ8 = timezone(timedelta(hours=8))
GACHA_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_BYTES = 8 * 1024 * 1024
EVENT_TYPES = {11, 12, 21, 22}


def fetch_json(url: str) -> dict:
    request = Request(url, headers={
        "User-Agent": "PolyxiaBannerData-StarRail-Webstatic/1.0",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=25) as response:
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("Official response exceeds 8 MiB")
    obj = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError("Official response must be a JSON object")
    return obj


def _base_url(value: str) -> str:
    url = value.rstrip("/")
    parsed = urlsplit(url)
    if (parsed.scheme != "https"
            or parsed.hostname not in {"operation-webstatic.mihoyo.com", "webstatic.mihoyo.com"}
            or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", parsed.path)
            or ".." in parsed.path.split("/")):
        raise ValueError("Webstatic base URL must use an approved official HTTPS host/path")
    return url


def _bytes(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(path: Path, default: dict) -> dict:
    if not path.exists():
        return default.copy()
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Invalid checkpoint: {path}")
    return obj


def _write(path: Path, payload: bytes) -> bool:
    if path.is_file() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as f:
            tmp = Path(f.name)
            f.write(payload)
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return True


def _save_versioned(path: Path, obj: dict, archive: Path) -> bool:
    new = _bytes(obj)
    if path.is_file():
        old = path.read_bytes()
        if old == new:
            return False
        _write(archive / f"{_sha(old)}.json", old)
    return _write(path, new)


def _gacha_type(value: object) -> int:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{1,4}", value):
        return int(value)
    raise ValueError(f"Invalid gacha_type: {value!r}")


def _validate_list(obj: dict) -> list[tuple[str, int, dict]]:
    if obj.get("retcode", 0) != 0:
        raise ValueError(f"Official list retcode={obj.get('retcode')}")
    data = obj.get("data", obj)
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError("Official list must contain 1..100 banners")
    unique: dict[str, tuple[str, int, dict]] = {}
    for row in items:
        if not isinstance(row, dict):
            raise ValueError("Malformed banner list entry")
        raw_id = row.get("gacha_id")
        if type(raw_id) not in (int, str):
            raise ValueError(f"Invalid gacha_id: {raw_id!r}")
        gid = str(raw_id)
        if not GACHA_ID.fullmatch(gid):
            raise ValueError(f"Unsafe gacha_id: {gid!r}")
        kind = _gacha_type(row.get("gacha_type"))
        if any(not isinstance(row.get(k), str) or not row[k].strip()
               for k in ("begin_time", "end_time")):
            raise ValueError(f"Missing banner dates for {gid}")
        if gid in unique and unique[gid][2] != row:
            raise ValueError(f"Conflicting entries for {gid}")
        unique[gid] = (gid, kind, row)
    return list(unique.values())


def _detail_payload(raw: dict) -> dict:
    if raw.get("retcode", 0) != 0:
        raise ValueError(f"Official detail retcode={raw.get('retcode')}")
    if "title" not in raw and isinstance(raw.get("data"), dict):
        return raw["data"]
    return raw


def _detail_ready(obj: dict, kind: int) -> bool:
    if not isinstance(obj.get("title"), str) or not obj["title"].strip():
        return False
    try:
        if _gacha_type(obj.get("gacha_type")) != kind:
            return False
    except ValueError:
        return False
    if kind in (1, 2):
        return True
    if kind not in EVENT_TYPES:
        return False
    five, four = obj.get("items_up_star_5"), obj.get("items_up_star_4")
    # These arrays ARE the featured lists. Never filter their rows by is_up.
    # Official crossover pools (21/22) intentionally return null for 4-star UP.
    four_valid = (four is None or isinstance(four, list)) if kind in (21, 22) else isinstance(four, list)
    return (isinstance(five, list) and bool(five)
            and all(isinstance(v, dict) for v in five)
            and four_valid
            and (four is None or all(isinstance(v, dict) for v in four)))


def collect(root: Path = ROOT, *, fetcher=fetch_json, base_url: str = BASE,
            observed_at: str | None = None) -> dict:
    """Save only well-formed observations; preserve last good files on failures."""
    base = _base_url(base_url)
    observed_at = observed_at or datetime.now(TZ8).isoformat(timespec="seconds")
    store = root / STORE
    checkpoint_path = store / "checkpoint.json"
    old = _load(checkpoint_path, {"format": "starrail-webstatic-checkpoint-v1",
                                  "list": {}, "banners": {}})
    if old.get("format") != "starrail-webstatic-checkpoint-v1":
        raise ValueError("Unsupported checkpoint format")
    listing = fetcher(base + "/gacha/list.json")
    entries = _validate_list(listing)  # Invalid/empty list must not replace a prior snapshot.
    result = {"listChanged": False, "discovered": 0, "detailsChanged": 0,
              "detailsReady": 0, "totalListed": len(entries), "errors": []}
    list_sha = _sha(_bytes(listing))
    state = old.setdefault("list", {})
    result["listChanged"] = list_sha != state.get("sha256")
    _save_versioned(store / "list.json", listing, store / "history/list")
    state.setdefault("firstSeenAt", observed_at)
    if result["listChanged"]:
        state["changedAt"] = observed_at
    state.update({"sha256": list_sha, "url": base + "/gacha/list.json"})
    banners = old.setdefault("banners", {})

    for gid, kind, row in entries:
        if gid not in banners:
            banners[gid] = {"firstSeenAt": observed_at}
            result["discovered"] += 1
        entry = banners[gid]
        url = f"{base}/{gid}/zh-cn.json"
        entry.update({"gachaType": kind, "beginTime": row["begin_time"],
                      "endTime": row["end_time"], "detailUrl": url})
        try:
            raw = fetcher(url)
            obj = _detail_payload(raw)
            if not isinstance(obj.get("title"), str) or not obj["title"].strip():
                raise ValueError("Detail has no title")
            if _gacha_type(obj.get("gacha_type")) != kind:
                raise ValueError("Detail/list gacha_type mismatch")
            changed = _save_versioned(store / "details" / f"{gid}.json", raw,
                                      store / "history/details" / gid)
            if changed:
                entry["detailChangedAt"] = observed_at
                result["detailsChanged"] += 1
            entry.setdefault("detailFirstSeenAt", observed_at)
            entry.update({"detailSha256": _sha(_bytes(raw)),
                          "detailPath": (STORE / "details" / f"{gid}.json").as_posix(),
                          "title": obj["title"]})
            entry.pop("lastError", None)
            if _detail_ready(obj, kind):
                entry.setdefault("detailReadyAt", observed_at)
                result["detailsReady"] += 1
            else:
                result["errors"].append(f"{gid}: incomplete/unknown banner detail")
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
            entry["lastError"] = str(exc)
            result["errors"].append(f"{gid}: {exc}")

    result["totalArchived"] = len(banners)
    _write(checkpoint_path, _bytes(old))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base-url", default=os.getenv("STARRAIL_WEBSTATIC_BASE_URL", BASE))
    args = parser.parse_args()
    try:
        report = collect(args.root.resolve(), base_url=args.base_url)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Star Rail official collection failed: {exc}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
