"""真实图片中「版本更新后～指定结束时刻」的处理回归测试。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.transform import recognize_genshin_wish_image_zh_cn as ocr
from scripts.transform import build_genshin_wish_notice_zh_cn as extractor


class ConditionalWishImageTimeTests(unittest.TestCase):
    def test_regular_version_update_then_one_end_time(self):
        result = ocr.parse_candidate("祈愿时间\n7.1版本更新后\n2026/10/13 17:59")
        self.assertEqual(result["startCondition"], "after_version_update")
        self.assertEqual(result["startRaw"], "7.1版本更新后")
        self.assertIsNone(result["startAt"])
        self.assertEqual(result["endAt"], "2026-10-13T17:59:00+08:00")

    def test_moon_version_with_brackets(self):
        result = ocr.parse_candidate("「月之八] 版本更新后\n~\n2026/07/21 17:59")
        self.assertEqual(result["startCondition"], "after_version_update")
        self.assertEqual(result["endAt"], "2026-07-21T17:59:00+08:00")

    def test_only_one_date_without_condition_is_unresolved(self):
        self.assertIsNone(ocr.parse_candidate("2026/10/13 17:59"))
        self.assertIsNone(ocr.parse_candidate("版本更新后，不含具体结束时间"))
        self.assertIsNone(ocr.parse_candidate("2026/15/32 28:59 版本更新后"))

    def test_real_68917812_ocr_month_split_by_space(self):
        # PSM 11 把 10 月的两个数字识别成了 1 0；保存原始OCR文本作证据。
        raw = "2025/09/30 18:00\n2025/1 0/21  14:59"
        result = ocr.parse_candidate(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["startAt"], "2025-09-30T18:00:00+08:00")
        self.assertEqual(result["endAt"], "2025-10-21T14:59:00+08:00")
        self.assertEqual(result["endRaw"], "2025/1 0/21  14:59")

    def test_real_73475919_ocr_day_split_by_space(self):
        # PSM 6 能识别版本更新后，但把 17 日识别成了 1 7。
        raw = "[月之五| 版本更新后\n2026/03/1 7 17:59"
        result = ocr.parse_candidate(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["startCondition"], "after_version_update")
        self.assertIsNone(result["startAt"])
        self.assertEqual(result["endAt"], "2026-03-17T17:59:00+08:00")
        self.assertEqual(result["endRaw"], "2026/03/1 7 17:59")

    def test_ocr_split_digits_still_rejects_invalid_dates(self):
        self.assertIsNone(ocr.parse_candidate("7.1版本更新后 2026/1 5/32 17:59"))
        self.assertIsNone(ocr.parse_candidate("2025/09/30 18:00\n2025/1 0/32 14:59"))

    def test_both_recognition_modes_agree(self):
        fake = [{"path": Path("/tmp/one.png"), "url": "https://upload-bbs.miyoushe.com/image.png",
                 "sha256": "abc", "ordinal": 2}]
        with patch.object(ocr, "validate_images", return_value=fake), patch.object(
                ocr, "tesseract_text", side_effect=[
                    "7.1版本更新后\n2026/10/13 17:59",
                    "7.1 版本更新后\n2026/10/13 17:59"]):
            result = ocr.recognize_time(Path("/tmp"), "78299710", [fake[0]["url"]])
        self.assertEqual(result["status"], "recognized_conditional")
        self.assertIsNone(result["times"]["startAt"])
        self.assertEqual(result["times"]["endAt"], "2026-10-13T17:59:00+08:00")

    def test_conflicting_ocr_modes_refuse_time(self):
        fake = [{"path": Path("/tmp/one.png"), "url": "https://upload-bbs.miyoushe.com/image.png",
                 "sha256": "abc", "ordinal": 2}]
        with patch.object(ocr, "validate_images", return_value=fake), patch.object(
                ocr, "tesseract_text", side_effect=[
                    "7.1版本更新后\n2026/10/13 17:59",
                    "7.1版本更新后\n2026/10/12 17:59"]):
            result = ocr.recognize_time(Path("/tmp"), "78299710", [fake[0]["url"]])
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["times"])

    def test_image_condition_is_written_to_output(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            pid = "78299710"
            raw = tmp / "raw.json"
            out = tmp / "wish-notice_zh-CN_78299710.json"
            raw.write_text(json.dumps({"retcode": 0, "data": {"post": {"post": {
                "post_id": pid, "subject": "「雪衰之锋」祈愿：概率UP！",
                "game_id": 2,
                "content": "<p>本祈愿属于「角色活动祈愿」</p>",
                "images": ["https://upload-bbs.miyoushe.com/upload/x.png"]
            }}}}, ensure_ascii=False), encoding="utf-8")
            with patch.object(extractor, "read_temporary_images", return_value=1), patch.object(
                ocr, "recognize_time", return_value={
                    "status": "recognized_conditional", "imageCount": 1,
                    "times": {"startRaw": "7.1版本更新后", "startAt": None,
                              "startCondition": "after_version_update",
                              "endRaw": "2026/10/13 17:59",
                              "endAt": "2026-10-13T17:59:00+08:00",
                              "imageOrdinal": 1, "imageSha256": "abc"},
                    "warnings": []
                }):
                self.assertEqual(extractor.main(["--post-id", pid, "--input", str(raw),
                         "--images-dir", str(tmp), "--output", str(out)]), 0)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(result["time"]["startCondition"], "after_version_update")
            self.assertIsNone(result["time"]["startAt"])
            self.assertEqual(result["time"]["endAt"], "2026-10-13T17:59:00+08:00")


if __name__ == "__main__":
    unittest.main()
