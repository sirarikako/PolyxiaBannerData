"""星铁正式导入器的隔离回归：所有写入仅在 tmp_path。"""
from copy import deepcopy
import json
from pathlib import Path
import shutil

from scripts.release.import_starrail_v1_zh_cn import import_v1, load
from scripts.release.starrail_manual_versions import FORMAT

HERE = Path(__file__).resolve().parents[1]

def setup(tmp_path):
    path = tmp_path / "public/v1"
    path.mkdir(parents=True)
    shutil.copyfile(HERE / "public/v1/starrail.json", path / "starrail.json")
    return path / "starrail.json"

def candidate(tmp_path, name, category="character_event", suffix="a", malformed=False):
    key = "manual-" + suffix * 20
    item_type = "character" if category in {"character_event", "collab_character"} else "light_cone"
    number = {"character_event": "11", "light_cone_event": "12",
              "collab_character": "21", "collab_light_cone": "22"}[category]
    d = {"gameVersion": "4.7", "phase": 1, "poolType": category,
         "category": item_type,
         "names": {"zh-CN": name}, "gachaTypes": {"raw": [number], "uigf": [number]},
         "featured": {"fiveStar": [{"itemId": None, "type": item_type, "names": {"zh-CN": "测试五星" + name}}],
                      "fourStar": [{"itemId": None, "type": item_type, "names": {"zh-CN": str(n)+"测试四星"+name}} for n in range(0 if category.startswith("collab_") else 3)]},
         "regions": [{"server": "cn_official", "startAt": "2026-11-12T06:00:00+08:00",
                      "endAt": None if category.startswith("collab_") else "2026-12-03T12:00:00+08:00"}],
         "sources": [{"provider": "manual", "externalId": "starrail-" + suffix * 20}]}
    if malformed:
        d["featured"]["fourStar"] = []
    row = {"format": "starrail-v1-candidate-zh-CN-v1", "game": "starrail", "locale": "zh-CN",
           "version": "4.7", "phase": 1, "poolType": category, "bannerName": name,
           "status": "ready_candidate", "sourceKey": key, "v1Draft": d}
    folder = tmp_path / "data/derived/starrail/v1-candidates"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("v1-candidate_zh-CN_" + key + ".json")
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

def manual(tmp_path, version, upcoming=None, existing=None):
    path = tmp_path / "manual"
    path.mkdir(parents=True, exist_ok=True)
    target = path / ("starrail_" + version + ".json")
    target.write_text(json.dumps({"format": FORMAT, "game": "starrail", "locale": "zh-CN",
                                  "version": version, "upcoming": upcoming or [],
                                  "existing": existing or []}, ensure_ascii=False), encoding="utf-8")
    return target

def test_dry_run_never_writes(tmp_path):
    target = setup(tmp_path)
    candidate(tmp_path, "测试角色跃迁", suffix="a")
    before = target.read_bytes()
    report = import_v1(tmp_path)
    assert report["v1Changed"] is True
    assert len(report["appended"]) == 1
    assert target.read_bytes() == before

def test_write_idempotent_and_allocates_contiguous_id(tmp_path):
    target = setup(tmp_path)
    before = load(target)["banners"]
    last = max(int(b["id"][4:]) for b in before if b["id"].startswith("hsr-0"))
    candidate(tmp_path, "测试角色跃迁", suffix="a")
    candidate(tmp_path, "测试光锥跃迁", category="light_cone_event", suffix="b")
    report = import_v1(tmp_path, write=True)
    assert len(report["appended"]) == 2
    assert {x["id"] for x in report["appended"]} == {
        f"hsr-{last + 1:06d}", f"hsr-{last + 2:06d}"
    }
    snapshot = target.read_bytes()
    second = import_v1(tmp_path, write=True)
    assert not second["appended"]
    assert len(second["skipped"]) == 2
    assert target.read_bytes() == snapshot

def test_invalid_pool_isolated_good_pool_survives(tmp_path):
    target = setup(tmp_path)
    baseline = len(load(target)["banners"])
    candidate(tmp_path, "坏池", suffix="c", malformed=True)
    candidate(tmp_path, "好池", suffix="d")
    report = import_v1(tmp_path, write=True, isolate_invalid=True)
    assert len(report["appended"]) == 1
    assert report["appended"][0]["identity"][3] == "好池"
    assert report["rejected"]
    assert len(load(target)["banners"]) == baseline + 1

def test_same_identity_blocks_all_candidates(tmp_path):
    setup(tmp_path)
    candidate(tmp_path, "冲突池", suffix="e")
    candidate(tmp_path, "冲突池", suffix="f")
    report = import_v1(tmp_path, isolate_invalid=True)
    assert not report["appended"]
    assert any("业务身份重复" in r["error"] for r in report["rejected"])

def test_upcoming_completed_with_same_write(tmp_path):
    target = setup(tmp_path)
    last = max(int(b["id"][4:]) for b in load(target)["banners"]
               if b["id"].startswith("hsr-0"))
    candidate(tmp_path, "待补新池", suffix="9")
    path = manual(tmp_path, "4.7", upcoming=[{
        "status": "pending", "match": {"phase": 1, "poolType": "character_event", "bannerName": "待补新池"},
        "set": {"names": {"ja-JP": "試験"}}, "itemIds": {"测试五星待补新池": None}}])
    assert len(import_v1(tmp_path)["completedManual"]) == 1
    assert load(path)["upcoming"][0]["status"] == "pending"
    result = import_v1(tmp_path, write=True)
    assert len(result["completedManual"]) == 1
    assert load(path)["upcoming"][0]["status"] == "completed"
    assert next(b for b in load(target)["banners"]
                if b["id"] == f"hsr-{last + 1:06d}")["names"]["ja-JP"] == "試験"

