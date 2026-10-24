#!/usr/bin/env python3
"""增量发现米游社原神简体中文公告，并调用现有单篇提取脚本。

仅访问米游社 getNewsList 与目标文章 getPostFull；仅祈愿公告解析期间临时下载图片。
首轮只建立检查基线（不追溯历史）；之后每次从列表顶部读取到上次的重叠位置。
临时网络故障保留 checkpoint.pending；OCR 未识别、结果冲突及脚本错误进入
checkpoint.manualReview，不再每日重试，等待通知与人工处理；不写入 public/v1。

python -m scripts.collect.collect_genshin_notices_zh_cn
python -m scripts.collect.collect_genshin_notices_zh_cn --max-pages 10
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
from typing import Any
from urllib.error import URLError, HTTPError

from scripts.collect.download_genshin_notice_images_zh_cn import download_images, ImageArchiveError
from scripts.collect.collect_miyoushe_announcements import (
    VerificationRequired, RateLimited, fetch, post_from_entry, save_json,
    validate_detail,
)
from scripts.transform.select_miyoushe_version_notices import version_notice_kind
from scripts.transform.build_genshin_version_update_zh_cn import (
    VERSION, LUNAR, output_filename as version_filename,
)
from scripts.transform.build_genshin_wish_preview_zh_cn import (
    TITLE as PREVIEW_TITLE, phase_number, output_filename as preview_filename,
)
from scripts.transform.build_genshin_wish_notice_zh_cn import TITLE as NOTICE_TITLE

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "data/derived/genshin/notice-discovery"
CHECKPOINT = STATE_DIR / "notice-discovery_zh-CN_checkpoint.json"
REPORT = STATE_DIR / "notice-discovery_zh-CN_report.json"
RAW_DIR = ROOT / "data/announcements/genshin/zh-cn/miyoushe/posts"
LIST_API = "https://bbs-api-static.miyoushe.com/painter/wapi/getNewsList"
# Official backup verified on GitHub Runner for both announcement feeds, including
# first two pages and identical cursors (P4 probe #40057185154).
BACKUP_LIST_API = "https://api-takumi.mihoyo.com/post/wapi/getNewsList"
DETAIL_API = "https://bbs-api.miyoushe.com/post/wapi/getPostFull"
FEEDS = (1, 3)
TZ8 = timezone(timedelta(hours=8))
# 保存最近几页的 ID 作为重叠锚点，不保存全站帖子 ID。
ANCHOR_LIMIT = 100


class DiscoveryError(RuntimeError):
    """列表不完整或检查点损坏；不允许把本次发现标记为完成。"""


class TransientSourceError(RuntimeError):
    """来源网络临时故障；仅这类单篇错误允许下次自动重试。"""


class TransientListError(DiscoveryError):
    """列表出现明确的网络故障，允许从第一页换官方入口重新扫描。"""


class ManualReviewRequired(RuntimeError):
    """OCR/解析或内容异常：暂停本篇文章，人工检查后显式恢复。"""


def now() -> str:
    return datetime.now(TZ8).isoformat(timespec="seconds")


def fresh_state() -> dict:
    return {
        "format": "genshin-notice-discovery-v1",
        "game": "genshin",
        "locale": "zh-CN",
        "feeds": {},
        "pending": {},
        "manualReview": {},
        "manualRecovered": {},
        "completed": {},
        "updatedAt": None,
    }


def load_state(path: Path = CHECKPOINT) -> dict:
    if not path.exists():
        return fresh_state()
    state = json.loads(path.read_text(encoding="utf-8"))
    # 兼容早期 checkpoint；升级不丢失原有 pending/completed。
    if isinstance(state, dict) and "manualReview" not in state:
        state["manualReview"] = {}
    if isinstance(state, dict) and "manualRecovered" not in state:
        state["manualRecovered"] = {}
    if (not isinstance(state, dict)
            or state.get("format") != "genshin-notice-discovery-v1"
            or state.get("game") != "genshin"
            or state.get("locale") != "zh-CN"
            or not all(isinstance(state.get(key), dict)
                       for key in ("feeds", "pending", "completed", "manualReview", "manualRecovered"))):
        raise DiscoveryError("检查点格式错误；请先修复，不可自动重置进度")
    return state


def persist(state: dict, path: Path = CHECKPOINT) -> None:
    state["updatedAt"] = now()
    save_json(path, state)


def list_page(feed: int, cursor: str = "", *, endpoint: str = LIST_API) -> tuple[list[dict], bool, str]:
    """读取指定官方列表源的一页。只对真实传输故障启动备用源重扫。

    两种 URL 均已经过 P4 Runner 双栏目、两页 ID/游标一致性验证。
    不自动切换未经验证的域名，更不会绕过验证码或 HTTP 429。
    """
    if feed not in FEEDS:
        raise ValueError("不支持的公告分栏")
    if endpoint not in (LIST_API, BACKUP_LIST_API):
        raise ValueError("不允许的公告列表来源")
    params = {
        "gids": 2, "type": feed, "page_size": 20, "last_id": cursor,
    }
    if endpoint == LIST_API:
        params["client_type"] = 4
    try:
        # 列表失败不做原地 HTTP 重试，也不能在中途替换游标来源。
        # 单篇详情仍沿用共享 fetch 默认的 3 次请求。
        data = fetch(endpoint, params, retries=1)["data"]
    except (VerificationRequired, RateLimited):
        raise  # 验证、限流：立即停止，不访问备用源
    except RuntimeError as exc:
        cause = exc.__cause__
        if isinstance(cause, HTTPError):
            transient = cause.code in (500, 502, 503, 504)
        else:
            transient = isinstance(cause, (URLError, TimeoutError, ConnectionError))
        if transient:
            raise TransientListError(
                f"type={feed} 官方列表网络故障：{type(cause).__name__}"
            ) from exc
        raise
    entries = data.get("list")
    if not isinstance(entries, list) or not isinstance(data.get("is_last"), bool):
        raise DiscoveryError(f"type={feed} 列表缺少 list / is_last")
    if not entries:
        raise DiscoveryError(f"type={feed} 返回空列表；不能当作没有新公告")
    posts = [post_from_entry(entry) for entry in entries]
    ids = [str(post["post_id"]) for post in posts]
    if len(set(ids)) != len(ids):
        raise DiscoveryError(f"type={feed} 同一页包含重复文章 ID")
    nxt = str(data.get("last_id") or "")
    if not data["is_last"] and (not nxt or nxt == cursor):
        raise DiscoveryError(f"type={feed} 列表游标没有前进")
    return posts, data["is_last"], nxt


def initial_list_page(feed: int) -> tuple[list[dict], bool, str]:
    """首次建立分栏基线：官方主源发生传输故障时回退一次。"""
    try:
        return list_page(feed)
    except TransientListError:
        print(f"type={feed} 主源网络故障，基线改用已验证官方备用源", flush=True)
        return list_page(feed, endpoint=BACKUP_LIST_API)


def classify(title: str) -> str | None:
    """只选择当前三个单篇提取器实际支持的标题类别。"""
    if version_notice_kind(title) == "release_notes":
        return "version_update"
    if "活动祈愿预告" in title and "第" in title:
        return "wish_preview"
    if (isinstance(title, str) and "预告" not in title
            and NOTICE_TITLE.match(title)
            and ("祈愿" in title or "概率UP" in title)):
        return "wish_notice"
    return None


def _discover_on(feed: int, anchors: list[str], max_pages: int, endpoint: str) -> tuple[list[dict], list[str], int]:
    """完整检查当前页；连续 3 个已知 ID 证明已与上次的列表重叠。

    如果限定页数内无法证明重叠，不提交新锚点，防止因漏页而跳过公告。
    """
    known = set(anchors)
    if not known:
        raise DiscoveryError("已有分栏缺少检查锚点")
    needed = min(3, len(known))
    streak = 0
    cursor = ""
    cursors = {cursor}
    visible: list[str] = []
    fresh: list[dict] = []
    reached = False
    for page in range(1, max_pages + 1):
        if endpoint == LIST_API:
            posts, is_last, nxt = list_page(feed, cursor)
        else:
            posts, is_last, nxt = list_page(feed, cursor, endpoint=endpoint)
        for post in posts:
            pid = str(post["post_id"])
            if pid in visible:
                raise DiscoveryError(f"type={feed} 跨页重复文章 {pid}")
            visible.append(pid)
            if not reached:
                if pid in known:
                    streak += 1
                else:
                    streak = 0
                    fresh.append(post)
                if streak >= needed:
                    reached = True
        if reached or is_last:
            # is_last=true 代表确实已经读完本分栏，允许全部新帖进入队列。
            return fresh, visible[:ANCHOR_LIMIT], page
        if nxt in cursors:
            raise DiscoveryError(f"type={feed} 出现循环游标")
        cursors.add(nxt)
        cursor = nxt
    raise DiscoveryError(
        f"type={feed} 检查 {max_pages} 页仍未遇到旧锚点；"
        "本分栏进度未前进，可增加 --max-pages 后重试"
    )



def discover(feed: int, anchors: list[str], max_pages: int) -> tuple[list[dict], list[str], int]:
    """网络故障时从第一页重扫备用官方源，绝不跨源复用游标。

    第一个扫描结果只有完全走到旧锚点或列表末尾后才会进入 checkpoint。
    HTTP 429 / 验证 / 无效数据不会触发备用源访问。
    """
    try:
        return _discover_on(feed, anchors, max_pages, LIST_API)
    except TransientListError:
        print(f"type={feed} 主列表源网络故障；从第一页使用官方备用源重扫", flush=True)
        return _discover_on(feed, anchors, max_pages, BACKUP_LIST_API)


def enqueue(state: dict, feed: int, posts: list[dict]) -> int:
    added = 0
    for post in reversed(posts):
        pid = str(post["post_id"])
        title = str(post.get("subject") or "")
        kind = classify(title)
        if not kind:
            continue
        if pid in state["completed"] or pid in state["manualReview"]:
            continue
        if pid not in state["pending"]:
            state["pending"][pid] = {
                "kind": kind, "title": title, "feeds": [feed],
                "discoveredAt": now(), "attempts": 0, "lastError": None,
            }
            added += 1
        else:
            old = state["pending"][pid]
            if old["kind"] != kind:
                raise DiscoveryError(f"文章 {pid} 的类型发生冲突：{old['kind']} / {kind}")
            if feed not in old["feeds"]:
                old["feeds"].append(feed)
    return added


def output_for(kind: str, title: str, pid: str) -> Path:
    if kind == "version_update":
        found = VERSION.search(title)
        lunar = LUNAR.search(title)
        if not found and not lunar:
            raise ValueError(f"版本公告缺少可识别版本号：{title}")
        version = found.group(1) if found else lunar.group(0)
        return ROOT / "data/derived/genshin/version-updates" / version_filename(version)
    if kind == "wish_preview":
        hit = PREVIEW_TITLE.fullmatch(title)
        if not hit:
            raise ValueError(f"暂不支持此祈愿预告标题：{title}")
        return ROOT / "data/derived/genshin/wish-previews" / preview_filename(
            hit["version"], phase_number(hit["phase"])
        )
    if kind == "wish_notice":
        return ROOT / "data/derived/genshin/wish-notices" / f"wish-notice_zh-CN_{pid}.json"
    raise ValueError(f"未知公告分类：{kind}")


MODULES = {
    "version_update": "scripts.transform.build_genshin_version_update_zh_cn",
    "wish_preview": "scripts.transform.build_genshin_wish_preview_zh_cn",
    "wish_notice": "scripts.transform.build_genshin_wish_notice_zh_cn",
}


def extract(pid: str, entry: dict) -> str:
    """解析目标文章；只给祈愿公告临时下载图片，运行结束后删除。"""
    kind = entry["kind"]
    output = output_for(kind, entry["title"], pid)

    # 复用候选时，不需要请求原文或下载图片。
    if output.is_file():
        existing = json.loads(output.read_text(encoding="utf-8"))
        expected_format = {
            "version_update": "genshin-version-update-v1",
            "wish_preview": "genshin-wish-preview-v1",
            "wish_notice": "genshin-wish-notice-v1",
        }[kind]
        if (
            not isinstance(existing, dict)
            or existing.get("format") != expected_format
            or existing.get("game") != "genshin"
            or existing.get("locale") != "zh-CN"
            or not isinstance(existing.get("source"), dict)
            or str(existing["source"].get("postId")) != pid
            or existing["source"].get("title") != entry["title"]
        ):
            raise ManualReviewRequired(
                f"输出文件已存在但并非同一篇公告：{output}；"
                "禁止自动覆盖，需人工核对"
            )
        # 祈愿公告旧结果若还未进行图片 OCR，则必须重新临时下载并补充识别；
        # 已处理且确认无可靠时间的图片不无限重复下载。
        image_status = (existing.get("imageTimeRecognition") or {}).get("status")
        if kind != "wish_notice" or image_status in ("recognized", "recognized_conditional"):
            print(f"复用已有公告结果：{output}", flush=True)
            return output.relative_to(ROOT).as_posix()
        if image_status in ("unresolved", "conflict", "error"):
            detail = "; ".join((existing.get("imageTimeRecognition") or {}).get("warnings") or [])
            raise ManualReviewRequired(
                f"公告 {pid} OCR {image_status}：{detail or '识别结果不可用'}"
            )
        print(f"公告 {pid} 尚未完成图片识别，重新生成候选 JSON", flush=True)

    raw_path = RAW_DIR / f"{pid}.json"
    if raw_path.is_file():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        try:
            raw = fetch(DETAIL_API, {"post_id": pid, "gids": 2})
        except (VerificationRequired, RateLimited):
            raise
        except RuntimeError as exc:
            # 来源 API 将网络和 HTTP 错误包装为 RuntimeError；明确的 4xx 不应盲目重试。
            message = str(exc)
            retry_signatures = ("TimeoutError", "URLError", "ConnectionError",
                                "ConnectionResetError", "RemoteDisconnected",
                                "HTTP Error 408", "HTTP Error 500", "HTTP Error 502",
                                "HTTP Error 503", "HTTP Error 504", "Errno 104")
            if any(part in message for part in retry_signatures):
                raise TransientSourceError(f"公告详情暂时获取失败：{message}") from exc
            raise ManualReviewRequired(f"公告详情返回异常（不自动重试）：{message}") from exc
        validate_detail(raw, pid)
        save_json(raw_path, raw)
    post = validate_detail(raw, pid)
    if post.get("subject") != entry["title"]:
        raise ManualReviewRequired(f"文章 {pid} 标题已变更，须人工确认")
    if (post.get("post_status") or {}).get("is_official") is False:
        raise ManualReviewRequired(f"文章 {pid} 明确标记为非官方内容")

    cmd = [sys.executable, "-m", MODULES[kind], "--post-id", pid,
           "--input", str(raw_path), "--output", str(output)]
    if kind == "wish_notice" and output.is_file():
        cmd.append("--force")
    # 即使图片请求或解析失败，TemporaryDirectory 也会自动清理文件。
    # 只有祈愿公告会进入图片下载分支；其他两个提取器只处理原始 JSON。
    with TemporaryDirectory(prefix=f"genshin-wish-images-zh-CN-{pid}-") as temporary_dir:
        if kind == "wish_notice":
            try:
                image_index = download_images(post, pid, output_root=Path(temporary_dir))
            except ImageArchiveError as exc:
                message = str(exc)
                if any(f"HTTP {code}" in message for code in (408, 500, 502, 503, 504)):
                    raise TransientSourceError(f"图片来源临时故障：{message}") from exc
                raise ManualReviewRequired(f"公告图片格式、内容或下载异常：{message}") from exc
            except (URLError, TimeoutError, ConnectionError) as exc:
                raise TransientSourceError(f"图片请求临时失败：{exc}") from exc
            if image_index is not None:
                cmd.extend(["--images-dir", str(image_index.parent)])
                print(f"祈愿公告临时图片已准备：{image_index}", flush=True)
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    if result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    if result.returncode or not output.is_file():
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise ManualReviewRequired(f"提取脚本失败（exit={result.returncode}）：{detail}")
    if kind == "wish_notice":
        # OCR 无结果、矛盾、程序错误都直接通知人工，不会每天重复运行。
        extracted = json.loads(output.read_text(encoding="utf-8"))
        recognition = extracted.get("imageTimeRecognition") or {}
        image_status = recognition.get("status")
        if image_status not in ("recognized", "recognized_conditional"):
            detail = "; ".join(recognition.get("warnings") or [])
            raise ManualReviewRequired(
                f"公告 {pid} OCR {image_status or 'missing'}：{detail or '未取得可靠识别结果'}"
            )
    return output.relative_to(ROOT).as_posix()


def run(*, max_pages: int = 5, checkpoint: Path = CHECKPOINT,
        report_path: Path = REPORT, pending_only: bool = False,
        retry_only: bool = False) -> dict:
    if not 1 <= max_pages <= 50:
        raise ValueError("--max-pages 必须在 1 到 50 之间")
    state = load_state(checkpoint)
    report: dict[str, Any] = {
        "format": "genshin-notice-discovery-report-v1",
        "game": "genshin", "locale": "zh-CN",
        "startedAt": now(), "feeds": {}, "enqueued": 0,
        "succeeded": [], "failed": [], "reviewNeeded": [],
        "pendingCount": 0, "manualReviewCount": 0,
    }
    # 两个栏目独立推进。某栏目读取失败时，不覆盖它上次的检查位置。
    for feed in (() if pending_only or retry_only else FEEDS):
        key = str(feed)
        previous = state["feeds"].get(key)
        if previous is None:
            posts, _, _ = initial_list_page(feed)
            state["feeds"][key] = {
                "anchors": [str(p["post_id"]) for p in posts],
                "lastCheckedAt": now(), "initializedOnly": True,
            }
            report["feeds"][key] = {"initialized": True, "pages": 1, "newPosts": 0}
            print(f"type={feed}: 首次运行，记录 {len(posts)} 个基线 ID，不回溯历史", flush=True)
        else:
            if not isinstance(previous.get("anchors"), list):
                raise DiscoveryError(f"type={feed} 检查点缺少 anchors")
            new_posts, anchors, pages = discover(feed, previous["anchors"], max_pages)
            new_count = enqueue(state, feed, new_posts)
            state["feeds"][key] = {
                "anchors": anchors, "lastCheckedAt": now(), "initializedOnly": False,
            }
            report["feeds"][key] = {
                "initialized": False, "pages": pages, "newPosts": len(new_posts),
                "matched": new_count,
            }
            report["enqueued"] += new_count
            print(f"type={feed}: 检查 {pages} 页，发现 {len(new_posts)} 条新帖，"
                  f"新增待提取 {new_count} 篇", flush=True)
        # 先提交可恢复的待处理队列和本栏目锚点，再请求详情或启动提取。
        persist(state, checkpoint)

    # 定时重试仅处理真正可重试的临时错误；人工/验证问题不盲试。
    if retry_only:
        from scripts.collect.genshin_notice_retry import is_retryable_pending
        targets = [(pid, entry) for pid, entry in state["pending"].items()
                   if is_retryable_pending(entry)]
    else:
        targets = list(state["pending"].items())
    for pid, entry in targets:
        entry["attempts"] += 1
        try:
            output = extract(pid, entry)
            state["completed"][pid] = {
                "kind": entry["kind"], "title": entry["title"],
                "outputFile": output, "completedAt": now(),
            }
            del state["pending"][pid]
            report["succeeded"].append(pid)
            print(f"完成 {pid} -> {output}", flush=True)
        except (VerificationRequired, RateLimited):
            entry["lastError"] = "米游社要求验证或出现限流，已停止"
            persist(state, checkpoint)
            raise
        except TransientSourceError as exc:
            entry["lastError"] = str(exc)[:1000]
            report["failed"].append({"postId": pid, "error": entry["lastError"]})
            print(f"临时网络故障（下次重试） {pid}: {entry['lastError']}", file=sys.stderr, flush=True)
        except (ManualReviewRequired, DiscoveryError, OSError,
                ValueError, RuntimeError, KeyError, TypeError) as exc:
            reason = str(exc)[:1000]
            state["manualReview"][pid] = {
                **entry, "reason": reason, "markedAt": now(),
                "outputFile": (f"data/derived/genshin/wish-notices/wish-notice_zh-CN_{pid}.json"
                               if entry["kind"] == "wish_notice" else None),
            }
            del state["pending"][pid]
            report["reviewNeeded"].append({"postId": pid, "kind": entry["kind"], "error": reason})
            print(f"人工复核（不再自动重试） {pid}: {reason}", file=sys.stderr, flush=True)
        persist(state, checkpoint)
    report["pendingCount"] = len(state["pending"])
    report["manualReviewCount"] = len(state["manualReview"])
    report["finishedAt"] = now()
    save_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=5,
                        help="单个栏目单轮最多读取的列表页数，默认 5")
    parser.add_argument('--pending-only', action='store_true',
                        help='仅重试 checkpoint.pending，不请求公告列表或更新栏目锚点')
    parser.add_argument("--retry-only", action="store_true",
                        help="仅重试已有临时失败 pending，不扫描新公告")
    args = parser.parse_args(argv)
    try:
        result = run(max_pages=args.max_pages, pending_only=args.pending_only,
                     retry_only=args.retry_only)
        print(f"检查完成：成功 {len(result['succeeded'])}，"
              f"失败 {len(result['failed'])}，待处理 {result['pendingCount']}", flush=True)
        return 1 if result["pendingCount"] else 0
    except (VerificationRequired, RateLimited, DiscoveryError, OSError,
            ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"检查中止（已有检查点保留）：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
