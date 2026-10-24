"""P3 end-to-end assembly against migrated derived documents, with zero raw posts.

This exercises real historical parsed artifacts as inputs, without official network
requests or writes to the repository's actual v1/manifest.
"""
from __future__ import annotations

import json
from pathlib import Path
from shutil import copy2

from scripts.transform.assemble_genshin_wish_candidates_zh_cn import build_index
from scripts.transform.assemble_starrail_warp_candidates_zh_cn import assemble as assemble_starrail

REPO = Path(__file__).resolve().parents[1]


def copied(root, path):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    copy2(REPO / path, target)
    return target


def save(root, path, obj):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def test_real_genshin_parsed_notice_accepts_manual_comparison_without_old_post(tmp_path):
    pid = "78782590"
    source = "data/derived/genshin/wish-notices/wish-notice_zh-CN_" + pid + ".json"
    copied(tmp_path, source)
    save(tmp_path, f"manual/notices/genshin/zh-CN/miyoushe/{pid}.json", {
        "format": "genshin-notice-manual-v1",
        "postId": pid,
        "data": {"poolType": "character_event_2"},
    })
    updates, previews, notices = build_index(tmp_path)
    assert updates == [] and previews == [] and len(notices) == 1
    row = notices[0]
    assert row["data"]["source"]["postId"] == pid
    assert row["manualFile"].endswith(pid + ".json")
    assert "poolType" in row["matched"]
    assert row["blockingDifferences"] == []
    assert not (tmp_path / "data/announcements/genshin/zh-cn/miyoushe/posts").exists()


def test_real_starrail_structured_source_and_manual_reassemble_twice_without_posts(tmp_path):
    pid = "79023863"
    copied(tmp_path, f"data/derived/starrail/warp-notices/warp-notice_zh-CN_{pid}.json")
    copied(tmp_path, "schemas/manual/starrail-notice-manual.schema.json")
    copied(tmp_path, "schemas/manual/starrail-missing-warp.schema.json")
    copied(tmp_path, "public/item-mappings/starrail/zh-CN.json")
    save(tmp_path, "public/v1/starrail.json", {"game": "starrail", "banners": []})
    save(tmp_path, f"manual/notices/starrail/zh-CN/miyoushe/{pid}.json", {
        "format": "starrail-notice-manual-v1", "postId": pid,
        "banners": [{
            "identity": {
                "version": "4.6", "phase": 2,
                "poolType": "character_event", "bannerName": "沧海萃珠",
                "fiveStarName": "真珠",
            },
            "data": {"featured": {"fiveStar": ["真珠"]}},
        }],
    })
    first = assemble_starrail(tmp_path, write=True)
    second = assemble_starrail(tmp_path, write=True)
    assert first["ready"] == second["ready"]
    assert len(first["rows"]) == len(second["rows"]) == 4
    assert any(r.get("manualData") and r["sourceKey"].startswith(pid + "-")
               for r in first["rows"])
    assert not (tmp_path / "data/announcements/starrail/zh-cn/miyoushe/posts").exists()
    # Check for deterministic regenerated candidates; no hidden original archive input.
    assert sorted((tmp_path / "data/derived/starrail/v1-candidates").glob("*.json"))
