"""原神 v1 导入器：追加、幂等、人工预设、指定 ID 修改及冲突保护。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.release.import_genshin_v1_zh_cn import import_v1


class ImportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.region = {"server": "cn_official", "startAt": "2026-10-13T18:00:00+08:00",
                       "endAt": "2026-11-03T15:00:00+08:00"}
        self.banner = {"id": "gi-000001", "gameVersion": "7.1", "phase": 2,
                       "category": "character", "poolType": "character_event",
                       "names": {"zh-CN": "原有祈愿"},
                       "gachaTypes": {"raw": ["301"], "uigf": ["301"]},
                       "featured": {"fiveStar": [{"itemId": None, "names": {"zh-CN": "角色甲"}, "type": "character"}],
                                    "fourStar": [{"itemId": None, "names": {"zh-CN": n}, "type": "character"} for n in ["甲", "乙", "丙"]]},
                       "regions": [deepcopy(self.region)],
                       "sources": [{"provider": "miyoushe", "url": "https://www.miyoushe.com/ys/article/100"}]}
        self.dataset = {"game": "genshin", "schemaVersion": 1,
                        "generatedAt": "2026-10-01T00:00:00+08:00", "banners": [deepcopy(self.banner)]}
        self.write("public/v1/genshin.json", self.dataset)
        self.manual = {"format": "genshin-v1-overrides-v2", "game": "genshin", "version": "7.1",
                       "locale": "zh-CN", "upcoming": [], "existing": []}
        self.save_manual()

    def save_manual(self):
        self.write(f"manual/genshin_{self.manual['version']}.json", self.manual)

    def write(self, path, value):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return p

    def candidate(self, *, pid="200", phase=2, pool_type="character_event_2", name="新卡池",
                  conditional=False):
        data = deepcopy(self.banner)
        data.pop("id")
        data["phase"] = phase
        data["poolType"] = pool_type
        data["names"] = {"zh-CN": name}
        data["gachaTypes"] = {"raw": ["400"], "uigf": ["301"]} if pool_type == "character_event_2" else self.banner["gachaTypes"]
        if conditional:
            data["regions"][0]["startAt"] = None
        data["sources"] = [{"provider": "miyoushe", "url": f"https://www.miyoushe.com/ys/article/{pid}"}]
        row = {"format": "genshin-v1-candidate-zh-CN-v1", "game": "genshin", "locale": "zh-CN",
               "status": "ready_candidate", "postId": pid, "version": "7.1", "phase": phase,
               "poolType": pool_type, "variant": None, "bannerName": name, "v1Draft": data,
               "provenance": {"noticePostId": pid},
               "timeEvidence": {"startCondition": "after_version_update" if conditional else None,
                                "versionMaintenanceStartAt": "2026-09-23T06:00:00+08:00"}}
        self.write(f"data/derived/genshin/v1-candidates/v1-candidate_zh-CN_{pid}.json", row)
        return row

    def run_import(self, write=False):
        # 校验器的完整 schema/跨池规则由既有 tests/test_v1.py 覆盖。
        with patch("scripts.release.import_genshin_v1_zh_cn.validate_publishable_dataset") as validate:
            result = import_v1(self.root, write=write)
            if result["changed"]:
                self.assertTrue(validate.called)
            return result

    def current(self):
        return json.loads((self.root / "public/v1/genshin.json").read_text())

    def test_dry_run_never_writes(self):
        self.candidate()
        before = (self.root / "public/v1/genshin.json").read_bytes()
        result = self.run_import()
        self.assertEqual([r["id"] for r in result["appended"]], ["gi-000002"])
        self.assertEqual((self.root / "public/v1/genshin.json").read_bytes(), before)

    def test_write_and_repeat_no_duplicate(self):
        self.candidate()
        self.assertEqual(len(self.run_import(True)["appended"]), 1)
        self.assertFalse(self.run_import(True)["changed"])
        self.assertEqual(len(self.current()["banners"]), 2)

    def test_existing_candidate_is_skipped_not_rewritten(self):
        self.candidate(pid="100", name="原有祈愿", pool_type="character_event")
        result = self.run_import(True)
        self.assertFalse(result["changed"])
        self.assertEqual(len(result["skippedExisting"]), 1)
        self.assertEqual(self.current()["banners"], self.dataset["banners"])

    def test_upcoming_matches_before_id(self):
        self.candidate()
        self.manual["upcoming"] = [{"match": {"version": "7.1", "phase": 2, "poolType": "character_event_2", "postId": "200"},
                                    "set": {"names": {"ja-JP": "新しい祈願"},
                                            "regions": [{"server": "asia", "startAt": "2026-10-13T19:00:00+08:00",
                                                         "endAt": "2026-11-03T16:00:00+08:00"}]},
                                    "itemIds": {"角色甲": "12345678"}}]
        self.save_manual()
        self.run_import(True)
        row = self.current()["banners"][-1]
        self.assertEqual(row["names"]["ja-JP"], "新しい祈願")
        self.assertEqual(row["featured"]["fiveStar"][0]["itemId"], "12345678")
        self.assertEqual(len(row["regions"]), 2)
        self.assertEqual(len(self.run_import(True)["unmatchedUpcoming"]), 0)
        manual = json.loads((self.root / "manual/genshin_7.1.json").read_text())
        self.assertEqual(manual["upcoming"][0]["status"], "completed")

    def test_existing_uses_only_id(self):
        self.manual["existing"] = [{"id": "gi-000001", "set": {"names": {"en-US": "Old Banner"}},
                                    "itemIds": {"角色甲": "12345"}}]
        self.save_manual()
        self.assertEqual(self.run_import(True)["updatedExistingIds"], ["gi-000001"])
        row = self.current()["banners"][0]
        self.assertEqual(row["names"]["zh-CN"], "原有祈愿")
        self.assertEqual(row["names"]["en-US"], "Old Banner")
        self.assertEqual(row["featured"]["fiveStar"][0]["itemId"], "12345")
        self.assertFalse(self.run_import(True)["changed"])
        manual = json.loads((self.root / "manual/genshin_7.1.json").read_text())
        self.assertEqual(manual["existing"][0]["status"], "completed")
        self.assertEqual(manual["existing"][0]["appliedId"], "gi-000001")

    def test_first_phase_uses_maintenance(self):
        self.candidate(phase=1, conditional=True)
        self.run_import(True)
        self.assertEqual(self.current()["banners"][-1]["regions"][0]["startAt"],
                         "2026-09-23T06:00:00+08:00")

    def test_ambiguous_overrides_fail_without_writing(self):
        self.candidate()
        match = {"version": "7.1", "phase": 2, "poolType": "character_event_2"}
        self.manual["upcoming"] = [
            {"match": match, "set": {"names": {"en-US": "A"}}},
            {"match": {**match, "postId": "200"}, "set": {"names": {"en-US": "B"}}},
        ]
        self.save_manual()
        before = self.current()
        with self.assertRaisesRegex(ValueError, "多个 upcoming"):
            self.run_import(True)
        self.assertEqual(self.current(), before)

    def test_future_override_is_kept(self):
        self.manual["version"] = "8.0"
        self.manual["upcoming"] = [{"match": {"version": "8.0", "phase": 1, "poolType": "character_event"},
                                    "set": {"names": {"en-US": "Future"}}}]
        self.save_manual()
        result = self.run_import(True)
        self.assertFalse(result["changed"])
        self.assertEqual(len(result["unmatchedUpcoming"]), 1)
        self.assertIsNone(json.loads((self.root / "manual/genshin_8.0.json").read_text())["upcoming"][0].get("status"))

    def test_isolation_skips_bad_candidate_without_consuming_id(self):
        self.candidate(pid="200", phase=2)
        self.candidate(pid="201", phase=3, pool_type="weapon_event", name="可发布池")
        self.manual["upcoming"] = [
            {"match": {"phase": 2, "poolType": "character_event_2", "postId": "200"},
             "itemIds": {"不存在的物品": "12345"}}
        ]
        self.save_manual()
        with patch("scripts.release.import_genshin_v1_zh_cn.validate_publishable_dataset"):
            result = import_v1(self.root, write=True, isolate_invalid=True)
        self.assertEqual([x["postId"] for x in result["rejected"]], ["200"])
        self.assertEqual([x["id"] for x in result["appended"]], ["gi-000002"])
        self.assertEqual(len(self.current()["banners"]), 2)
        self.assertEqual(self.manual["upcoming"][0].get("status"), None)

    def test_isolation_blocks_both_duplicate_pool_slot_candidates(self):
        self.candidate(pid="200")
        self.candidate(pid="201")
        with patch("scripts.release.import_genshin_v1_zh_cn.validate_publishable_dataset"):
            result = import_v1(self.root, write=True, isolate_invalid=True)
        self.assertEqual(result["appended"], [])
        self.assertEqual(len(result["rejected"]), 2)
        self.assertFalse(result["changed"])

    def test_isolation_skips_broken_manual_version_file(self):
        self.candidate()
        self.write("manual/genshin_9.9.json", {"bad": "json schema"})
        with patch("scripts.release.import_genshin_v1_zh_cn.validate_publishable_dataset"):
            result = import_v1(self.root, write=True, isolate_invalid=True)
        self.assertEqual(result["appended"][0]["id"], "gi-000002")
        self.assertEqual(result["rejected"][0]["file"], "genshin_9.9.json")

    def test_isolation_rejects_bad_existing_without_blocking_new(self):
        self.candidate()
        self.manual["existing"] = [
            {"id": "gi-999999", "set": {"names": {"en-US": "X"}}}
        ]
        self.save_manual()
        with patch("scripts.release.import_genshin_v1_zh_cn.validate_publishable_dataset"):
            result = import_v1(self.root, write=True, isolate_invalid=True)
        self.assertEqual(result["appended"][0]["id"], "gi-000002")
        self.assertEqual(result["rejected"][0]["id"], "gi-999999")

    def test_missing_id_refuses_write(self):
        self.manual["existing"] = [{"id": "gi-999999", "set": {"names": {"en-US": "X"}}}]
        self.save_manual()
        with self.assertRaisesRegex(ValueError, "找不到已发布内部 ID"):
            self.run_import(True)


if __name__ == "__main__":
    unittest.main()