def test_existing_requires_id_and_does_not_rewrite_candidate_pool(tmp_path):
    target = setup(tmp_path)
    path = manual(tmp_path, "4.6", existing=[{
        "id": "hsr-000275", "status": "pending",
        "set": {"names": {"ja-JP": "テスト更新"}}}])
    before = len(load(target)["banners"])
    result = import_v1(tmp_path, write=True)
    assert result["updatedExistingIds"] == ["hsr-000275"]
    assert len(load(target)["banners"]) == before
    assert load(path)["existing"][0]["status"] == "completed"
    assert next(b for b in load(target)["banners"] if b["id"] == "hsr-000275")["names"]["ja-JP"] == "テスト更新"


def test_collaboration_special_id_and_open_end(tmp_path):
    target = setup(tmp_path)
    existing = load(target)["banners"]
    next_special = max(int(b["id"][4:]) for b in existing if b["id"].startswith("hsr-1")) + 1
    expected = {f"hsr-{next_special:06d}", f"hsr-{next_special + 1:06d}"}
    candidate(tmp_path, "长期角色联动测试", category="collab_character", suffix="c")
    candidate(tmp_path, "长期光锥联动测试", category="collab_light_cone", suffix="d")
    first = import_v1(tmp_path, write=True)
    assert {x["id"] for x in first["appended"]} == expected
    recorded = load(target)["banners"]
    assert all(x["regions"][0]["endAt"] is None for x in recorded if x["id"] in expected)
    after = target.read_bytes()
    assert not import_v1(tmp_path, write=True)["appended"]
    assert target.read_bytes() == after

def test_existing_long_term_collab_not_published_again(tmp_path):
    target = setup(tmp_path)
    candidate(tmp_path, "圣剑辉烈之誓", category="collab_character", suffix="c")
    path = tmp_path / "data/derived/starrail/v1-candidates" / ("v1-candidate_zh-CN_manual-" + "c"*20 + ".json")
    data = json.loads(path.read_text())
    data["v1Draft"]["featured"]["fiveStar"][0]["names"]["zh-CN"] = "Saber"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    result = import_v1(tmp_path, write=False)
    assert not result["appended"]
    assert result["skipped"][0]["id"] == "hsr-100003"
    assert len(load(target)["banners"]) == len(load(HERE / "public/v1/starrail.json")["banners"])


def test_version_manual_public_schema_accepts_upcoming_existing():
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads((HERE / "schemas/manual/starrail-v1-overrides.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    sample = {"format": FORMAT, "game": "starrail", "locale": "zh-CN", "version": "4.7",
              "upcoming": [{"match": {"phase": 1, "poolType": "character_event",
                                     "bannerName": "测试池", "fiveStarName": "测试五星"},
                            "status": "pending", "itemIds": {"测试五星": None}}],
              "existing": [{"id": "hsr-000276", "status": "pending",
                            "set": {"names": {"ja-JP": "仮名"}}}]}
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(sample))
    assert not errors, [str(e) for e in errors]


def test_historical_official_name_alias_does_not_duplicate_published_pool(tmp_path):
    """即使候选使用过时池名，也不得把同五星已发布池重发。"""
    target = setup(tmp_path)
    published = next(b for b in load(target)["banners"] if b["id"] == "hsr-000078")
    draft = deepcopy(published)
    draft.pop("id")
    draft["names"]["zh-CN"] = "夜将不眠"
    key = "manual-" + "a" * 20
    draft["sources"] = [{"provider": "manual", "externalId": "starrail-" + "a" * 20}]
    row = {"format": "starrail-v1-candidate-zh-CN-v1", "game": "starrail",
           "locale": "zh-CN", "version": "2.5", "phase": 1,
           "poolType": draft["poolType"], "bannerName": draft["names"]["zh-CN"],
           "status": "ready_candidate", "sourceKey": key, "v1Draft": draft}
    folder = tmp_path / "data/derived/starrail/v1-candidates"
    folder.mkdir(parents=True)
    (folder / ("v1-candidate_zh-CN_" + key + ".json")).write_text(
        json.dumps(row, ensure_ascii=False), encoding="utf-8")
    before = target.read_bytes()
    result = import_v1(tmp_path, write=True)
    assert result["appended"] == []
    assert any("池名不同" in item["error"] for item in result["rejected"])
    assert target.read_bytes() == before

def test_continued_banner_phase_two_is_not_reissued(tmp_path):
    """4.0 第二期公告重复列出第一期继续开放的爻光池。"""
    target = setup(tmp_path)
    published = next(b for b in load(target)["banners"] if b["id"] == "hsr-000205")
    draft = deepcopy(published)
    draft.pop("id")
    draft["phase"] = 2
    key = "manual-" + "b" * 20
    draft["sources"] = [{"provider": "manual", "externalId": "starrail-" + "b" * 20}]
    row = {"format": "starrail-v1-candidate-zh-CN-v1", "game": "starrail",
           "locale": "zh-CN", "version": "4.0", "phase": 2,
           "poolType": draft["poolType"], "bannerName": draft["names"]["zh-CN"],
           "status": "ready_candidate", "sourceKey": key, "v1Draft": draft}
    folder = tmp_path / "data/derived/starrail/v1-candidates"
    folder.mkdir(parents=True)
    (folder / ("v1-candidate_zh-CN_" + key + ".json")).write_text(
        json.dumps(row, ensure_ascii=False), encoding="utf-8")
    before = target.read_bytes()
    result = import_v1(tmp_path, write=True)
    assert result["appended"] == []
    assert result["skipped"][0]["id"] == "hsr-000205"
    assert target.read_bytes() == before
