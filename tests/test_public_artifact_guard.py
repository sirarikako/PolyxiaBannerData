"""Prevent uploading or committing full official article bodies to Public Git or Artifacts.

Inspect the six active production workflows directly.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
NAMES = (
    "official-item-mappings-daily.yml",
    "refresh-v1-manifest.yml",
    "genshin-notices-zh-cn-daily-preview.yml",
    "genshin-v1-auto-publish.yml",
    "starrail-notices-zh-cn-daily-preview.yml",
    "starrail-v1-auto-publish.yml",
)
PRIVATE_PREFIXES = ("data/announcements/", "posts/", "images/", "manual/archive/")
UNSAFE_WILDCARDS = {".", "./", "**", "**/*", "*", "/"}


def _uploads(text: str) -> list[list[str]]:
    result = []
    for snippet in text.split("uses: actions/upload-artifact@v4")[1:]:
        snippet = re.split(r"\n\s{6}- (?:name|uses):", snippet, maxsplit=1)[0]
        match = re.search(r"(?m)^\s{10}path:\s*(.*)$", snippet)
        assert match is not None, "artifact upload must have an explicit input path"
        paths = [match.group(1).strip()]
        if not paths[0]:
            for line in snippet[match.end():].splitlines():
                if line and not line.startswith("            "):
                    break
                if line.strip():
                    paths.append(line.strip())
        result.append([path for path in paths if path])
    return result


def test_public_artifacts_are_explicit_non_raw_results():
    for name in NAMES:
        path = WORKFLOWS / name
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        for paths in _uploads(text):
            assert paths, name
            for item in paths:
                assert item not in UNSAFE_WILDCARDS, (name, item)
                assert not any(prefix in item for prefix in PRIVATE_PREFIXES), (name, item)
                assert not item.startswith("~"), (name, item)
                assert not item.startswith("$"), (name, item)


def test_public_notice_collectors_never_commit_raw_or_debug_dumps():
    for game in ("genshin", "starrail"):
        name = f"{game}-notices-zh-cn-daily-preview.yml"
        body = (WORKFLOWS / name).read_text(encoding="utf-8")
        adds = re.findall(r"(?m)^\s*git add\s+[^\n]+", body)
        assert len(adds) == 1
        assert adds[0].strip() == f"git add -A -- data/derived/{game}"
        assert "git add -A -- data/announcements" not in body
        assert "set -x" not in body


def test_decommissioned_live_probe_cannot_run_in_ci():
    assert not (ROOT / "tests/p3_live_official_probe.py").exists()
    assert not (ROOT / "deploy/migration/p3-live-once.flag").exists()
    workflow = (WORKFLOWS / "public-production-safety.yml").read_text(encoding="utf-8")
    assert "p3-live-once.flag" not in workflow
    assert "p3_live_official_probe.py" not in workflow

def test_both_games_manual_changes_trigger_active_reassembly():
    genshin = (WORKFLOWS / "genshin-notices-zh-cn-daily-preview.yml").read_text(encoding="utf-8")
    starrail = (WORKFLOWS / "starrail-notices-zh-cn-daily-preview.yml").read_text(encoding="utf-8")
    for needle in (
        "'manual/notices/genshin/zh-CN/missing/**'",
        "'manual/notices/genshin/zh-CN/miyoushe/**'",
    ):
        assert needle in genshin
    assert "'manual/notices/starrail/zh-CN/**'" in starrail
    assert "python -m scripts.collect.recover_manual_raw_zh_cn --game genshin" in genshin
    assert "python -m scripts.collect.recover_manual_raw_zh_cn --game starrail" in starrail
