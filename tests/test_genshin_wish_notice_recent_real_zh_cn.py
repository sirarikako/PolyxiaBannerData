"""以米游社官方公告列表归档选出的最近五个版本，离线测试每篇独立祈愿公告。

只读取 data/announcements/genshin/zh-cn/miyoushe/posts 内已保存的 28 篇正文。
不访问其他网站、不读取/修改 v1、不按其他公告补足版本或时间。
"""
import json
from pathlib import Path
import unittest

from scripts.transform.build_genshin_wish_notice_zh_cn import build

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "data/announcements/genshin/zh-cn/miyoushe/posts"

# 每条来自米游社「官方」公告列表；分组版本仅用于测试覆盖，不传给解析器。
# 注意：月之六列表中目前只有三篇符合筛选条件的独立祈愿公告。
BY_VERSION = {
    "7.1": (
        "78782593", "78782590", "78782589",
        "78299710", "78299709", "78299708",
    ),
    "7.0": (
        "77797178", "77797177", "77797176",
        "77322275", "77322273", "77322269",
    ),
    "月之八": (
        "76723989", "76723988", "76723985",
        "76308879", "76308876", "76308874", "76308871",
    ),
    "月之七": (
        "75781477", "75781476", "75781475",
        "75443624", "75443619", "75443617",
    ),
    "月之六": ("74412299", "74412295", "74412291"),
}
WEAPON = {
    "78782593", "78299708", "77797178", "77322275",
    "76723985", "76308874", "75781477", "75443624", "74412299",
}
SPECIAL = {"76308871"}


class RecentFiveVersionGenshinWishNotices(unittest.TestCase):
    def test_28_official_notices_from_five_versions(self):
        self.assertEqual([len(v) for v in BY_VERSION.values()], [6, 6, 7, 6, 3])
        seen = set()
        for version, ids in BY_VERSION.items():
            for pid in ids:
                with self.subTest(version=version, post_id=pid):
                    self.assertNotIn(pid, seen)
                    seen.add(pid)
                    source_file = POSTS / f"{pid}.json"
                    self.assertTrue(source_file.is_file(), f"缺少原始公告：{source_file}")
                    raw = json.loads(source_file.read_text(encoding="utf-8"))
                    post = raw["data"]["post"]["post"]
                    self.assertTrue(post["post_status"]["is_official"])
                    result = build(raw, post_id=pid,
                                   source_file=f"data/announcements/genshin/zh-cn/miyoushe/posts/{pid}.json")
                    self.assertEqual(result["source"]["postId"], pid)
                    self.assertEqual(result["locale"], "zh-CN")
                    self.assertIsNotNone(result["bannerName"])
                    self.assertEqual(result["version"], None)
                    self.assertEqual(result["phase"], None)
                    self.assertEqual(result["review"]["status"], "pending_manual_review")
                    self.assertFalse(any("itemId" in item for group in result["up"].values() for item in group))
                    if pid in WEAPON:
                        self.assertEqual(result["poolType"], "weapon_event")
                        self.assertEqual(len(result["up"]["fiveStarWeapons"]), 2)
                        self.assertEqual(len(result["up"]["fourStarWeapons"]), 5)
                        self.assertFalse(result["up"]["fiveStarCharacters"])
                    elif pid in SPECIAL:
                        self.assertEqual(result["poolType"], "chronicled")
                        self.assertEqual(result["variant"], "special_recollection")
                        self.assertEqual(result["up"]["fiveStarCharacters"], [])
                        self.assertGreaterEqual(len(result["selectable"]["fiveStarCharacters"]), 5)
                        self.assertGreaterEqual(len(result["selectable"]["fiveStarWeapons"]), 5)
                        self.assertGreaterEqual(len(result["selectable"]["fourStarCharacters"]), 10)
                        self.assertGreaterEqual(len(result["selectable"]["fourStarWeapons"]), 10)
                    else:
                        self.assertIn(result["poolType"], ("character_event", "character_event_2"))
                        self.assertEqual(len(result["up"]["fiveStarCharacters"]), 1)
                        self.assertEqual(len(result["up"]["fourStarCharacters"]), 3)
                        self.assertFalse(result["up"]["fiveStarWeapons"])
                    self.assertGreaterEqual(len(result["imageUrls"]), 1)
        self.assertEqual(len(seen), 28)


if __name__ == "__main__":
    unittest.main()
