"""ItemID Issue 负责人指定、去重、完整校验后自动关闭的无网络测试。"""
import json
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from scripts.release.notify_official_itemid_conflicts import (
    actions, notify, verified_complete, title_for, closure_comment,
)


def sample(*, blocked=None, missing=None):
    rows = [
        {"category": "genshin-characters", "source": "international"},
        {"category": "genshin-weapons", "source": "international"},
        {"category": "starrail-characters", "source": "cn"},
        {"category": "starrail-lightcones", "source": "cn"},
    ]
    if missing:
        rows = [row for row in rows if row["category"] != missing]
    return {"catalogs": rows, "blockedGames": blocked or {}}


def issue(game, number, assignees=None, *, body=None):
    original_id = "21006" if game == "starrail" else "10000022"
    return {
        "title": title_for(game), "number": number,
        "body": body if body is not None else
                f"官方与已有对照表同 ID 不同名称 {original_id}: '旧名' / '官方名'",
        "assignees": [{"login": name} for name in (assignees or [])],
    }


class NotifyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for game, mapping in (
            ("genshin", {"温迪": 10000022}),
            ("starrail", {"「我」的诞生": 21006}),
        ):
            path = self.root / "public/item-mappings" / game / "zh-CN.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        mock = patch("scripts.release.notify_official_itemid_conflicts.ROOT", self.root)
        mock.start()
        self.addCleanup(mock.stop)

    def test_new_issue_assigns_repository_owner(self):
        report = sample(blocked={"starrail": ["21006: 名称A / 名称B"]})
        cmds = actions(report, [], "sirarikako", "https://github.com/example/test/actions/runs/123")
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0][:3], ["gh", "issue", "create"])
        self.assertEqual(cmds[0][-2:], ["--assignee", "sirarikako"])
        self.assertIn("21006", cmds[0][cmds[0].index("--body") + 1])

    def test_existing_unassigned_issue_is_assigned_not_duplicated(self):
        report = sample(blocked={"starrail": ["21006"]})
        cmds = actions(report, [issue("starrail", 9)], "sirarikako", "https://example.com")
        self.assertEqual(cmds, [["gh", "issue", "edit", "9", "--add-assignee", "sirarikako"]])

    def test_existing_assignee_is_not_duplicated(self):
        cmds = actions(sample(blocked={"starrail": ["21006"]}),
                       [issue("starrail", 9, ["sirarikako"])], "sirarikako", "https://example.com")
        self.assertEqual(cmds, [])

    def test_resolved_issue_closes_with_comment_only_on_fully_validated_game(self):
        cmds = actions(sample(), [issue("starrail", 9, ["sirarikako"])],
                       "sirarikako", "https://example.com")
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0][:4], ["gh", "issue", "close", "9"])
        self.assertIn("--comment", cmds[0])
        self.assertIn("--reason", cmds[0])
        content = cmds[0][cmds[0].index("--comment") + 1]
        self.assertIn("原始冲突", content)
        self.assertIn("处理结论", content)
        self.assertIn("21006", content)
        self.assertIn("「我」的诞生", content)
        self.assertIn("public/item-mappings/starrail/zh-CN.json", content)

    def test_failure_missing_one_catalog_does_not_close(self):
        report = sample(missing="starrail-lightcones")
        self.assertFalse(verified_complete(report, "starrail"))
        self.assertEqual(actions(report, [issue("starrail", 9)], "sirarikako", "url"), [])

    def test_failed_catalog_does_not_close(self):
        report = sample()
        report["catalogs"][3]["source"] = "unavailable"
        self.assertFalse(verified_complete(report, "starrail"))
        self.assertEqual(actions(report, [issue("starrail", 9)], "sirarikako", "url"), [])

    def test_genshin_conflict_does_not_block_starrail_issue_auto_close(self):
        report = sample(blocked={"genshin": ["333: A / B"]})
        cmds = actions(report, [issue("starrail", 9, ["sirarikako"]), issue("genshin", 12)],
                       "sirarikako", "url")
        self.assertEqual(cmds[0][:4], ["gh", "issue", "edit", "12"])
        self.assertEqual(cmds[1][:4], ["gh", "issue", "close", "9"])

    def test_no_auto_close_when_same_game_still_conflicts(self):
        report = sample(blocked={"starrail": ["21006: A / B"]})
        cmds = actions(report, [issue("starrail", 9, ["sirarikako"])], "sirarikako", "url")
        self.assertEqual(cmds, [])

    def test_missing_original_conflict_id_prevents_close(self):
        issue_without_id = issue("starrail", 9, body="名称冲突但尚未确定编号")
        self.assertEqual(
            actions(sample(), [issue_without_id], "sirarikako", "url"), []
        )

    def test_unmapped_id_prevents_close(self):
        target = issue("starrail", 9, body="官方与已有对照表同 ID 不同名称 99999: '甲' / '乙'")
        self.assertEqual(
            actions(sample(), [target], "sirarikako", "url"), []
        )

    def test_multiple_original_conflicts_all_need_final_mapping(self):
        entry = issue("starrail", 9, body=(
            "官方与已有对照表同 ID 不同名称 21006: '甲' / '乙'\n"
            "官方与已有对照表同 ID 不同名称 21007: '丙' / '丁'"
        ))
        self.assertIsNone(closure_comment(entry, "starrail", "url", self.root))
        path = self.root / "public/item-mappings/starrail/zh-CN.json"
        path.write_text(json.dumps({"「我」的诞生": 21006, "新光锥": 21007},
                                   ensure_ascii=False), encoding="utf-8")
        resolved = closure_comment(entry, "starrail", "url", self.root)
        self.assertIn("21006", resolved)
        self.assertIn("21007", resolved)
        self.assertIn("新光锥", resolved)

    def test_duplicate_id_in_mapping_prevents_close(self):
        path = self.root / "public/item-mappings/starrail/zh-CN.json"
        path.write_text(json.dumps({"名称甲": 21006, "名称乙": 21006},
                                   ensure_ascii=False), encoding="utf-8")
        self.assertIsNone(closure_comment(issue("starrail", 9), "starrail", "url", self.root))

    def test_notify_calls_gh_as_expected(self):
        seen = []

        def fake(cmd, **kwargs):
            seen.append(cmd)
            if cmd[:3] == ["gh", "issue", "list"]:
                return CompletedProcess(cmd, 0, stdout=json.dumps([issue("starrail", 9)]))
            return CompletedProcess(cmd, 0)

        cmds = notify(sample(blocked={"starrail": ["21006"]}), owner="sirarikako",
                      repository="sirarikako/CastoriceWishBannerData", run_id="123", runner=fake)
        self.assertEqual(len(cmds), 1)
        self.assertEqual(seen[1], ["gh", "issue", "edit", "9", "--add-assignee", "sirarikako"])


if __name__ == "__main__":
    unittest.main()
