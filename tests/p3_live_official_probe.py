"""P3 read-only live official-source probe (explicit opt-in only).

Only two previously identified official article IDs are fetched. Do not expose
raw JSON, article content, images, or OCR text in logs or artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

from scripts.collect.collect_miyoushe_announcements import (
    fetch, validate_detail,
)
from scripts.collect.download_genshin_notice_images_zh_cn import (
    download_images, image_urls,
)
from scripts.transform.build_genshin_wish_notice_zh_cn import build as build_genshin
from scripts.transform.recognize_genshin_wish_image_zh_cn import recognize_time
from scripts.transform.starrail_notice_text_zh_cn import post_from_raw
from scripts.transform.build_starrail_warp_notice_zh_cn import build as build_starrail

ROOT = Path(__file__).resolve().parents[1]
URL = "https://bbs-api.miyoushe.com/post/wapi/getPostFull"
GENSHIN = "78782590"
STARRAIL = "79023863"


def _source(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def probe_genshin():
    pid = GENSHIN
    saved = _source(f"data/derived/genshin/wish-notices/wish-notice_zh-CN_{pid}.json")
    raw = fetch(URL, {"post_id": pid, "gids": 2}, retries=1, timeout=12)
    post = validate_detail(raw, pid)
    if ((post.get("post_status") or {}).get("is_official") is False
            or post.get("subject") != saved["source"]["title"]):
        raise ValueError("Genshin source title or official identity differs from verified baseline")
    parsed = build_genshin(raw, post_id=pid, source_file="runner-temp-only")
    if parsed["source"]["url"] != saved["source"]["url"] or not any(parsed["up"].values()):
        raise ValueError("Genshin parsed source or UP list invalid")
    if parsed["poolType"] != saved["poolType"]:
        raise ValueError("Genshin poolType changed")

    urls = image_urls(post)
    if not 1 <= len(urls) <= 4:
        raise ValueError("Genshin expected 1 to 4 official images, refusing unbounded download")
    with TemporaryDirectory(prefix="p3-genshin-ocr-") as directory:
        indexed = download_images(post, pid, output_root=Path(directory))
        if indexed is None or not indexed.is_file():
            raise ValueError("Genshin official images were not obtained")
        result = recognize_time(indexed.parent, pid, urls)
        status = result["status"]
        if status not in ("recognized", "recognized_conditional"):
            raise ValueError("Genshin OCR could not independently recognize the dates")
        saved_times = (saved.get("imageTimeRecognition") or {}).get("times") or {}
        times = result.get("times") or {}
        if (times.get("startAt") != saved_times.get("startAt")
                or times.get("endAt") != saved_times.get("endAt")):
            raise ValueError("Genshin live OCR time differs from prior verified metadata")
        print(f"P3_GENSHIN_OK id={pid} images={len(urls)} OCR={status}", flush=True)
    # TemporaryDirectory removes all images and manifests; no raw JSON was saved.


def probe_starrail():
    pid = STARRAIL
    saved = _source(f"data/derived/starrail/warp-notices/warp-notice_zh-CN_{pid}.json")
    raw = fetch(URL, {"post_id": pid, "gids": 6}, retries=1, timeout=12)
    post = post_from_raw(raw, pid)
    if ((post.get("post_status") or {}).get("is_official") is False
            or post.get("subject") != saved["source"]["title"]):
        raise ValueError("Star Rail source title or official identity differs from verified baseline")
    parsed = build_starrail(raw, pid)
    if (parsed["source"]["url"] != saved["source"]["url"]
            or parsed["version"] != saved["version"]
            or parsed["phase"] != saved["phase"]):
        raise ValueError("Star Rail parsed source metadata differs")
    if len(parsed.get("banners") or []) != len(saved.get("banners") or []):
        raise ValueError("Star Rail banner count mismatch")
    print(f"P3_STARRAIL_OK id={pid} banners={len(parsed['banners'])}", flush=True)


def main():
    errors = []
    for name, probe in [("GENSHIN", probe_genshin), ("STARRAIL", probe_starrail)]:
        try:
            probe()
        except Exception as exc:
            # Never print exception details/URLs/response bodies to Public CI.
            print(f"P3_{name}_FAILED error_type={type(exc).__name__}", flush=True)
            errors.append(name)
    if errors:
        print("P3_LIVE_RESULT=BLOCKED", flush=True)
        return 1
    print("P3_LIVE_RESULT=PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
