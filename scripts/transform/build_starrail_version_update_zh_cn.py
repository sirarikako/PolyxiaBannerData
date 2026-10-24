"""仅从已保存的星铁版本更新公告解析维护时间；不写 v1。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from .starrail_notice_text_zh_cn import VERSION, article_text, iso, source, timestamp, post_from_raw

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/announcements/starrail/zh-cn/miyoushe/posts"
OUT = ROOT / "data/derived/starrail/version-updates"

def build(raw, post_id):
    post = post_from_raw(raw, post_id)
    title = post.get("subject") or ""
    match = VERSION.search(title)
    if not match or not re.search(r"版本.*更新说明", title) or any(x in title for x in ("云•", "云·", "云.", "云・")):
        raise ValueError("不是星铁正式版本更新说明")
    body = article_text(post)
    section = re.search(r"(?:■|▌|〓)更新时间[^\n]*\n?([^\n]+)", body)
    start = timestamp(section.group(1)) if section else None
    if start is None:
        # 兼容“2026/08/26 06:00开始”；仅从靠近更新时间的文本提取。
        pos = body.find("更新时间")
        start = timestamp(body[pos:pos + 180]) if pos >= 0 else None
    return {"format": "starrail-version-update-v1", "game": "starrail", "locale": "zh-CN",
            "version": match.group(1), "maintenance": {"startAt": iso(start)},
            "source": source(post, post_id),
            "review": {"warnings": [] if start else ["无法提取维护开始时间"]}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--post-id", required=True)
    p.add_argument("--input", type=Path)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    src = a.input or RAW / (a.post_id + ".json")
    row = build(json.loads(src.read_text(encoding="utf-8")), a.post_id)
    dst = a.output or OUT / ("version-update_zh-CN_" + row["version"] + ".json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and json.loads(dst.read_text(encoding="utf-8"))["source"]["postId"] != a.post_id:
        raise ValueError("同版本已有其他文章，禁止自动覆盖")
    dst.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(dst)

if __name__ == "__main__":
    main()
