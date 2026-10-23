"""星铁采集边界及 Issue 去重：全部使用隔离目录、模拟接口，不联网。"""
import json
from pathlib import Path

from scripts.collect import collect_starrail_notices_zh_cn as collector
from scripts.collect import notify_starrail_notice_problems as notifier

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def test_discovery_first_run_only_establishes_latest_page(monkeypatch):
    def page(cursor):
        assert cursor == ""
        return [{"post_id": i} for i in range(1, 21)], False, "next"
    monkeypatch.setattr(collector, "page", page)
    recent, anchors = collector.discover([], 15)
    assert recent == []
    assert anchors == [str(x) for x in range(1, 21)]

def test_discovery_requires_three_known_overlap(monkeypatch):
    def page(cursor):
        if not cursor:
            return [{"post_id": x} for x in ("102", "101", "100", "99", "98")], False, "p2"
        return [{"post_id": x} for x in ("97", "96", "95")], True, ""
    monkeypatch.setattr(collector, "page", page)
    fresh, anchors = collector.discover(["100", "99", "98", "97"], 4)
    assert [str(x["post_id"]) for x in fresh] == ["102", "101"]
    assert anchors[:4] == ["102", "101", "100", "99"]

def test_discovery_no_anchor_overlap_does_not_advance(monkeypatch):
    monkeypatch.setattr(collector, "page", lambda cursor:
                        ([{"post_id": "200"}], False, "next" if not cursor else "last"))
    import pytest
    with pytest.raises(ValueError):
        collector.discover(["100", "99", "98"], 2)

def test_new_versions_and_collab_discovered_without_cloud_client():
    assert collector.kind("4.6版本更新说明") == "version_update"
    assert collector.kind("《云•星穹铁道》4.5版本更新说明") is None
    assert collector.kind("4.6版本活动跃迁（其一）") == "warp_notice"
    assert collector.kind("Fate[UBW] 联动跃迁说明") == "collab_notice"
    assert collector.kind("「联动跃迁」说明") == "collab_notice"

def test_stable_issue_fingerprint_does_not_change_on_retry_count(tmp_path):
    checkpoint = {"pending": {"456": {"attempts": 3, "lastError": "Timeout 1"}},
                  "manualReview": {}}
    write(tmp_path / notifier.STATE, checkpoint)
    write(tmp_path / notifier.READINESS, {"rows": [], "unparsedNotices": []})
    first = notifier.problems(tmp_path)
    checkpoint["pending"]["456"]["attempts"] = 8
    checkpoint["pending"]["456"]["lastError"] = "Timeout 8"
    write(tmp_path / notifier.STATE, checkpoint)
    second = notifier.problems(tmp_path)
    assert first == second
    assert "pending-456" in first
    assert notifier.fingerprint(first["pending-456"]) == notifier.fingerprint(second["pending-456"])

def test_manual_recovered_notice_suppresses_old_issue(tmp_path):
    write(tmp_path / notifier.STATE, {"manualReview": {"123": {"error": "parse error"}}})
    write(tmp_path / notifier.READINESS, {"rows": [
        {"sourceKey": "123-abcdef123456", "status": "already_published",
         "manualRecovery": True, "publishedDifferences": []}],
        "unparsedNotices": [
            {"postId": "123", "type": "waiting_identity", "issues": []}]})
    assert notifier.problems(tmp_path) == {}

def test_published_discrepancy_surfaces_for_review(tmp_path):
    write(tmp_path / notifier.STATE, {"manualReview": {}, "pending": {}})
    write(tmp_path / notifier.READINESS, {"rows": [
        {"sourceKey": "567-abcdef123456", "status": "already_published",
         "publishedDifferences": ["regions.cn_official.endAt"], "existingId": "hsr-000276"}],
        "unparsedNotices": []})
    result = notifier.problems(tmp_path)
    assert "published-567-abcdef123456" in result

def test_missing_checkpoint_and_report_cannot_close_issues(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        notifier.problems(tmp_path)
