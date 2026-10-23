"""星铁 3-2 修复回归：在隔离目录模拟新增两池→完整校验→Manifest 预览。"""
import json
import shutil
from pathlib import Path

from scripts.release.import_starrail_v1_zh_cn import import_v1
from scripts.release.refresh_v1_manifest import refresh_manifest
from scripts.release.validate_v1 import (
    load, validate_manifest, validate_publishable_dataset,
)

ROOT = Path(__file__).resolve().parents[1]

def make_candidate(tmp_path, name, pool_type, item):
    code, category, kind = (
        ("11", "character", "character") if pool_type == "character_event"
        else ("12", "light_cone", "light_cone")
    )
    stem = "a" if category == "character" else "b"
    source_key = "manual-" + stem * 20
    draft = {
        "gameVersion": "99.0",
        "phase": 1,
        "category": category,
        "poolType": pool_type,
        "names": {"zh-CN": name},
        "gachaTypes": {"raw": [code], "uigf": [code]},
        "featured": {
            "fiveStar": [{"itemId": None, "type": kind, "names": {"zh-CN": item}}],
            "fourStar": [
                {"itemId": None, "type": kind, "names": {"zh-CN": f"【回归】四星{i}{name}"}}
                for i in range(3)
            ],
        },
        "regions": [{
            "server": "cn_official",
            "startAt": "2039-01-01T06:00:00+08:00",
            "endAt": "2039-01-24T12:00:00+08:00",
        }],
        "sources": [{"provider": "manual", "externalId": "starrail-" + stem * 20}],
    }
    row = {
        "format": "starrail-v1-candidate-zh-CN-v1",
        "game": "starrail",
        "locale": "zh-CN",
        "version": "99.0",
        "phase": 1,
        "poolType": pool_type,
        "bannerName": name,
        "status": "ready_candidate",
        "sourceKey": source_key,
        "v1Draft": draft,
    }
    folder = tmp_path / "data/derived/starrail/v1-candidates"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"v1-candidate_zh-CN_{source_key}.json").write_text(
        json.dumps(row, ensure_ascii=False), encoding="utf-8"
    )

def test_new_banners_require_temporary_manifest_before_full_contract_check(tmp_path):
    published = tmp_path / "public/v1"
    published.mkdir(parents=True)
    for name in ("genshin.json", "starrail.json", "manifest.json"):
        shutil.copyfile(ROOT / "public/v1" / name, published / name)

    original_v1 = (published / "starrail.json").read_bytes()
    original_manifest = (published / "manifest.json").read_bytes()
    original_len = len(load(published / "starrail.json")["banners"])
    make_candidate(tmp_path, "【回归】新角色池", "character_event", "【回归】五星角色")
    make_candidate(tmp_path, "【回归】新光锥池", "light_cone_event", "【回归】五星光锥")

    result = import_v1(tmp_path, write=True, isolate_invalid=False)
    assert len(result["appended"]) == 2
    after = load(published / "starrail.json")
    assert len(after["banners"]) == original_len + 2
    assert validate_publishable_dataset(after) == original_len + 2

    # 此时旧 Manifest 与新 V1 的哈希不同，是正常的发布中间状态。
    from pytest import raises
    with raises(ValueError, match="starrail: sha256 mismatch"):
        validate_manifest(load(published / "manifest.json"), published)

    # 工作流应临时重算，做完整真实哈希校验，但由 1-1 负责正式提交。
    assert refresh_manifest(published) is True
    assert validate_manifest(load(published / "manifest.json"), published) is True
    assert load(published / "manifest.json")["games"]["starrail"]["bannerCount"] == original_len + 2

    # 二次导入是幂等的。
    repeated = import_v1(tmp_path, write=True, isolate_invalid=False)
    assert repeated["appended"] == []

    # 所有临时操作严格在 tmp_path，绝不触及生产数据。
    assert (ROOT / "public/v1/starrail.json").read_bytes() == original_v1
    assert (ROOT / "public/v1/manifest.json").read_bytes() == original_manifest
