#!/usr/bin/env python3
"""原神简中 v1 最终安全预览报告：统一报告候选、差异、缺失和未解决的解析错误。

这是最终检查/消息通知的唯一输入；仅只读 v1，不执行导入 --write。
"""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter
import json
import os
from pathlib import Path
import re

from scripts.transform.genshin_notice_manual_zh_cn import MANUAL_ROOT

ROOT = Path(__file__).resolve().parents[2]
READINESS = Path("data/derived/genshin/v1-readiness/v1-readiness_zh-CN.json")
CHECKPOINT = Path("data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json")
REPORT = Path("data/derived/genshin/v1-readiness/v1-final-review_zh-CN.json")


def load(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON 必须是对象")
    return value


def generate(root: Path = ROOT, *, preview_file: Path | None = None,
             stage_results: dict | None = None) -> dict:
    ready = load(root / READINESS)
    state = load(root / CHECKPOINT)
    preview = load(preview_file) if preview_file is not None else {}
    stages = stage_results or {}
    # 本轮整合自身失败时，仓库里的旧 readiness 不能被当作本轮可发布候选。
    if str(stages.get("assemble", "0")) not in ("0", "None", ""):
        ready = {}
    notifications: dict[str, dict] = {}
    notices = ready.get("notices") or []
    by_id = {str(r.get("manualSourceKey") or r.get("postId") or r.get("sourceKey")): r
             for r in notices if r.get("manualSourceKey") or r.get("postId") or r.get("sourceKey")}
    # 只要求已经出现公告、且已经有实质问题时才通知；单纯等待其他公告不会报警。
    for pid, row in by_id.items():
        status, issues = row.get("status"), row.get("issues") or []
        # 上游版本/预告的人工差异由对应上游文章自己通知，不再重复通知每个依赖池。
        inherited = {"preview_manual_auto_mismatch", "version_manual_auto_mismatch"}
        actionable_issues = [issue for issue in issues if issue not in inherited]
        has_problem = status == "conflict" and bool(actionable_issues)
        # 兼容旧 checkpoint：此前可能把 unresolved OCR 当作 completed。
        # 普通 waiting 缺版本/预告仍不能触发消息。
        if "waiting_ocr_end_time" in issues and row.get("noticeFile"):
            notice_path = root / row["noticeFile"]
            if notice_path.is_file():
                recognition = (load(notice_path).get("imageTimeRecognition") or {})
                if recognition.get("status") in {"unresolved", "conflict", "error"}:
                    has_problem = True
        review = (state.get("manualReview") or {}).get(str(row.get("postId") or ""))
        if review and status != "ready_candidate":
            # 单篇解析异常只有最终不能产生可用候选时才通知。
            has_problem = True
        if not has_problem:
            continue
        notifications[pid] = {
            "kind": "notice", "status": status, "severity": "blocking",
            "reasons": actionable_issues + ([str(review.get("reason"))] if review else []),
            "differences": list(row.get("manualDifferences") or []),
            "manualFile": row.get("manualFile"),
            "manualSourceKey": row.get("manualSourceKey"),
            "manualEvidence": row.get("manualEvidence"),
            "manualAudits": row.get("manualAudits", []),
            "file": row.get("noticeFile"),
            "missing": [x for x in issues if x.startswith(("missing_", "incomplete_", "waiting_ocr"))],
        }

    # 已被完整的有效候选使用的人工恢复公告，不应再按旧错误通知。
    recovered_sources = {
        path for row in notices if row.get("status") == "ready_candidate"
        for path in (row.get("noticeFile"), row.get("previewFile"), row.get("versionUpdateFile"))
        if path
    }
    resolved_ids = {
        str(c.get("postId")) for c in ready.get("manualComparisons") or []
        if c.get("file") in recovered_sources
        and not c.get("blockingDifferences", c.get("differences"))
    }
    for pid, entry in (state.get("manualReview") or {}).items():
        if pid not in by_id and pid not in resolved_ids:
            notifications[pid] = {
                "kind": "notice", "status": "manualReview", "severity": "blocking",
                "reasons": [str(entry.get("reason") or "解析尚未恢复")],
                "differences": [], "missing": ["parser_output"],
                "file": entry.get("outputFile"),
                "manualFile": (MANUAL_ROOT / f"{pid}.json").as_posix()
                if (root / MANUAL_ROOT / f"{pid}.json").exists() else None,
            }

    # 即使预告/版本更新尚未匹配到某一篇祈愿公告，也不能丢失人工比对差异。
    for comparison in ready.get("manualComparisons") or []:
        differences = list(comparison.get("differences") or [])
        if not differences:
            continue
        blocking = list(comparison.get("blockingDifferences") or [])
        warning = list(comparison.get("warningDifferences") or [])
        # 旧格式的报告不能证明差异是非关键字段，因此安全地默认阻断。
        if not blocking and not warning:
            blocking = differences
        pid = str(comparison.get("sourceKey") or comparison.get("postId") or "workflow-assemble")
        problem = notifications.setdefault(pid, {
            "kind": "notice" if pid.isdecimal() or pid.startswith("manual-") else "workflow",
            "status": "manual_mismatch",
            "severity": "blocking" if blocking else "warning",
            "reasons": [], "differences": [], "missing": [],
            "manualFile": comparison.get("manualFile"), "file": comparison.get("file"),
            "manualEvidence": comparison.get("evidence"), "manualIdentity": comparison.get("identity"),
        })
        if blocking:
            problem["severity"] = "blocking"
        elif "severity" not in problem:
            problem["severity"] = "warning"
        problem["reasons"].append(f"{comparison.get('kind')} 公告与人工数据存在"
                                  + ("关键差异" if blocking else "非关键差异（允许发布）"))
        already = {x.get("field") + repr(x.get("manual")) for x in problem["differences"]}
        for item in differences:
            key = str(item.get("field")) + repr(item.get("manual"))
            if key not in already:
                problem["differences"].append(item)
                already.add(key)

    for row in ready.get("sourceErrors") or []:
        filename = str(row.get("file") or "")
        hit = re.search(r"_(\d+)\.json$", filename)
        pid = str(row.get("sourceKey") or row.get("postId") or (hit.group(1) if hit else
                  "manual-file-" + hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]))
        issue = notifications.setdefault(pid, {
            "kind": "notice" if pid.isdecimal() or pid.startswith(("manual-", "manual-file-")) else "workflow",
            "status": "source_error", "severity": "blocking",
            "reasons": [], "differences": [],
            "missing": [], "manualFile": None, "file": filename
        })
        issue["reasons"].append(f"无法读取候选源 {filename}: {row.get('error')}")

    # 连续失败三次的临时网络请求才触发提醒；无人工修复要求时仍继续重试。
    for pid, entry in (state.get("pending") or {}).items():
        if not isinstance(entry, dict) or int(entry.get("attempts") or 0) < 3:
            continue
        notifications.setdefault(str(pid), {
            "kind": "notice", "status": "transient_retry_exceeded", "severity": "warning",
            "reasons": [f"临时来源错误累计 {entry['attempts']} 次，仍将自动重试："
                        + str(entry.get("lastError") or "未知错误")],
            "differences": [], "missing": [], "manualFile": None, "file": None,
        })

    for stage, code in stages.items():
        if code in (0, "0", None, ""):
            continue
        # 无法读取列表、网络风控属于采集级故障。临时来源失败只有 pending 时保持重试。
        if stage == "collect" and (state.get("pending") or {}) and not (state.get("manualReview") or {}):
            continue
        notifications[f"workflow-{stage}"] = {
            "kind": "workflow", "status": "script_failed", "severity": "blocking",
            "reasons": [f"{stage} 阶段运行失败，退出码 {code}，检查 Action 日志"],
            "differences": [], "missing": [], "manualFile": None, "file": None,
        }

    statuses = Counter(row.get("status") for row in notices)
    report = {
        "format": "genshin-v1-final-review-zh-CN-v1",
        "game": "genshin", "locale": "zh-CN",
        "publicationEnabled": False,
        "blockingNotifications": sorted(pid for pid, issue in notifications.items()
                                        if issue.get("severity") != "warning"),
        "counts": {
            "ready": statuses["ready_candidate"],
            "waiting": statuses["waiting"],
            "conflict": statuses["conflict"],
            "requiresAttention": len(notifications),
            "blocking": sum(issue.get("severity") != "warning" for issue in notifications.values()),
            "warnings": sum(issue.get("severity") == "warning" for issue in notifications.values()),
            "wouldAppend": len(preview.get("appended") or []),
            "wouldUpdateExisting": len(preview.get("updatedExistingIds") or []),
        },
        "preview": {
            "mode": preview.get("mode") or "unavailable",
            "appended": preview.get("appended") or [],
            "updatedExistingIds": preview.get("updatedExistingIds") or [],
        },
        "notifications": notifications,
    }
    return report


def write(root: Path, obj: dict) -> None:
    target = root / REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    if not target.exists() or target.read_text(encoding="utf-8") != data:
        target.write_text(data, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--preview", type=Path, default=Path("/tmp/genshin-v1-preview.json"))
    args = parser.parse_args(argv)
    stages = {
        "collect": os.environ.get("GENSHIN_COLLECT_CODE"),
        "manual_source": os.environ.get("GENSHIN_MANUAL_SOURCE_CODE"),
        "assemble": os.environ.get("GENSHIN_ASSEMBLE_CODE"),
        "preview": os.environ.get("GENSHIN_PREVIEW_CODE"),
        "sandbox": os.environ.get("GENSHIN_SANDBOX_CODE"),
    }
    result = generate(args.root.resolve(), preview_file=args.preview, stage_results=stages)
    write(args.root.resolve(), result)
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))
    for pid, issue in result["notifications"].items():
        print(f"需人工复核 {pid}: {'; '.join(issue['reasons'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
