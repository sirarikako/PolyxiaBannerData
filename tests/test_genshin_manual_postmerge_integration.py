"""PR #10 合并后离线联调：全部操作都在 pytest tmp_path，禁止写回正式 V1/检查点/Issue。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from scripts.collect import collect_genshin_notices_zh_cn as collector
from scripts.collect.notify_genshin_notice_problems import notify
from scripts.release.import_genshin_v1_zh_cn import import_v1
from scripts.release.report_genshin_v1_preview_zh_cn import generate, write as write_final
from scripts.release.validate_v1 import validate_publishable_dataset
from scripts.transform.assemble_genshin_wish_candidates_zh_cn import assemble

REPO = Path(__file__).resolve().parents[1]
REAL_V1 = REPO / "public/v1/genshin.json"
MISSING = Path("manual/notices/genshin/zh-CN/missing")
VERSION = "沙箱联调99.0"
START = "2027-05-01T18:00:00+08:00"
END = "2027-05-22T14:59:00+08:00"
CHANGE_END = "2027-05-23T14:59:00+08:00"
OFFICIAL_ID = "99999881"


def save(root: Path, path: str | Path, payload: dict) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def file_bytes(root: Path) -> bytes:
    return (root / "public/v1/genshin.json").read_bytes()


def manual(kind: str, data: dict) -> dict:
    identity = {"version": VERSION}
    if kind in {"wish_preview", "wish_notice"}:
        identity["phase"] = 2
    if kind == "wish_notice":
        identity["poolType"] = "character_event"
    return {"format": "genshin-missing-notice-v1", "noticeType": kind,
            "identity": identity, "data": data,
            "evidence": {"summary": "完全虚构的临时目录离线测试，绝不是真实公告"}}


def base_data() -> dict:
    return {
        "version_update": {"maintenance": {"startAt": "2027-05-01T06:00:00+08:00"}},
        "wish_preview": {"time": {"startAt": START, "endAt": END},
                         "up": {"fiveStarCharacters": ["虚拟角色甲"], "fiveStarWeapons": []}},
        "wish_notice": {"bannerName": "虚拟祈愿", "time": {"startAt": START, "endAt": END},
                        "up": {"fiveStarCharacters": ["虚拟角色甲"],
                               "fourStarCharacters": ["虚拟角色乙", "虚拟角色丙", "虚拟角色丁"]}},
    }


def populate(root: Path, missing_kinds: set[str]) -> None:
    data = base_data()
    for kind in ("version_update", "wish_preview", "wish_notice"):
        if kind in missing_kinds:
            name = {"version_update": "version-update",
                    "wish_preview": "wish-preview", "wish_notice": "wish-notice"}[kind]
            save(root, MISSING / f"{name}-{kind}.json", manual(kind, data[kind]))
            continue
        # 已解析的官方数据仅为合成测试夹具，不下载/伪造真实帖子到仓库。
        source_id = {"version_update": "99999879", "wish_preview": "99999880",
                     "wish_notice": OFFICIAL_ID}[kind]
        obj = {"game": "genshin", "locale": "zh-CN", "noticeType": kind,
               **deepcopy(data[kind]),
               "source": {"postId": source_id,
                          "url": f"https://www.miyoushe.com/ys/article/{source_id}"},
               "review": {"warnings": []}}
        if kind in {"version_update", "wish_preview"}:
            obj["version"] = VERSION
        if kind == "wish_preview":
            obj["phase"] = 2
        if kind == "wish_notice":
            obj["poolType"] = "character_event"
            obj["imageTimeRecognition"] = {
                "status": "recognized", "times": {"startAt": START, "endAt": END}}
        folder, name = {
            "version_update": ("version-updates", f"version-update_zh-CN_{VERSION}.json"),
            "wish_preview": ("wish-previews", f"wish-preview_zh-CN_{VERSION}-phase-2.json"),
            "wish_notice": ("wish-notices", f"wish-notice_zh-CN_{source_id}.json"),
        }[kind]
        save(root, f"data/derived/genshin/{folder}/{name}", obj)


def isolate(root: Path) -> None:
    target = root / "public/v1/genshin.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REAL_V1, target)


def artifact(name: str, payload: dict) -> None:
    path = os.environ.get("GENSHIN_POSTMERGE_ARTIFACT_DIR")
    if not path:
        return
    target = Path(path) / (name + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("missing_kinds", [
    {"version_update"}, {"wish_preview"}, {"wish_notice"},
    {"version_update", "wish_preview", "wish_notice"},
], ids=["only-update-missing", "only-preview-missing", "only-notice-missing", "all-missing"])
def test_manual_missing_combinations_form_one_candidate(tmp_path: Path, missing_kinds: set[str]):
    populate(tmp_path, missing_kinds)
    state = assemble(tmp_path, write=True)
    assert not state["sourceErrors"]
    assert state["counts"]["statuses"] == {"ready_candidate": 1}
    row = state["notices"][0]
    assert (row["version"], row["phase"]) == (VERSION, 2)
    candidate = json.loads((tmp_path / row["candidateFile"]).read_text(encoding="utf-8"))
    assert candidate["v1Draft"]["regions"][0]["endAt"] == "2027-05-22T15:00:00+08:00"
    assert len(candidate["manualAudit"]["sources"]) == len(missing_kinds)
    artifact("candidate-" + "-".join(sorted(missing_kinds)),
             {"statuses": state["counts"]["statuses"], "sourceKey": row["sourceKey"],
              "manuallySupplied": sorted(missing_kinds), "candidateFile": row["candidateFile"]})


def test_full_manual_publication_then_official_conflict_no_real_writes(tmp_path: Path, monkeypatch):
    original_sha = hashlib.sha256(REAL_V1.read_bytes()).hexdigest()
    isolate(tmp_path)
    before = file_bytes(tmp_path)
    initial_count = len(json.loads(before)["banners"])
    populate(tmp_path, {"version_update", "wish_preview", "wish_notice"})
    # 模拟官方详情临时失败；手工 V1 写入不能结清 pending。
    checkpoint = Path("data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json")
    state = collector.fresh_state()
    state["pending"][OFFICIAL_ID] = {
        "kind": "wish_notice", "title": "虚拟祈愿",
        "attempts": 1, "lastError": "公告详情暂时获取失败：模拟网络问题"}
    save(tmp_path, checkpoint, state)

    readiness = assemble(tmp_path, write=True)
    assert readiness["counts"]["statuses"] == {"ready_candidate": 1}
    key = readiness["notices"][0]["sourceKey"]
    expected_candidate = tmp_path / readiness["notices"][0]["candidateFile"]
    assert expected_candidate.exists()
    preview = import_v1(tmp_path, write=False)
    assert preview["changed"] and len(preview["appended"]) == 1
    assert file_bytes(tmp_path) == before
    first = import_v1(tmp_path, write=True)
    assert first["changed"] and len(first["appended"]) == 1
    published = file_bytes(tmp_path)
    assert len(json.loads(published)["banners"]) == initial_count + 1
    assert validate_publishable_dataset(json.loads(published)) == initial_count + 1
    assert not import_v1(tmp_path, write=True)["changed"]
    assert file_bytes(tmp_path) == published
    assert OFFICIAL_ID in json.loads((tmp_path / checkpoint).read_text())["pending"]

    # 官方下载恢复：名称和结束时间与人工不一致。
    official = {"game": "genshin", "locale": "zh-CN", "noticeType": "wish_notice",
                "poolType": "character_event", "bannerName": "官方不同名称",
                "time": {"startAt": START, "endAt": CHANGE_END},
                "up": deepcopy(base_data()["wish_notice"]["up"]),
                "imageTimeRecognition": {"status": "recognized",
                    "times": {"startAt": START, "endAt": CHANGE_END}},
                "source": {"postId": OFFICIAL_ID,
                    "url": f"https://www.miyoushe.com/ys/article/{OFFICIAL_ID}"},
                "review": {"warnings": []}}
    save(tmp_path, f"data/derived/genshin/wish-notices/wish-notice_zh-CN_{OFFICIAL_ID}.json", official)
    report = assemble(tmp_path, write=True)
    assert report["counts"]["statuses"] == {"conflict": 1}
    row = report["notices"][0]
    assert row["existingV1Id"] == first["appended"][0]["id"]
    assert row["manualSourceKey"] == key
    assert {"time.endAt", "bannerName"} <= {d["field"] for d in row["manualDifferences"]}
    assert not expected_candidate.exists()  # 不允许旧候选再次被发布
    assert not import_v1(tmp_path, write=True)["changed"]  # 不自动纠错/回滚
    assert file_bytes(tmp_path) == published

    final = generate(tmp_path)
    assert key in final["notifications"]
    assert final["notifications"][key]["severity"] == "blocking"
    write_final(tmp_path, final)
    notification = notify(tmp_path, "", "", "", dry_run=True)
    assert notification["dryRun"] and notification["total"] >= 1
    assert any(key in item["title"] for item in notification["candidates"])

    # 仅在成功获取后结清下载 pending；不得靠人工先发布删除。
    monkeypatch.setattr(collector, "list_page", lambda *a, **kw: pytest.fail("retry_only 禁止联网扫描列表"))
    monkeypatch.setattr(collector, "extract", lambda pid, entry: "data/derived/genshin/wish-notices/mock.json")
    retry_result = collector.run(
        checkpoint=tmp_path / checkpoint,
        report_path=tmp_path / "data/derived/genshin/notice-discovery/retry-report.json",
        retry_only=True)
    after_checkpoint = json.loads((tmp_path / checkpoint).read_text(encoding="utf-8"))
    assert retry_result["succeeded"] == [OFFICIAL_ID]
    assert OFFICIAL_ID not in after_checkpoint["pending"]
    assert OFFICIAL_ID in after_checkpoint["completed"]
    assert file_bytes(tmp_path) == published
    assert hashlib.sha256(REAL_V1.read_bytes()).hexdigest() == original_sha
    artifact("full-manual-publish-then-conflict", {
        "originalV1Sha256": original_sha, "isolatedOnly": True,
        "initialBanners": initial_count, "isolatedBanners": initial_count + 1,
        "publishedOnce": True, "secondImportChanged": False,
        "officialConflictStatus": row["status"], "manualSourceKey": key,
        "issueDryRun": True, "pendingClearedOnlyAfterFetch": True,
        "formalV1UnchangedByTest": True})
