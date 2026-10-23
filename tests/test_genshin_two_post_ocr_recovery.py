"""验证两篇旧 OCR 错误在真实公告恢复后的全链只读整合。

只在 pytest 临时目录复制持久化公告、V1、item mappings 和人工配置。
原仓库文件只读取，不创建或关闭 Issue、不写正式 V1 或 checkpoint。
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import shutil

from scripts.release.import_genshin_v1_zh_cn import import_v1
from scripts.release.report_genshin_v1_preview_zh_cn import generate
from scripts.transform.assemble_genshin_wish_candidates_zh_cn import assemble

ROOT = Path(__file__).resolve().parents[1]
POSTS = {
    "68917812": {"status": "recognized", "startAt": "2025-09-30T18:00:00+08:00",
                 "endAt": "2025-10-21T14:59:00+08:00", "startCondition": None},
    "73475919": {"status": "recognized_conditional", "startAt": None,
                 "endAt": "2026-03-17T17:59:00+08:00",
                 "startCondition": "after_version_update"},
}
CHECKPOINT = Path("data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json")
V1 = Path("public/v1/genshin.json")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_actual_ocr_and_checkpoint_are_reconciled():
    state = json.loads((ROOT / CHECKPOINT).read_text(encoding="utf-8"))
    for pid, expected in POSTS.items():
        assert pid not in (state.get("manualReview") or {})
        assert pid not in (state.get("pending") or {})
        entry = state["completed"][pid]
        assert entry["resolution"] == "ocr_reprocessed_verified"
        doc = json.loads((ROOT / f"data/derived/genshin/wish-notices/wish-notice_zh-CN_{pid}.json").read_text(encoding="utf-8"))
        ocr = doc["imageTimeRecognition"]
        assert ocr["status"] == expected["status"]
        assert ocr["times"]["imageSha256"] == entry["imageSha256"]
        assert ocr["imageCount"] == 2
        assert not ocr["warnings"]
        assert doc["source"]["postId"] == pid
        for key in ("startAt", "endAt", "startCondition"):
            assert doc["time"][key] == expected[key]


def test_recovered_times_match_existing_published_history():
    # 68917812 的旧预告不在近期 derived 样本内，仍可能出现 unmatched_end_time；
    # 但 V1 中原有卡池身份、国服时间必须与最新实际 OCR 一致。
    banners = json.loads((ROOT / V1).read_text(encoding="utf-8"))["banners"]
    expected_ids = {"68917812": "gi-000244", "73475919": "gi-000266"}
    for pid, bid in expected_ids.items():
        matching = [banner for banner in banners if any(
            pid in str(source.get("url") or "") for source in banner["sources"])]
        assert len(matching) == 1
        banner = matching[0]
        assert banner["id"] == bid
        cn = next(region for region in banner["regions"] if region["server"] == "cn_official")
        raw = POSTS[pid]
        if raw["startAt"] is not None:
            assert cn["startAt"] == raw["startAt"]
        # V1 结束时间为排他端点，恰好比官方公告最后一分钟加 1。
        from datetime import datetime, timedelta
        assert datetime.fromisoformat(cn["endAt"]) == (
            datetime.fromisoformat(raw["endAt"]) + timedelta(minutes=1))


def test_restored_announcements_reassemble_without_new_public_changes(tmp_path):
    before_v1 = sha(ROOT / V1)
    before_checkpoint = sha(ROOT / CHECKPOINT)
    for rel in ("data/derived/genshin", "manual"):
        shutil.copytree(ROOT / rel, tmp_path / rel, dirs_exist_ok=True)
    for rel in ("public/v1/genshin.json", "public/item-mappings/genshin/zh-CN.json"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    # 手动历史原文仅供有原文身份的人工恢复路径读取。
    raw = ROOT / "data/announcements/genshin/zh-cn/miyoushe/posts"
    if raw.exists():
        shutil.copytree(raw, tmp_path / "data/announcements/genshin/zh-cn/miyoushe/posts")

    result = assemble(tmp_path, write=True)
    by_id = {row.get("postId"): row for row in result["notices"]}
    notice_statuses = {}
    for pid in POSTS:
        assert pid in by_id, f"恢复公告 {pid} 在整合中消失"
        row = by_id[pid]
        notice_statuses[pid] = {"status": row["status"], "issues": row.get("issues"),
                                "existingV1Id": row.get("existingV1Id")}
        assert row["status"] != "conflict", f"恢复后的公告 {pid} 发生真实整合冲突"
        assert "waiting_ocr_end_time" not in (row.get("issues") or [])

    preview = import_v1(tmp_path, write=False, isolate_invalid=True)
    report = generate(tmp_path, preview_file=None, stage_results={
        "collect": "0", "assemble": "0", "preview": "0", "sandbox": "0"})
    print("GENSHIN_REAL_OCR_RECOVERY_REPLAY=" + json.dumps({
        "noticeStatuses": notice_statuses,
        "allCounts": result["counts"], "sourceErrors": result.get("sourceErrors", []),
        "previewAppended": preview.get("appended"), "previewUpdated": preview.get("updatedExistingIds"),
        "previewRejected": preview.get("rejected"),
        "notificationKeys": sorted((report.get("notifications") or {})),
        "originalV1Sha256": before_v1, "formalV1Unchanged": before_v1 == sha(ROOT / V1),
        "checkpointUnchanged": before_checkpoint == sha(ROOT / CHECKPOINT),
    }, ensure_ascii=False))
    assert not result.get("sourceErrors"), "存在意料外来源错误"
    assert not preview.get("rejected"), "修复后有不可导入的候选"
    assert not preview.get("updatedExistingIds"), "不得自动变更已发布 V1"
    assert not preview.get("appended"), "出现未预期的自动新增 V1 候选，请人工审核"
    assert not preview.get("changed"), "只读回放不应有尚未发布的差异"
    for pid in POSTS:
        assert pid not in (report.get("notifications") or {}), f"未结清历史 Issue: {pid}"
    assert before_v1 == sha(ROOT / V1)
    assert before_checkpoint == sha(ROOT / CHECKPOINT)
    assert before_v1 == sha(tmp_path / V1)
