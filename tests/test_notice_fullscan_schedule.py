"""核对三组自动化的 UTC 时间与后续完整列表扫描设置。

只读静态检查，避免 pending 为空时跳过后续公告扫描。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def test_official_item_mapping_daily_time():
    body = (ROOT / "official-item-mappings-daily.yml").read_text(encoding="utf-8")
    assert "cron: '17 5 * * *'" in body  # UTC+8 13:17


def test_genshin_all_five_scheduled_runs_are_full_scans():
    body = (ROOT / "genshin-notices-zh-cn-daily-preview.yml").read_text(encoding="utf-8")
    assert "cron: '17 6 * * *'" in body
    assert "cron: '27,37,47,57 6 * * *'" in body
    assert "os.environ['EVENT_NAME'] == 'workflow_dispatch'" in body
    collect = body.split("        id: collect", 1)[1].split("        id: assemble", 1)[0]
    assert "SCHEDULE" not in collect
    assert "python -m scripts.collect.collect_genshin_notices_zh_cn --max-pages 15" in collect
    assert 'elif [ "${{ inputs.retry_only }}" = \'true\' ]; then' in collect


def test_starrail_all_five_scheduled_runs_are_full_scans():
    body = (ROOT / "starrail-notices-zh-cn-daily-preview.yml").read_text(encoding="utf-8")
    assert "cron: '17 7 * * *'" in body
    assert "cron: '27,37,47,57 7 * * *'" in body
    assert "echo 'should_run=true' >>" in body
    collect = body.split("            if [ \"$EVENT_NAME\" = \"push\" ]; then", 1)[1].split(
        "            python -m scripts.transform.assemble_starrail_warp_candidates", 1
    )[0]
    assert "SCHEDULE" not in collect
    assert 'elif [ "$RETRY_ONLY" = "true" ]; then' in collect
    assert "python -m scripts.collect.collect_starrail_notices_zh_cn --max-pages 15" in collect
