"""8 篇正式版本更新公告维护时间与 38 条历史池的逐条安全核对。"""
from copy import deepcopy
import json
from pathlib import Path

from scripts.experiments.audit_starrail_maintenance_zh_cn import EVIDENCE, audit

ROOT = Path(__file__).resolve().parents[1]


def test_38_historical_first_phase_pools_match_update_notices():
    report = audit(ROOT / "public/v1/starrail.json")
    assert len(EVIDENCE) == 8
    assert report["total"] == 38
    assert report["matched"] == 38
    assert report["mismatched"] == []
    assert len({row["id"] for row in report["rows"]}) == 38


def test_wrong_start_time_is_reported_not_overwritten(tmp_path):
    dataset = json.loads((ROOT / "public/v1/starrail.json").read_text(encoding="utf-8"))
    target = next(b for b in dataset["banners"] if b["id"] == "hsr-000193")
    region = next(r for r in target["regions"] if r["server"] == "cn_official")
    region["startAt"] = "2025-12-17T07:00:00+08:00"
    path = tmp_path / "starrail.json"
    path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    result = audit(path)
    assert result["matched"] == 37
    assert result["mismatched"][0]["id"] == "hsr-000193"
    assert result["mismatched"][0]["officialMaintenanceStart"] == "2025-12-17T06:00:00+08:00"
