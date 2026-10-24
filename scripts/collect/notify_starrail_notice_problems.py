"""星铁公告和发布异常的 GitHub Issue 通知（按稳定身份去重）。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
STATE = Path("data/derived/starrail/notice-discovery/notice-discovery_zh-CN_checkpoint.json")
READINESS = Path("data/derived/starrail/v1-readiness/v1-readiness_zh-CN.json")
PREFIX = "[星铁公告复核] "

def read(path):
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def problems(root=ROOT, publication=None):
    state = read(root / STATE)
    readiness = read(root / READINESS)
    if not state and not readiness:
        raise ValueError("检查点和最终核对报告同时缺失，不得空集合结清历史 Issue")
    out = {}
    for pid, record in (state.get("manualReview") or {}).items():
        out["post-" + pid] = {
            "type": "manualReview", "postId": pid, "error": record.get("error"),
            "title": record.get("title")}
    for pid, record in (state.get("pending") or {}).items():
        if int(record.get("attempts", 0)) >= 3:
            out["pending-" + pid] = {
                "type": "pending", "postId": pid,
                "warning": "同一文章连续三次以上遇到临时网络失败；已保留待重试队列"}
    resolved = set()
    for row in readiness.get("rows", []):
        if row.get("status") in {"ready_candidate", "already_published"} and row.get("manualRecovery"):
            resolved.add(row["sourceKey"].split("-", 1)[0])
        key = row.get("sourceKey")
        if row.get("status") == "needs_review" and key:
            out["pool-" + key] = {
                "type": "pool", "sourceKey": key, "version": row.get("version"),
                "phase": row.get("phase"), "bannerName": row.get("bannerName"),
                "issues": row.get("issues")}
        if row.get("publishedDifferences"):
            out["published-" + key] = {
                "type": "published_mismatch", "sourceKey": key,
                "existingId": row.get("existingId"),
                "differences": row.get("publishedDifferences")}
    for pid in resolved:
        out.pop("post-" + pid, None)
    for row in readiness.get("unparsedNotices", []):
        if row.get("type") == "waiting_identity":
            continue  # 官方原文无版本或期数，正常等待人工身份，不是解析错误。
        pid = str(row.get("postId"))
        if pid not in resolved:
            out["unparsed-" + pid] = {"type": "unparsed", "postId": pid,
                                    "issues": row.get("issues")}
    if publication:
        for i, row in enumerate(publication.get("rejected", [])):
            identifier = str(row.get("identity") or row.get("id") or row.get("file") or i)
            key = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:14]
            out["publish-" + key] = {"type": "publication", "item": row}
    return out

def fingerprint(info):
    return hashlib.sha256(json.dumps(info, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

def gh(*args, repository):
    res = subprocess.run(["gh", *args, "--repo", repository], capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {res.stderr[-1000:]}")
    return res.stdout.strip()

def notify(root, repository, owner, run_url, publication=None, *, dry_run=False):
    target = problems(root, publication)
    if dry_run:
        return {"wouldOpenOrUpdate": list(target), "total": len(target)}
    if not repository or not owner:
        raise ValueError("通知必须给出仓库和管理员")
    existing = json.loads(gh("issue", "list", "--state", "all", "--limit", "1000",
                             "--json", "number,title,state,body", repository=repository) or "[]")
    by_title = {issue["title"]: issue for issue in existing if issue["title"].startswith(PREFIX)}
    created, updated, closed, unchanged = [], [], [], []
    for key, info in sorted(target.items()):
        title = PREFIX + key
        digest = fingerprint(info)
        body = ("<!-- starrail-fingerprint:" + digest + " -->\n"
                + "### 星铁自动采集／发布复核\n\n"
                + "问题身份：" + key + "\n\n"
                + "JSON 诊断数据：\n\n"
                + json.dumps(info, ensure_ascii=False, indent=2) + "\n\n"
                + "运行记录：" + (run_url or "GitHub Actions") + "\n\n"
                + "请核实数据、记录处理结论，再由后续成功运行结清。")
        issue = by_title.get(title)
        if issue is None:
            output = gh("issue", "create", "--title", title, "--body", body,
                        "--assignee", owner, repository=repository)
            created.append({"key": key, "url": output})
        elif issue["state"] != "OPEN":
            gh("issue", "reopen", str(issue["number"]), repository=repository)
            gh("issue", "edit", str(issue["number"]), "--body", body,
               "--add-assignee", owner, repository=repository)
            gh("issue", "comment", str(issue["number"]), "--body",
               "问题重新出现或再次核对仍不一致，已重新开启。", repository=repository)
            updated.append(key)
        elif ("<!-- starrail-fingerprint:" + digest + " -->") not in issue.get("body", ""):
            gh("issue", "edit", str(issue["number"]), "--body", body,
               "--add-assignee", owner, repository=repository)
            gh("issue", "comment", str(issue["number"]), "--body",
               "重新采集或发布后问题内容发生变化，已更新诊断。", repository=repository)
            updated.append(key)
        else:
            unchanged.append(key)
    for title, issue in by_title.items():
        if issue["state"] == "OPEN" and title.removeprefix(PREFIX) not in target:
            gh("issue", "close", str(issue["number"]), "--comment",
               "星铁本次采集与正式候选核对均未再报告此问题，自动结清。", repository=repository)
            closed.append(title)
    return {"opened": created, "updated": updated, "closed": closed,
            "unchanged": unchanged, "totalProblems": len(target)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--publication-report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner = repo.split("/")[0] if "/" in repo else ""
    publish = read(args.publication_report) if args.publication_report else None
    run_url = "https://github.com/" + repo + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", "")
    print(json.dumps(notify(ROOT, repo, owner, run_url, publish,
                            dry_run=args.dry_run), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
