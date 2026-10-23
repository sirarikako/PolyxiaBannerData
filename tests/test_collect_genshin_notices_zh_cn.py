"""原神简体中文米游社增量发现测试；不访问网络。"""
from unittest.mock import patch

import pytest

from scripts.collect import collect_genshin_notices_zh_cn as collector


def post(pid, title="无关文章"):
    return {"post_id": str(pid), "subject": title, "game_id": 2}


def test_title_routes():
    assert collector.classify("「往冥府的安魂歌」7.1版本更新说明") == "version_update"
    assert collector.classify("7.1版本活动祈愿预告第二期") == "wish_preview"
    assert collector.classify("「莓色香颂」祈愿：「明绚千韵·爱可菲(冰)」概率UP！") == "wish_notice"
    assert collector.classify("7.1版本更新维护预告") is None
    assert collector.classify("原神 版本更新相关问题说明") is None


def test_output_naming():
    assert collector.output_for("version_update", "「往冥府的安魂歌」7.1版本更新说明", "12").name == "version-update_zh-CN_7.1.json"
    assert collector.output_for("wish_preview", "7.1版本活动祈愿预告第二期", "12").name == "wish-preview_zh-CN_7.1-phase-2.json"
    assert collector.output_for("wish_notice", "「莓色香颂」祈愿：「爱可菲」概率UP！", "12").name == "wish-notice_zh-CN_12.json"


@pytest.mark.parametrize("feed", collector.FEEDS)
def test_list_page_uses_one_http_attempt(feed):
    """原神两类公告列表都只请求一次，正文的默认重试策略不受影响。"""
    body = {
        "data": {
            "list": [{"post": post("98")}],
            "is_last": True,
            "last_id": "",
        }
    }
    with patch.object(collector, "fetch", return_value=body) as fetch:
        posts, is_last, cursor = collector.list_page(feed, "old-cursor")
    assert [entry["post_id"] for entry in posts] == ["98"]
    assert is_last is True
    assert cursor == ""
    fetch.assert_called_once_with(
        collector.LIST_API,
        {"gids": 2, "type": feed, "page_size": 20,
         "last_id": "old-cursor", "client_type": 4},
        retries=1,
    )


def test_list_timeout_does_not_retry_or_sleep():
    """使用真实 HTTP 包装函数，离线模拟超时并验证没有隐藏的第二次请求。"""
    from urllib.error import URLError
    from scripts.collect import collect_miyoushe_announcements as http

    with patch.object(http, "urlopen", side_effect=URLError("timed out")) as urlopen, \
         patch.object(http.time, "sleep") as sleep:
        with pytest.raises(RuntimeError, match="URLError"):
            collector.list_page(1)
    urlopen.assert_called_once()
    sleep.assert_not_called()


def test_detail_http_retains_default_three_attempts(tmp_path):
    """确认单篇公告获取仍使用共享 HTTP 包装函数的默认 retries=3。"""
    from inspect import signature
    from scripts.collect import collect_miyoushe_announcements as http

    assert signature(http.fetch).parameters["retries"].default == 3
    with patch.object(collector, "RAW_DIR", tmp_path / "raw"), \
         patch.object(collector, "output_for", return_value=tmp_path / "candidate.json"), \
         patch.object(collector, "fetch",
                      side_effect=RuntimeError("remote API returned malformed data")) as fetch:
        with pytest.raises(collector.ManualReviewRequired, match="公告详情返回异常"):
            collector.extract(
                "98", {"kind": "wish_preview", "title": "7.1版本活动祈愿预告第二期"}
            )
    fetch.assert_called_once_with(collector.DETAIL_API, {"post_id": "98", "gids": 2})


def test_incremental_overlap_and_no_duplicate():
    pages = [
        ([post("99", "7.1版本活动祈愿预告第二期"), post("98"), post("5")], False, "next"),
        ([post("4"), post("3")], True, ""),
    ]
    with patch.object(collector, "list_page", side_effect=pages) as mock:
        posts, anchors, count = collector.discover(1, ["5", "4", "3"], 5)
    assert count == 2
    assert [p["post_id"] for p in posts] == ["99", "98"]
    assert anchors == ["99", "98", "5", "4", "3"]
    assert mock.call_count == 2


