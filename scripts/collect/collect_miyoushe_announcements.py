#!/usr/bin/env python3
"""Resumable, manually-triggered archive of original Genshin Chinese notices.

The news API's cursor is committed together with raw pages and full post JSON.
This program never writes public/v1 or mixes games/languages in one archive.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.client import HTTPException
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from scripts.transform.analyze_miyoushe_banner_notices import banner_candidate
    from scripts.transform.select_miyoushe_version_notices import version_notice_candidate, version_notice_kind
except ImportError:  # Executed as python scripts/collect/collect_miyoushe_announcements.py
    from scripts.transform.analyze_miyoushe_banner_notices import banner_candidate
    from scripts.transform.select_miyoushe_version_notices import version_notice_candidate, version_notice_kind

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "data/announcements/genshin/zh-cn/miyoushe"
SOURCE_URL = "https://www.miyoushe.com/ys/home/28?type=1"
GAME = "genshin"
GAME_ID = 2
TZ8 = timezone(timedelta(hours=8))
PAGE_SOURCES = (
    ("https://bbs-api-static.miyoushe.com/painter/wapi/getNewsList", True),
    ("https://bbs-api.mihoyo.com/post/wapi/getNewsList", False),
    ("https://api-takumi.mihoyo.com/post/wapi/getNewsList", False),
)
DETAIL_SOURCES = (
    "https://bbs-api.miyoushe.com/post/wapi/getPostFull",
    "https://bbs-api.mihoyo.com/post/wapi/getPostFull",
)
# Historical archiver can write complete official posts. Never permit that old
# Git-push mode in Public, even when the CLI is bypassed and git_commit() is called
# directly. GitHub Actions always sets GITHUB_REPOSITORY; local clones are checked
# by their actual origin remote. Unknown remotes fail closed.
PRIVATE_DEV_REPOSITORY = "sirarikako/castoricewishbannerdata"


def archive_git_write_allowed() -> bool:
    current = os.environ.get("GITHUB_REPOSITORY", "").strip().lower()
    if current and current != PRIVATE_DEV_REPOSITORY:
        return False
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=REPO_ROOT,
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    # Exact repository, not a name substring or a fork.
    return bool(re.fullmatch(
        r"(?:(?:https?|ssh)://(?:git@)?|git@)github\.com[:/]"
        r"sirarikako/CastoriceWishBannerData(?:\.git)?/?",
        result.stdout.strip(), flags=re.IGNORECASE,
    ))


def require_private_archive_git_write() -> None:
    if not archive_git_write_allowed():
        raise PermissionError(
            "旧公告归档的 Git 提交仅允许 Private 开发仓库；"
            "Public/未知仓库禁止 --commit-progress 或直接 git_commit"
        )


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CastoriceWishBannerData/1.0)",
    "Accept": "application/json",
    "Referer": "https://www.miyoushe.com/",
    "x-rpc-client_type": "4",
}
MAX_RESPONSE = 12 * 1024 * 1024
TERMINATE = False


class VerificationRequired(RuntimeError):
    """The provider requires a human captcha challenge (retcode 1034)."""


class RateLimited(RuntimeError):
    """HTTP 429; do not bypass or aggressively retry this response."""



def log(message: str) -> None:
    print(datetime.now(TZ8).strftime("%Y-%m-%d %H:%M:%S +08:00"), message, flush=True)


def handle_signal(_signum, _frame) -> None:
    global TERMINATE
    TERMINATE = True
    log("Shutdown requested; stopping at next safe checkpoint")


def fetch(url: str, params: dict, retries: int = 3, timeout: int = 15) -> dict:
    full_url = url + "?" + urlencode(params)
    last = None
    for attempt in range(retries):
        if TERMINATE:
            raise InterruptedError("Cancellation requested")
        try:
            with urlopen(Request(full_url, headers=HEADERS), timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ValueError("Response exceeds byte limit")
            body = json.loads(raw)
            if isinstance(body, dict) and body.get("retcode") == 1034:
                raise VerificationRequired("Miyoushe requires captcha verification (retcode 1034)")
            if not isinstance(body, dict) or body.get("retcode") != 0 or not isinstance(body.get("data"), dict):
                raise ValueError("Unexpected API response: " + str(body)[:300])
            return body
        except HTTPError as exc:
            if exc.code == 429:
                raise RateLimited("Miyoushe HTTP 429 Too Many Requests") from exc
            last = exc
            if exc.code in (400, 401, 403, 404, 410):
                break  # A permanently invalid endpoint must not retry for minutes.
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError, HTTPException) as exc:
            last = exc
        if attempt < retries - 1:
            time.sleep(1.5 * (2**attempt))
    # Preserve the transport cause so the active Genshin scanner can distinguish
    # a transient network failure from malformed data, HTTP 4xx or verification.
    raise RuntimeError(f"{full_url} -> {type(last).__name__}: {last}") from last


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def post_from_entry(entry: dict) -> dict:
    if not isinstance(entry, dict) or not isinstance(entry.get("post"), dict):
        raise ValueError("Invalid news-list entry")
    post = entry["post"]
    pid = str(post.get("post_id", ""))
    if not pid.isdecimal():
        raise ValueError("Missing numeric post_id")
    # News posts returned by the Genshin-scoped (gids=2, type=1)
    # official news endpoint may use game_id=0 (unclassified/global notice).
    # Do NOT mistake this legacy sentinel for a different game. A positive
    # foreign game ID remains forbidden and is never archived here.
    game_id = post.get("game_id")
    if game_id not in (None, "", 0, "0", GAME_ID, str(GAME_ID)):
        raise ValueError(f"Cross-game post {pid}: {game_id} != {GAME_ID}")
    return post


def validate_detail(response: dict, pid: str) -> dict:
    try:
        post = response["data"]["post"]["post"]
    except (TypeError, KeyError):
        raise ValueError("Missing full post object") from None
    if not isinstance(post, dict) or str(post.get("post_id")) != pid:
        raise ValueError("Mismatched post_id")
    # The same game_id=0 sentinel occurs in full-post API responses.
    # Preserve the raw ID unchanged; only reject explicitly foreign games.
    if post.get("game_id") not in (None, "", 0, "0", GAME_ID, str(GAME_ID)):
        raise ValueError("Wrong game ID in detail")
    if not isinstance(post.get("subject"), str) or not post["subject"]:
        raise ValueError("Missing post title")
    if not any(post.get(field) for field in ("content", "structured_content", "images")):
        raise ValueError("Missing full post content")
    return post


def read_pages(folder: Path) -> tuple[list[dict], dict, str, bool, set[str]]:
    """Reconstruct cursor from files, not from potentially stale index/checkpoint."""
    pages = []
    seen_posts: dict[str, dict] = {}
    all_cursors = set()
    cursor = ""
    last_page = False
    page_paths = sorted((folder / "pages").glob("*.json"))
    for expected, path in enumerate(page_paths, 1):
        if path.name != f"{expected:06d}.json":
            raise ValueError("Missing archive page before " + path.name)
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        params = wrapper["params"]
        response = wrapper["response"]
        if str(params.get("last_id", "")) != cursor or str(params.get("gids")) != "2":
            raise ValueError("Archived cursor/game mismatch in " + path.name)
        data = response["data"]
        if not isinstance(data.get("list"), list) or not isinstance(data.get("is_last"), bool):
            raise ValueError("Invalid cached page " + path.name)
        if last_page:
            raise ValueError("Extra page after terminal page " + path.name)
        for entry in data["list"]:
            post = post_from_entry(entry)
            seen_posts[str(post["post_id"])] = post
        pages.append(wrapper)
        last_page = data["is_last"]
        if not last_page:
            next_cursor = str(data.get("last_id") or "")
            if not next_cursor or next_cursor == cursor or next_cursor in all_cursors:
                raise ValueError("Invalid cached next cursor in " + path.name)
            all_cursors.add(cursor)
            cursor = next_cursor
    return pages, seen_posts, cursor, last_page, all_cursors


def utc8_date(post: dict) -> str | None:
    try:
        return datetime.fromtimestamp(int(post["created_at"]), TZ8).isoformat(timespec="seconds")
    except (ValueError, KeyError, TypeError, OverflowError, OSError):
        return None


class Collector:
    def __init__(self, folder: Path, *, commit_progress: bool = False,
                 batch_size: int = 50, checkpoint_seconds: int = 120,
                 max_minutes: int = 90, max_pages: int = 2000,
                 max_detail_failures: int = 6, stage: str = "all",
                 max_detail_requests: int = 0):
        if stage not in ("list", "details", "all", "banner-details", "version-details"):
            raise ValueError("Unsupported collection stage")
        if commit_progress:
            require_private_archive_git_write()
        self.stage = stage
        self.folder = folder
        self.commit_progress = commit_progress
        self.batch_size = batch_size
        self.checkpoint_seconds = checkpoint_seconds
        self.max_minutes = max_minutes
        self.max_pages = max_pages
        self.max_detail_failures = max_detail_failures
        if max_detail_requests < 0:
            raise ValueError("max_detail_requests cannot be negative")
        self.max_detail_requests = max_detail_requests
        self.details_attempted = 0
        self.detail_budget_exhausted = False
        self.start = time.monotonic()
        self.last_commit = time.monotonic()
        self.new_files = 0
        self.errors: list[str] = []
        self.list_errors: list[str] = []
        self.detail_errors: dict[str, str] = {}
        self.pages: list[dict] = []
        self.posts: dict[str, dict] = {}
        self.cursor = ""
        self.last_page = False
        self.list_exhausted = False
        self.list_end_basis: str | None = None
        self.seen_cursors: set[str] = set()
        self.source: tuple[str, bool] | None = None
        self.interrupted = False
        self.detail_paused = False
        self.pause_reason: str | None = None
        self.request_delay = 2.0  # Conservative spacing; no retry if challenged.

    def timed_out(self) -> bool:
        return TERMINATE or (time.monotonic() - self.start) >= 60 * self.max_minutes

    def detail_file(self, pid: str) -> Path:
        return self.folder / "posts" / f"{pid}.json"

    def is_valid_detail(self, pid: str) -> bool:
        path = self.detail_file(pid)
        if not path.is_file():
            return False
        try:
            validate_detail(json.loads(path.read_text(encoding="utf-8")), pid)
            return True
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False

    def load(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.pages, self.posts, self.cursor, self.last_page, self.seen_cursors = read_pages(self.folder)
        if self.pages:
            url = self.pages[0]["apiUrl"]
            self.source = next((x for x in PAGE_SOURCES if x[0] == url), None)
            if self.source is None:
                raise ValueError("Unknown archived API source " + str(url))
            if any(p.get("apiUrl") != url for p in self.pages):
                raise ValueError("Archived pages used inconsistent API sources")
        self.list_exhausted = self.last_page
        self.list_end_basis = "api_is_last" if self.last_page else None
        terminal_path = self.folder / "end-probe.json"
        if terminal_path.exists():
            # A confirmed terminal probe is part of the archival evidence.
            # Never rely on the summary/checkpoint alone for completion.
            if self.last_page or not self.pages or self.source is None:
                raise ValueError("Terminal probe conflicts with archived pages")
            probe = json.loads(terminal_path.read_text(encoding="utf-8"))
            before = probe.get("response", {}).get("data", {})
            after = probe.get("confirmation", {}).get("data", {})
            previous = self.pages[-1]["response"]["data"]["list"]
            early = any((utc8_date(p) or "9999")[:10] <= "2020-09-30"
                        for p in self.posts.values())
            if (probe.get("apiUrl") != self.source[0]
                    or str(probe.get("params", {}).get("last_id", "")) != self.cursor
                    or not (0 < len(previous) < 20) or not early
                    or before.get("list") != [] or before.get("is_last") is not False
                    or after.get("list") != [] or after.get("is_last") is not False):
                raise ValueError("Terminal probe cannot be verified from saved page chain")
            self.list_exhausted = True
            self.list_end_basis = "confirmed_empty_after_short_page"
        log(f"恢复断点: 已保存 {len(self.pages)} 页, 列表去重 {len(self.posts)} 篇, "
            f"API到末页={self.last_page}, 推定列表到底={self.list_exhausted}")

    def get_page(self) -> dict:
        candidates = (self.source,) if self.source is not None else PAGE_SOURCES
        failures = []
        for url, needs_client in candidates:
            params = {"gids": GAME_ID, "type": 1, "page_size": 20, "last_id": self.cursor}
            if needs_client:
                params["client_type"] = 4
            try:
                response = fetch(url, params)
                data = response["data"]
                if not isinstance(data.get("list"), list) or not isinstance(data.get("is_last"), bool):
                    raise ValueError("No list/is_last fields in news API")
                if not data["list"] and not data["is_last"]:
                    # This provider may return 15 posts on the last page,
                    # followed by an empty page with is_last=false. Require
                    # all three: a short previous page, coverage before
                    # 2020-09-30, and an independent empty confirmation.
                    previous = (self.pages[-1]["response"]["data"]["list"]
                                if self.pages else [])
                    early = any((utc8_date(p) or "9999")[:10] <= "2020-09-30"
                                for p in self.posts.values())
                    if not (0 < len(previous) < 20 and early):
                        raise ValueError("Empty non-terminal page without terminal evidence")
                    time.sleep(1.0)
                    confirmation = fetch(url, params)
                    second = confirmation["data"]
                    if not isinstance(second.get("list"), list) or not isinstance(second.get("is_last"), bool):
                        raise ValueError("Invalid confirmation response")
                    if second["list"] == [] and second["is_last"] is False:
                        return {"apiUrl": url, "params": params, "response": response,
                                "terminalProbe": True, "confirmation": confirmation}
                    # A temporary empty response must not terminate an archive.
                    response, data = confirmation, second
                if not data["is_last"]:
                    nxt = str(data.get("last_id") or "")
                    if not nxt or nxt == self.cursor or nxt in self.seen_cursors:
                        raise ValueError("Invalid or repeated list cursor")
                for entry in data["list"]:
                    post_from_entry(entry)
                return {"apiUrl": url, "params": params, "response": response}
            except (VerificationRequired, RateLimited):
                # An access challenge is not evidence that another host
                # is safe or appropriate to try.
                raise
            except Exception as exc:
                failures.append(str(exc))
                if self.source is not None:
                    break  # Do not swap providers mid-scan.
        raise RuntimeError("No usable news API: " + " | ".join(failures))

    def store_page(self, wrapper: dict) -> None:
        if wrapper.get("terminalProbe") is True:
            if self.list_exhausted or self.last_page:
                raise ValueError("Duplicate terminal list probe")
            save_json(self.folder / "end-probe.json", wrapper)
            self.list_exhausted = True
            self.list_end_basis = "confirmed_empty_after_short_page"
            self.new_files += 1
            log(f"第 {len(self.pages)+1} 页连续两次为空：上页不足20篇且已有2020年前公告；"
                "保留原始证据，将列表标记为推定到底（非 API is_last=true）")
            return
        page_number = len(self.pages) + 1
        data = wrapper["response"]["data"]
        fingerprint = {str(post_from_entry(e)["post_id"]) for e in data["list"]}
        if fingerprint and fingerprint.issubset(self.posts):
            raise ValueError("Page adds zero new post IDs; refusing false completion")
        save_json(self.folder / "pages" / f"{page_number:06d}.json", wrapper)
        old_cursor = self.cursor
        self.pages.append(wrapper)
        self.source = next(x for x in PAGE_SOURCES if x[0] == wrapper["apiUrl"])
        for entry in data["list"]:
            post = post_from_entry(entry)
            self.posts[str(post["post_id"])] = post
        self.last_page = data["is_last"]
        if self.last_page:
            self.list_exhausted = True
            self.list_end_basis = "api_is_last"
        if not self.last_page:
            self.seen_cursors.add(old_cursor)
            self.cursor = str(data["last_id"])
        self.new_files += 1
        log(f"列表页 {page_number}: +{len(data['list'])} 条，累计去重 {len(self.posts)} 篇，下一游标 {self.cursor!r}，到末页={self.last_page}")

    def get_detail(self, pid: str) -> None:
        if self.is_valid_detail(pid):
            return
        if self.detail_paused:
            return
        failures = []
        for url in DETAIL_SOURCES:
            try:
                # Respect the site's request rate; do not try alternate hosts
                # when a captcha or HTTP 429 has been received.
                if not TERMINATE:
                    time.sleep(self.request_delay)
                body = fetch(url, {"gids": GAME_ID, "post_id": pid, "read": 1})
                validate_detail(body, pid)
                save_json(self.detail_file(pid), body)
                self.detail_errors.pop(pid, None)
                self.new_files += 1
                return
            except (VerificationRequired, RateLimited) as exc:
                self.detail_paused = True
                self.pause_reason = f"{type(exc).__name__}: {exc}"
                self.detail_errors[pid] = self.pause_reason
                log(f"正文暂缓 {pid}: {self.pause_reason}; 不再尝试绕过验证，本轮继续采集公告列表")
                return
            except Exception as exc:
                failures.append(str(exc))
        self.detail_errors[pid] = " | ".join(failures)
        log(f"正文失败 {pid}: {self.detail_errors[pid][:270]}")

    def list_quality(self) -> dict:
        seen = set()
        repeated = set()
        entries = 0
        timestamp_reversals = 0
        previous_timestamp = None
        short_nonterminal_pages = 0
        for page in self.pages:
            data = page["response"]["data"]
            items = data["list"]
            if len(items) < 20 and not data["is_last"]:
                short_nonterminal_pages += 1
            for entry in items:
                post = post_from_entry(entry)
                pid = str(post["post_id"])
                entries += 1
                if pid in seen:
                    repeated.add(pid)
                seen.add(pid)
                try:
                    stamp = int(post["created_at"])
                except (KeyError, ValueError, TypeError):
                    stamp = None
                if stamp is not None:
                    if previous_timestamp is not None and stamp > previous_timestamp:
                        timestamp_reversals += 1
                    previous_timestamp = stamp
        return {
            "rawListEntries": entries,
            "uniquePostIds": len(seen),
            "duplicatePostIdCount": entries - len(seen),
            "duplicatePostIdsSample": sorted(repeated)[:20],
            "createdAtOrderReversals": timestamp_reversals,
            "shortNonterminalPages": short_nonterminal_pages,
            "limitations": [
                "Offset-like last_id cursor can shift if the provider inserts or removes notices during collection",
                "Provider category does not prove all historically published or removed notices are available",
            ],
        }

    def flush(self, *, force_commit: bool = False) -> dict:
        rows = []
        for pid, post in self.posts.items():
            path = self.detail_file(pid)
            ok = self.is_valid_detail(pid)
            rows.append({"postId": pid, "title": post.get("subject"),
                         "createdAtUtc8": utc8_date(post),
                         "sourceUrl": f"https://www.miyoushe.com/ys/article/{pid}",
                         "rawFile": f"posts/{pid}.json" if ok else None,
                         "sha256": sha256(path.read_bytes()).hexdigest() if ok else None})
        rows.sort(key=lambda x: (x["createdAtUtc8"] or "", x["postId"]), reverse=True)
        earliest = min((r["createdAtUtc8"] for r in rows if r["createdAtUtc8"]), default=None)
        saved = sum(r["rawFile"] is not None for r in rows)
        missing = sorted(r["postId"] for r in rows if r["rawFile"] is None)
        reached_launch = bool(earliest and earliest[:10] <= "2020-09-30")
        # A later DETAIL failure must not revoke verified LIST coverage.
        list_complete = (self.list_exhausted and not self.list_errors and reached_launch and bool(rows))
        complete = list_complete and not missing
        banner_ids = [pid for pid, post in self.posts.items()
                      if banner_candidate(post.get("subject", ""))]
        banner_saved = sum(self.is_valid_detail(pid) for pid in banner_ids)
        version_ids = [pid for pid, post in self.posts.items()
                       if version_notice_candidate(post.get("subject", ""))]
        version_saved = sum(self.is_valid_detail(pid) for pid in version_ids)
        kind_counts = {}
        for pid in version_ids:
            kind = version_notice_kind(self.posts[pid].get("subject", ""))
            kind_counts.setdefault(kind, {"total": 0, "saved": 0})
            kind_counts[kind]["total"] += 1
            kind_counts[kind]["saved"] += int(self.is_valid_detail(pid))
        progress = {"format": "miyoushe-news-archive-progress-v2", "game": GAME,
                    "language": "zh-cn", "sourcePage": SOURCE_URL,
                    "listApi": self.source[0] if self.source else None,
                    "pagesSaved": len(self.pages), "nextCursor": None if self.list_exhausted else self.cursor,
                    "lastPageReached": self.last_page,
                    "listExhausted": self.list_exhausted,
                    "listEndBasis": self.list_end_basis,
                    "listComplete": bool(list_complete),
                    "collectionStage": self.stage,
                    "listedUniquePosts": len(rows),
                    "listQuality": self.list_quality(),
                    "fullPostsSaved": saved, "fullPostsMissing": len(missing),
                    "bannerCandidateNotices": len(banner_ids),
                    "bannerDetailsSaved": banner_saved,
                    "bannerDetailsMissing": len(banner_ids) - banner_saved,
                    "bannerDetailsComplete": bool(list_complete and banner_saved == len(banner_ids)),
                    "versionCandidateNotices": len(version_ids),
                    "versionDetailsSaved": version_saved,
                    "versionDetailsMissing": len(version_ids) - version_saved,
                    "versionDetailsComplete": bool(list_complete and version_saved == len(version_ids)),
                    "versionCandidateKinds": kind_counts,
                    "detailRequestsAttempted": self.details_attempted,
                    "detailRequestLimit": self.max_detail_requests or None,
                    "detailBudgetExhausted": self.detail_budget_exhausted,
                    "earliestUtc8": earliest, "reachesLaunch2020": reached_launch,
                    "complete": complete, "stopRequested": self.interrupted or TERMINATE,
                    "detailPaused": self.detail_paused,
                    "detailPauseReason": self.pause_reason,
                    "elapsedSeconds": round(time.monotonic() - self.start, 1),
                    "errors": self.errors,
                    "listErrors": self.list_errors,
                    # The index already identifies ALL missing IDs (rawFile=null).
                    # Only include actual request failures here, not 1,000+
                    # duplicated placeholders for never-attempted posts.
                    "detailErrors": {pid: error for pid, error in self.detail_errors.items()
                                     if pid in missing},
                    "lastCheckpointUtc8": datetime.now(TZ8).isoformat(timespec="seconds")}
        save_json(self.folder / "index.json", {"format": "miyoushe-news-index-v2",
                  "game": GAME, "language": "zh-cn", "source": SOURCE_URL,
                  "complete": complete, "listComplete": bool(list_complete), "posts": rows})
        save_json(self.folder / "collection-report.json", progress)
        # This file is a convenience; the true cursor is reconstructed from pages/.
        save_json(self.folder / "checkpoint.json", {
            "game": GAME, "language": "zh-cn", "savedPageCount": len(self.pages),
            "nextCursor": None if self.list_exhausted else self.cursor,
            "lastPageReached": self.last_page, "listExhausted": self.list_exhausted,
            "listEndBasis": self.list_end_basis,
            "updatedAtUtc8": progress["lastCheckpointUtc8"]})
        if self.commit_progress and (force_commit or self.new_files >= self.batch_size
                                     or time.monotonic() - self.last_commit >= self.checkpoint_seconds):
            self.git_commit()
        return progress

    def checkpoint_if_due(self) -> None:
        """Avoid repeatedly rebuilding/hashing the entire archive per post."""
        if (self.new_files >= self.batch_size or
                time.monotonic() - self.last_commit >= self.checkpoint_seconds):
            self.flush(force_commit=True)

    def git_commit(self) -> None:
        require_private_archive_git_write()
        rel = self.folder.resolve().relative_to(REPO_ROOT.resolve())
        subprocess.run(["git", "add", "-A", "--", str(rel)], cwd=REPO_ROOT, check=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet", "--", str(rel)], cwd=REPO_ROOT)
        if diff.returncode == 0:
            self.new_files = 0
            self.last_commit = time.monotonic()
            return
        if diff.returncode != 1:
            raise RuntimeError("git diff failed")
        subprocess.run(["git", "commit", "-m", f"Archive Genshin Chinese notices: {len(self.pages)} pages"],
                       cwd=REPO_ROOT, check=True, timeout=60)
        push = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=90)
        if push.returncode != 0:
            # Another workflow may have advanced main. Never force-push.
            # Rebase once, preserving both histories; on conflict abort and
            # fail visibly, leaving previously pushed checkpoints intact.
            log("GitHub main 已变化或推送失败，尝试安全同步一次（不强制推送）")
            subprocess.run(["git", "fetch", "origin", "main"], cwd=REPO_ROOT,
                           check=True, timeout=90)
            rebase = subprocess.run(["git", "rebase", "FETCH_HEAD"], cwd=REPO_ROOT,
                                    capture_output=True, text=True, timeout=90)
            if rebase.returncode != 0:
                subprocess.run(["git", "rebase", "--abort"], cwd=REPO_ROOT,
                               check=False, timeout=30)
                raise RuntimeError("Checkpoint rebase conflict; original data remains local "
                                   "but cannot be pushed safely: " + rebase.stderr[-400:])
            subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=REPO_ROOT,
                           check=True, timeout=90)
        self.new_files = 0
        self.last_commit = time.monotonic()
        log("已提交归档检查点到 GitHub main")

    def run(self) -> dict:
        self.load()
        # Priority 1: establish the entire historical LIST, all the way back
        # to launch. A challenged DETAIL endpoint must not prevent that.
        # Every fetched list page and cursor is persisted before progressing.
        while (self.stage in ("list", "all") and not self.list_exhausted and not self.errors
               and not self.timed_out() and len(self.pages) < self.max_pages):
            try:
                page = self.get_page()
                self.store_page(page)
                self.checkpoint_if_due()
            except (VerificationRequired, RateLimited) as exc:
                message = "List API access suspended: " + str(exc)
                self.errors.append(message)
                self.list_errors.append(message)
                log(message)
                break
            except Exception as exc:
                message = f"Page {len(self.pages)+1}: {type(exc).__name__}: {exc}"
                self.errors.append(message)
                self.list_errors.append(message)
                log(message)
                break
            time.sleep(0.5)

        if not self.list_exhausted and len(self.pages) >= self.max_pages and self.stage in ("list", "all"):
            self.errors.append("Max-page safety limit reached")
            self.list_errors.append("Max-page safety limit reached")

        # Priority 2: backfill missing DETAILS; existing full JSON remains
        # untouched and is not downloaded again. One provider challenge pauses
        # ALL detail requests for this run, without bypassing the challenge.
        if self.stage in ("details", "all", "banner-details", "version-details") and not self.list_exhausted:
            self.errors.append("Details stage requires an evidenced complete historical list")
        if (self.stage in ("details", "all", "banner-details", "version-details") and self.list_exhausted
                and not self.errors and not self.timed_out()):
            if self.stage == "banner-details":
                # Prefer oldest missing card-pool notices: most historical
                # gaps lie in 2020-2025, while 2026 is partly archived.
                target_ids = sorted(
                    (pid for pid, post in self.posts.items()
                     if banner_candidate(post.get("subject", ""))),
                    key=lambda pid: (int(self.posts[pid].get("created_at") or 0), pid))
                log(f"定向正文补全：卡池公告候选 {len(target_ids)} 篇，"
                    f"单次请求上限 {self.max_detail_requests or '不限'}")
            elif self.stage == "version-details":
                target_ids = sorted(
                    (pid for pid, post in self.posts.items()
                     if version_notice_candidate(post.get("subject", ""))),
                    key=lambda pid: (int(self.posts[pid].get("created_at") or 0), pid))
                log(f"定向正文补全：版本更新及维护公告候选 {len(target_ids)} 篇，"
                    f"单次请求上限 {self.max_detail_requests or '不限'}")
            else:
                target_ids = list(self.posts)
            fail_streak = 0
            for pid in target_ids:
                if self.timed_out():
                    self.interrupted = True
                    break
                if self.detail_paused:
                    break
                if self.is_valid_detail(pid):
                    continue
                if self.max_detail_requests and self.details_attempted >= self.max_detail_requests:
                    self.detail_budget_exhausted = True
                    log(f"已达到本次请求预算 {self.max_detail_requests}；保留断点，下次继续")
                    break
                self.get_detail(pid)
                self.details_attempted += 1
                fail_streak = 0 if self.is_valid_detail(pid) else fail_streak + 1
                if self.details_attempted % 10 == 0:
                    log(f"正文补全: 本轮尝试 {self.details_attempted} 篇, 连续失败 {fail_streak}")
                self.checkpoint_if_due()
                if self.detail_paused:
                    log(f"正文接口已暂缓：{self.pause_reason}")
                    break
                if fail_streak >= self.max_detail_failures:
                    self.errors.append("Too many consecutive non-challenge full-post failures")
                    break

        if self.timed_out():
            self.interrupted = True
            log("Reached time budget or received cancellation; saving checkpoint")
        status = self.flush(force_commit=True)
        log(f"本轮结束: 页={status['pagesSaved']} 正文={status['fullPostsSaved']}/{status['listedUniquePosts']} "
            f"最早={status['earliestUtc8']} 列表完整={status['listComplete']} "
            f"正文完整={status['complete']} 卡池候选正文={status['bannerDetailsSaved']}/"
            f"{status['bannerCandidateNotices']} 版本公告={status['versionDetailsSaved']}/"
            f"{status['versionCandidateNotices']} 暂缓正文={status['detailPaused']} "
            f"未保存={status['fullPostsMissing']}")
        return status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--stage", choices=("list", "details", "all", "banner-details", "version-details"),
                        default="list",
                        help="Historical list, all missing details, both, banner or version candidates only")
    parser.add_argument("--commit-progress", action="store_true", help="Commit and push checkpoints to main during Actions")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--checkpoint-seconds", type=int, default=120)
    parser.add_argument("--max-minutes", type=int, default=90)
    parser.add_argument("--max-pages", type=int, default=2000)
    parser.add_argument("--max-detail-failures", type=int, default=6)
    parser.add_argument("--max-detail-requests", type=int, default=0,
                        help="Max full post IDs attempted per run; 0 = unlimited")
    args = parser.parse_args(argv)
    if args.commit_progress and not archive_git_write_allowed():
        parser.error("--commit-progress 仅允许 Private 开发仓库；Public 禁止写入历史公告")
    if min(args.batch_size, args.checkpoint_seconds, args.max_minutes,
           args.max_pages, args.max_detail_failures) <= 0:
        parser.error("All numeric options must be positive")
    collector = Collector(args.output, commit_progress=args.commit_progress,
                          batch_size=args.batch_size, checkpoint_seconds=args.checkpoint_seconds,
                          max_minutes=args.max_minutes, max_pages=args.max_pages,
                          max_detail_failures=args.max_detail_failures, stage=args.stage,
                          max_detail_requests=args.max_detail_requests)
    try:
        result = collector.run()
        if args.stage == "list":
            return 0 if result["listComplete"] else 2
        if args.stage in ("banner-details", "version-details"):
            # A bounded, manual batch is considered operationally successful
            # if it stopped safely, even when candidates still need bodies.
            # Distinguish this from categoryDetailsComplete in the report.
            return (0 if (result["listComplete"] and not result["errors"]
                          and not result["detailPaused"]) else 2)
        return 0 if result["complete"] else 2
    except Exception as exc:
        log(f"FATAL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    sys.exit(main())