"""星铁 Webstatic 采集器离线回归：无真实接口依赖。"""
import json
import tempfile
import unittest
from pathlib import Path

from scripts.collect.collect_starrail_webstatic import BASE, STORE, collect

TS = "2026-11-15T12:00:00+08:00"
SAMPLE_GACHA_ID = "92d9ade0ec396252823b0ac911fd9e583ec162d0"
LIST_URL = "https://operation-webstatic.mihoyo.com/gacha_info/hkrpg/prod_gf_cn/gacha/list.json"
DETAIL_URL = f"https://operation-webstatic.mihoyo.com/gacha_info/hkrpg/prod_gf_cn/{SAMPLE_GACHA_ID}/zh-cn.json"
LIST = {"retcode": 0, "data": {"list": [
    {"gacha_id": "101", "gacha_type": 11,
     "begin_time": "2026-11-11 06:30:00", "end_time": "2026-12-22 15:00:00"},
    {"gacha_id": "202", "gacha_type": 22,
     "begin_time": "2026-11-11 06:30:00", "end_time": "2099-12-31 23:59:59"},
]}}
DETAIL = {
    "title": "角色活动跃迁", "gacha_type": 11,
    "items_up_star_5": [{"item_name": "测试角色", "item_id": -1,
                         "origin_item_id": 1507, "is_up": 0}],
    "items_up_star_4": [],
    "r5_prob_list": [{"item_name": "测试角色", "is_up": 1}],
}
COLLAB = {"title": "联动光锥活动跃迁", "gacha_type": 22,
          "items_up_star_5": [{"item_name": "测试光锥", "origin_item_id": 23059}],
          "items_up_star_4": None}


class StarRailWebstaticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.payloads = {"gacha/list.json": LIST, "101/zh-cn.json": DETAIL,
                         "202/zh-cn.json": COLLAB}

    def fetch(self, url):
        for key, obj in self.payloads.items():
            if url.endswith(key):
                return json.loads(json.dumps(obj))
        raise AssertionError(url)

    def run_collect(self, ts=TS):
        return collect(self.root, fetcher=self.fetch, base_url=BASE, observed_at=ts)

    def test_idempotent_and_original_featured_fields(self):
        first = self.run_collect()
        self.assertEqual((first["discovered"], first["detailsReady"]), (2, 2))
        self.assertEqual(self.run_collect()["detailsChanged"], 0)
        saved = json.loads((self.root / STORE / "details/101.json").read_text())
        self.assertEqual(saved["items_up_star_5"][0]["origin_item_id"], 1507)
        self.assertEqual(saved["items_up_star_5"][0]["is_up"], 0)
        checkpoint = json.loads((self.root / STORE / "checkpoint.json").read_text())
        self.assertEqual(checkpoint["banners"]["101"]["firstSeenAt"], TS)
        self.assertFalse((self.root / "public/v1/starrail.json").exists())

    def test_history_keeps_prior_bytes(self):
        self.run_collect()
        self.payloads["101/zh-cn.json"] = dict(DETAIL, title="修订后的卡池")
        later = self.run_collect("2026-11-16T12:00:00+08:00")
        self.assertEqual(later["detailsChanged"], 1)
        self.assertEqual(len(list((self.root / STORE / "history/details/101").glob("*.json"))), 1)

    def test_reject_corrupt_list_without_overwriting(self):
        self.run_collect()
        before = (self.root / STORE / "list.json").read_bytes()
        self.payloads["gacha/list.json"] = {"retcode": -1, "data": {"list": []}}
        with self.assertRaises(ValueError):
            self.run_collect()
        self.assertEqual((self.root / STORE / "list.json").read_bytes(), before)

    def test_partial_detail_failure_keeps_last_good(self):
        self.run_collect()
        before = (self.root / STORE / "details/101.json").read_bytes()
        self.payloads["101/zh-cn.json"] = {"retcode": -1}
        outcome = self.run_collect("2026-11-16T12:00:00+08:00")
        self.assertTrue(outcome["errors"])
        self.assertEqual((self.root / STORE / "details/101.json").read_bytes(), before)

    def test_supplied_official_url_pattern_and_40_character_gacha_id(self):
        self.assertEqual(BASE + "/gacha/list.json", LIST_URL)
        self.assertEqual(f"{BASE}/{SAMPLE_GACHA_ID}/zh-cn.json", DETAIL_URL)
        self.payloads["gacha/list.json"]["data"]["list"][0]["gacha_id"] = SAMPLE_GACHA_ID
        self.payloads[f"{SAMPLE_GACHA_ID}/zh-cn.json"] = self.payloads.pop("101/zh-cn.json")
        report = self.run_collect()
        self.assertEqual(report["detailsReady"], 2)
        self.assertTrue((self.root / STORE / "details" / f"{SAMPLE_GACHA_ID}.json").is_file())

    def test_eighteen_entry_index_without_fixed_production_count(self):
        self.payloads["gacha/list.json"] = {"retcode": 0, "data": {"list": []}}
        self.payloads = {"gacha/list.json": self.payloads["gacha/list.json"]}
        for i in range(18):
            gid = f"{i + 1:040x}"
            kind = (1, 2, 11, 12, 21, 22)[i % 6]
            self.payloads["gacha/list.json"]["data"]["list"].append({
                "gacha_id": gid, "gacha_type": kind,
                "begin_time": "2026-11-11 06:30:00", "end_time": "2026-12-22 15:00:00",
            })
            data = {"title": f"测试卡池{i + 1}", "gacha_type": kind}
            if kind not in (1, 2):
                data["items_up_star_5"] = [{"item_name": "测试角色"}]
                data["items_up_star_4"] = None if kind in (21, 22) else []
            self.payloads[f"{gid}/zh-cn.json"] = data
        report = self.run_collect()
        self.assertEqual(report["totalListed"], 18)
        self.assertEqual(report["detailsReady"], 18)
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(list((self.root / STORE / "details").glob("*.json"))), 18)

    def test_collab_null_four_star_is_ready_without_deriving_fake_up(self):
        result = self.run_collect()
        self.assertEqual(result["errors"], [])
        checkpoint = json.loads((self.root / STORE / "checkpoint.json").read_text())
        self.assertEqual(checkpoint["banners"]["202"]["detailReadyAt"], TS)
        detail = json.loads((self.root / STORE / "details/202.json").read_text())
        self.assertIsNone(detail["items_up_star_4"])

    def test_reject_untrusted_base(self):
        with self.assertRaises(ValueError):
            collect(self.root, fetcher=self.fetch, base_url="https://example.com/path", observed_at=TS)


if __name__ == "__main__":
    unittest.main()
