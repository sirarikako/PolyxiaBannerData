"""虚拟人工配置端到端测试：现有真实 v1 的临时副本 + 持久化候选 + 3个完全虚拟的新池。

仅在系统临时目录执行，包括 --write；正式 public/v1 不触碰。
虚拟公告、卡池、ID、服务器时间只用于测试，禁止发布为正式数据。
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.release.import_genshin_v1_zh_cn import import_v1, validate_publishable_dataset

REPO = Path(__file__).resolve().parents[1]
ORIGINAL = REPO / "public/v1/genshin.json"
REAL_CANDIDATES = REPO / "data/derived/genshin/v1-candidates"
CAND_DIR = "data/derived/genshin/v1-candidates"
MANUAL_PATH = "manual/genshin_测试版本8.0.json"
TARGET_PATH = "public/v1/genshin.json"
NOTICE_FORMAT = "genshin-v1-candidate-zh-CN-v1"
LABEL = "【虚拟测试，不得发布】"
DATE1 = "2027-01-01T06:00:00+08:00"
DATE1_END = "2027-01-22T18:00:00+08:00"
DATE2 = "2027-01-22T18:00:00+08:00"
DATE2_END = "2027-02-12T15:00:00+08:00"


def write_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def item(name: str, kind: str) -> dict:
    return {"itemId": None, "names": {"zh-CN": f"{LABEL}{name}"}, "type": kind}


def make_candidate(post: str, pool: str, phase: int, start: str | None) -> dict:
    if pool == "weapon_event":
        five = [item("虚拟五星武器甲", "weapon"), item("虚拟五星武器乙", "weapon")]
        four = [item(f"虚拟四星武器{i}", "weapon") for i in range(1, 6)]
        name, category, raw, uigf = "神铸赋形", "weapon", ["302"], ["302"]
    else:
        five = [item(f"虚拟五星角色{post}", "character")]
        four = [item(f"虚拟四星角色{post}-{i}", "character") for i in range(1, 4)]
        name = f"{LABEL}祈愿{post}"
        category, raw, uigf = "character", ["400"] if pool == "character_event_2" else ["301"], ["301"]
    draft = {
        "gameVersion": "测试版本8.0", "phase": phase, "poolType": pool, "category": category,
        "names": {"zh-CN": name},
        "gachaTypes": {"raw": raw, "uigf": uigf},
        "featured": {"fiveStar": five, "fourStar": four},
        "regions": [{"server": "cn_official", "startAt": start,
                     "endAt": DATE1_END if phase == 1 else DATE2_END}],
        "sources": [{"provider": "manual", "externalId": f"temporary-test-only-{post}"}],
    }
    if pool == "weapon_event":
        draft["fatePointLimit"] = 1
    return {
        "format": NOTICE_FORMAT, "game": "genshin", "locale": "zh-CN",
        "status": "ready_candidate", "postId": post,
        "version": "测试版本8.0", "phase": phase,
        "poolType": pool, "variant": None, "bannerName": name, "v1Draft": draft,
        "timeEvidence": {
            "versionMaintenanceStartAt": DATE1,
            "startCondition": "after_version_update" if start is None else None,
        },
        "provenance": {"noticePostId": post},
    }


def manual_template() -> dict:
    return {"format": "genshin-v1-overrides-v2", "version": "测试版本8.0",
            "game": "genshin", "locale": "zh-CN", "upcoming": [], "existing": []}


class SyntheticIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="castorice-v1-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        src = ORIGINAL
        if not src.is_file() or not REAL_CANDIDATES.is_dir():
            self.skipTest("本测试要求先在 Action 临时生成28个真实候选")
        shutil.copytree(REAL_CANDIDATES, self.root / CAND_DIR)
        target = self.root / TARGET_PATH
        target.parent.mkdir(parents=True)
        shutil.copy2(src, target)
        self.before_bytes = target.read_bytes()
        self.before = json.loads(self.before_bytes)
        ordinary = [int(b["id"][3:]) for b in self.before["banners"]
                    if b["id"].startswith("gi-0")]
        last = max(ordinary, default=0)
        self.virtual_ids = [f"gi-{i:06d}" for i in range(last + 1, last + 4)]
        self.expected_total = len(self.before["banners"]) + 3
        self.orig_hash = hashlib.sha256(src.read_bytes()).hexdigest()
        self.manual = manual_template()
        self.save_manual()

    def save_manual(self):
        # 同一场景中刻意让未来8.0/9.0预设与已有7.1修订分属各自的版本文件。
        versions = {}
        for entry in self.manual["upcoming"]:
            version = entry["match"].get("version", "测试版本8.0")
            versions.setdefault(version, {"upcoming": [], "existing": []})["upcoming"].append(entry)
        if self.manual["existing"]:
            versions.setdefault("7.1", {"upcoming": [], "existing": []})["existing"] = self.manual["existing"]
        versions.setdefault("测试版本8.0", {"upcoming": [], "existing": []})
        for version, groups in versions.items():
            record = {"format": "genshin-v1-overrides-v2", "game": "genshin",
                      "locale": "zh-CN", "version": version, **groups}
            write_json(self.root / f"manual/genshin_{version}.json", record)

    def new_fake(self):
        rows = [
            make_candidate("99990001", "character_event", 1, None),
            make_candidate("99990002", "weapon_event", 1, None),
            make_candidate("99990003", "character_event_2", 2, DATE2),
        ]
        for row in rows:
            write_json(self.root / CAND_DIR / f"v1-candidate_zh-CN_{row['postId']}.json", row)
        return rows

    def import_cli(self, write=False):
        args = [sys.executable, "-m", "scripts.release.import_genshin_v1_zh_cn",
                "--root", str(self.root)]
        if write:
            args.append("--write")
        result = subprocess.run(args, cwd=REPO, text=True, capture_output=True)
        if result.returncode:
            self.fail(f"导入器命令失败:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return json.loads(result.stdout)

    def data(self):
        return json.loads((self.root / TARGET_PATH).read_text(encoding="utf-8"))

    def assert_original_safe(self):
        self.assertEqual(hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(), self.orig_hash)

    def test_full_real_v1_copy_with_virtual_manual_preconfiguration(self):
        rows = self.new_fake()
        existing_before = next(b for b in self.before["banners"] if b["id"] == "gi-000299")
        cn_before = deepcopy(next(r for r in existing_before["regions"] if r["server"] == "cn_official"))
        self.manual["upcoming"] = [
            {
                "match": {"version": "测试版本8.0", "phase": 1,
                          "poolType": "character_event", "postId": "99990001"},
                "itemIds": {f"{LABEL}虚拟五星角色99990001": "900000001"},
                "set": {
                    "names": {"en-US": "Synthetic Character Wish", "ja-JP": "架空テスト祈願"},
                    "regions": [
                        {"server": "asia", "startAt": "2027-01-01T07:00:00+08:00",
                         "endAt": "2027-01-22T19:00:00+08:00"},
                    ],
                },
                "addSources": [{"provider": "manual", "externalId": "virtual-upcoming-override"}],
            },
            {
                "match": {"version": "测试版本8.0", "phase": 1,
                          "poolType": "weapon_event", "bannerName": "神铸赋形"},
                "set": {"names": {"en-US": "Synthetic Weapon Event"}},
            },
            {
                "match": {"version": "测试版本9.0", "phase": 1, "poolType": "character_event"},
                "set": {"names": {"en-US": "Unmatched Future Wish"}},
            },
        ]
        self.manual["existing"] = [
            {"id": "gi-000299",
             "set": {
                 "names": {"en-US": "Synthetic Existing Banner Translation"},
                 "regions": [{"server": "asia", "startAt": "2026-10-13T19:00:00+08:00",
                              "endAt": "2026-11-03T16:00:00+08:00"}],
             },
             "addSources": [{"provider": "manual", "externalId": "virtual-existing-override"}]}
        ]
        self.save_manual()
        fixture_source = self.root / MANUAL_PATH
        dry = self.import_cli()
        self.assertEqual(dry["mode"], "dry-run")
        self.assertEqual(dry["candidates"], len(list((self.root / CAND_DIR).glob('v1-candidate_zh-CN_*.json'))))
        self.assertEqual(len(dry["appended"]), 3)
        self.assertEqual([a["id"] for a in dry["appended"]], self.virtual_ids)
        self.assertEqual([a["manual"] for a in dry["appended"]], [True, True, False])
        self.assertEqual(len(dry["skippedExisting"]), dry["candidates"] - len(dry["appended"]))
        self.assertEqual(dry["updatedExistingIds"], ["gi-000299"])
        self.assertEqual(len(dry["unmatchedUpcoming"]), 1)
        self.assertEqual(dry["manualFilesScanned"], 3)
        self.assertEqual(len(dry["completedManual"]), 3)
        self.assertEqual(dry["totalBanners"], self.expected_total)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)
        self.assert_original_safe()

        self.assertTrue(all(entry.get("status", "pending") == "pending"
                            for entry in json.loads((self.root / MANUAL_PATH).read_text())["upcoming"]))
        applied = self.import_cli(write=True)  # 仅写 tempdir 中的 v1 副本！
        self.assertEqual(applied["mode"], "write")
        self.assertTrue(applied["changed"])
        self.assertEqual(applied["appended"], dry["appended"])
        m8 = json.loads((self.root / MANUAL_PATH).read_text(encoding="utf-8"))
        m7 = json.loads((self.root / "manual/genshin_7.1.json").read_text(encoding="utf-8"))
        m9 = json.loads((self.root / "manual/genshin_测试版本9.0.json").read_text(encoding="utf-8"))
        self.assertEqual([e["status"] for e in m8["upcoming"]], ["completed", "completed"])
        self.assertEqual([e["appliedId"] for e in m8["upcoming"]], self.virtual_ids[:2])
        self.assertEqual(m7["existing"][0]["status"], "completed")
        self.assertEqual(m9["upcoming"][0].get("status", "pending"), "pending")
        after = self.data()
        self.assertEqual(len(after["banners"]), self.expected_total)
        by_id = {b["id"]: b for b in after["banners"]}
        char = by_id[self.virtual_ids[0]]
        weapon = by_id[self.virtual_ids[1]]
        later = by_id[self.virtual_ids[2]]
        self.assertEqual(char["names"]["en-US"], "Synthetic Character Wish")
        self.assertEqual(char["names"]["ja-JP"], "架空テスト祈願")
        self.assertEqual(char["featured"]["fiveStar"][0]["itemId"], "900000001")
        self.assertEqual(char["regions"][0]["startAt"], DATE1)
        self.assertEqual(char["regions"][1]["server"], "asia")
        self.assertEqual(char["regions"][1]["startAt"], "2027-01-01T07:00:00+08:00")
        self.assertEqual(weapon["names"]["en-US"], "Synthetic Weapon Event")
        self.assertEqual(weapon["fatePointLimit"], 1)
        self.assertEqual(weapon["regions"][0]["startAt"], DATE1)
        self.assertEqual(later["regions"][0]["startAt"], DATE2)
        self.assertEqual(later["poolType"], "character_event_2")
        existing = by_id["gi-000299"]
        self.assertEqual(existing["names"]["en-US"], "Synthetic Existing Banner Translation")
        self.assertEqual(existing["regions"][0], cn_before)
        self.assertEqual(existing["regions"][1]["server"], "asia")
        unchanged = [b["id"] for b in self.before["banners"] if b["id"] != "gi-000299"]
        self.assertEqual({bid: by_id[bid] for bid in unchanged},
                         {b["id"]: b for b in self.before["banners"] if b["id"] != "gi-000299"})
        self.assertEqual(validate_publishable_dataset(after), self.expected_total)

        written = (self.root / TARGET_PATH).read_bytes()
        again = self.import_cli(write=True)
        self.assertFalse(again["changed"])
        self.assertEqual(again["pendingManualEntries"], 1)
        self.assertEqual(again["completedManual"], [])
        self.assertEqual(again["totalBanners"], self.expected_total)
        self.assertEqual(len(again["skippedExisting"]), dry["candidates"])
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), written)
        self.assert_original_safe()
        artifact_folder = os.environ.get("GENSHIN_SYNTHETIC_REPORT_DIR")
        if artifact_folder:
            output = Path(artifact_folder)
            output.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture_source, output / "synthetic-manual-overrides.json")
            for candidate in rows:
                write_json(output / f"synthetic-candidate-{candidate['postId']}.json", candidate)
            write_json(output / "result.json", {
                "note": "全部为虚拟数据；--write 仅写临时副本，未修改正式 v1",
                "baseline": len(self.before["banners"]),
                "preview": dry,
                "writeToTemporaryCopy": applied,
                "repeatOnTemporaryCopy": again,
                "realV1Sha256BeforeAndAfter": self.orig_hash,
                "realV1Unchanged": True,
            })

    def test_two_overlapping_upcoming_rules_rejected(self):
        self.new_fake()
        self.manual["upcoming"] = [
            {"match": {"version": "测试版本8.0", "phase": 1, "poolType": "character_event"},
             "set": {"names": {"en-US": "A"}}},
            {"match": {"version": "测试版本8.0", "phase": 1, "poolType": "character_event",
                       "postId": "99990001"},
             "set": {"names": {"en-US": "B"}}},
        ]
        self.save_manual()
        with self.assertRaisesRegex(ValueError, "同时匹配多个 upcoming"):
            import_v1(self.root, write=True)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)

    def test_unknown_existing_id_rejected(self):
        self.manual["existing"] = [
            {"id": "gi-999999", "set": {"names": {"en-US": "Should Fail"}}}
        ]
        self.save_manual()
        with self.assertRaisesRegex(ValueError, "找不到已发布内部 ID"):
            import_v1(self.root, write=True)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)

    def test_invalid_item_name_rejected(self):
        self.new_fake()
        self.manual["upcoming"] = [
            {"match": {"version": "测试版本8.0", "phase": 1, "poolType": "character_event"},
             "itemIds": {"【虚拟测试】错误的名字": "900000019"}}
        ]
        self.save_manual()
        with self.assertRaisesRegex(ValueError, "未唯一匹配到 UP 物品"):
            import_v1(self.root, write=True)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)

    def test_illegal_id_edit_rejected(self):
        self.manual["existing"] = [
            {"id": "gi-000299", "set": {"id": "gi-000998"}}
        ]
        self.save_manual()
        with self.assertRaisesRegex(ValueError, "set 只能包含可编辑"):
            import_v1(self.root, write=True)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)

    def test_duplicate_slot_rejected(self):
        self.new_fake()
        other = make_candidate("99990004", "character_event", 1, None)
        write_json(self.root / CAND_DIR / "v1-candidate_zh-CN_99990004.json", other)
        with self.assertRaisesRegex(ValueError, "卡池槽位重复"):
            import_v1(self.root, write=True)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)

    def test_upcoming_cannot_modify_existing_banner(self):
        self.manual["upcoming"] = [
            {"match": {"version": "7.1", "phase": 2, "poolType": "character_event",
                       "postId": "78782589"},
             "set": {"names": {"en-US": "Must Not Modify Old Pool"}}}
        ]
        self.save_manual()
        r = import_v1(self.root, write=True)
        self.assertFalse(r["changed"])
        self.assertEqual(len(r["unmatchedUpcoming"]), 1)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)

    def test_same_version_partially_completed_then_archived(self):
        self.new_fake()
        self.manual["upcoming"] = [
            {"match": {"phase": 1, "poolType": "character_event", "postId": "99990001"},
             "set": {"names": {"en-US": "First Part"}}},
            {"match": {"phase": 1, "poolType": "weapon_event", "postId": "99990002"},
             "set": {"names": {"en-US": "Second Part"}}},
            {"match": {"phase": 2, "poolType": "weapon_event"},
             "set": {"names": {"en-US": "Not Yet Announced"}}},
        ]
        self.save_manual()
        dry = self.import_cli()
        self.assertEqual(len(dry["completedManual"]), 2)
        self.assertEqual(len(dry["unmatchedUpcoming"]), 1)
        self.assertTrue(all("status" not in e for e in
                            json.loads((self.root / MANUAL_PATH).read_text())["upcoming"]))
        applied = self.import_cli(write=True)
        self.assertEqual(len(applied["completedManual"]), 2)
        statuses = [e.get("status", "pending") for e in
                    json.loads((self.root / MANUAL_PATH).read_text())["upcoming"]]
        self.assertEqual(statuses, ["completed", "completed", "pending"])
        again = self.import_cli(write=True)
        self.assertFalse(again["changed"])
        self.assertEqual(again["pendingManualEntries"], 1)
        self.assertEqual(again["completedManual"], [])
        # 等待中的第三项只能显式完成后归档，archive 下文件不会被读取。
        record = json.loads((self.root / MANUAL_PATH).read_text())
        record["upcoming"][2]["status"] = "completed"
        write_json(self.root / MANUAL_PATH, record)
        archive = self.root / "manual/archive"
        archive.mkdir(exist_ok=True)
        (self.root / MANUAL_PATH).rename(archive / "genshin_测试版本8.0.json")
        archived = self.import_cli()
        self.assertEqual(archived["manualFilesScanned"], 0)
        self.assertEqual(archived["pendingManualEntries"], 0)

    def test_archive_directory_is_not_loaded(self):
        self.new_fake()
        write_json(self.root / "manual/archive/genshin_测试版本8.0.json", {
            "format": "genshin-v1-overrides-v2", "game": "genshin",
            "locale": "zh-CN", "version": "测试版本8.0",
            "upcoming": [{"match": {"phase": 1, "poolType": "character_event"},
                           "set": {"names": {"en-US": "ARCHIVED MUST NOT APPLY"}}}],
            "existing": [],
        })
        report = self.import_cli()
        self.assertEqual(report["manualFilesScanned"], 1)
        self.assertTrue(all(not b["manual"] for b in report["appended"]))

    def test_wrong_version_existing_id_is_rejected(self):
        # 将 7.1 的内部 ID 错放到其他版本，绝不能静默跨版本修改。
        write_json(self.root / "manual/genshin_7.2.json", {
            "format": "genshin-v1-overrides-v2", "game": "genshin",
            "locale": "zh-CN", "version": "7.2", "upcoming": [],
            "existing": [{"id": "gi-000299", "set": {"names": {"en-US": "WRONG VERSION"}}}],
        })
        with self.assertRaisesRegex(ValueError, "拒绝跨版本更新"):
            import_v1(self.root, write=True)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)

    def test_colliding_item_ids_rejected_by_full_v1_validator(self):
        self.new_fake()
        self.manual["upcoming"] = [
            {"match": {"version": "测试版本8.0", "phase": 1, "poolType": "character_event"},
             "itemIds": {f"{LABEL}虚拟五星角色99990001": "10000022"}},
        ]
        self.save_manual()
        with self.assertRaisesRegex(ValueError, "conflicting itemId"):
            import_v1(self.root, write=True)
        self.assertEqual((self.root / TARGET_PATH).read_bytes(), self.before_bytes)


if __name__ == "__main__":
    unittest.main()
