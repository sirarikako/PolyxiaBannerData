"""星铁 4.4 只给开始日期的正式公告回归，保留真实原文入口。"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import pytest

from scripts.transform.starrail_notice_text_zh_cn import parse_range
from scripts.transform.build_starrail_warp_notice_zh_cn import build
from scripts.transform.assemble_starrail_warp_candidates_zh_cn import assemble

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://www.miyoushe.com/sr/article/76661906"
MAINTENANCE = "2026-07-15T06:00:00+08:00"
UPDATE_SOURCE = "https://sr.mihoyo.com/news/165210?type=activity"


def test_date_only_is_parseable_but_no_time_is_invented():
    first = parse_range("2026/07/15 - 2026/08/25 15:00")
    second = parse_range("2026/07/15 - 2026/08/05 11:59")
    assert first["startAt"] is None
    assert second["startAt"] is None
    assert first["startDate"] == second["startDate"] == "2026-07-15"
    assert first["startCondition"] == second["startCondition"] == "date_only"
    assert first["endAt"] == "2026-08-25T15:00:00+08:00"
    assert second["endAt"] == "2026-08-05T12:00:00+08:00"


def test_invalid_or_ambiguous_short_dates_must_not_publish():
    assert parse_range("2026/07/15 - 2026/08/05") is None
    assert parse_range("2026/07/15 06:00 - 2026/07/14 15:00") is None


def test_real_44_8_pools_and_isolated_maintenance_match(tmp_path):
    raw_path = os.environ.get("STAR_RAIL_44_RAW")
    if not raw_path:
        pytest.skip("真实官方原文只在 Actions Artifact 回放时提供")
    raw = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    notice = build(raw, "76661906")
    assert notice["review"]["status"] == "parsed", notice["review"]
    assert len(notice["banners"]) == 8
    expected = json.loads((ROOT / "public/v1/starrail.json").read_text(encoding="utf-8"))
    actual = {b["bannerName"]: b for b in notice["banners"]}
    old = [b for b in expected["banners"] if b["id"] in {
        f"hsr-{i:06d}" for i in range(251, 259)}]
    assert len(old) == 8
    for b in old:
        current = actual[b["names"]["zh-CN"]]
        assert current["poolType"] == b["poolType"]
        for grade in ("fiveStar", "fourStar"):
            assert sorted(current["featured"][grade]) == sorted(
                item["names"]["zh-CN"] for item in b["featured"][grade])
        assert current["time"]["startDate"] == "2026-07-15"
        assert current["time"]["startAt"] is None
        region = next(r for r in b["regions"] if r["server"] == "cn_official")
        assert region["startAt"] == MAINTENANCE
        assert current["time"]["endAt"] == region["endAt"]

    for rel in ("public/v1/starrail.json",
                "public/item-mappings/starrail/zh-CN.json",
                "schemas/manual/starrail-missing-warp.schema.json",
                "schemas/manual/starrail-notice-manual.schema.json"):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    raw_output = tmp_path / "data/derived/starrail/warp-notices/warp-notice_zh-CN_76661906.json"
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    raw_output.write_text(json.dumps(notice, ensure_ascii=False), encoding="utf-8")
    version_output = tmp_path / "data/derived/starrail/version-updates/version-update_zh-CN_4.4.json"
    version_output.parent.mkdir(parents=True, exist_ok=True)
    version_output.write_text(json.dumps({
        "format": "starrail-version-update-v1", "game": "starrail",
        "locale": "zh-CN", "version": "4.4",
        "maintenance": {"startAt": MAINTENANCE},
        "source": {"url": UPDATE_SOURCE},
        "review": {"warnings": []},
    }, ensure_ascii=False), encoding="utf-8")
    result = assemble(tmp_path, write=False)
    assert result["count"] == 8, result
    assert result["ready"] == 0, result
    assert result["alreadyPublished"] == 8, result
    assert not [row for row in result["rows"] if row["publishedDifferences"]], result


def test_only_verified_maintenance_same_date_can_complete(tmp_path):
    # 这是产品级的隔离组装安全门：时间缺失的日期型原文，不得产生 ready 新池。
    from scripts.transform.assemble_starrail_warp_candidates_zh_cn import assemble
    for rel in ("public/v1/starrail.json",
                "public/item-mappings/starrail/zh-CN.json",
                "schemas/manual/starrail-missing-warp.schema.json",
                "schemas/manual/starrail-notice-manual.schema.json"):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    candidate = {
        "format": "starrail-warp-notice-v1", "game": "starrail", "locale": "zh-CN",
        "version": "4.4", "phase": 1,
        "source": {"postId": "76661906", "url": SOURCE},
        "banners": [{
            "bannerName": "拓星启明",
            "poolType": "character_event",
            "featured": {"fiveStar": ["姬子•启行"], "fourStar": ["貊泽", "寒鸦", "希露瓦"]},
            "time": parse_range("2026/07/15 - 2026/08/25 15:00"),
        }],
        "review": {"status": "parsed", "warnings": []},
    }
    p = tmp_path / "data/derived/starrail/warp-notices/warp-notice_zh-CN_76661906.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    no_maintenance = assemble(tmp_path, write=False)
    assert no_maintenance["ready"] == 0
    assert no_maintenance["rows"][0]["status"] == "needs_review"
    v = tmp_path / "data/derived/starrail/version-updates/version-update_zh-CN_4.4.json"
    v.parent.mkdir(parents=True, exist_ok=True)
    v.write_text(json.dumps({"format": "starrail-version-update-v1",
                            "game": "starrail", "version": "4.4",
                            "maintenance": {"startAt": "2026-07-16T06:00:00+08:00"}},
                           ensure_ascii=False), encoding="utf-8")
    different_date = assemble(tmp_path, write=False)
    assert different_date["ready"] == 0
    assert any("日期不一致" in str(x) for x in different_date["rows"][0]["issues"])
