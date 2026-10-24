"""星铁 type=1 公告增量发现；保存原始文章并调用独立纯文本解析器。"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

from scripts.collect.collect_miyoushe_announcements import fetch, save_json

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data/derived/starrail/notice-discovery/notice-discovery_zh-CN_checkpoint.json"
REPORT = ROOT / "data/derived/starrail/notice-discovery/notice-discovery_zh-CN_report.json"
RAW = ROOT / "data/announcements/starrail/zh-cn/miyoushe/posts"
LIST = "https://bbs-api-static.miyoushe.com/painter/wapi/getNewsList"
DETAIL = "https://bbs-api.miyoushe.com/post/wapi/getPostFull"
PATTERN_WARP = re.compile(r"\d{1,2}\.\d{1,2}版本活动跃迁[（(]其[一二三四五六七八九][）)]")
PATTERN_UPDATE = re.compile(r"\d{1,2}\.\d{1,2}版本.*更新说明")

def kind(title):
    if PATTERN_WARP.search(title):
        return "warp_notice"
    if "联动跃迁" in title and "说明" in title and "测试" not in title:
        return "collab_notice"
    if PATTERN_UPDATE.search(title) and not any(x in title for x in ("云·", "云•", "云.", "云・")):
        return "version_update"
    return None

def state_new():
    return {"format": "starrail-notice-discovery-v1", "game": "starrail",
            "locale": "zh-CN", "anchors": [], "pending": {},
            "manualReview": {}, "completed": {}}

def state_load():
    if not STATE.exists():
        return state_new()
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("format") != "starrail-notice-discovery-v1" or not all(
        isinstance(state.get(k), t) for k, t in
        [("anchors", list), ("pending", dict), ("manualReview", dict), ("completed", dict)]
    ):
        raise ValueError("检查点非法，拒绝丢弃原有进度")
    return state

def page(cursor):
    data = fetch(LIST, {"gids": 6, "type": 1, "page_size": 20,
                        "last_id": cursor, "client_type": 4})["data"]
    entries = data.get("list")
    if not isinstance(entries, list) or not entries or not isinstance(data.get("is_last"), bool):
        raise ValueError("公告列表为空或格式无效，不能推进 checkpoint")
    posts = []
    for entry in entries:
        # 原神工具基于 game_id=2，星铁应使用独立验证而不是原样复用。
        p = entry.get("post") if isinstance(entry, dict) else None
        if not isinstance(p, dict) or not str(p.get("post_id", "")).isdigit():
            raise ValueError("列表中存在非法文章")
        if p.get("game_id") not in (None, "", 0, "0", 6, "6"):
            raise ValueError("发现其他游戏文章，拒绝推进")
        posts.append(p)
    nxt = str(data.get("last_id") or "")
    if not data["is_last"] and (not nxt or nxt == cursor):
        raise ValueError("公告游标没有推进")
    return posts, data["is_last"], nxt

def discover(anchors, max_pages):
    if not anchors:
        # 首轮只建立最新一页的检查锚点；不要求翻到站点最旧页，也不虚构“历史已抓完”。
        rows, _final, _nxt = page("")
        return [], [str(post["post_id"]) for post in rows]
    cursor, seen, fresh, known = "", [], [], set(anchors)
    visited = set()
    overlap = 0
    for _ in range(max_pages):
        if cursor in visited:
            raise ValueError("公告分页循环")
        visited.add(cursor)
        rows, final, nxt = page(cursor)
        for row in rows:
            pid = str(row["post_id"])
            if pid in seen:
                raise ValueError("公告分页存在重复 ID")
            seen.append(pid)
            if known and pid in known:
                overlap += 1
            else:
                overlap = 0
                fresh.append(row)
        if final or (known and overlap >= min(3, len(known))):
            return fresh, seen[:100]
        cursor = nxt
    raise ValueError("超过翻页上限，未与检查点重叠；拒绝推进")

def process(pid, entry):
    raw_path = RAW / (pid + ".json")
    if raw_path.exists():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        raw = fetch(DETAIL, {"post_id": pid, "gids": 6})
        from scripts.transform.starrail_notice_text_zh_cn import post_from_raw
        post_from_raw(raw, pid)
        save_json(raw_path, raw)
    modules = {"warp_notice": "scripts.transform.build_starrail_warp_notice_zh_cn",
               "version_update": "scripts.transform.build_starrail_version_update_zh_cn",
               "collab_notice": "scripts.transform.build_starrail_collab_notice_zh_cn"}
    module = modules[entry["kind"]]
    cmd = [sys.executable, "-m", module, "--post-id", pid, "--input", str(raw_path)]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(result.stderr[-3000:] or result.stdout[-3000:])
    if entry["kind"] == "warp_notice":
        output = ROOT / "data/derived/starrail/warp-notices" / ("warp-notice_zh-CN_" + pid + ".json")
        parsed = json.loads(output.read_text(encoding="utf-8"))
        if parsed["review"]["warnings"]:
            raise ValueError("; ".join(parsed["review"]["warnings"]))
    elif entry["kind"] == "collab_notice":
        output = ROOT / "data/derived/starrail/collab-notices" / ("collab-notice_zh-CN_" + pid + ".json")
        parsed = json.loads(output.read_text(encoding="utf-8"))
        if parsed["review"]["status"] == "needs_review":
            raise ValueError("; ".join(parsed["review"]["warnings"]))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--max-pages", type=int, default=15)
    p.add_argument("--retry-only", action="store_true")
    args = p.parse_args()
    state = state_load()
    if not args.retry_only:
        new, anchors = discover(state["anchors"], args.max_pages)
        # 首次运行只确立基线；回放需要单篇解析器指定文章 ID。
        if state["anchors"]:
            for post in reversed(new):
                pid = str(post["post_id"])
                k = kind(str(post.get("subject") or ""))
                if k and pid not in state["completed"] and pid not in state["manualReview"]:
                    state["pending"].setdefault(pid, {"kind": k, "title": post["subject"],
                                                       "attempts": 0})
        state["anchors"] = anchors
    report = {"completed": [], "manualReview": [], "pending": [], "baseline": not bool(state["completed"] or state["pending"] or state["manualReview"])}
    for pid, entry in list(state["pending"].items()):
        try:
            process(pid, entry)
        except Exception as exc:
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            entry["lastError"] = str(exc)
            # 非网络脚本异常不得盲目每日重试，人工复核后才能恢复。
            message = str(exc)
            retryable = any(part in message for part in (
                "Timeout", "URLError", "Connection", "RemoteDisconnected",
                "HTTP Error 408", "HTTP Error 429", "HTTP Error 500",
                "HTTP Error 502", "HTTP Error 503", "HTTP Error 504",
                "Too Many Requests", "RateLimited"))
            if not retryable:
                state["manualReview"][pid] = {**entry, "error": str(exc)}
                del state["pending"][pid]
                report["manualReview"].append(pid)
            else:
                report["pending"].append(pid)
        else:
            state["completed"][pid] = {"kind": entry["kind"], "title": entry["title"]}
            del state["pending"][pid]
            report["completed"].append(pid)
    save_json(STATE, state)
    save_json(REPORT, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
