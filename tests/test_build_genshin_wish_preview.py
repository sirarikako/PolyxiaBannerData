"""原神祈愿预告独立解析测试；无需网络访问。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.transform.build_genshin_wish_preview_zh_cn import build, load_or_fetch, main, output_filename


def notice(title="7.1版本活动祈愿预告第二期", content=None, post_id="78879329"):
    if content is None:
        content = ('<p>旅行者好呀~</p>'
                   '<p>本期活动祈愿时间为2026/10/13 18:00 ~ 2026/11/03 14:59。</p>'
                   '<p>限定5星角色「虚渊暗星·丝柯克(冰)」「明绚千韵·爱可菲(冰)」，'
                   '限定5星武器「单手剑·苍耀」「长柄武器·香韵奏者」等的祈愿获取概率将大幅提升！</p>')
    return {"retcode": 0, "data": {"post": {"post": {"post_id": post_id,
        "game_id": 2, "subject": title, "content": content,
        "created_at": 1791864000, "updated_at": 1791864000}}}}


class WishPreviewTest(unittest.TestCase):
    def test_output_filename_matches_version_updates(self):
        self.assertEqual(output_filename("7.1", 2), "wish-preview_zh-CN_7.1-phase-2.json")
        self.assertEqual(output_filename("月之八", 1), "wish-preview_zh-CN_月之八-phase-1.json")

    def test_7_1_second_phase_and_groups(self):
        parsed = build(notice(), post_id="78879329", source_file="posts/78879329.json")
        self.assertEqual((parsed["version"], parsed["phase"], parsed["noticeType"]),
                         ("7.1", 2, "wish_preview"))
        self.assertEqual(parsed["time"]["startAt"], "2026-10-13T18:00:00+08:00")
        self.assertEqual(parsed["time"]["endAt"], "2026-11-03T14:59:00+08:00")
        self.assertEqual([i["name"] for i in parsed["up"]["fiveStarCharacters"]], ["丝柯克", "爱可菲"])
        self.assertEqual([i["name"] for i in parsed["up"]["fiveStarWeapons"]], ["苍耀", "香韵奏者"])
        self.assertEqual(parsed["up"]["fourStarCharacters"], [])
        self.assertEqual(parsed["review"]["warnings"], [])

    def test_lunar_phase_one_and_other_wish(self):
        body = ('<p>本期活动祈愿时间为2026/02/25 「月之五」版本更新后 ~ 2026/03/17 17:59。</p>'
                '<p>限定5星角色「北风骑士·法尔伽(风)」「诡灯陌影·菲林斯(雷)」，'
                '4星角色「猫尾特调·迪奥娜(冰)」「蔚风引灵·伊法(风)」的祈愿获取概率将大幅提升！</p>'
                '<p>限定5星武器「双手剑·狼的武功歌」「长柄武器·血染荒城」，'
                '限定4星武器「弓·幽夜华尔兹」、4星武器「单手剑·笛剑」的祈愿获取概率也将大幅提升！</p>'
                '<p>此外还将开启「晨风之诗」集录祈愿。</p>')
        parsed = build(notice("「月之五」版本活动祈愿预告第一期", body),
                       post_id="78879329", source_file="sample.json")
        self.assertIsNone(parsed["time"]["startAt"])
        self.assertEqual(parsed["time"]["startCondition"], "after_version_update")
        self.assertEqual(len(parsed["up"]["fourStarCharacters"]), 2)
        self.assertEqual([x["name"] for x in parsed["up"]["fourStarWeapons"]], ["幽夜华尔兹", "笛剑"])
        self.assertEqual(parsed["additionalWishes"],
                         [{"name": "晨风之诗", "kind": "chronicled", "noticeType": "集录祈愿"}])
        self.assertEqual(parsed["version"], "月之五")
        self.assertEqual(parsed["phase"], 1)

    def test_reject_announcements_and_wrong_post_id(self):
        with self.assertRaises(ValueError):
            build(notice("「神铸赋形」武器活动祈愿公告"),
                  post_id="78879329", source_file="fixture.json")
        with self.assertRaises(ValueError):
            build(notice(), post_id="123", source_file="fixture.json")

    def test_no_body_does_not_fabricate(self):
        with self.assertRaises(ValueError):
            build(notice(content='<img src="demo.jpg">'),
                  post_id="78879329", source_file="fixture.json")

    def test_delta_body_fallback(self):
        d = notice(content="")
        d["data"]["post"]["post"]["structured_content"] = json.dumps([
            {"insert": "本期活动祈愿时间为2026/10/13 18:00 ~ 2026/11/03 14:59。\n"},
            {"insert": "限定5星角色「虚渊暗星·丝柯克(冰)」的祈愿获取概率将大幅提升！\n"}],
            ensure_ascii=False)
        p = build(d, post_id="78879329", source_file="fixture.json")
        self.assertEqual(p["source"]["textSource"], "structured_content")
        self.assertEqual(len(p["up"]["fiveStarCharacters"]), 1)

    def test_fetch_caches_raw_then_reuses_it(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "78879329.json"
            with patch("scripts.transform.build_genshin_wish_preview_zh_cn.ARCHIVE", Path(folder)), patch("scripts.transform.build_genshin_wish_preview_zh_cn.ACCOUNT_ARCHIVE", Path(folder)):
                with patch("scripts.collect.collect_miyoushe_announcements.fetch",
                           return_value=notice()) as fetched:
                    data, path = load_or_fetch("78879329")
                self.assertEqual(path, target)
                self.assertTrue(path.exists())
                self.assertEqual(fetched.call_count, 1)
                data2, _ = load_or_fetch("78879329", offline=True)
                self.assertEqual(data, data2)

    def test_fetch_rejects_mismatched_article_before_caching(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "78879329.json"
            with patch("scripts.transform.build_genshin_wish_preview_zh_cn.ARCHIVE", Path(folder)), patch("scripts.transform.build_genshin_wish_preview_zh_cn.ACCOUNT_ARCHIVE", Path(folder)):
                with patch("scripts.collect.collect_miyoushe_announcements.fetch",
                           return_value=notice(post_id="99999999")):
                    with self.assertRaisesRegex(ValueError, "文章 ID 不匹配"):
                        load_or_fetch("78879329")
            self.assertFalse(target.exists())

    def test_cli_file_name_includes_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "input.json"
            source.write_text(json.dumps(notice(), ensure_ascii=False), encoding="utf-8")
            with patch("scripts.transform.build_genshin_wish_preview_zh_cn.OUTPUT", folder):
                rc = main(["--post-id", "78879329", "--input", str(source)])
            self.assertEqual(rc, 0)
            self.assertTrue((folder / "wish-preview_zh-CN_7.1-phase-2.json").is_file())


if __name__ == "__main__":
    unittest.main()
