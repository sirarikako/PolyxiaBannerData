"""P3: 临时获取缺失的真实文章身份凭证，不将完整原文提交公开仓库。

只对人工引用的、尚无已验证结构化来源的文章按 postId 调用官方详情 API。
完整响应仅写入被 Public .gitignore 忽略的 Runner 本地 posts/，供本轮解析使用。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from scripts.collect.collect_miyoushe_announcements import (
    fetch, save_json, validate_detail,
)
from scripts.transform.genshin_notice_manual_zh_cn import MANUAL_ROOT, read_manual
from scripts.transform.starrail_notice_manual_zh_cn import (
    validate_manual, verified_structured_source,
)
from scripts.transform.starrail_notice_text_zh_cn import post_from_raw

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "https://bbs-api.miyoushe.com/post/wapi/getPostFull"
GENSHIN_RAW = Path("data/announcements/genshin/zh-cn/miyoushe/posts")
STARRAIL_RAW = Path("data/announcements/starrail/zh-cn/miyoushe/posts")
GENSHIN_STATE = Path("data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json")


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _has_derived_genshin(root, pid, kind):
    folder, pattern, fmt = {
        "version_update": ("version-updates", "version-update_zh-CN_*.json", "genshin-version-update-v1"),
        "wish_preview": ("wish-previews", "wish-preview_zh-CN_*.json", "genshin-wish-preview-v1"),
        "wish_notice": ("wish-notices", f"wish-notice_zh-CN_{pid}.json", "genshin-wish-notice-v1"),
    }[kind]
    for path in (root / "data/derived/genshin" / folder).glob(pattern):
        try:
            obj = _json(path)
        except (OSError, ValueError):
            continue
        src = obj.get("source") or {}
        if (obj.get("format") == fmt and obj.get("game") == "genshin"
                and obj.get("locale") == "zh-CN"
                and str(src.get("postId")) == pid
                and src.get("url") == f"https://www.miyoushe.com/ys/article/{pid}"):
            return True
    return False


def _verified_recovered(state, pid, kind):
    entry = (state.get("manualRecovered") or {}).get(pid) or {}
    completed = (state.get("completed") or {}).get(pid) or {}
    return (entry.get("kind") == kind and
            completed.get("resolution") == "manual_verified" and
            completed.get("kind") == kind and
            bool(entry.get("title")) and entry.get("title") == completed.get("title"))


def _required_genshin(root):
    state_path = root / GENSHIN_STATE
    if not state_path.is_file():
        return []
    state = _json(state_path)
    if state.get("format") != "genshin-notice-discovery-v1":
        raise ValueError("原神 checkpoint 格式错误，拒绝自动补抓")
    entries = dict(state.get("manualRecovered") or {})
    entries.update(state.get("manualReview") or {})
    required = []
    for pid, row in sorted(entries.items()):
        path = root / MANUAL_ROOT / f"{pid}.json"
        if not path.is_file():
            continue
        kind = row.get("kind")
        if not re.fullmatch(r"\d+", pid) or kind not in ("version_update", "wish_preview", "wish_notice"):
            raise ValueError("原神人工记录有非法 postId 或公告种类")
        read_manual(path, pid, kind)
        if (root / GENSHIN_RAW / f"{pid}.json").is_file():
            continue
        if _has_derived_genshin(root, pid, kind) or _verified_recovered(state, pid, kind):
            continue
        required.append((pid, row.get("title")))
    return required


def _required_starrail(root):
    folder = root / "manual/notices/starrail/zh-CN/miyoushe"
    required = []
    for path in sorted(folder.glob("*.json")):
        obj = validate_manual(path, "starrail-notice-manual.schema.json", root)
        pid = str(obj["postId"])
        if not re.fullmatch(r"\d+", pid) or path.stem != pid:
            raise ValueError(f"星铁人工文章文件名与 postId 不匹配：{path.name}")
        if ((root / STARRAIL_RAW / f"{pid}.json").is_file()
                or verified_structured_source(root, pid)):
            continue
        required.append((pid, None))
    return required


def recover(game, root=ROOT, fetcher=None):
    """在单次 Runner 缓存必需的原文，失败时不伪造来源或修改 checkpoint。"""
    if game not in ("genshin", "starrail"):
        raise ValueError("不支持的游戏")
    fetcher = fetch if fetcher is None else fetcher
    needed = (_required_genshin(root) if game == "genshin" else _required_starrail(root))
    raw_folder = root / (GENSHIN_RAW if game == "genshin" else STARRAIL_RAW)
    fetched, failures = [], []
    for pid, expected_title in needed:
        try:
            response = fetcher(ENDPOINT, {"post_id": pid, "gids": 2 if game == "genshin" else 6})
            post = validate_detail(response, pid) if game == "genshin" else post_from_raw(response, pid)
            if ((post.get("post_status") or {}).get("is_official") is False
                    or not isinstance(post.get("subject"), str) or not post["subject"].strip()
                    or (expected_title and post["subject"] != expected_title)):
                raise ValueError("官方文章身份/标题不匹配")
            save_json(raw_folder / f"{pid}.json", response)
            fetched.append(pid)
        except (Exception) as exc:
            # 不能在报告、日志、Public Issue 中转储外部原文/错误请求正文。
            failures.append({"postId": pid, "errorType": type(exc).__name__})
    result = {"game": game, "requested": len(needed),
              "fetched": fetched, "failed": failures, "temporaryOnly": True}
    if failures:
        raise RuntimeError("人工来源临时补抓失败：" +
                           ", ".join(item["postId"] + "/" + item["errorType"]
                                     for item in failures))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", required=True, choices=["genshin", "starrail"])
    args = parser.parse_args(argv)
    print(json.dumps(recover(args.game), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
