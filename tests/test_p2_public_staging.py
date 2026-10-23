"""P2 read-only assertions: public staging excludes full official posts and live workflows."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_public_staging_is_safe():
    assert sorted(p.name for p in (ROOT/".github/workflows").glob("*.yml")) == ["p2-staging-validate.yml"]
    assert not list((ROOT/"data/announcements").glob("**/posts/*.json"))
    assert not list((ROOT/"data/announcements").glob("**/images/*"))
    assert (ROOT/"public/v1/genshin.json").exists()
    assert (ROOT/"public/v1/starrail.json").exists()
    assert (ROOT/"data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json").exists()
    assert (ROOT/"data/derived/starrail/notice-discovery/notice-discovery_zh-CN_checkpoint.json").exists()
    for name in ("genshin-notices-zh-cn-daily-preview.yml","starrail-notices-zh-cn-daily-preview.yml"):
        w=(ROOT/"deploy/production/workflows"/name).read_text(encoding="utf-8")
        assert "git add -A -- data/announcements" not in w
        assert "git add -A -- data/derived" in w


def test_future_publish_still_dispatches_local_manifest():
    for name in ("genshin-v1-auto-publish.yml","starrail-v1-auto-publish.yml"):
        s=(ROOT/"deploy/production/workflows"/name).read_text(encoding="utf-8")
        assert "gh workflow run refresh-v1-manifest.yml" in s
        assert "UPSTREAM_HEAD_BRANCH" in s
        assert "UPSTREAM_REPOSITORY" in s
        assert "GITHUB_REF:-" in s
