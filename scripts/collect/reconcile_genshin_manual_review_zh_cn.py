#!/usr/bin/env python3
"""将已通过逐池整合的人工恢复记录从 manualReview 转入 completed。

不重新执行 OCR，不改人工文件或 v1。完全解析失败的记录另外保存到
manualRecovered，以便每天仍能用真实官方原文+人工文件重建候选。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.collect.collect_genshin_notices_zh_cn import (
    CHECKPOINT, ROOT, load_state, now, persist,
)
from scripts.transform.assemble_genshin_wish_candidates_zh_cn import REPORT


def reconcile(root: Path = ROOT) -> dict:
    checkpoint = root / CHECKPOINT.relative_to(ROOT)
    readiness = root / REPORT
    if not checkpoint.exists() or not readiness.exists():
        return {"resolved": [], "stillPendingReview": 0, "reason": "missing_checkpoint_or_readiness"}
    state = load_state(checkpoint)
    report = json.loads(readiness.read_text(encoding="utf-8"))
    if report.get("format") != "genshin-v1-readiness-zh-CN-v1":
        raise ValueError("逐池整合报告格式错误，拒绝清除待复核状态")
    ready = [row for row in report.get("notices", []) if row.get("status") == "ready_candidate"]
    resolved: dict[str, tuple[str, bool]] = {}

    for row in ready:
        if row.get("postId") and row.get("manualFile"):
            resolved[str(row["postId"])] = (
                str(row.get("noticeFile") or ""), bool(row.get("recoveredFromRaw")))

    used = {
        source for row in ready for source in (
            row.get("previewFile"), row.get("versionUpdateFile"))
        if source
    }
    for entry in report.get("manualComparisons") or []:
        if (entry.get("file") in used and entry.get("manualFile")
                and not entry.get("blockingDifferences", entry.get("differences"))
                and entry.get("postId")):
            resolved[str(entry["postId"])] = (
                str(entry["file"]), bool(entry.get("fallback")))

    moved = []
    for pid, entry in list(state["manualReview"].items()):
        if pid not in resolved:
            continue
        source_file, fallback = resolved[pid]
        state["completed"][pid] = {
            "kind": entry["kind"], "title": entry.get("title"),
            "outputFile": source_file, "completedAt": now(),
            "resolution": "manual_verified",
        }
        if fallback:
            state["manualRecovered"][pid] = entry
        del state["manualReview"][pid]
        moved.append(pid)

    if moved:
        persist(state, checkpoint)
    return {"resolved": sorted(moved), "stillPendingReview": len(state["manualReview"]),
            "manualRecovered": len(state["manualRecovered"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(reconcile(args.root.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
