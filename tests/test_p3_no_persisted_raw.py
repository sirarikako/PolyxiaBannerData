"""P3 isolated checks for manual source recovery without persisted original notices.

All generated raw documents live in pytest tmp_path; no official API access.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from scripts.collect.recover_manual_raw_zh_cn import (
    recover, _required_genshin, _required_starrail, GENSHIN_RAW, STARRAIL_RAW,
)
from scripts.transform.genshin_notice_manual_zh_cn import (
    index_additional, MANUAL_ROOT,
)
from scripts.transform.starrail_notice_manual_zh_cn import (
    load_real, verified_structured_source,
)

REPO = Path(__file__).resolve().parents[1]
G_STATE = "data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json"
S_MANUAL = "manual/notices/starrail/zh-CN/miyoushe"


def save(root, name, payload):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def genshin_doc(pid="99310001", title="虚构祈愿公告", game=2):
    return {"retcode": 0, "data": {"post": {"post": {
        "post_id": int(pid), "game_id": game, "subject": title,
        "content": "<p>虚构测试正文</p>",
    }}}}


def starrail_doc(pid="99320001", game=6):
    return {"retcode": 0, "data": {"post": {"post": {
        "post_id": int(pid), "game_id": game, "subject": "虚构跃迁公告",
        "content": "<p>虚构测试正文</p>",
    }}}}


def gen_manual(root, pid):
    save(root, MANUAL_ROOT / f"{pid}.json", {
        "format": "genshin-notice-manual-v1",
        "postId": pid,
        "data": {"bannerName": "虚构祈愿公告"},
    })


def gen_state(root, pid, *, verified=False):
    row = {"kind": "wish_notice", "title": "虚构祈愿公告",
           "reason": "解析失败"}
    completed = ({pid: {"kind": "wish_notice", "title": "虚构祈愿公告",
                        "resolution": "manual_verified"}} if verified else {})
    save(root, G_STATE, {
        "format": "genshin-notice-discovery-v1", "game": "genshin",
        "locale": "zh-CN", "feeds": {}, "pending": {},
        "manualReview": {} if verified else {pid: row},
        "manualRecovered": {pid: row} if verified else {},
        "completed": completed,
    })


def star_manual(root, pid):
    (root / "schemas/manual").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "schemas/manual/starrail-notice-manual.schema.json",
                 root / "schemas/manual/starrail-notice-manual.schema.json")
    return save(root, f"{S_MANUAL}/{pid}.json", {
        "format": "starrail-notice-manual-v1", "postId": pid,
        "banners": [{"identity": {"version": "4.6", "phase": 2,
                                 "poolType": "character_event",
                                 "bannerName": "虚构测试跃迁"},
                     "data": {"featured": {"fiveStar": ["虚构角色"],
                                           "fourStar": ["甲", "乙", "丙"]}}}],
    })


def test_genshin_verified_recovered_is_rebuilt_without_raw(tmp_path):
    pid = "99310001"
    gen_state(tmp_path, pid, verified=True)
    gen_manual(tmp_path, pid)
    assert not (tmp_path / GENSHIN_RAW / f"{pid}.json").exists()
    rows = index_additional(tmp_path, [], "wish_notice")
    assert len(rows) == 1
    assert rows[0]["fallback"] is True
    assert rows[0]["data"]["source"]["postId"] == pid
    assert rows[0]["data"]["source"]["title"] == "虚构祈愿公告"
    assert rows[0]["evidenceFile"] == G_STATE
    assert "rawFile" not in rows[0]["data"]["source"]
    assert _required_genshin(tmp_path) == []


def test_genshin_unverified_manual_is_not_silent_or_official(tmp_path):
    pid = "99310001"
    gen_state(tmp_path, pid)
    gen_manual(tmp_path, pid)
    rows = index_additional(tmp_path, [], "wish_notice")
    assert len(rows) == 1
    assert "error" in rows[0] and "补抓" in rows[0]["error"]
    assert "data" not in rows[0]
    assert _required_genshin(tmp_path) == [(pid, "虚构祈愿公告")]


def test_genshin_temporary_recovery_checks_post_id_title_and_game(tmp_path):
    pid = "99310001"
    gen_state(tmp_path, pid)
    gen_manual(tmp_path, pid)
    calls = []
    def ok(_url, params):
        calls.append(params)
        return genshin_doc()
    report = recover("genshin", tmp_path, ok)
    assert report["fetched"] == [pid] and report["temporaryOnly"]
    assert calls[0] == {"post_id": pid, "gids": 2}
    assert (tmp_path / GENSHIN_RAW / f"{pid}.json").exists()
    assert index_additional(tmp_path, [], "wish_notice")[0]["fallback"]
    assert recover("genshin", tmp_path, lambda *_: pytest.fail("no second request"))["requested"] == 0


@pytest.mark.parametrize("wrong", [
    genshin_doc(pid="99310002"),
    genshin_doc(title="被篡改的公告标题"),
    genshin_doc(game=6),
    {"retcode": -1},
])
def test_genshin_recovery_rejects_unverified_source(tmp_path, wrong):
    pid = "99310001"
    gen_state(tmp_path, pid)
    gen_manual(tmp_path, pid)
    with pytest.raises(RuntimeError, match="补抓失败"):
        recover("genshin", tmp_path, lambda *_: wrong)
    assert not (tmp_path / GENSHIN_RAW / f"{pid}.json").exists()
    assert "error" in index_additional(tmp_path, [], "wish_notice")[0]


def test_starrail_derived_document_is_evidence_without_raw(tmp_path):
    pid = "99320001"
    star_manual(tmp_path, pid)
    save(tmp_path, f"data/derived/starrail/warp-notices/warp-notice_zh-CN_{pid}.json", {
        "format": "starrail-warp-notice-v1", "game": "starrail",
        "source": {"postId": pid, "title": "虚构跃迁公告",
                   "url": f"https://www.miyoushe.com/sr/article/{pid}"},
        "version": "4.6", "phase": 2, "banners": [],
    })
    assert verified_structured_source(tmp_path, pid)
    assert len(load_real(tmp_path)) == 1
    assert _required_starrail(tmp_path) == []
    assert not (tmp_path / STARRAIL_RAW / f"{pid}.json").exists()


def test_starrail_unverified_manual_requires_raw_or_recovery(tmp_path):
    pid = "99320001"
    star_manual(tmp_path, pid)
    with pytest.raises(ValueError, match="缺少已验证"):
        load_real(tmp_path)
    assert _required_starrail(tmp_path) == [(pid, None)]


def test_starrail_transient_fetch_can_unlock_manual_recovery(tmp_path):
    pid = "99320001"
    star_manual(tmp_path, pid)
    assert recover("starrail", tmp_path, lambda _url, params: starrail_doc())["fetched"] == [pid]
    assert len(load_real(tmp_path)) == 1
    assert (tmp_path / STARRAIL_RAW / f"{pid}.json").is_file()


@pytest.mark.parametrize("wrong", [starrail_doc(pid="99320002"),
                                   starrail_doc(game=2), {"retcode": -1}])
def test_starrail_wrong_source_fails_closed(tmp_path, wrong):
    pid = "99320001"
    star_manual(tmp_path, pid)
    with pytest.raises(RuntimeError, match="补抓失败"):
        recover("starrail", tmp_path, lambda *_: wrong)
    assert not (tmp_path / STARRAIL_RAW / f"{pid}.json").exists()
    with pytest.raises(ValueError, match="缺少已验证"):
        load_real(tmp_path)


def test_fetch_network_failure_does_not_clear_manual_checkpoint(tmp_path):
    pid = "99310001"
    gen_state(tmp_path, pid)
    gen_manual(tmp_path, pid)
    before = (tmp_path / G_STATE).read_bytes()
    def fails(*_args):
        raise TimeoutError("offline test")
    with pytest.raises(RuntimeError, match="TimeoutError"):
        recover("genshin", tmp_path, fails)
    assert (tmp_path / G_STATE).read_bytes() == before
    assert "error" in index_additional(tmp_path, [], "wish_notice")[0]


def test_manual_source_failure_keeps_public_issue_guard_closed(tmp_path, monkeypatch):
    from unittest.mock import patch
    from scripts.collect import notify_genshin_notice_problems as notify
    from scripts.release.report_genshin_v1_preview_zh_cn import generate

    save(tmp_path, G_STATE, {
        "format": "genshin-notice-discovery-v1",
        "game": "genshin", "locale": "zh-CN",
        "pending": {}, "manualReview": {}, "manualRecovered": {},
        "completed": {}, "feeds": {},
    })
    final = generate(tmp_path, stage_results={"manual_source": "1"})
    assert "workflow-manual_source" in final["notifications"]
    assert final["counts"]["blocking"] >= 1

    save(tmp_path, notify.FINAL, {"notifications": {}})
    for stage in ("COLLECT", "ASSEMBLE", "PREVIEW", "SANDBOX"):
        monkeypatch.setenv("GENSHIN_" + stage + "_CODE", "0")
    monkeypatch.setenv("GENSHIN_MANUAL_SOURCE_CODE", "1")
    with patch.object(notify, "gh") as github:
        out = notify.notify(tmp_path, "sirarikako/PolyxiaBannerData",
                            "sirarikako", "", dry_run=False)
    assert out["closed"] == []
    github.assert_not_called()


def test_source_recovery_does_not_embed_raw_in_public_report(tmp_path):
    pid = "99320001"
    star_manual(tmp_path, pid)
    report = recover("starrail", tmp_path, lambda *_: starrail_doc())
    assert report == {"game": "starrail", "requested": 1,
                      "fetched": [pid], "failed": [], "temporaryOnly": True}
    assert "虚构测试正文" not in json.dumps(report, ensure_ascii=False)
