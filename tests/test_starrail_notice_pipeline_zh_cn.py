"""星铁纯文本解析、候选校验与写入保护的初步单测。"""
import json
import pytest
from scripts.transform.starrail_notice_text_zh_cn import parse_range, post_from_raw
from scripts.transform.build_starrail_warp_notice_zh_cn import build as build_warp
from scripts.release.import_starrail_v1_zh_cn import import_v1

def raw(post_id, subject, content):
    return {"retcode": 0, "data": {"post": {"post": {
        "post_id": int(post_id), "game_id": 6, "subject": subject, "content": content}}}}

def test_range_last_minute():
    x = parse_range("2026/08/26 4.5版本更新后 - 2026/09/12 11:59")
    assert x["startAt"] == "2026-08-26T06:00:00+08:00"
    assert x["endAt"] == "2026-09-12T12:00:00+08:00"
    assert x["startDerived"]

def test_exact_boundary():
    x = parse_range("2026/09/28 06:00 - 2026/11/10 15:00")
    assert x["endAt"] == "2026-11-10T15:00:00+08:00"

def test_game_guard():
    x = raw("123", "4.5版本活动跃迁（其一）", "text")
    x["data"]["post"]["post"]["game_id"] = 2
    with pytest.raises(ValueError):
        post_from_raw(x, "123")

def test_unparsed_is_not_success():
    x = build_warp(raw("123", "4.5版本活动跃迁（其一）", "无法识别的正文"), "123")
    assert x["review"]["status"] == "needs_review"
    assert not x["banners"]

def test_preview_no_write(tmp_path):
    from pathlib import Path
    import shutil
    repo = Path(__file__).resolve().parents[1]
    v1 = tmp_path / "starrail.json"
    shutil.copyfile(repo / "public/v1/starrail.json", v1)
    before = v1.read_bytes()
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    result = import_v1(tmp_path, candidate_dir=candidates, v1_path=v1)
    assert result["appended"] == []
    assert v1.read_bytes() == before
