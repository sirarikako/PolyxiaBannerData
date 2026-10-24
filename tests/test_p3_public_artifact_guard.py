"""P3: prevent uploading or committing full official post bodies to the Public repo.

Read only staged production workflows, not the active Actions runner configuration.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "deploy/production/workflows"
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


def test_official_live_probe_is_disabled_without_explicit_one_shot_opt_in():
    assert not (ROOT / "deploy/migration/p3-live-once.flag").exists()
    body = (ROOT / ".github/workflows/p2-staging-validate.yml").read_text(encoding="utf-8")
    assert "hashFiles('deploy/migration/p3-live-once.flag') != ''" in body
    assert "github.event.pull_request.head.repo.full_name == github.repository" in body
    assert "PYTHONPATH=. python tests/p3_live_official_probe.py" in body