def test_anchor_not_found_does_not_advance():
    with patch.object(collector, "list_page", side_effect=[
        ([post("99"), post("98")], False, "next"),
        ([post("97")], False, "more"),
    ]):
        with pytest.raises(collector.DiscoveryError, match="进度未前进"):
            collector.discover(3, ["5", "4", "3"], 2)


def test_first_run_initializes_and_second_run_retries(tmp_path):
    checkpoint = tmp_path / "notice-discovery_zh-CN_checkpoint.json"
    report = tmp_path / "notice-discovery_zh-CN_report.json"
    first = ([post("5"), post("4"), post("3")], False, "next")
    with patch.object(collector, "list_page", return_value=first), patch.object(collector, "extract") as extract:
        result = collector.run(checkpoint=checkpoint, report_path=report)
    assert result["succeeded"] == []
    assert not extract.called
    state = collector.load_state(checkpoint)
    assert set(state["feeds"]) == {"1", "3"}

    def feed(feed, cursor=""):
        return ([post("10", "7.1版本活动祈愿预告第二期"),
                 post("5"), post("4"), post("3")], False, "next")

    with patch.object(collector, "list_page", side_effect=feed), patch.object(
        collector, "extract", side_effect=collector.TransientSourceError("暂时失败")
    ):
        result = collector.run(checkpoint=checkpoint, report_path=report)
    assert len(result["failed"]) == 1
    assert result["pendingCount"] == 1
    state = collector.load_state(checkpoint)
    assert state["pending"]["10"]["attempts"] == 1

    with patch.object(collector, "list_page", return_value=(
        [post("10"), post("5"), post("4"), post("3")], False, "next"
    )), patch.object(collector, "extract", return_value="test.json") as extract:
        result = collector.run(checkpoint=checkpoint, report_path=report)
    assert result["pendingCount"] == 0
    assert state["pending"]["10"]["kind"] == "wish_preview"
    assert extract.call_count == 1
    assert collector.load_state(checkpoint)["completed"]["10"]["outputFile"] == "test.json"


def test_existing_same_post_json_reused_without_overwriting(tmp_path):
    """真实回退测试回归：已有预告来源于账号归档，不应因详情原文路径不同而失败。"""
    import json

    outfile = tmp_path / "data/derived/genshin/wish-previews/wish-preview_zh-CN_7.1-phase-2.json"
    outfile.parent.mkdir(parents=True)
    title = "7.1版本活动祈愿预告第二期"
    obj = {
        "format": "genshin-wish-preview-v1",
        "game": "genshin", "locale": "zh-CN",
        "source": {"postId": "78879329", "title": title,
                   "rawFile": "data/announcements/genshin/zh-cn/miyoushe-account-75276539/posts/78879329.json"},
    }
    before = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    outfile.write_text(before, encoding="utf-8")
    raw = tmp_path / "posts/78879329.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"data": {"post": {"post": {
        "post_id": "78879329", "subject": title, "content": "可解析的测试正文",
    }}}}), encoding="utf-8")
    with patch.object(collector, "ROOT", tmp_path), patch.object(
        collector, "RAW_DIR", raw.parent
    ), patch.object(collector, "download_images", return_value=None), patch.object(
        collector, "output_for", return_value=outfile
    ), patch.object(collector, "fetch", side_effect=AssertionError("不应再请求原文")):
        actual = collector.extract("78879329", {"kind": "wish_preview", "title": title})
    assert actual.endswith("wish-preview_zh-CN_7.1-phase-2.json")
    assert outfile.read_text(encoding="utf-8") == before


