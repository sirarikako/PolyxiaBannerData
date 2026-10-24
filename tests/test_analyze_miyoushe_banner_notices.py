"""Offline tests for unverified Genshin Miyoushe banner candidate extraction."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.transform import analyze_miyoushe_banner_notices as m


class BannerNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "posts").mkdir()

    def put(self, pid, title, body=None, images=None):
        records = self.records
        record = {"postId": pid, "title": title,
                  "createdAtUtc8": "2025-02-01T12:00:00+08:00",
                  "sourceUrl": "https://www.miyoushe.com/ys/article/" + pid,
                  "rawFile": f"posts/{pid}.json" if body is not None else None}
        records.append(record)
        if body is not None:
            post = {"post_id": pid, "game_id": 2, "subject": title,
                    "structured_content": json.dumps(
                        [{"insert": {"image": image}} for image in (images or [])] +
                        [{"insert": body}], ensure_ascii=False),
                    "images": images or []}
            (self.root / "posts" / f"{pid}.json").write_text(
                json.dumps({"data": {"post": {"post": post}}}, ensure_ascii=False),
                encoding="utf-8")

    def start(self):
        self.records = []

    def analyze(self):
        (self.root / "index.json").write_text(json.dumps({
            "game": "genshin", "language": "zh-cn", "posts": self.records
        }, ensure_ascii=False), encoding="utf-8")
        return m.analyze(self.root)

    def test_filter_and_missing_details(self):
        self.start()
        self.put("11", "角色祈愿：「新星」概率UP！")
        self.put("12", "活动公告：拍照分享")
        self.put("13", "「神铸赋形」武器概率UP")
        result = self.analyze()
        self.assertEqual(result["summary"]["candidateNotices"], 2)
        self.assertEqual(result["summary"]["detailsMissing"], 2)
        self.assertTrue(all(x["status"] == "full_detail_missing" for x in result["candidates"]))
        self.assertFalse(result["publishable"])
        self.assertFalse(result["timesVerified"])

    def test_structured_text_dates_and_images_remain_unverified(self):
        self.start()
        self.put("20", "「神铸赋形」祈愿概率UP！",
                 "活动期间：2025/02/10 18:00 - 2025/02/28 14:59\n"
                 "●限定5星武器「单手剑·苍耀」「法器·帷间夜曲」的祈愿概率大幅提升",
                 ["https://upload-bbs.miyoushe.com/image.png"])
        result = self.analyze()
        record = result["candidates"][0]
        self.assertEqual(record["status"], "body_time_candidates_need_review")
        self.assertEqual(len(record["bodyTimeMentions"]), 2)
        self.assertIn("单手剑·苍耀", record["fiveStarTextCandidates"])
        self.assertEqual(record["imageUrls"], ["https://upload-bbs.miyoushe.com/image.png"])
        self.assertTrue(record["reviewRequired"])
        self.assertFalse(result["timesVerified"])

    def test_image_only_notice_needs_review_not_fabricated_time(self):
        self.start()
        self.put("30", "「神铸赋形」概率UP", "活动期间详见图片",
                 ["https://upload-bbs.miyoushe.com/banner.png"])
        result = self.analyze()
        record = result["candidates"][0]
        self.assertEqual(record["status"], "time_in_images_or_not_present")
        self.assertEqual(record["bodyTimeMentions"], [])
        self.assertTrue(record["imageRecognitionNeeded"])

    def test_invalid_detail_path_and_duplicate_ids_fail_closed(self):
        self.start()
        self.put("40", "「神铸赋形」概率UP", "正文")
        self.records[0]["rawFile"] = "posts/../other.json"
        with self.assertRaisesRegex(ValueError, "Unexpected raw detail path"):
            self.analyze()
        self.records[0]["rawFile"] = "posts/40.json"
        self.records.append(dict(self.records[0]))
        with self.assertRaisesRegex(ValueError, "Duplicate ID"):
            self.analyze()

    def test_html_fallback_and_game_separation(self):
        parser = m.BodyText()
        parser.feed('<p>活动期间：<span>2025/01/01 18:00</span></p><img src="x">')
        self.assertIn("2025/01/01 18:00", parser.result())
        self.start()
        self.put("50", "祈愿公告", "文本")
        p = self.root / "posts/50.json"
        obj = json.loads(p.read_text(encoding="utf-8"))
        obj["data"]["post"]["post"]["game_id"] = 6
        p.write_text(json.dumps(obj), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Wrong game"):
            self.analyze()


if __name__ == "__main__":
    unittest.main()
