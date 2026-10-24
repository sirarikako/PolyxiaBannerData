"""官方 ItemID 补全器离线回归：国服优先、国际服回退与 ID 冲突边界。"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from scripts.release.refresh_official_item_mappings import (
    CatalogUnavailable, MappingConflict, get_category, merge_game, parse_catalog, refresh
)


class OfficialMappingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.write("genshin", {"旧武器": 5001, "旧角色": 10000020})
        self.write("starrail", {"旧光锥": 2001, "旧人物": 1001})
        # 单元测试不必伪造百条目录；完整性门槛由实际 Action 测试。
        self.lower = patch.dict("scripts.release.refresh_official_item_mappings.MIN_IDS", {
            "genshin-characters": 1, "genshin-weapons": 1,
            "starrail-characters": 1, "starrail-lightcones": 1,
        })
        self.lower.start()
        self.addCleanup(self.lower.stop)
        self.calls = []

    def write(self, game, value):
        path = self.root / "public/item-mappings" / game / "zh-CN.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def read(self, game):
        return json.loads((self.root / "public/item-mappings" / game / "zh-CN.json").read_text())

    def requester(self, url, **kwargs):
        self.calls.append(url)
        if "/event/platsimulator/config" in url:
            return {"all_avatar": [{"id": 10000020, "name": "旧角色"}, {"id": 10000021, "name": "新增角色"}],
                    "all_weapon": [{"id": 5001, "name": "旧武器"}, {"id": 5002, "name": "新增武器"}]}
        if "/event/rpgsimulator/config" in url:
            return {"avatar": [{"item_id": 1001, "item_name": "旧人物"},
                               {"item_id": 1002, "item_name": "新人物"}],
                    "equipment": [{"item_id": 2001, "item_name": "旧光锥"},
                                  {"item_id": 2002, "item_name": "新光锥"}]}
        raise AssertionError(f"不应访问其他接口: {url}")

    def test_four_primary_catalogs_and_write_only_mappings(self):
        before = [self.read(x) for x in ("genshin", "starrail")]
        dry = refresh(self.root, requester=self.requester)
        self.assertEqual(dry["updatedGames"], ["genshin", "starrail"])
        self.assertEqual([r["source"] for r in dry["catalogs"]], ["cn"] * 4)
        self.assertEqual([r["newEntries"] for r in dry["games"].values()], [2, 2])
        self.assertEqual([self.read(x) for x in ("genshin", "starrail")], before)
        applied = refresh(self.root, write=True, requester=self.requester)
        self.assertEqual(applied["mode"], "write")
        self.assertEqual(self.read("genshin")["新增武器"], 5002)
        self.assertEqual(self.read("starrail")["新人物"], 1002)
        self.assertFalse(refresh(self.root, write=True, requester=self.requester)["updatedGames"])

    def test_primary_failure_falls_back_to_international(self):
        def fallback(url, **kwargs):
            if "api-takumi.mihoyo.com" in url:
                raise CatalogUnavailable("国服不可用")
            if "simulatoros/config" in url:
                return {"all_avatar": [{"id": 10000021, "name": "新角色"}],
                        "all_weapon": [{"id": 5002, "name": "新增武器"}]}
            if "/avatar/list?" in url:
                return {"list": [{"item_id": 1002, "item_name": "新人物"}]}
            if "/equipment/list?" in url:
                return {"list": [{"item_id": 2002, "item_name": "新光锥"}]}
            raise AssertionError(url)
        report = refresh(self.root, requester=fallback)
        self.assertTrue(all(x["source"] == "international" for x in report["catalogs"]))
        self.assertTrue(all(x["fallbackReason"] for x in report["catalogs"]))

    def test_same_name_different_id_allowed_no_overwrite(self):
        self.write("genshin", {"同名角色": 10000030})
        merged, report = merge_game({"同名角色": 10000030},
                                    [("genshin-characters", [(10000030, "同名角色"),
                                                             (10000031, "同名角色"),
                                                             (10000032, "真正新增")])])
        self.assertEqual(merged["同名角色"], 10000030)
        self.assertEqual(merged["真正新增"], 10000032)
        self.assertEqual(report["allowedSameNameDifferentId"], 1)

    def test_new_same_name_different_id_still_safe(self):
        merged, report = merge_game({}, [("genshin-characters", [(31, "角色A"), (32, "角色A")])])
        self.assertEqual(merged, {"角色A": 31})
        self.assertEqual(report["allowedSameNameDifferentId"], 1)

    def test_same_id_two_names_in_official_data_is_error(self):
        with self.assertRaisesRegex(MappingConflict, "同 ID 不同名称"):
            parse_catalog([{"id": 123, "name": "角色甲"}, {"id": 123, "name": "角色乙"}],
                          "genshin-characters")

    def test_same_id_two_names_across_categories_is_error(self):
        with self.assertRaisesRegex(MappingConflict, "同 ID 不同名称"):
            merge_game({}, [("genshin-characters", [(123, "角色甲")]),
                            ("genshin-weapons", [(123, "角色乙")])])

    def test_same_id_different_name_vs_existing_is_error(self):
        with self.assertRaisesRegex(MappingConflict, "同 ID 不同名称"):
            merge_game({"旧角色": 101}, [("genshin-characters", [(101, "新角色")])])

    def test_existing_duplicate_id_different_names_is_error(self):
        with self.assertRaisesRegex(MappingConflict, "现有映射同 ID 不同名称"):
            merge_game({"甲": 1, "乙": 1}, [])

    def test_one_catalog_both_fail_other_games_still_checked(self):
        def broken(url, **kwargs):
            if "platsimulator/config" in url or "simulatoros/config" in url:
                raise CatalogUnavailable("网络失败")
            return self.requester(url, **kwargs)
        report = refresh(self.root, write=True, requester=broken)
        self.assertEqual([x["source"] for x in report["catalogs"]],
                         ["unavailable", "unavailable", "cn", "cn"])
        self.assertEqual(self.read("genshin"), {"旧武器": 5001, "旧角色": 10000020})
        self.assertEqual(self.read("starrail")["新光锥"], 2002)

    def test_failed_source_does_not_fallback_on_business_conflict(self):
        def conflicting(url, **kwargs):
            if "platsimulator/config" in url:
                return {"all_avatar": [{"id": 10000020, "name": "甲"},
                                       {"id": 10000020, "name": "乙"}],
                        "all_weapon": [{"id": 5001, "name": "旧武器"}]}
            return self.requester(url, **kwargs)
        report = refresh(self.root, write=True, requester=conflicting)
        self.assertIn("genshin", report["blockedGames"])
        self.assertNotIn("genshin", report["updatedGames"])
        self.assertEqual(self.read("genshin"), {"旧武器": 5001, "旧角色": 10000020})

    def test_starrail_conflict_does_not_block_genshin_updates(self):
        def fake(url, **kwargs):
            if "/event/rpgsimulator/config" in url:
                return {
                    "avatar": [{"item_id": 1001, "item_name": "旧人物"}],
                    "equipment": [{"item_id": 2001, "item_name": "另一个名称"}],
                }
            return self.requester(url, **kwargs)
        result = refresh(self.root, write=True, requester=fake)
        self.assertEqual(result["updatedGames"], ["genshin"])
        self.assertIn("starrail", result["blockedGames"])
        self.assertTrue(any("同 ID 不同名称" in x for x in result["blockedGames"]["starrail"]))
        self.assertEqual(self.read("genshin")["新增角色"], 10000021)
        self.assertEqual(self.read("starrail"), {"旧光锥": 2001, "旧人物": 1001})

    def test_dict_catalog_and_genshin_same_id_seven_element_forms(self):
        values = [{"id": 10000005, "name": "空"} for _ in range(7)]
        values.extend([{"id": 10000022, "name": "温迪"}])
        rows = parse_catalog(values, "genshin-characters")
        self.assertEqual(rows, [(10000005, "空"), (10000022, "温迪")])
        rows = parse_catalog({"123": {"name": "测试物品"}}, "genshin-weapons")
        self.assertEqual(rows, [(123, "测试物品")])


if __name__ == "__main__":
    unittest.main()
