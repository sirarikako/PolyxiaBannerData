"""防止正式工作流更名后 workflow_run 依赖失效。"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
EXPECTED = {
    "refresh-v1-manifest.yml": "1-1_V1 Manifest自动更新",
    "sync-public-data.yml": "1-2_公开仓库数据自动同步",
    "genshin-notices-zh-cn-daily-preview.yml": "2-1_原神公告每日自动采集与解析",
    "genshin-v1-auto-publish.yml": "2-2_原神每日V1数据自动发布",
    "starrail-notices-zh-cn-daily-preview.yml": "3-1_星铁公告每日自动采集与解析",
    "starrail-v1-auto-publish.yml": "3-2_星铁每日V1数据自动发布",
}


def first_name(filename: str) -> str:
    content = (WORKFLOWS / filename).read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*(.+?)\s*$", content)
    assert match, filename
    return match.group(1).strip("'\"")


def test_production_names_match_ordered_labels():
    for filename, expected in EXPECTED.items():
        assert first_name(filename) == expected


def test_workflow_run_matches_upstream_exact_name():
    upstream = [
        ("genshin-v1-auto-publish.yml", "genshin-notices-zh-cn-daily-preview.yml"),
        ("starrail-v1-auto-publish.yml", "starrail-notices-zh-cn-daily-preview.yml"),
    ]
    for follower, previous in upstream:
        content = (WORKFLOWS / follower).read_text(encoding="utf-8")
        assert f"- '{first_name(previous)}'" in content


def test_manifest_dispatch_retains_stable_filename():
    publish = (WORKFLOWS / "genshin-v1-auto-publish.yml").read_text(encoding="utf-8")
    assert "gh workflow run refresh-v1-manifest.yml" in publish


def test_explicit_manifest_to_sync_dispatch_after_validation():
    refresh = (WORKFLOWS / "refresh-v1-manifest.yml").read_text(encoding="utf-8")
    sync = (WORKFLOWS / "sync-public-data.yml").read_text(encoding="utf-8")
    assert "  actions: write" in refresh
    assert "gh workflow run sync-public-data.yml" in refresh
    assert refresh.index("python -m scripts.release.validate_v1 --public") < refresh.index(
        "gh workflow run sync-public-data.yml")
    assert "workflow_run:" not in sync
    assert "workflow_dispatch:" in sync


def test_both_games_validate_temporary_manifest_before_contract_tests():
    for filename, game in (
        ("genshin-v1-auto-publish.yml", "genshin"),
        ("starrail-v1-auto-publish.yml", "starrail"),
    ):
        content = (WORKFLOWS / filename).read_text(encoding="utf-8")
        commands = [
            f"python -m scripts.release.import_{game}_v1_zh_cn --isolate-invalid --write",
            "python -m scripts.release.validate_v1 --datasets-only",
            "python -m scripts.release.refresh_v1_manifest",
            "python -m scripts.release.validate_v1 --public",
            "python -m unittest discover -s tests -p 'test_v1.py'",
            "git restore -- public/v1/manifest.json",
        ]
        positions = [content.index(command) for command in commands]
        assert positions == sorted(positions), filename
