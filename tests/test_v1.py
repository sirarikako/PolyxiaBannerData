"""Schema and semantic regression for fictional v1 fixtures."""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 模块使用 scripts 包导入
from scripts.release.validate_v1 import load, validate_dataset, validate_schema, validate_publishable_dataset, validate_manifest


class V1ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gi = load(ROOT / "tests/fixtures/v1/genshin.json")
        cls.hsr = load(ROOT / "tests/fixtures/v1/starrail.json")

    def test_fixtures(self):
        self.assertEqual(validate_dataset(self.gi), 1)
        self.assertEqual(validate_dataset(self.hsr), 1)

    def test_banner_id_uses_six_digit_suffix(self):
        for invalid_id in ("gi-302", "gi-303", "gi-abc", "hsr-000302"):
            with self.subTest(invalid_id=invalid_id):
                data = copy.deepcopy(self.gi)
                data["banners"][0]["id"] = invalid_id
                with self.assertRaises(ValueError):
                    validate_dataset(data)
        for valid_id in ("gi-000302", "gi-100001", "gi-100002"):
            with self.subTest(valid_id=valid_id):
                data = copy.deepcopy(self.gi)
                data["banners"][0]["id"] = valid_id
                self.assertEqual(validate_dataset(data), 1)

    def test_real_public_manifest(self):
        folder = ROOT / "public/v1"
        manifest = load(folder / "manifest.json")
        self.assertTrue(validate_manifest(manifest, folder))
        for game, info in manifest["games"].items():
            self.assertEqual(len(load(folder / info["path"])["banners"]), info["bannerCount"])

    def test_published_starrail_id_ranges_are_contiguous(self):
        banners = load(ROOT / "public/v1/starrail.json")["banners"]
        regular = sorted(
            (b for b in banners if b["id"].startswith("hsr-0")),
            key=lambda b: b["id"],
        )
        # 发布后普通池会从 276 连续增长；不能把首次上线快照 286 写死。
        # 保留历史基线下界，检查所有 ID 不重复、两段编号连续且无孤儿池。
        self.assertGreaterEqual(len(regular), 276)
        self.assertEqual(
            [b["id"] for b in regular],
            [f"hsr-{i:06d}" for i in range(1, len(regular) + 1)],
        )
        self.assertTrue(all(b["poolType"] not in (
            "collab_character", "collab_light_cone", "standard", "beginner",
        ) for b in regular))
        special = {b["id"]: b for b in banners if b["id"].startswith("hsr-1")}
        self.assertGreaterEqual(len(special), 10)
        self.assertEqual(
            set(special),
            {f"hsr-{i:06d}" for i in range(100001, 100001 + len(special))},
        )
        self.assertEqual(len(banners), len(regular) + len(special))
        self.assertEqual(special["hsr-100001"]["poolType"], "standard")
        self.assertEqual(special["hsr-100002"]["poolType"], "beginner")
        expected_gacha_ids = ["5001", "5002", "6001", "6002",
                              "5003", "5004", "6003", "6004"]
        for num, gacha_id in enumerate(expected_gacha_ids, 100003):
            banner = special[f"hsr-{num:06d}"]
            self.assertEqual(banner["gachaIds"], [gacha_id])
            self.assertIn(banner["poolType"], ("collab_character", "collab_light_cone"))
            self.assertTrue(any(r["endAt"] is None for r in banner["regions"]))

    def test_phase_one_supports_half_and_full_duration(self):
        for sample in (self.gi, self.hsr):
            with self.subTest(game=sample["game"]):
                data = copy.deepcopy(sample)
                banner = data["banners"][0]
                banner["gameVersion"] = "3.7"
                banner["phase"] = 1
                # Both shorter and longer valid intervals use the same start-phase value.
                self.assertEqual(validate_dataset(data), 1)
                for region in banner["regions"]:
                    region["endAt"] = "2030-03-20T15:00:00+08:00"
                self.assertEqual(validate_dataset(data), 1)

    def test_all_nine_phases_accepted_for_both_games(self):
        for sample in (self.gi, self.hsr):
            for phase in range(1, 10):
                with self.subTest(game=sample["game"], phase=phase):
                    data = copy.deepcopy(sample)
                    data["banners"][0]["phase"] = phase
                    self.assertEqual(validate_dataset(data), 1)

    def test_limited_pool_unknown_phase_allowed(self):
        data = copy.deepcopy(self.gi)
        data["banners"][0]["phase"] = None
        self.assertEqual(validate_dataset(data), 1)

    def test_invalid_phase_values_rejected(self):
        for value in ("full", "permanent", "full_version", "1", "3", 0, 10, -1, 2.5, True):
            with self.subTest(phase=value):
                data = copy.deepcopy(self.gi)
                data["banners"][0]["phase"] = value
                with self.assertRaises(ValueError):
                    validate_dataset(data)

    def test_permanent_pools_require_null_phase(self):
        for raw, kind in (("1", "standard"), ("2", "beginner")):
            for phase in (1, 2, 3, 9):
                with self.subTest(pool=kind, phase=phase):
                    data = copy.deepcopy(self.hsr)
                    banner = data["banners"][0]
                    banner["gachaTypes"] = {"raw": [raw], "uigf": [raw]}
                    banner["poolType"] = kind
                    banner["category"] = kind
                    banner["gameVersion"] = "3.7"
                    banner["phase"] = phase
                    for region in banner["regions"]:
                        region["endAt"] = None
                    with self.assertRaisesRegex(ValueError, "permanent pools require phase null"):
                        validate_dataset(data)

    def test_permanent_pool_null_phase_allowed(self):
        data = copy.deepcopy(self.hsr)
        banner = data["banners"][0]
        banner["gachaTypes"] = {"raw": ["1"], "uigf": ["1"]}
        banner["poolType"] = "standard"
        banner["category"] = "standard"
        banner["gameVersion"] = None
        banner["phase"] = None
        for region in banner["regions"]:
            region["endAt"] = None
        self.assertEqual(validate_dataset(data), 1)

    def test_server_duplicate_rejected(self):
        broken = copy.deepcopy(self.gi)
        broken["banners"][0]["regions"][1]["server"] = "cn_official"
        with self.assertRaisesRegex(ValueError, "duplicate region"):
            validate_dataset(broken)

    def test_wrong_uigf_400_rejected(self):
        broken = copy.deepcopy(self.gi)
        broken["banners"][0]["gachaTypes"]["uigf"] = ["400"]
        with self.assertRaises(ValueError):
            validate_dataset(broken)

    def test_invalid_time_or_offset(self):
        for bad in ("2030-01-01T18:00:00Z", "2030-01-01T18:00:00+09:00"):
            broken = copy.deepcopy(self.gi)
            broken["banners"][0]["regions"][0]["startAt"] = bad
            with self.assertRaises(ValueError):
                validate_dataset(broken)

    def test_reversed_range(self):
        broken = copy.deepcopy(self.hsr)
        broken["banners"][0]["regions"][0]["endAt"] = "2020-01-01T00:00:00+08:00"
        with self.assertRaisesRegex(ValueError, "time range"):
            validate_dataset(broken)

    def test_unknown_fourstar_null_vs_empty(self):
        broken = copy.deepcopy(self.gi)
        broken["banners"][0]["featured"]["fourStar"] = []
        validate_dataset(broken)
        broken["banners"][0]["featured"]["fourStar"] = None
        validate_dataset(broken)

    def test_publish_requires_cn_not_six_servers(self):
        data = copy.deepcopy(self.gi)
        b = data["banners"][0]
        b["gameVersion"] = "3.7"
        b["featured"]["fourStar"] = [
            {"itemId": None, "type": "character", "names": {"zh-CN": f"【虚构】四星{i}"}}
            for i in range(3)
        ]
        b["sources"] = [{"provider": "official", "url": "https://example.org/notice"}]
        b["regions"] = [r for r in b["regions"] if r["server"] == "cn_official"]
        self.assertEqual(validate_publishable_dataset(data), 1)
        b["regions"][0]["server"] = "asia"
        with self.assertRaisesRegex(ValueError, "cn_official"):
            validate_publishable_dataset(data)

    def test_genshin_gacha_ids_forbidden(self):
        for ids in ([], ["2003"]):
            broken = copy.deepcopy(self.gi)
            broken["banners"][0]["gachaIds"] = ids
            with self.assertRaises(ValueError):
                validate_dataset(broken)
        hsr = copy.deepcopy(self.hsr)
        hsr["banners"][0]["gachaIds"] = ["123456"]
        self.assertEqual(validate_dataset(hsr), 1)
        hsr["banners"][0]["gachaIds"] = []
        with self.assertRaises(ValueError):
            validate_dataset(hsr)

    def _make_chronicled(self):
        data = copy.deepcopy(self.gi)
        banner = data["banners"][0]
        banner["category"] = "chronicled"
        banner["variant"] = "chronicled"
        banner["poolType"] = "chronicled"
        banner["gachaTypes"] = {"raw": ["500"], "uigf": ["500"]}
        banner["featured"]["fiveStar"] = [
            {"itemId": None, "type": "character", "names": {"zh-CN": "【虚构】定轨角色"}},
            {"itemId": None, "type": "weapon", "names": {"zh-CN": "【虚构】定轨武器"}},
        ]
        # 可获取的四星列表不等于四星固定 UP，不能自动写入 featured。
        banner["featured"]["fourStar"] = []
        return data

    def test_chronicled_requires_variant(self):
        for variant in ("chronicled", "special_recollection"):
            data = self._make_chronicled()
            data["banners"][0]["variant"] = variant
            self.assertEqual(validate_dataset(data), 1)
        data = self._make_chronicled()
        del data["banners"][0]["variant"]
        with self.assertRaisesRegex(ValueError, "variant"):
            validate_dataset(data)

    def test_chronicled_variant_only_on_genshin_chronicled(self):
        invalid = copy.deepcopy(self.gi)
        invalid["banners"][0]["variant"] = "special_recollection"
        with self.assertRaisesRegex(ValueError, "variant"):
            validate_dataset(invalid)
        invalid = copy.deepcopy(self.hsr)
        invalid["banners"][0]["variant"] = "chronicled"
        with self.assertRaisesRegex(ValueError, "variant"):
            validate_dataset(invalid)

    def test_chronicled_unknown_variant_rejected(self):
        for variant in ("unknown", "special", None, 500):
            with self.subTest(variant=variant):
                data = self._make_chronicled()
                data["banners"][0]["variant"] = variant
                with self.assertRaises(ValueError):
                    validate_dataset(data)

    def test_chronicled_still_requires_uigf_500(self):
        data = self._make_chronicled()
        data["banners"][0]["variant"] = "special_recollection"
        data["banners"][0]["gachaTypes"]["uigf"] = ["301"]
        with self.assertRaises(ValueError):
            validate_dataset(data)

    def test_chronicled_unknown_four_star_not_automatically_up(self):
        data = self._make_chronicled()
        b = data["banners"][0]
        b["featured"]["fourStar"] = None
        b["gameVersion"] = "3.7"
        b["sources"] = [{"provider": "official", "externalId": "example"}]
        with self.assertRaisesRegex(ValueError, "chronicled fourStar"):
            validate_publishable_dataset(data)
        b["featured"]["fourStar"] = []
        self.assertEqual(validate_publishable_dataset(data), 1)

    def test_no_new_selectable_or_obtainable_fields(self):
        for field in ("selectable", "obtainable", "pityGroup"):
            with self.subTest(field=field):
                data = self._make_chronicled()
                data["banners"][0][field] = {}
                with self.assertRaises(ValueError):
                    validate_dataset(data)

    def test_raw_null_and_category_check(self):
        data = copy.deepcopy(self.gi)
        data["banners"][0]["gachaTypes"]["raw"] = None
        self.assertEqual(validate_dataset(data), 1)
        data["banners"][0]["gachaTypes"]["uigf"] = ["302"]
        with self.assertRaisesRegex(ValueError, "mapping"):
            validate_dataset(data)

    def test_fate_point_limit(self):
        data = self._make_chronicled()
        for limit in (0, 1, 2, None):
            data["banners"][0]["fatePointLimit"] = limit
            self.assertEqual(validate_dataset(data), 1)
        data["banners"][0]["fatePointLimit"] = 3
        with self.assertRaises(ValueError):
            validate_dataset(data)

    def test_collab_category(self):
        for raw, pool, category in (("21", "collab_character", "character"),
                                     ("22", "collab_light_cone", "light_cone")):
            data = copy.deepcopy(self.hsr)
            b = data["banners"][0]
            b["gachaTypes"] = {"raw": [raw], "uigf": [raw]}
            b["poolType"], b["category"] = pool, category
            self.assertEqual(validate_dataset(data), 1)
            b["category"] = pool
            with self.assertRaises(ValueError):
                validate_dataset(data)

    def test_eight_open_ended_starrail_collab_banners_publishable(self):
        # Purely synthetic records: exercise all eight long-running collab slots
        # without putting fictional announcements into public/v1.
        data = copy.deepcopy(self.hsr)
        banners = []
        for index in range(8):
            raw, pool, category, item_type = (
                ("21", "collab_character", "character", "character")
                if index % 2 == 0
                else ("22", "collab_light_cone", "light_cone", "light_cone")
            )
            banner = copy.deepcopy(self.hsr["banners"][0])
            banner["id"] = f"hsr-{100003 + index:06d}"
            banner["gameVersion"] = "3.4" if index < 4 else "4.4"
            banner["phase"] = 1 if index < 4 else 2
            banner["poolType"] = pool
            banner["category"] = category
            banner["gachaTypes"] = {"raw": [raw], "uigf": [raw]}
            banner["featured"]["fiveStar"][0]["type"] = item_type
            banner["featured"]["fourStar"] = []
            banner["sources"] = [
                {"provider": "regression", "externalId": f"synthetic-collab-{index + 1}"}
            ]
            for region in banner["regions"]:
                region["endAt"] = None
            banners.append(banner)
        data["banners"] = banners
        self.assertEqual(validate_dataset(data), 8)
        self.assertEqual(validate_publishable_dataset(data), 8)

    def test_schema_enforces_open_ended_pool_types(self):
        # The public JSON Schema must enforce the same endAt policy as the Python validator.
        for pool, raw, category in (
            ("collab_character", "21", "character"),
            ("collab_light_cone", "22", "light_cone"),
            ("standard", "1", "standard"),
            ("beginner", "2", "beginner"),
        ):
            with self.subTest(allowed=pool):
                data = copy.deepcopy(self.hsr)
                b = data["banners"][0]
                b["poolType"], b["category"] = pool, category
                b["gachaTypes"] = {"raw": [raw], "uigf": [raw]}
                b["phase"] = None if pool in ("standard", "beginner") else 1
                for region in b["regions"]:
                    region["endAt"] = None
                validate_schema(data, "banner-data")
        for pool, raw, category in (
            ("character_event", "11", "character"),
            ("light_cone_event", "12", "light_cone"),
        ):
            with self.subTest(rejected=pool):
                data = copy.deepcopy(self.hsr)
                b = data["banners"][0]
                b["poolType"], b["category"] = pool, category
                b["gachaTypes"] = {"raw": [raw], "uigf": [raw]}
                for region in b["regions"]:
                    region["endAt"] = None
                with self.assertRaisesRegex(ValueError, "endAt"):
                    validate_schema(data, "banner-data")

    def test_end_at_null_rejected_for_ordinary_limited_banners(self):
        for sample in (self.gi, self.hsr):
            with self.subTest(game=sample["game"]):
                data = copy.deepcopy(sample)
                for region in data["banners"][0]["regions"]:
                    region["endAt"] = None
                with self.assertRaisesRegex(ValueError, "endAt"):
                    validate_dataset(data)
        light_cone = copy.deepcopy(self.hsr)
        banner = light_cone["banners"][0]
        banner["gachaTypes"] = {"raw": ["12"], "uigf": ["12"]}
        banner["poolType"], banner["category"] = "light_cone_event", "light_cone"
        for region in banner["regions"]:
            region["endAt"] = None
        with self.assertRaisesRegex(ValueError, "endAt"):
            validate_dataset(light_cone)

    def test_open_ended_starrail_collab_still_requires_version_and_phase(self):
        data = copy.deepcopy(self.hsr)
        banner = data["banners"][0]
        banner["gachaTypes"] = {"raw": ["21"], "uigf": ["21"]}
        banner["poolType"], banner["category"] = "collab_character", "character"
        banner["id"] = "hsr-100003"
        banner["gameVersion"], banner["phase"] = "3.4", 1
        banner["featured"]["fourStar"] = []
        banner["sources"] = [{"provider": "regression", "externalId": "synthetic-collab"}]
        for region in banner["regions"]:
            region["endAt"] = None
        self.assertEqual(validate_publishable_dataset(data), 1)
        for field in ("gameVersion", "phase"):
            with self.subTest(missing=field):
                invalid = copy.deepcopy(data)
                invalid["banners"][0][field] = None
                with self.assertRaisesRegex(ValueError, "version and phase"):
                    validate_publishable_dataset(invalid)

    def test_manifest_single_game(self):
        sample = {"schemaVersion": 1, "generatedAt": "2026-10-13T23:30:00+08:00",
                  "games": {"genshin": {"path": "genshin.json", "sha256": "0" * 64, "bannerCount": 1}}}
        validate_schema(sample, "manifest")
        sample["games"] = {}
        with self.assertRaises(ValueError):
            validate_schema(sample, "manifest")

    def test_data_quality_not_public(self):
        data = copy.deepcopy(self.gi)
        data["banners"][0]["dataQuality"] = "confirmed"
        with self.assertRaises(ValueError):
            validate_dataset(data)

    def test_manifest_path_restrict(self):
        sample = {
            "schemaVersion": 1,
            "generatedAt": "2026-10-13T23:30:00+08:00",
            "games": {
                "genshin": {"path": "../genshin.json", "sha256": "0" * 64, "bannerCount": 1},
                "starrail": {"path": "starrail.json", "sha256": "0" * 64, "bannerCount": 1}
            }
        }
        with self.assertRaises(ValueError):
            validate_schema(sample, "manifest")

    def test_schema_fields_are_documented(self):
        """All published JSON v1 fields and reusable definitions have descriptions."""
        for name in ("banner-data", "manifest"):
            schema = load(ROOT / "schemas/public/v1" / f"{name}.schema.json")

            def check(node, where):
                if not isinstance(node, dict):
                    return
                for key in ("properties", "$defs", "patternProperties"):
                    for field, child in node.get(key, {}).items():
                        self.assertTrue(
                            isinstance(child.get("description"), str)
                            and bool(child["description"].strip()),
                            f"{name}: missing field description at {where}/{key}/{field}",
                        )
                        check(child, f"{where}/{key}/{field}")
                if isinstance(node.get("items"), dict):
                    check(node["items"], where + "/items")
                for index, child in enumerate(node.get("oneOf", [])):
                    check(child, f"{where}/oneOf/{index}")

            check(schema, "#")


    def test_public_cross_record_consistency(self):
        """两游戏已发布数据必须通过跨记录检查。"""
        for game in ("genshin", "starrail"):
            with self.subTest(game=game):
                data = load(ROOT / "public/v1" / f"{game}.json")
                self.assertEqual(validate_publishable_dataset(data), len(data["banners"]))

    def test_published_chronicled_four_star_is_empty(self):
        data = load(ROOT / "public/v1/genshin.json")
        banners = [b for b in data["banners"] if b["poolType"] == "chronicled"]
        self.assertTrue(banners)
        self.assertTrue(all(b["featured"]["fourStar"] == [] for b in banners))
        banners[0]["featured"]["fourStar"] = None
        with self.assertRaisesRegex(ValueError, "chronicled fourStar"):
            validate_publishable_dataset(data)

    def test_published_id_gap_rejected(self):
        data = load(ROOT / "public/v1/genshin.json")
        banner = next(b for b in data["banners"] if b["id"] == "gi-000002")
        banner["id"] = "gi-000999"
        with self.assertRaisesRegex(ValueError, "contiguous"):
            validate_publishable_dataset(data)

    def test_published_duplicate_official_gacha_id_rejected(self):
        data = load(ROOT / "public/v1/starrail.json")
        data["banners"][3]["gachaIds"] = data["banners"][2]["gachaIds"][:]
        with self.assertRaisesRegex(ValueError, "duplicate gachaId"):
            validate_publishable_dataset(data)

    def test_published_item_name_conflict_rejected(self):
        data = load(ROOT / "public/v1/genshin.json")
        target = next(b for b in data["banners"] if b["poolType"] == "character_event")
        target["featured"]["fiveStar"][0]["names"]["zh-CN"] = "【测试】同ID异名"
        with self.assertRaisesRegex(ValueError, "conflicting itemId"):
            validate_publishable_dataset(data)

    def test_published_duplicate_featured_item_rejected(self):
        data = load(ROOT / "public/v1/starrail.json")
        banner = next(b for b in data["banners"] if b["poolType"] == "character_event")
        banner["featured"]["fourStar"][1] = copy.deepcopy(banner["featured"]["fourStar"][0])
        with self.assertRaisesRegex(ValueError, "duplicate featured itemId"):
            validate_publishable_dataset(data)

    def test_published_incorrect_featured_count_rejected(self):
        data = load(ROOT / "public/v1/starrail.json")
        banner = next(b for b in data["banners"] if b["poolType"] == "light_cone_event")
        banner["featured"]["fourStar"].pop()
        with self.assertRaisesRegex(ValueError, "incorrect featured counts"):
            validate_publishable_dataset(data)

    def test_published_wrong_item_type_rejected(self):
        data = load(ROOT / "public/v1/genshin.json")
        banner = next(b for b in data["banners"] if b["poolType"] == "weapon_event")
        banner["featured"]["fiveStar"][0]["type"] = "character"
        with self.assertRaisesRegex(ValueError, "incorrect featured item type"):
            validate_publishable_dataset(data)

    def test_published_special_ids_must_be_contiguous(self):
        data = load(ROOT / "public/v1/starrail.json")
        banner = next(b for b in data["banners"] if b["id"] == "hsr-100003")
        banner["id"] = "hsr-100099"
        with self.assertRaisesRegex(ValueError, "collaboration banner IDs must be contiguous"):
            validate_publishable_dataset(data)


if __name__ == "__main__":
    unittest.main()
