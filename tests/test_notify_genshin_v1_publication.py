"""发布异常通知纯单元测试：验证 Issue 去重、变更评论与恢复自动关闭。"""
import json
from unittest.mock import patch

from scripts.release import notify_genshin_v1_publication as publication


def test_dry_run_reports_rejected_banner_without_github():
    problems = publication.sync("", "", {"rejected": [
        {"postId": "123", "error": "UP 冲突"}]},
        failed=False, run_url="", dry_run=True)
    assert problems["problems"] == 1
    assert problems["issues"] == {"公告 #123": ["UP 冲突"]}


def test_existing_issue_changed_posts_robot_comment():
    old = [{"title": "[原神 v1 发布复核] 公告 #123", "number": 77,
            "state": "OPEN", "body": "旧问题"}]
    with patch.object(publication, "gh", side_effect=[json.dumps(old), "", ""]) as gh:
        result = publication.sync("owner/repo", "owner", {"rejected": [
            {"postId": "123", "error": "新的冲突"}]},
            failed=False, run_url="https://example.com/action")
    assert result["changed"] == ["公告 #123"]
    assert gh.call_count == 3
    assert gh.call_args_list[-1].args[:3] == ("issue", "comment", "77")


def test_clean_publication_closes_only_managed_issues():
    old = [{"title": "[原神 v1 发布复核] 发布工作流", "number": 15,
            "state": "OPEN", "body": ""},
           {"title": "[临时测试] 无关问题", "number": 16,
            "state": "OPEN", "body": ""}]
    with patch.object(publication, "gh", side_effect=[json.dumps(old), "", ""]) as gh:
        result = publication.sync("owner/repo", "owner", {"rejected": []},
                                  failed=False, run_url="https://example.com")
    assert result["closed"] == ["[原神 v1 发布复核] 发布工作流"]
    assert gh.call_count == 3


def test_failed_publication_does_not_close_previous_issues():
    old = [{"title": "[原神 v1 发布复核] 公告 #123", "number": 15,
            "state": "OPEN", "body": ""}]
    with patch.object(publication, "gh", side_effect=[json.dumps(old),
                                                       "https://example.com/issues/16"]) as gh:
        result = publication.sync("owner/repo", "owner", {}, failed=True, run_url="")
    assert result["created"] == ["发布工作流"]
    assert result["closed"] == []
    assert gh.call_count == 2
