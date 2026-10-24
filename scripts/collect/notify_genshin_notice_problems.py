#!/usr/bin/env python3
"""为原神简中采集与整合异常创建去重 GitHub Issue；正常 waiting 不通知。

Actions 使用仓库 GITHUB_TOKEN (issues: write)；同一公告的 Issue 只建立一次。
--dry-run 可以离线验证通知内容，不访问 GitHub。
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = Path("data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json")
READINESS = Path("data/derived/genshin/v1-readiness/v1-readiness_zh-CN.json")
PREFIX = "[原神简中公告人工复核]"


def load(path: Path) -> dict:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON 根必须为对象")
    return value


FINAL = Path("data/derived/genshin/v1-readiness/v1-final-review_zh-CN.json")


def final_notices_to_review(root: Path) -> dict[str, dict]:
    """最终 v1 门槛的诊断才有通知资格；已靠人工补齐的问题不再提醒。"""
    report = load(root / FINAL)
    result = {}
    for pid, item in (report.get("notifications") or {}).items():
        differences = item.get("differences") or []
        details = []
        for difference in differences:
            details.append("字段 {field}：自动={auto}，人工={manual}".format(
                field=difference.get("field"),
                auto=json.dumps(difference.get("automatic"), ensure_ascii=False),
                manual=json.dumps(difference.get("manual"), ensure_ascii=False)))
        reason = list(item.get("reasons") or []) + details
        files = [x for x in (item.get("file"), item.get("manualFile")) if x]
        result[pid] = {"reasons": reason, "files": files,
                       "severity": item.get("severity", "blocking")}
    return result


def notices_to_review(root: Path = ROOT) -> dict[str, dict]:
    state, readiness = load(root / CHECKPOINT), load(root / READINESS)
    issues: dict[str, dict] = defaultdict(lambda: {"reasons": [], "files": []})

    for post_id, entry in (state.get("manualReview") or {}).items():
        if not isinstance(entry, dict):
            raise ValueError(f"manualReview[{post_id}] 格式无效")
        item = issues[str(post_id)]
        item["reasons"].append("单篇采集/解析异常：" + str(entry.get("reason") or "原因未知"))
        if entry.get("outputFile"):
            item["files"].append(str(entry["outputFile"]))

    for row in readiness.get("notices", []):
        if not isinstance(row, dict):
            continue
        pid = str(row.get("postId") or "")
        if not re.fullmatch(r"\d+", pid):
            continue
        status = row.get("status")
        if status == "conflict":
            issues[pid]["reasons"].append("跨公告整合冲突：" + ", ".join(map(str, row.get("issues") or [])))
            if row.get("noticeFile"):
                issues[pid]["files"].append(str(row["noticeFile"]))
        elif status == "waiting" and "waiting_ocr_end_time" in (row.get("issues") or []):
            # 历史 checkpoint 可能已标完成，但 OCR 未识别。只报告确定的 OCR 故障。
            source = row.get("noticeFile")
            notice = load(root / source) if isinstance(source, str) and source else {}
            recognition = notice.get("imageTimeRecognition") or {}
            if recognition.get("status") in {"error", "unresolved", "conflict"}:
                issues[pid]["reasons"].append(
                    "OCR 无法识别可靠时间：" + str(recognition.get("status")) +
                    "；" + "; ".join(map(str, recognition.get("warnings") or []))
                )
                issues[pid]["files"].append(source)

    for err in readiness.get("sourceErrors", []):
        source = str(err.get("file") or "")
        match = re.search(r"_(\d+)\.json$", source)
        key = match.group(1) if match else "workflow-assemble"
        issues[key]["reasons"].append("候选来源 JSON 损坏：" + str(err.get("error")))
        issues[key]["files"].append(source)

    # 集成/导入器崩溃没有对应文章时也需通知。
    stage_results = {
        "collect": os.environ.get("GENSHIN_COLLECT_CODE"),
        "manual_source": os.environ.get("GENSHIN_MANUAL_SOURCE_CODE"),
        "assemble": os.environ.get("GENSHIN_ASSEMBLE_CODE"),
        "preview": os.environ.get("GENSHIN_PREVIEW_CODE"),
    }
    for stage, code in stage_results.items():
        if code in (None, "", "0"):
            continue
        if stage == "collect" and (state.get("pending") or {}):
            # 临时网络问题仍在 pending，等待下次重试，避免每日额外告警。
            continue
        issues[f"workflow-{stage}"]["reasons"].append(
            f"自动流程阶段 {stage} 退出码 {code}，请检查本次 GitHub Actions 日志"
        )
    return {pid: info for pid, info in issues.items() if info["reasons"]}


def issue_title(pid: str) -> str:
    if pid.startswith("workflow-"):
        return f"{PREFIX} 流程异常 {pid.removeprefix('workflow-')}"
    return f"{PREFIX} 公告 #{pid}"


def fingerprint(info: dict) -> str:
    stable = {"reasons": sorted(set(info.get("reasons") or [])),
              "files": sorted(set(info.get("files") or [])),
              "severity": info.get("severity", "blocking")}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def issue_body(pid: str, info: dict, run_url: str) -> str:
    reasons = "\n".join(f"- {x}" for x in dict.fromkeys(info["reasons"]))
    files = "\n".join(f"- `{x}`" for x in dict.fromkeys(info["files"])) or "- 请检查 checkpoint 与 v1-readiness"
    url = f"https://www.miyoushe.com/ys/article/{pid}" if pid.isdecimal() else "非单篇公告异常"
    grade = "非关键提醒（不阻断发布）" if info.get("severity") == "warning" else "需要人工复核"
    marker = f"<!-- genshin-notice-fingerprint:{fingerprint(info)} -->"
    return (f"## {grade}\n\n{marker}\n\n公告：{url}\n\n### 异常原因\n{reasons}\n\n"
            f"### 相关文件\n{files}\n\n"
            f"Action：{run_url or '未指定'}\n\n"
            "正常等待其他公告不报警。若为人工差异，请检查自动值与人工值。"
            "阻断问题解决后可恢复；非关键提醒不阻断发布。"
            "本通知流程不会直接修改 public/v1。\n")


def gh(*args: str) -> str:
    output = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return output.stdout.strip()


def notify(root: Path, repository: str, owner: str, run_url: str, *, dry_run: bool) -> dict:
    if os.environ.get("GENSHIN_FINAL_REPORT_ONLY") == "1" and not (root / FINAL).is_file():
        raise RuntimeError("缺少 v1 最终复核报告，禁止退回旧的解析阶段通知")
    problems = (final_notices_to_review(root) if (root / FINAL).is_file() else notices_to_review(root))
    result = {"total": len(problems), "created": [], "existing": [],
              "updated": [], "reopened": [], "closed": [], "dryRun": dry_run}
    healthy = (root / FINAL).is_file() and all(
        os.environ.get(key) == "0"
        for key in ("GENSHIN_COLLECT_CODE", "GENSHIN_MANUAL_SOURCE_CODE", "GENSHIN_ASSEMBLE_CODE",
                    "GENSHIN_PREVIEW_CODE", "GENSHIN_SANDBOX_CODE"))
    if dry_run or (not problems and not healthy):
        result["candidates"] = [
            {"title": issue_title(pid), "body": issue_body(pid, info, run_url)}
            for pid, info in sorted(problems.items())
        ]
        return result
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GITHUB_REPOSITORY 缺失或无效")
    if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
        raise ValueError("GITHUB_REPOSITORY_OWNER 缺失或无效")

    # 同一公告无论 OCR、内容冲突还是脚本错误，都复用同一个 Issue。
    existing = json.loads(gh("issue", "list", "--repo", repository, "--state", "all",
                             "--limit", "1000", "--json", "number,title,state,body"))
    managed = {item["title"]: item for item in existing
               if item.get("title", "").startswith(PREFIX)}
    for pid, info in sorted(problems.items()):
        title = issue_title(pid)
        issue = managed.get(title)
        body = issue_body(pid, info, run_url)
        if issue is None:
            link = gh("issue", "create", "--repo", repository, "--title", title,
                      "--body", body, "--assignee", owner)
            result["created"].append({"postId": pid, "url": link})
            continue
        number = str(issue["number"])
        result["existing"].append({"postId": pid, "issue": issue["number"]})
        reopened = issue.get("state", "").upper() == "CLOSED"
        if reopened:
            gh("issue", "reopen", number, "--repo", repository)
            result["reopened"].append(issue["number"])
        marker = f"<!-- genshin-notice-fingerprint:{fingerprint(info)} -->"
        changed = marker not in (issue.get("body") or "")
        if changed:
            gh("issue", "edit", number, "--repo", repository, "--body", body)
            # 机器人对已订阅 Issue 的新评论已通过实测可触发邮件；
            # 仅新问题或变化时评论，避免每天重复发信。
            gh("issue", "comment", number, "--repo", repository, "--body",
               "自动检查发现问题" + ("再次出现" if reopened else "发生变化")
               + "，已更新 Issue 正文。\n\n"
               + "\n".join("- " + line for line in info.get("reasons", []))
               + (f"\n\nAction：{run_url}" if run_url else ""))
            result["updated"].append(issue["number"])
    # 仅完整、可信的本轮最终诊断有权关闭问题，避免上游阶段崩溃时误关闭历史 Issue。
    if healthy:
        expected = {issue_title(pid) for pid in problems}
        for issue in managed.values():
            if issue["title"] not in expected and issue.get("state", "").upper() == "OPEN":
                number = str(issue["number"])
                gh("issue", "comment", number, "--repo", repository,
                   "--body", "最新的完整 v1 安全预览已确认此问题不再存在；自动关闭。")
                gh("issue", "close", number, "--repo", repository,
                   "--reason", "completed")
                result["closed"].append(issue["number"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    url = f"https://github.com/{repo}/actions/runs/{run_id}" if repo and run_id else ""
    result = notify(args.root, repo, owner, url, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
