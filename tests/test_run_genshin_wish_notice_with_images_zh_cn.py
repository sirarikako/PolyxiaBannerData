"""验证单篇临时图片的下载/解析/清理流程（无需联网与 pytest）。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.collect import run_genshin_wish_notice_with_images_zh_cn as runner


class SingleNoticeImageRunnerTests(unittest.TestCase):
    def test_download_one_article_and_cleanup(self):
        pid = "78782590"
        with TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "posts"
            archive.mkdir()
            (archive / f"{pid}.json").write_text(json.dumps({
                "retcode": 0, "data": {"post": {"post": {
                    "post_id": pid,
                    "images": ["https://upload-bbs.miyoushe.com/upload/test.png"]
                }}}
            }), encoding="utf-8")
            output = root / "candidate.json"
            temp_files = []

            def fake_download(post, post_id, *, output_root):
                self.assertEqual(post_id, pid)
                folder = output_root / pid
                folder.mkdir()
                image = folder / f"image_zh-CN_{pid}_01.png"
                image.write_bytes(b"mock image")
                temp_files.append(image)
                return folder / f"images_zh-CN_{pid}.json"

            def fake_builder(argv):
                self.assertEqual(argv[argv.index("--post-id") + 1], pid)
                self.assertIn("--force", argv)
                image_dir = Path(argv[argv.index("--images-dir") + 1])
                self.assertTrue(temp_files[0].exists())
                self.assertEqual(image_dir, temp_files[0].parent)
                Path(argv[argv.index("--output") + 1]).write_text(json.dumps({
                    "locale": "zh-CN", "noticeType": "wish_notice",
                    "source": {"postId": pid},
                    "imageTimeRecognition": {"status": "recognized", "times": {"startAt": "2026-10-13T18:00:00+08:00"}}
                }), encoding="utf-8")
                return 0

            with patch.object(runner, "ARCHIVE", archive), patch.object(
                    runner, "download_images", side_effect=fake_download) as downloader, patch.object(
                    runner, "build_main", side_effect=fake_builder):
                self.assertEqual(runner.process(pid, output=output), output)
            downloader.assert_called_once()
            self.assertTrue(output.exists())
            self.assertFalse(temp_files[0].exists(), "临时图片不应该保留在仓库")

    def test_invalid_id_does_not_download(self):
        with patch.object(runner, "download_images") as downloader:
            with self.assertRaises(ValueError):
                runner.process("not-a-number")
            downloader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
