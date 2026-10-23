"""现役脚本、归档边界与 GitHub Actions 入口的保护测试。"""

import importlib
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "2026-10"

ACTIVE = {
    "collect": (
        "collect_genshin_notices_zh_cn",
        "collect_miyoushe_announcements",
        "download_genshin_notice_images_zh_cn",
        "notify_genshin_notice_problems",
        "run_genshin_wish_notice_with_images_zh_cn",
    ),
    "transform": (
        "analyze_miyoushe_banner_notices",
        "assemble_genshin_wish_candidates_zh_cn",
        "build_genshin_version_update_zh_cn",
        "build_genshin_wish_notice_zh_cn",
        "build_genshin_wish_preview_zh_cn",
        "recognize_genshin_wish_image_zh_cn",
        "select_miyoushe_version_notices",
    ),
    "release": (
        "genshin_manual_versions",
        "import_genshin_v1_zh_cn",
        "refresh_v1_manifest",
        "validate_v1",
    ),
}


class ScriptLayoutTest(unittest.TestCase):
    def test_active_modules_importable_in_expected_directory(self):
        for category, names in ACTIVE.items():
            for name in names:
                module_name = f"scripts.{category}.{name}"
                with self.subTest(module=module_name):
                    module = importlib.import_module(module_name)
                    self.assertEqual(
                        Path(module.__file__).resolve(),
                        ROOT / "scripts" / category / f"{name}.py",
                    )
                    for root_name in ("ROOT", "REPO_ROOT"):
                        if root_name == "ROOT" and category == "transform":
                            continue  # 历史公告分析器的 ROOT 是输入数据目录
                        if hasattr(module, root_name):
                            self.assertEqual(getattr(module, root_name), ROOT)

    def test_retired_modules_are_preserved_but_not_active(self):
        samples = (
            ("scripts/audit/audit_history.py", "scripts.audit.audit_history"),
            ("scripts/legacy/import_genshin_cn.py", "scripts.legacy.import_genshin_cn"),
            ("scripts/release/build_item_mappings.py", "scripts.release.build_item_mappings"),
            ("scripts/collect/bootstrap_history.py", "scripts.collect.bootstrap_history"),
            ("collectors/adapters.py", "collectors.adapters"),
            ("tests/test_audit_history.py", None),
        )
        for source, module_name in samples:
            with self.subTest(path=source):
                self.assertTrue((ARCHIVE / source).is_file())
                self.assertFalse((ROOT / source).exists())
                if module_name:
                    try:
                        spec = importlib.util.find_spec(module_name)
                    except ModuleNotFoundError:
                        spec = None
                    self.assertIsNone(spec)

    def test_workflows_use_existing_module_entries(self):
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            content = workflow.read_text(encoding="utf-8")
            for name in re.findall(r"python(?:\s+-u)?\s+-m\s+(scripts\.[\w.]+)", content):
                with self.subTest(workflow=workflow.name, module=name):
                    self.assertIsNotNone(importlib.util.find_spec(name))


if __name__ == "__main__":
    unittest.main()
