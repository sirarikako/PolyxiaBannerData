"""Offline regression for deleted, inaccessible and changed official article bodies.

GitHub repo is never modified. Source failures may cause manual review or pending,
but may not overwrite the last valid checkpoint, published v1 or parsed artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path
from shutil import copy2
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from scripts.collect import collect_genshin_notices_zh_cn as genshin
from scripts.collect import collect_starrail_notices_zh_cn as starrail
from scripts.collect.recover_manual_raw_zh_cn import (
    GENSHIN_RAW, STARRAIL_RAW, recover,
)
from scripts.transform.genshin_notice_manual_zh_cn import MANUAL_ROOT
from scripts.transform.starrail_notice_manual_zh_cn import load_real

ROOT = Path(__file__).resolve().parents[1]
G_STATE = Path("data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json")


def save(root, filename, obj):
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def manual_genshin(root, pid="99310001"):
    return save(root, MANUAL_ROOT / f"{pid}.json", {
        "format": "genshin-notice-manual-v1",
        "postId": pid,
        "data": {"bannerName": "虚构官方公告"},
    })


def state_genshin(root, pid="99310001"):
    state = genshin.fresh_state()
    state["manualReview"] = {
        pid: {"kind": "wish_notice", "title": "虚构官方公告",
              "reason": "需要人工补齐"}
    }
    return save(root, G_STATE, state)


def manual_starrail(root, pid="99320001"):
    schema = root / "schemas/manual/starrail-notice-manual.schema.json"
    schema.parent.mkdir(parents=True, exist_ok=True)
    copy2(ROOT / "schemas/manual/starrail-notice-manual.schema.json", schema)
    return save(root, f"manual/notices/starrail/zh-CN/miyoushe/{pid}.json", {
        "format": "starrail-notice-manual-v1",
        "postId": pid,
        "banners": [{
            "identity": {
                "version": "4.6", "phase": 2,
                "poolType": "character_event",
                "bannerName": "虚构活动跃迁",
            },
            "data": {"featured": {"fiveStar": ["虚构人物"]}},
        }],
    })


def archive_sentinel(root, game):
    """A valid existing candidate and published data must survive all failures."""
    v1 = save(root, f"public/v1/{game}.json", {
        "game": game, "banners": [{"id": f"{game}-existing"}],
    })
    candidate = save(root, f"data/derived/{game}/v1-candidates/existing.json", {
        "id": "known-good", "featured": ["existing"],
    })
    return (v1, v1.read_bytes()), (candidate, candidate.read_bytes())


def assert_sentinel_files_unchanged(pairs):
    for path, original in pairs:
        assert path.read_bytes() == original


@pytest.mark.parametrize("error", [
    HTTPError("https://www.miyoushe.com", 404, "deleted", {}, None),
    HTTPError("https://www.miyoushe.com", 410, "gone", {}, None),
    HTTPError("https://www.miyoushe.com", 403, "blocked", {}, None),
    HTTPError("https://www.miyoushe.com", 429, "rate limited", {}, None),
    URLError("timed out"),
])
@pytest.mark.parametrize("game", ["genshin", "starrail"])
def test_deleted_or_unreachable_manual_article_does_not_corrupt_saved_data(tmp_path, error, game):
    pid = "99310001" if game == "genshin" else "99320001"
    if game == "genshin":
        manual_genshin(tmp_path, pid)
        cp = state_genshin(tmp_path, pid)
        checkpoint_before = cp.read_bytes()
    else:
        manual_starrail(tmp_path, pid)
    records = archive_sentinel(tmp_path, game)
    called = []
    def network(_url, params):
        called.append(params)
        raise error

    with pytest.raises(RuntimeError, match="补抓失败"):
        recover(game, tmp_path, network)

    assert called == [{"post_id": pid, "gids": 2 if game == "genshin" else 6}]
    assert not (tmp_path / (GENSHIN_RAW if game == "genshin" else STARRAIL_RAW)
                / f"{pid}.json").exists()
    if game == "genshin":
        assert cp.read_bytes() == checkpoint_before
    else:
        with pytest.raises(ValueError, match="缺少已验证"):
            load_real(tmp_path)
    assert_sentinel_files_unchanged(records)


def test_genshin_missing_source_goes_to_manual_review_without_v1_write(tmp_path, monkeypatch):
    pid = "99310001"
    state = genshin.fresh_state()
    state["pending"][pid] = {
        "kind": "wish_notice", "title": "虚构祈愿公告",
        "attempts": 0,
    }
    cp = save(tmp_path, G_STATE, state)
    report = tmp_path / "data/derived/genshin/notice-discovery/test-report.json"
    baseline = archive_sentinel(tmp_path, "genshin")
    monkeypatch.setattr(genshin, "ROOT", tmp_path)
    monkeypatch.setattr(genshin, "RAW_DIR", tmp_path / GENSHIN_RAW)
    with patch.object(genshin, "fetch", side_effect=RuntimeError("HTTP Error 404: post deleted")) as web:
        result = genshin.run(checkpoint=cp, report_path=report, pending_only=True)

    saved = json.loads(cp.read_text(encoding="utf-8"))
    assert pid not in saved["pending"]
    assert pid in saved["manualReview"]
    assert pid not in saved["completed"]
    assert result["manualReviewCount"] == 1
    assert not (tmp_path / GENSHIN_RAW / f"{pid}.json").exists()
    assert_sentinel_files_unchanged(baseline)
    web.assert_called_once()


def test_starrail_missing_source_goes_to_manual_review_without_v1_write(tmp_path, monkeypatch):
    pid = "99320001"
    state = starrail.state_new()
    state["pending"][pid] = {
        "kind": "warp_notice", "title": "虚构活动跃迁",
        "attempts": 0,
    }
    cp = save(tmp_path, "checkpoint.json", state)
    report = tmp_path / "report.json"
    baseline = archive_sentinel(tmp_path, "starrail")
    monkeypatch.setattr(starrail, "STATE", cp)
    monkeypatch.setattr(starrail, "REPORT", report)
    monkeypatch.setattr(starrail, "RAW", tmp_path / STARRAIL_RAW)
    with patch("sys.argv", ["collect_starrail_notices_zh_cn.py", "--retry-only"]):
        with patch.object(starrail, "fetch",
                          side_effect=RuntimeError("HTTP Error 404: post deleted")) as web:
            starrail.main()

    saved = json.loads(cp.read_text(encoding="utf-8"))
    assert pid not in saved["pending"]
    assert pid in saved["manualReview"]
    assert pid not in saved["completed"]
    assert not (tmp_path / STARRAIL_RAW / f"{pid}.json").exists()
    assert_sentinel_files_unchanged(baseline)
    web.assert_called_once()


def test_existing_parsed_genshin_notice_works_when_original_article_is_gone(tmp_path, monkeypatch):
    """Reusing a previously validated parsed JSON must not re-fetch dead raw."""
    pid, title = "99310001", "虚构祈愿公告"
    monkeypatch.setattr(genshin, "ROOT", tmp_path)
    monkeypatch.setattr(genshin, "RAW_DIR", tmp_path / GENSHIN_RAW)
    output = save(tmp_path, f"data/derived/genshin/wish-notices/wish-notice_zh-CN_{pid}.json", {
        "format": "genshin-wish-notice-v1",
        "game": "genshin",
        "locale": "zh-CN",
        "source": {"postId": pid, "title": title, "rawFile": f"data/announcements/genshin/zh-cn/miyoushe/posts/{pid}.json"},
        "imageTimeRecognition": {"status": "recognized"},
    })
    with patch.object(genshin, "fetch", side_effect=AssertionError("must not re-fetch")) as web:
        result = genshin.extract(pid, {"kind": "wish_notice", "title": title})
    assert result == output.relative_to(tmp_path).as_posix()
    assert not (tmp_path / GENSHIN_RAW / f"{pid}.json").exists()
    web.assert_not_called()


def test_starrail_existing_parsed_notice_is_valid_source_after_raw_removed(tmp_path):
    pid = "99320001"
    manual_starrail(tmp_path, pid)
    save(tmp_path, f"data/derived/starrail/warp-notices/warp-notice_zh-CN_{pid}.json", {
        "format": "starrail-warp-notice-v1", "game": "starrail",
        "source": {"postId": pid, "title": "虚构活动跃迁",
                   "url": f"https://www.miyoushe.com/sr/article/{pid}"},
    })
    with patch("scripts.collect.recover_manual_raw_zh_cn.fetch",
               side_effect=AssertionError("verified parsed source should be reused")) as web:
        result = recover("starrail", tmp_path)
    assert result["requested"] == 0 and result["fetched"] == []
    assert len(load_real(tmp_path)) == 1
    assert not (tmp_path / STARRAIL_RAW / f"{pid}.json").exists()
    web.assert_not_called()
