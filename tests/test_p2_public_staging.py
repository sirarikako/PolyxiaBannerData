"""P2 safety gates: no raw posts or active production jobs in public staging."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "deploy/production/workflows"
EXPECTED_PRODUCTION = {
    "official-item-mappings-daily.yml",
    "refresh-v1-manifest.yml",
    "genshin-notices-zh-cn-daily-preview.yml",
    "genshin-v1-auto-publish.yml",
    "starrail-notices-zh-cn-daily-preview.yml",
    "starrail-v1-auto-publish.yml",
}
BANNED_PREFIXES = (
    "archive/", "docs/", "data/review/", "data/audit/", "data/cache/",
    "data/derived/genshin/archive/", "manual/archive/",
)
OLD_FILES = {"index.json", "checkpoint.json", "collection-report.json", "end-probe.json"}


def _tracked():
    # Git index: check what a merge would actually publish.
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return {path.decode("utf-8") for path in output.split(b"\0") if path}


def test_only_readonly_p2_workflow_is_deployed():
    tracked = _tracked()
    assert {p for p in tracked if p.startswith(".github/workflows/")} == {
        ".github/workflows/p2-staging-validate.yml"
    }
    assert {p.name for p in PRODUCTION.glob("*.yml")} == EXPECTED_PRODUCTION
    workflow = (ROOT / ".github/workflows/p2-staging-validate.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "  pull_request:" in workflow
    assert "  schedule:" not in workflow
    assert not re.search(r"(?m)^\s*contents:\s*write\s*$", workflow)
    assert not re.search(r"(?m)^\s*(?:git\s+(?:push|add)\b|gh\s+workflow\s+run\b)", workflow)


def test_git_index_excludes_old_content_and_raw_notices():
    tracked = _tracked()
    assert not {"AGENTS.md", "requirements-hoyoverse-archive.txt"} & tracked
    for path in tracked:
        assert not path.startswith(BANNED_PREFIXES), path
        if path.startswith("data/announcements/"):
            assert not re.search(r"/(?:posts|images)/", path), path
            assert Path(path).name not in OLD_FILES, path

    for path in (
        "public/v1/genshin.json",
        "public/v1/starrail.json",
        "data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json",
        "data/derived/starrail/notice-discovery/notice-discovery_zh-CN_checkpoint.json",
    ):
        assert path in tracked, path


def test_production_templates_cannot_add_raw_posts():
    for game, filename in (
        ("genshin", "genshin-notices-zh-cn-daily-preview.yml"),
        ("starrail", "starrail-notices-zh-cn-daily-preview.yml"),
    ):
        workflow = (PRODUCTION / filename).read_text(encoding="utf-8")
        additions = re.findall(r"(?m)^\s*git add\s+[^\n]+", workflow)
        assert [line.strip() for line in additions] == [
            f"git add -A -- data/derived/{game}"
        ], filename

    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for path in (
        "/data/announcements/genshin/zh-cn/miyoushe/posts/",
        "/data/announcements/starrail/zh-cn/miyoushe/posts/",
        "/data/announcements/genshin/zh-cn/miyoushe/images/",
    ):
        assert path in ignored


def test_publishing_keeps_manifest_local():
    for name in ("genshin-v1-auto-publish.yml", "starrail-v1-auto-publish.yml"):
        workflow = (PRODUCTION / name).read_text(encoding="utf-8")
        assert "gh workflow run refresh-v1-manifest.yml" in workflow
        assert "UPSTREAM_HEAD_BRANCH" in workflow
        assert "UPSTREAM_REPOSITORY" in workflow
        assert "GITHUB_REF:-" in workflow
        assert "sync-public-data.yml" not in workflow
