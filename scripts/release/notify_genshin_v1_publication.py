"""维护原神 v1 发布阶段的 GitHub Issues；仅在问题变化时由机器人评论提醒。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from scripts.collect.notify_genshin_notice_problems import gh

PREFIX = "[原神 v1 发布复核]"


def problem_key(item: dict) -> str:
    pid = item.get("postId")
    if pid:
        return f"公告 #{pid}"
    bid = item.get("id")
    if bid:
        return f"已有卡池 {bid}"
    return f"人工配置 {item.get('file', '未知')}"


def problems_from_result(report: dict, failed: bool) -> dict[str, list[str]]:
    issues: dict[str, list[str]] = {}
    for entry in report.get("rejected") or []:
        key = problem_key(entry)
        issues.setdefault(key, []).append(str(entry.get("error") or "原因未知"))
    for item in report.get("unmatchedUpcoming") or []:
        if item.get("reason") == "existing_pool_not_overwritten":
            key = f"人工配置 {item.get('file', '未知')}#{item.get('index', '?')}"
            issues.setdefault(key, []).append("新池已经存在，但 upcoming 值未被应用；"
                                              "请使用 existing 按内部 ID 定向修订")
    if failed:
        issues["发布工作流"] = ["v1 发布链发生运行失败，请检查 Actions 日志；"
                            "不能将私有 v1 提交成功等同于公开仓库已经同步"]
    return issues


def sync(repo: str, owner: str, report: dict, *, failed: bool,
         run_url: str, dry_run: bool = False) -> dict:
    issues = problems_from_result(report, failed)
    out = {"problems": len(issues), "created": [], "changed": [], "closed": []}
    if dry_run:
        out["issues"] = issues
        return out
    existing = json.loads(gh("issue", "list", "--repo", repo, "--state", "all",
                             "--limit", "1000", "--json", "number,title,state,body"))
    by_title = {x["title"]: x for x in existing if x.get("title", "").startswith(PREFIX)}
    for key, reasons in sorted(issues.items()):
        title = f"{PREFIX} {key}"
        message = "\n".join("- " + x for x in sorted(set(reasons)))
        digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:20]
        marker = f"<!-- genshin-v1-release-fingerprint:{digest} -->"
        body = f"## 需要处理\n\n{marker}\n\n{message}\n\nAction：{run_url}\n"
        old = by_title.get(title)
        if old is None:
            gh("issue", "create", "--repo", repo, "--title", title,
               "--body", body, "--assignee", owner)
            out["created"].append(key)
        else:
            number = str(old["number"])
            reopened = old.get("state", "").upper() == "CLOSED"
            if reopened:
                gh("issue", "reopen", number, "--repo", repo)
            if reopened or marker not in (old.get("body") or ""):
                gh("issue", "edit", number, "--repo", repo, "--body", body)
                gh("issue", "comment", number, "--repo", repo,
                   "--body", "原神 v1 发布复核问题发生变化或再次出现。\n\n" + message
                             + "\n\nAction：" + run_url)
                out["changed"].append(key)
    if not failed:
        for title, old in by_title.items():
            if title not in {f"{PREFIX} {k}" for k in issues} and old.get("state", "").upper() == "OPEN":
                num = str(old["number"])
                gh("issue", "comment", num, "--repo", repo,
                   "--body", "最新发布检查已通过，原问题消失；自动关闭。")
                gh("issue", "close", num, "--repo", repo, "--reason", "completed")
                out["closed"].append(title)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, default=Path("/tmp/genshin-v1-publish.json"))
    parser.add_argument("--failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.failure and not args.result.is_file():
        raise FileNotFoundError("成功发布流程缺少结果报告，拒绝自动关闭旧 Issue")
    report = json.loads(args.result.read_text(encoding="utf-8")) if args.result.is_file() else {}
    if not isinstance(report, dict):
        raise ValueError("发布报告格式无效")
    repo, owner = os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_REPOSITORY_OWNER", "")
    if not args.dry_run and (not repo or not owner):
        raise ValueError("缺少 GitHub 仓库环境变量")
    run_url = f"https://github.com/{repo}/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}"
    print(json.dumps(sync(repo, owner, report, failed=args.failure,
                          run_url=run_url, dry_run=args.dry_run), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
