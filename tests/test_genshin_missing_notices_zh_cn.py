"""无官方帖子人工来源的离线回归。仅在临时目录构造模拟数据。"""
import json

from scripts.transform.assemble_genshin_wish_candidates_zh_cn import assemble
from scripts.transform.genshin_missing_notices_zh_cn import MISSING_ROOT


def store(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return target


def missing(root, kind, identity, data):
    name = kind + "-" + str(identity["version"]) + "-" + str(identity.get("phase", 0))
    if kind == "wish_notice":
        name += "-" + identity["poolType"]
    return store(root, MISSING_ROOT / (name + ".json"), {
        "format": "genshin-missing-notice-v1", "noticeType": kind,
        "identity": identity, "data": data,
        "evidence": {"summary": "离线模拟用人工核对资料"}
    })


def test_all_three_announcements_missing_can_make_candidate(tmp_path):
    start = "2026-10-13T18:00:00+08:00"
    end = "2026-11-03T14:59:00+08:00"
    missing(tmp_path, "version_update", {"version": "7.1"},
            {"maintenance": {"startAt": "2026-10-13T06:00:00+08:00"}})
    missing(tmp_path, "wish_preview", {"version": "7.1", "phase": 2},
            {"time": {"startAt": start, "endAt": end},
             "up": {"fiveStarCharacters": ["甲"], "fiveStarWeapons": []}})
    missing(tmp_path, "wish_notice",
            {"version": "7.1", "phase": 2, "poolType": "character_event"},
            {"bannerName": "模拟祈愿",
             "time": {"startAt": start, "endAt": end},
             "up": {"fiveStarCharacters": ["甲"],
                    "fourStarCharacters": ["乙", "丙", "丁"]}})
    store(tmp_path, "public/item-mappings/genshin/zh-CN.json",
          {"甲": 101, "乙": 102, "丙": 103, "丁": 104})
    rows = assemble(tmp_path, write=True)["notices"]
    assert len(rows) == 1
    assert rows[0]["status"] == "ready_candidate"
    assert rows[0]["postId"] is None
    source_key = rows[0]["sourceKey"]
    assert source_key.startswith("manual-")
    candidate = json.loads((tmp_path / f"data/derived/genshin/v1-candidates/v1-candidate_zh-CN_{source_key}.json").read_text())
    assert candidate["v1Draft"]["sources"][0]["provider"] == "manual"
    assert candidate["v1Draft"]["regions"][0]["endAt"] == "2026-11-03T15:00:00+08:00"


def test_invalid_manual_without_evidence_is_not_accepted(tmp_path):
    store(tmp_path, MISSING_ROOT / "invalid.json", {
        "format": "genshin-missing-notice-v1", "noticeType": "version_update",
        "identity": {"version": "7.1"},
        "data": {"maintenance": {"startAt": "2026-10-13T06:00:00+08:00"}}})
    result = assemble(tmp_path)
    assert result["sourceErrors"]
    assert all(row["status"] != "ready_candidate" for row in result["notices"])


def full_manual(root, *, end="2026-11-03T14:59:00+08:00", notice_end=None, 
                preview_up=True, pool="character_event", variant=None):
    start = "2026-10-13T18:00:00+08:00"
    missing(root, "version_update", {"version": "7.1"},
            {"maintenance": {"startAt": "2026-10-13T06:00:00+08:00"}})
    data = {"time": {"startAt": start, "endAt": end}}
    if preview_up:
        data["up"] = {"fiveStarCharacters": ["甲"], "fiveStarWeapons": []}
    missing(root, "wish_preview", {"version": "7.1", "phase": 2}, data)
    ident = {"version": "7.1", "phase": 2, "poolType": pool}
    if variant:
        ident["variant"] = variant
    notice_data = {"bannerName": "人工祈愿",
                   "time": {"startAt": start, "endAt": notice_end or end}}
    if pool == "chronicled":
        notice_data["selectable"] = {"fiveStarCharacters": ["甲"], "fiveStarWeapons": ["戊"]}
    else:
        notice_data["up"] = {"fiveStarCharacters": ["甲"],
                             "fourStarCharacters": ["乙", "丙", "丁"]}
    missing(root, "wish_notice", ident, notice_data)
    store(root, "public/item-mappings/genshin/zh-CN.json",
          {"甲": 101, "乙": 102, "丙": 103, "丁": 104, "戊": 105})
    return start


def test_manual_identity_selects_correct_preview_despite_same_end(tmp_path):
    full_manual(tmp_path)
    # 历史预告结束时间碰撞：旧的“仅按 endAt”会报 ambiguous_end_time。
    store(tmp_path, "data/derived/genshin/wish-previews/wish-preview_zh-CN_7.0-phase-1.json", {
        "game": "genshin", "locale": "zh-CN", "noticeType": "wish_preview",
        "version": "7.0", "phase": 1,
        "time": {"endAt": "2026-11-03T14:59:00+08:00"},
        "up": {"fiveStarCharacters": [{"name": "甲"}]},
        "source": {"postId": "5678", "url": "https://www.miyoushe.com/ys/article/5678"}})
    row = assemble(tmp_path)["notices"][0]
    assert row["status"] == "ready_candidate"
    assert (row["version"], row["phase"]) == ("7.1", 2)


def test_manual_notice_wrong_end_becomes_conflict_not_waiting(tmp_path):
    full_manual(tmp_path, notice_end="2026-11-04T14:59:00+08:00")
    row = assemble(tmp_path)["notices"][0]
    assert row["status"] == "conflict"
    assert "manual_identity_end_time_conflict" in row["issues"]


def test_official_recovery_compares_even_when_name_and_end_differ(tmp_path):
    from scripts.release.report_genshin_v1_preview_zh_cn import generate
    start = full_manual(tmp_path, notice_end="2026-11-04T14:59:00+08:00")
    store(tmp_path, "data/derived/genshin/wish-notices/wish-notice_zh-CN_901234.json", {
        "game": "genshin", "locale": "zh-CN", "noticeType": "wish_notice",
        "bannerName": "官方不同名称", "poolType": "character_event", "variant": None,
        "time": {"startAt": start, "endAt": "2026-11-03T14:59:00+08:00"},
        "up": {"fiveStarCharacters": [{"name": "甲"}],
               "fourStarCharacters": [{"name": n} for n in ["乙", "丙", "丁"]]},
        "imageTimeRecognition": {
            "status": "recognized",
            "times": {"startAt": start, "endAt": "2026-11-03T14:59:00+08:00"}},
        "source": {"postId": "901234", "url": "https://www.miyoushe.com/ys/article/901234"},
        "review": {"warnings": []}
    })
    result = assemble(tmp_path, write=True)
    assert len(result["notices"]) == 1  # 不会把人工和官方当作两个独立卡池
    row = result["notices"][0]
    assert row["status"] == "conflict"
    assert row["postId"] == "901234"
    assert row["manualSourceKey"].startswith("manual-")
    assert {d["field"] for d in row["manualDifferences"]} >= {"bannerName", "time.endAt"}
    report = generate(tmp_path)
    assert row["manualSourceKey"] in report["notifications"]
    assert "time.endAt" in {d["field"] for d in report["notifications"][row["manualSourceKey"]]["differences"]}
    assert not list((tmp_path / "data/derived/genshin/v1-candidates").glob("*.json"))


def test_special_pool_without_preview_up_is_accepted_and_audited(tmp_path):
    full_manual(tmp_path, preview_up=False, pool="chronicled", variant="special_recollection")
    row = assemble(tmp_path, write=True)["notices"][0]
    assert row["status"] == "ready_candidate"
    candidate = json.loads((tmp_path / row["candidateFile"]).read_text())
    assert candidate["v1Draft"]["poolType"] == "chronicled"
    assert len(candidate["manualAudit"]["sources"]) == 3
    assert all(source["evidence"]["summary"] for source in candidate["manualAudit"]["sources"])


def test_duplicate_identity_is_not_silently_published(tmp_path):
    full_manual(tmp_path)
    original = next((tmp_path / MISSING_ROOT).glob("wish_notice-*.json"))
    duplicate = tmp_path / MISSING_ROOT / "same-identity-again.json"
    duplicate.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
    result = assemble(tmp_path, write=True)
    assert result["sourceErrors"]
    assert all(row["status"] != "ready_candidate" for row in result["notices"])
    assert not list((tmp_path / "data/derived/genshin/v1-candidates").glob("*.json"))

def test_official_recovery_uses_phase_window_when_both_times_and_name_differ(tmp_path):
    full_manual(tmp_path)
    # 官方名称、开始和结束均不同；官方开池仍落在该期预告区间里。
    start, end = "2026-10-14T18:00:00+08:00", "2026-11-04T14:59:00+08:00"
    store(tmp_path, "data/derived/genshin/wish-notices/wish-notice_zh-CN_901235.json", {
        "game": "genshin", "locale": "zh-CN", "noticeType": "wish_notice",
        "bannerName": "官方另一个名称", "poolType": "character_event",
        "time": {"startAt": start, "endAt": end},
        "up": {"fiveStarCharacters": [{"name": "甲"}],
               "fourStarCharacters": [{"name": n} for n in ["乙", "丙", "丁"]]},
        "imageTimeRecognition": {"status": "recognized",
                                  "times": {"startAt": start, "endAt": end}},
        "source": {"postId": "901235", "url": "https://www.miyoushe.com/ys/article/901235"},
        "review": {"warnings": []}
    })
    notices = assemble(tmp_path)["notices"]
    assert len(notices) == 1
    row = notices[0]
    assert row["status"] == "conflict"
    assert row["postId"] == "901235"
    assert row["manualSourceKey"].startswith("manual-")
    assert {d["field"] for d in row["manualDifferences"]} >= {"bannerName", "time.startAt", "time.endAt"}

def test_published_manual_v1_stays_unchanged_when_official_conflicts(tmp_path):
    start = full_manual(tmp_path)
    first = assemble(tmp_path, write=True)["notices"]
    assert len(first) == 1 and first[0]["status"] == "ready_candidate"
    draft = json.loads((tmp_path / first[0]["candidateFile"]).read_text())["v1Draft"]
    draft["id"] = "gi-000001"
    v1 = store(tmp_path, "public/v1/genshin.json", {
        "game": "genshin", "schemaVersion": 1,
        "generatedAt": "2026-10-18T18:00:00+08:00", "banners": [draft]})
    before = v1.read_bytes()
    actual_end = "2026-11-04T14:59:00+08:00"
    store(tmp_path, "data/derived/genshin/wish-notices/wish-notice_zh-CN_901236.json", {
        "game": "genshin", "locale": "zh-CN", "noticeType": "wish_notice",
        "bannerName": "官方变更名称", "poolType": "character_event",
        "time": {"startAt": start, "endAt": actual_end},
        "up": {"fiveStarCharacters": [{"name": "甲"}],
               "fourStarCharacters": [{"name": n} for n in ["乙", "丙", "丁"]]},
        "imageTimeRecognition": {"status": "recognized",
                                  "times": {"startAt": start, "endAt": actual_end}},
        "source": {"postId": "901236", "url": "https://www.miyoushe.com/ys/article/901236"},
        "review": {"warnings": []}
    })
    final = assemble(tmp_path, write=True)
    assert len(final["notices"]) == 1
    assert final["notices"][0]["status"] == "conflict"
    assert final["notices"][0]["existingV1Id"] == "gi-000001"
    assert v1.read_bytes() == before
    assert not list((tmp_path / "data/derived/genshin/v1-candidates").glob("*.json"))

def test_missing_schema_rejects_derived_identity_repeated_in_data(tmp_path):
    path = missing(tmp_path, "version_update", {"version": "7.1"},
                   {"maintenance": {"startAt": "2026-10-13T06:00:00+08:00"}})
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["data"]["version"] = "7.1"  # 版本只能在 identity 中填写
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    result = assemble(tmp_path)
    assert any("Schema 校验失败" in item["error"] for item in result["sourceErrors"])
    assert not any(row["status"] == "ready_candidate" for row in result["notices"])


def test_normal_pool_cannot_omit_preview_up_even_if_schema_allows_special_only(tmp_path):
    full_manual(tmp_path, preview_up=False, pool="character_event")
    row = assemble(tmp_path)["notices"][0]
    assert row["status"] == "conflict"
    assert "five_star_preview_conflict" in row["issues"]
