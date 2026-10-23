"""离线测试公告异常通知，不访问 GitHub，也不修改真实 v1。"""
import json
from unittest.mock import patch

from scripts.collect import notify_genshin_notice_problems as notifier


def save(root, rel, obj):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_missing_announcements_are_normal_waiting(tmp_path):
    save(tmp_path, notifier.CHECKPOINT, {"pending": {}, "manualReview": {}})
    save(tmp_path, notifier.READINESS, {"notices": [
        {"postId": "777", "status": "waiting", "issues": ["unmatched_end_time"]},
        {"postId": "778", "status": "waiting", "issues": ["waiting_version_update"]},
    ], "sourceErrors": []})
    assert notifier.notices_to_review(tmp_path) == {}
    assert notifier.notify(tmp_path, "", "", "", dry_run=True)["total"] == 0


def test_ocr_and_script_failure_create_same_notice_problem(tmp_path):
    save(tmp_path, notifier.CHECKPOINT, {"manualReview": {
        "12345": {"kind": "wish_notice", "reason": "OCR unresolved", "outputFile": "data/derived/genshin/wish-notices/wish-notice_zh-CN_12345.json"},
        "54321": {"kind": "wish_preview", "reason": "脚本错误: 模块退出"},
    }})
    save(tmp_path, notifier.READINESS, {"notices": [{
        "postId": "12345", "status": "conflict", "issues": ["ocr_notice_end_conflict"],
        "noticeFile": "data/derived/genshin/wish-notices/wish-notice_zh-CN_12345.json"
    }], "sourceErrors": []})
    found = notifier.notices_to_review(tmp_path)
    assert len(found) == 2
    assert len(found["12345"]["reasons"]) == 2
    dry = notifier.notify(tmp_path, "", "", "", dry_run=True)
    assert dry["total"] == 2
    assert "miyoushe.com/ys/article/12345" in dry["candidates"][0]["body"]


def test_problem_issue_is_deduplicated_even_when_closed(tmp_path):
    save(tmp_path, notifier.CHECKPOINT, {"manualReview": {"12345": {
        "kind": "wish_notice", "reason": "OCR conflict"
    }}})
    existing_body = notifier.issue_body("12345", {"reasons": ["单篇采集/解析异常：OCR conflict"], "files": []}, "")
    with patch.object(notifier, "gh", return_value=json.dumps([
        {"number": 12, "title": notifier.issue_title("12345"),
         "state": "OPEN", "body": existing_body}
    ])) as gh:
        result = notifier.notify(tmp_path, "sirarikako/CastoriceWishBannerData",
                                 "sirarikako", "", dry_run=False)
    assert result["created"] == []
    assert result["existing"][0]["issue"] == 12
    gh.assert_called_once()


def test_new_issue_contains_reason_and_assignee(tmp_path):
    save(tmp_path, notifier.CHECKPOINT, {"manualReview": {"12345": {
        "kind": "wish_notice", "reason": "OCR error"
    }}})
    with patch.object(notifier, "gh", side_effect=["[]", "https://github.com/example/issues/55"]) as gh:
        result = notifier.notify(tmp_path, "sirarikako/CastoriceWishBannerData",
                                 "sirarikako", "https://github.com/example/actions/runs/1",
                                 dry_run=False)
    assert len(result["created"]) == 1
    assert gh.call_count == 2
    assert "--assignee" in gh.call_args.args
    assert "sirarikako" in gh.call_args.args


def test_legacy_unresolved_notice_notified(tmp_path):
    notice_path = "data/derived/genshin/wish-notices/wish-notice_zh-CN_99999.json"
    save(tmp_path, notifier.CHECKPOINT, {"manualReview": {}})
    save(tmp_path, notice_path, {"imageTimeRecognition": {
        "status": "unresolved", "warnings": ["无法确定结束时间"]
    }})
    save(tmp_path, notifier.READINESS, {"notices": [{
        "postId": "99999", "noticeFile": notice_path,
        "status": "waiting", "issues": ["waiting_ocr_end_time"],
    }], "sourceErrors": []})
    assert "99999" in notifier.notices_to_review(tmp_path)


def test_pipeline_crash_alerts_without_a_post_id(tmp_path, monkeypatch):
    save(tmp_path, notifier.CHECKPOINT, {"pending": {}, "manualReview": {}})
    monkeypatch.setenv("GENSHIN_ASSEMBLE_CODE", "1")
    problems = notifier.notices_to_review(tmp_path)
    assert "workflow-assemble" in problems
    assert "流程异常" in notifier.issue_title("workflow-assemble")


def test_transient_pending_does_not_raise_pipeline_issue(tmp_path, monkeypatch):
    save(tmp_path, notifier.CHECKPOINT, {"pending": {
        "9999": {"lastError": "network timeout"}
    }, "manualReview": {}})
    monkeypatch.setenv("GENSHIN_COLLECT_CODE", "1")
    assert notifier.notices_to_review(tmp_path) == {}


def test_issue_change_posts_comment_but_stable_issue_does_not(tmp_path):
    save(tmp_path, notifier.CHECKPOINT, {"manualReview": {
        "12345": {"kind": "wish_notice", "reason": "OCR conflict"}
    }})
    existing = [{"number": 12, "title": notifier.issue_title("12345"),
                 "state": "OPEN", "body": "旧的 Issue 正文"}]
    with patch.object(notifier, "gh", side_effect=[json.dumps(existing), "", ""]) as gh:
        result = notifier.notify(tmp_path, "sirarikako/CastoriceWishBannerData",
                                 "sirarikako", "", dry_run=False)
    assert result["updated"] == [12]
    assert gh.call_count == 3
    assert gh.call_args_list[-1].args[:3] == ("issue", "comment", "12")


def test_resolved_issue_is_closed_only_after_healthy_final_review(tmp_path, monkeypatch):
    save(tmp_path, notifier.FINAL, {"notifications": {}})
    for stage in ("COLLECT", "ASSEMBLE", "PREVIEW", "SANDBOX"):
        monkeypatch.setenv(f"GENSHIN_{stage}_CODE", "0")
    old = [{"number": 12, "title": notifier.issue_title("12345"),
            "state": "OPEN", "body": "旧问题"}]
    with patch.object(notifier, "gh", side_effect=[json.dumps(old), "", ""]) as gh:
        result = notifier.notify(tmp_path, "sirarikako/CastoriceWishBannerData",
                                 "sirarikako", "", dry_run=False)
    assert result["closed"] == [12]
    assert gh.call_count == 3


def test_unhealthy_final_report_does_not_close_issue(tmp_path, monkeypatch):
    save(tmp_path, notifier.FINAL, {"notifications": {}})
    monkeypatch.setenv("GENSHIN_ASSEMBLE_CODE", "1")
    old = [{"number": 12, "title": notifier.issue_title("12345"),
            "state": "OPEN", "body": "旧问题"}]
    with patch.object(notifier, "gh", return_value=json.dumps(old)) as gh:
        result = notifier.notify(tmp_path, "sirarikako/CastoriceWishBannerData",
                                 "sirarikako", "", dry_run=False)
    assert result["closed"] == []
    gh.assert_not_called()
