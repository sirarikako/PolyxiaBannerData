"""使用真实归档公告与存档 JSON 核对最近六期原神版本更新。"""
import json
import unittest
from pathlib import Path

from scripts.transform.build_genshin_version_update_zh_cn import build, REPO_ROOT, output_filename

ARCHIVE = REPO_ROOT / "data/announcements/genshin/zh-cn/miyoushe/posts"
OUTPUT = REPO_ROOT / "data/derived/genshin/version-updates"
CASES = (
    ("7.1", "78335167", 2, 6),
    ("7.0", "77363392", 3, 12),
    ("月之八", "76345546", 1, 1),
    ("月之七", "75440954", 3, 2),
    ("月之六", "74446206", 1, 1),
    ("月之五", "73521381", 1, 1),
)

class RealVersionsTest(unittest.TestCase):
    def test_archives_match_saved_derived_results(self):
        for version, post_id, characters, weapons in CASES:
            with self.subTest(version=version):
                source = ARCHIVE / (post_id + ".json")
                record = OUTPUT / output_filename(version)
                self.assertTrue(source.is_file())
                self.assertTrue(record.is_file())
                actual = build(json.loads(source.read_text(encoding="utf-8")), post_id=post_id,
                               source_file=source.relative_to(REPO_ROOT).as_posix())
                expected = json.loads(record.read_text(encoding="utf-8"))
                self.assertEqual(actual, expected)
                self.assertEqual(len(actual["newCharacters"]), characters)
                self.assertEqual(len(actual["newWeapons"]), weapons)

    def test_7_0_weapon_sources_and_traveller(self):
        record = json.loads((OUTPUT / output_filename("7.0")).read_text(encoding="utf-8"))
        traveller = next(item for item in record["newCharacters"] if item["name"] == "旅行者")
        self.assertEqual(traveller["element"], "冰")
        self.assertIsNone(traveller["weaponType"])
        self.assertEqual({item["acquisition"] for item in record["newWeapons"]},
                         {"wish", "quest", "craft", "battle_pass"})
        self.assertNotIn("血红之证", {item["name"] for item in record["newWeapons"]})

    def test_lunar7_weapon_source(self):
        record = json.loads((OUTPUT / output_filename("月之七")).read_text(encoding="utf-8"))
        self.assertEqual([item["acquisition"] for item in record["newWeapons"]], ["wish", "wish"])
        self.assertEqual(record["review"]["warnings"], [])

if __name__ == "__main__":
    unittest.main()