def test_existing_conflicting_output_is_rejected(tmp_path):
    import json

    outfile = tmp_path / "same.json"
    outfile.write_text(json.dumps({
        "format": "genshin-wish-preview-v1", "game": "genshin",
        "locale": "zh-CN",
        "source": {"postId": "99999", "title": "7.1版本活动祈愿预告第二期"},
    }), encoding="utf-8")
    raw = tmp_path / "posts/78879329.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"data": {"post": {"post": {
        "post_id": "78879329",
        "subject": "7.1版本活动祈愿预告第二期",
        "content": "测试正文",
    }}}}), encoding="utf-8")
    with patch.object(collector, "ROOT", tmp_path), patch.object(
        collector, "RAW_DIR", raw.parent
    ), patch.object(collector, "download_images", return_value=None), patch.object(
        collector, "output_for", return_value=outfile
    ), patch.object(collector, "fetch", side_effect=AssertionError("不应发请求")):
        with pytest.raises(collector.ManualReviewRequired, match="禁止自动覆盖"):
            collector.extract("78879329", {
                "kind": "wish_preview", "title": "7.1版本活动祈愿预告第二期"
            })

def test_ocr_content_error_only_alert_once_no_automatic_retry(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    report = tmp_path / "report.json"
    first = collector.fresh_state()
    first["feeds"] = {
        "1": {"anchors": ["5", "4", "3"]},
        "3": {"anchors": ["5", "4", "3"]},
    }
    first["pending"]["99"] = {
        "kind": "wish_notice", "title": "「测试」祈愿：概率UP！",
        "feeds": [1], "discoveredAt": "2026-10-17T18:00:00+08:00",
        "attempts": 0, "lastError": None
    }
    collector.persist(first, checkpoint)
    feed = ([post("99"), post("5"), post("4"), post("3")], False, "next")
    with patch.object(collector, "list_page", return_value=feed), patch.object(
        collector, "extract", side_effect=collector.ManualReviewRequired("OCR unresolved")
    ) as extract:
        result = collector.run(checkpoint=checkpoint, report_path=report)
    assert extract.call_count == 1
    assert result["pendingCount"] == 0
    assert result["manualReviewCount"] == 1
    assert result["reviewNeeded"][0]["postId"] == "99"
    assert collector.load_state(checkpoint)["manualReview"]["99"]["reason"] == "OCR unresolved"
    with patch.object(collector, "list_page", return_value=feed), patch.object(
        collector, "extract", side_effect=AssertionError("不应再次执行 OCR")
    ) as extract:
        result = collector.run(checkpoint=checkpoint, report_path=report)
    assert extract.call_count == 0
    assert result["manualReviewCount"] == 1


def test_parser_error_enters_manual_review(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    report = tmp_path / "report.json"
    initial = collector.fresh_state()
    initial["feeds"] = {
        "1": {"anchors": ["5", "4", "3"]},
        "3": {"anchors": ["5", "4", "3"]},
    }
    initial["pending"]["88"] = {
        "kind": "wish_preview", "title": "7.1版本活动祈愿预告第二期",
        "feeds": [3], "discoveredAt": "2026-10-17T18:00:00+08:00",
        "attempts": 0, "lastError": None
    }
    collector.persist(initial, checkpoint)
    feed = ([post("88"), post("5"), post("4"), post("3")], False, "next")
    with patch.object(collector, "list_page", return_value=feed), patch.object(
        collector, "extract", side_effect=RuntimeError("解析脚本异常")
    ):
        result = collector.run(checkpoint=checkpoint, report_path=report)
    assert result["pendingCount"] == 0
    assert result["manualReviewCount"] == 1
    assert "解析脚本异常" in collector.load_state(checkpoint)["manualReview"]["88"]["reason"]


def test_legacy_checkpoint_auto_adds_manual_review_field(tmp_path):
    path = tmp_path / "checkpoint.json"
    checkpoint = collector.fresh_state()
    del checkpoint["manualReview"]
    import json
    path.write_text(json.dumps(checkpoint), encoding="utf-8")
    assert collector.load_state(path)["manualReview"] == {}


@pytest.mark.parametrize("status", ["unresolved", "conflict", "error"])
def test_cached_ocr_unusable_is_manual_review_without_redownload(tmp_path, status):
    import json

    outfile = tmp_path / "wish-notice_zh-CN_77.json"
    title = "「测试」祈愿：概率UP！"
    outfile.write_text(json.dumps({
        "format": "genshin-wish-notice-v1", "game": "genshin",
        "locale": "zh-CN", "source": {"postId": "77", "title": title},
        "imageTimeRecognition": {"status": status, "warnings": ["日期不可用"]},
    }, ensure_ascii=False), encoding="utf-8")
    with patch.object(collector, "ROOT", tmp_path), patch.object(
        collector, "output_for", return_value=outfile
    ), patch.object(collector, "download_images", side_effect=AssertionError("不得再次下载")):
        with pytest.raises(collector.ManualReviewRequired, match="日期不可用"):
            collector.extract("77", {"kind": "wish_notice", "title": title})


def test_pending_only_skips_discovery_and_retries_existing_entries(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    report = tmp_path / "report.json"
    initial = collector.fresh_state()
    initial["feeds"] = {
        "1": {"anchors": ["old"], "lastCheckedAt": "2026-10-17T18:17:00+08:00"},
        "3": {"anchors": ["old"], "lastCheckedAt": "2026-10-17T18:17:00+08:00"},
    }
    initial["pending"]["123"] = {
        "kind": "wish_preview", "title": "7.1版本活动祈愿预告第二期",
        "feeds": [3], "discoveredAt": "2026-10-17T18:17:00+08:00",
        "attempts": 1, "lastError": "暂时超时",
    }
    collector.persist(initial, checkpoint)
    with patch.object(collector, "list_page", side_effect=AssertionError("不得请求公告列表")), patch.object(
        collector, "discover", side_effect=AssertionError("不得推进 checkpoint 锚点")
    ), patch.object(collector, "extract", return_value="output.json") as extract:
        result = collector.run(checkpoint=checkpoint, report_path=report, pending_only=True)
    assert result["pendingCount"] == 0
    assert result["succeeded"] == ["123"]
    assert extract.call_count == 1
    state = collector.load_state(checkpoint)
    assert state["feeds"] == initial["feeds"]
    assert state["completed"]["123"]["outputFile"] == "output.json"


def test_pending_only_with_empty_queue_has_no_network_or_extraction(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    report = tmp_path / "report.json"
    collector.persist(collector.fresh_state(), checkpoint)
    with patch.object(collector, "list_page", side_effect=AssertionError("不得联网")), patch.object(
        collector, "extract", side_effect=AssertionError("不得解析")
    ):
        result = collector.run(checkpoint=checkpoint, report_path=report, pending_only=True)
    assert result["pendingCount"] == 0
    assert result["succeeded"] == []


def test_retry_only_does_not_scan_feeds(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    report = tmp_path / "report.json"
    state = collector.fresh_state()
    state["pending"]["99"] = {
        "kind": "wish_preview", "title": "7.1版本活动祈愿预告第二期",
        "feeds": [3], "attempts": 1,
        "lastError": "公告详情暂时获取失败：TimeoutError",
    }
    state["pending"]["98"] = {
        "kind": "wish_preview", "title": "7.1版本活动祈愿预告第一期",
        "feeds": [3], "attempts": 1,
        "lastError": "米游社要求验证或出现限流，已停止",
    }
    collector.persist(state, checkpoint)
    with patch.object(collector, "list_page", side_effect=AssertionError("不应请求列表")), patch.object(
        collector, "extract", return_value="test.json"
    ) as extract:
        result = collector.run(checkpoint=checkpoint, report_path=report, retry_only=True)
    assert result["succeeded"] == ["99"]
    assert result["pendingCount"] == 1
    assert extract.call_count == 1
    assert extract.call_args.args[0] == "99"
    assert collector.load_state(checkpoint)["pending"]["98"]["attempts"] == 1


def test_retry_check_only_transient_pending():
    from scripts.collect.genshin_notice_retry import is_retryable_pending
    assert is_retryable_pending({"lastError": None})
    assert is_retryable_pending({"lastError": "图片请求临时失败：timeout"})
    assert not is_retryable_pending({"lastError": "OCR unresolved"})
    assert not is_retryable_pending({"lastError": "米游社要求验证或出现限流，已停止"})
