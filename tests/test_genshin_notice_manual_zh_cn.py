"""原神公告预置人工 JSON、补缺、差异、OCR 失败恢复的离线回归测试。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.transform.genshin_notice_manual_zh_cn import (
    MANUAL_ROOT, merge_data, apply, read_manual,
)
from scripts.transform.assemble_genshin_wish_candidates_zh_cn import (
    assemble, OUTPUT,
)
from scripts.release.report_genshin_v1_preview_zh_cn import generate, READINESS, CHECKPOINT


def save(root: Path, name: str | Path, data: dict):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def manual(root: Path, pid: str, data: dict):
    return save(root, MANUAL_ROOT / f"{pid}.json", {
        "format": "genshin-notice-manual-v1", "postId": pid, "data": data
    })


def example(tmp_path):
    start, end = "2026-10-13T18:00:00+08:00", "2026-11-03T14:59:00+08:00"
    root = "data/derived/genshin"
    ver = {"game": "genshin", "locale": "zh-CN", "noticeType": "version_update",
           "version": "7.1",
           "maintenance": {"startAt": "2026-09-23T06:00:00+08:00"},
           "source": {"postId": "101", "url": "https://www.miyoushe.com/ys/article/101"}}
    preview = {"game": "genshin", "locale": "zh-CN", "noticeType": "wish_preview",
               "version": "7.1", "phase": 2,
               "time": {"startAt": start, "endAt": end},
               "up": {"fiveStarCharacters": [{"name": "甲"}, {"name": "乙"}],
                      "fiveStarWeapons": [{"name": "丙"}, {"name": "丁"}]},
               "source": {"postId": "102", "url": "https://www.miyoushe.com/ys/article/102"}}
    notice = {"game": "genshin", "locale": "zh-CN", "noticeType": "wish_notice",
              "bannerName": "独立祈愿A", "poolType": "character_event", "variant": None,
              "up": {"fiveStarCharacters": [{"name": "甲", "rarity": 5}],
                     "fourStarCharacters": [{"name": x, "rarity": 4} for x in "戊己庚"],
                     "fiveStarWeapons": [], "fourStarWeapons": []},
              "time": {"startAt": start, "endAt": end, "startCondition": None},
              "imageTimeRecognition": {"status": "recognized",
                                       "times": {"startAt": start, "endAt": end}},
              "source": {"postId": "103", "url": "https://www.miyoushe.com/ys/article/103"},
              "review": {"warnings": []}}
    save(tmp_path, f"{root}/version-updates/version-update_zh-CN_7.1.json", ver)
    save(tmp_path, f"{root}/wish-previews/wish-preview_zh-CN_7.1-phase-2.json", preview)
    notice_file = f"{root}/wish-notices/wish-notice_zh-CN_103.json"
    save(tmp_path, notice_file, notice)
    save(tmp_path, "public/item-mappings/genshin/zh-CN.json",
         {x: i + 100 for i, x in enumerate("甲乙丙丁戊己庚")})
    return notice, notice_file, end


def test_automatic_values_are_compared_not_overwritten():
    auto = {"bannerName": "自动名称", "time": {"endAt": None},
            "up": {"fourStarCharacters": [{"name": "甲", "rarity": 4}, {"name": "乙"}]}}
    human = {"bannerName": "人工名称", "time": {"endAt": "2026-11-03T14:59:00+08:00"},
             "up": {"fourStarCharacters": ["乙", "甲"]}}
    merged, diff, filled, matched = merge_data(auto, human)
    assert merged["bannerName"] == "自动名称"
    assert merged["time"]["endAt"] == human["time"]["endAt"]
    assert diff == [{"field": "bannerName", "automatic": "自动名称", "manual": "人工名称"}]
    assert filled == ["time.endAt"]
    assert matched == ["up.fourStarCharacters"]
    assert auto["time"]["endAt"] is None


def test_manual_cannot_forge_source_or_ocr(tmp_path):
    path = manual(tmp_path, "103", {"source": {"postId": "104"}})
    with pytest.raises(ValueError, match="不允许人工修改"):
        read_manual(path, "103", "wish_notice")
    manual(tmp_path, "103", {"imageTimeRecognition": {"status": "recognized"}})
    with pytest.raises(ValueError, match="不允许人工修改"):
        read_manual(path, "103", "wish_notice")


def test_prepared_manual_fills_failed_ocr_and_allows_candidate(tmp_path):
    notice, path, end = example(tmp_path)
    notice["imageTimeRecognition"] = {"status": "unresolved", "times": None,
                                      "warnings": ["OCR 时间无法识别"]}
    notice["time"]["endAt"] = None
    notice["review"]["warnings"] = ["正文未明确给出祈愿结束时间", "文章含图片，但未识别图片"]
    save(tmp_path, path, notice)
    manual(tmp_path, "103", {"time": {"endAt": end}})
    result = assemble(tmp_path, write=True)
    row = result["notices"][0]
    assert row["status"] == "ready_candidate"
    assert row["endTimeEvidence"] == "manual"
    assert row["manualFilled"] == ["time.endAt"]
    saved = json.loads((tmp_path / OUTPUT / "v1-candidate_zh-CN_103.json").read_text())
    assert saved["v1Draft"]["regions"][0]["endAt"] == "2026-11-03T15:00:00+08:00"
    assert saved["timeEvidence"]["ocrEndAt"] is None
    assert saved["timeEvidence"]["endTimeSource"] == "manual"


def test_difference_is_blocked_and_final_report_shows_values(tmp_path):
    example(tmp_path)
    manual(tmp_path, "103", {"time": {"endAt": "2026-11-03T13:59:00+08:00"}})
    result = assemble(tmp_path, write=True)
    row = result["notices"][0]
    assert row["status"] == "conflict"
    assert "manual_auto_mismatch" in row["issues"]
    assert row["manualDifferences"][0]["automatic"] == "2026-11-03T14:59:00+08:00"
    assert not (tmp_path / OUTPUT / "v1-candidate_zh-CN_103.json").exists()
    save(tmp_path, CHECKPOINT, {"manualReview": {}})
    final = generate(tmp_path)
    assert final["counts"]["requiresAttention"] == 1
    assert final["notifications"]["103"]["differences"][0]["field"] == "time.endAt"


def test_noncritical_manual_difference_is_warning_but_candidate_ready(tmp_path):
    example(tmp_path)
    manual(tmp_path, "103", {"bannerName": "人工别名"})
    row = assemble(tmp_path, write=True)["notices"][0]
    assert row["status"] == "ready_candidate"
    assert row["blockingDifferences"] == []
    assert [d["field"] for d in row["warningDifferences"]] == ["bannerName"]
    save(tmp_path, CHECKPOINT, {"manualReview": {}})
    final = generate(tmp_path)
    assert final["notifications"]["103"]["severity"] == "warning"
    assert final["counts"]["warnings"] == 1
    assert final["counts"]["blocking"] == 0


def test_manual_fills_missing_four_star_without_rewriting_other_fields(tmp_path):
    notice, path, _ = example(tmp_path)
    notice["up"]["fourStarCharacters"] = None
    save(tmp_path, path, notice)
    manual(tmp_path, "103", {"up": {"fourStarCharacters": ["戊", "己", "庚"]}})
    row = assemble(tmp_path, write=True)["notices"][0]
    assert row["status"] == "ready_candidate"
    saved = json.loads((tmp_path / OUTPUT / "v1-candidate_zh-CN_103.json").read_text())
    assert [x["names"]["zh-CN"] for x in saved["v1Draft"]["featured"]["fourStar"]] == ["戊", "己", "庚"]


def test_complete_parser_failure_uses_verified_raw_plus_manual(tmp_path):
    notice, path, end = example(tmp_path)
    (tmp_path / path).unlink()
    pid = "103"
    raw_path = "data/announcements/genshin/zh-cn/miyoushe/posts/103.json"
    save(tmp_path, raw_path, {"data": {"post": {"post": {
        "post_id": 103, "game_id": 2, "subject": "公告测试"
    }}}})
    save(tmp_path, CHECKPOINT, {"manualReview": {
        pid: {"kind": "wish_notice", "reason": "解析脚本失败", "attempts": 1}
    }})
    manual(tmp_path, pid, {"bannerName": notice["bannerName"],
                            "poolType": notice["poolType"], "variant": None,
                            "time": {"startAt": notice["time"]["startAt"], "endAt": end},
                            "up": {"fiveStarCharacters": ["甲"],
                                   "fourStarCharacters": ["戊", "己", "庚"]}})
    result = assemble(tmp_path, write=True)
    row = result["notices"][0]
    assert row["status"] == "ready_candidate"
    assert row["recoveredFromRaw"] is True
    assert row["endTimeEvidence"] == "manual"
    assert (tmp_path / OUTPUT / "v1-candidate_zh-CN_103.json").is_file()
    final = generate(tmp_path)
    assert "103" not in final["notifications"]


def test_not_yet_published_manual_alone_does_not_generate_fake_banner(tmp_path):
    example(tmp_path)
    manual(tmp_path, "99999", {
        "bannerName": "不存在的公告", "poolType": "character_event",
        "time": {"endAt": "2026-12-31T14:59:00+08:00"}
    })
    result = assemble(tmp_path, write=True)
    assert result["counts"]["statuses"] == {"ready_candidate": 1}
    assert (tmp_path / OUTPUT / "v1-candidate_zh-CN_99999.json").exists() is False


def test_invalid_manual_time_reports_error_instead_of_waiting(tmp_path):
    path = manual(tmp_path, "103", {"time": {"endAt": "bad date"}})
    with pytest.raises(ValueError, match="ISO 时间"):
        read_manual(path, "103", "wish_notice")


def test_upstream_preview_difference_is_reported_at_final_stage(tmp_path):
    example(tmp_path)
    manual(tmp_path, "102", {"time": {"endAt": "2026-11-03T13:59:00+08:00"}})
    row = assemble(tmp_path, write=True)["notices"][0]
    assert row["status"] == "conflict"
    assert "preview_manual_auto_mismatch" in row["issues"]
    save(tmp_path, CHECKPOINT, {"manualReview": {}})
    final = generate(tmp_path)
    assert "102" in final["notifications"]
    assert final["notifications"]["102"]["differences"][0]["field"] == "time.endAt"


def test_waiting_other_announcement_never_triggers_issue(tmp_path):
    notice, path, _ = example(tmp_path)
    (tmp_path / "data/derived/genshin/version-updates/version-update_zh-CN_7.1.json").unlink()
    result = assemble(tmp_path, write=True)
    assert result["notices"][0]["status"] == "waiting"
    save(tmp_path, CHECKPOINT, {"pending": {}, "manualReview": {}})
    final = generate(tmp_path)
    assert final["notifications"] == {}


def test_manual_recovery_checkpoint_reconciles_and_remains_rebuildable(tmp_path):
    notice, path, end = example(tmp_path)
    (tmp_path / path).unlink()
    save(tmp_path, "data/announcements/genshin/zh-cn/miyoushe/posts/103.json",
         {"data": {"post": {"post": {"post_id": 103, "game_id": 2, "subject": "恢复用公告"}}}})
    save(tmp_path, CHECKPOINT, {"format": "genshin-notice-discovery-v1",
                               "game": "genshin", "locale": "zh-CN",
                               "feeds": {}, "pending": {}, "completed": {}, "manualReview": {
                                   "103": {"kind": "wish_notice", "title": "恢复用公告",
                                           "reason": "解析器错误", "attempts": 1}},
                               "updatedAt": None})
    manual(tmp_path, "103", {"bannerName": notice["bannerName"],
                             "poolType": "character_event",
                             "time": {"startAt": notice["time"]["startAt"], "endAt": end},
                             "up": {"fiveStarCharacters": ["甲"],
                                    "fourStarCharacters": ["戊", "己", "庚"]}})
    assert assemble(tmp_path, write=True)["notices"][0]["status"] == "ready_candidate"
    from scripts.collect.reconcile_genshin_manual_review_zh_cn import reconcile
    summary = reconcile(tmp_path)
    assert summary["resolved"] == ["103"]
    state = json.loads((tmp_path / CHECKPOINT).read_text(encoding="utf-8"))
    assert "103" not in state["manualReview"]
    assert state["manualRecovered"]["103"]["kind"] == "wish_notice"
    assert state["completed"]["103"]["resolution"] == "manual_verified"
    assert assemble(tmp_path, write=True)["notices"][0]["status"] == "ready_candidate"


def test_manual_difference_classification_allows_display_names():
    from scripts.transform.genshin_notice_manual_zh_cn import classify_differences
    differences = [
        {"field": "bannerName", "automatic": "A", "manual": "B"},
        {"field": "up.fiveStarCharacters", "automatic": ["甲"], "manual": ["乙"]},
        {"field": "time.endAt", "automatic": "T1", "manual": "T2"},
        {"field": "time.endRaw", "automatic": "中文", "manual": "英文"},
    ]
    blocking, warning = classify_differences("wish_notice", differences)
    assert [x["field"] for x in blocking] == ["up.fiveStarCharacters", "time.endAt"]
    assert [x["field"] for x in warning] == ["bannerName", "time.endRaw"]
