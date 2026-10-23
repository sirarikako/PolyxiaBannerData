"""已有候选 JSON 仍需图片 OCR 时重新解析，避免缓存永久保留 null。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.collect import collect_genshin_notices_zh_cn as collector


class NoticeImageRefreshTests(unittest.TestCase):
    def test_legacy_notice_candidate_gets_reparsed_with_temporary_images(self):
        pid = "78782590"
        title = "「莓色香颂」祈愿：「明绚千韵·爱可菲(冰)」概率UP！"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "posts"
            original.mkdir()
            post = {"post_id": pid, "subject": title,
                    "post_status": {"is_official": True}}
            (original / f"{pid}.json").write_text(json.dumps({
                "retcode": 0, "data": {"post": {"post": post}}
            }), encoding="utf-8")
            result = root / "data/derived/genshin/wish-notices" / f"wish-notice_zh-CN_{pid}.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({
                "format": "genshin-wish-notice-v1", "game": "genshin",
                "locale": "zh-CN", "source": {"postId": pid, "title": title},
                "time": {"startAt": None, "endAt": None}
            }), encoding="utf-8")

            child_args = []
            def fake_child(argv, **kwargs):
                child_args.extend(argv)
                result.write_text(json.dumps({
                    "format": "genshin-wish-notice-v1",
                    "imageTimeRecognition": {"status": "recognized"},
                }), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="完成", stderr="")

            def fake_images(post, pid_arg, *, output_root):
                self.assertEqual(pid_arg, pid)
                folder = output_root / pid
                folder.mkdir()
                return folder / f"images_zh-CN_{pid}.json"

            with patch.object(collector, "ROOT", root), patch.object(
                collector, "RAW_DIR", original
            ), patch.object(
                collector, "validate_detail", return_value=post
            ), patch.object(
                collector, "download_images", side_effect=fake_images
            ) as downloader, patch.object(
                collector.subprocess, "run", side_effect=fake_child
            ):
                output = collector.extract(pid, {"kind": "wish_notice", "title": title})
            downloader.assert_called_once()
            self.assertIn("--force", child_args)
            self.assertIn("--images-dir", child_args)
            self.assertEqual(output, f"data/derived/genshin/wish-notices/wish-notice_zh-CN_{pid}.json")
            self.assertEqual(json.loads(result.read_text())["imageTimeRecognition"]["status"], "recognized")


if __name__ == "__main__":
    unittest.main()
