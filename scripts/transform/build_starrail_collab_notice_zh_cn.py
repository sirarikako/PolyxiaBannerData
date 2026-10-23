"""星铁联动长期跃迁正文解析。文章不提供版本/期数，因此需人工身份后才能发布。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

from .starrail_notice_text_zh_cn import article_text, item_name, post_from_raw, source, timestamp, iso

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/announcements/starrail/zh-cn/miyoushe/posts"
OUT = ROOT / "data/derived/starrail/collab-notices"
POOL = re.compile(r"[●•]\s*「(?P<name>[^」]+)」(?P<kind>角色|光锥)联动跃迁期间")
FIVE = re.compile(r"联动限定5星(?:角色|光锥)「(?P<name>[^」]+)」")
OPEN = re.compile(r"(?P<date>20\d{2}[/.-]\d{1,2}[/.-]\d{1,2}\s+\d{1,2}:\d{2})\s*后长期开放")

def build(raw, post_id):
    post = post_from_raw(raw, post_id)
    title = post.get("subject") or ""
    if "联动跃迁" not in title or "说明" not in title:
        raise ValueError("不是星铁联动跃迁正式说明")
    text = article_text(post)
    opening = OPEN.search(text[:1400])
    start = timestamp(opening.group("date")) if opening else None
    if "无关闭时间" not in text:
        start = None  # 没有明确长期开放承诺时不推断 endAt=null
    markers = list(POOL.finditer(text))
    banners, issues = [], []
    for i, marker in enumerate(markers):
        stop = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        fragment = re.split(r"\n\s*(?:▌|※)", text[marker.start():stop], maxsplit=1)[0]
        five = FIVE.search(fragment)
        if not five:
            issues.append(marker["name"] + ": 无法核实限定五星 UP")
        if start is None:
            issues.append(marker["name"] + ": 缺少经确认的长期开放起始时间")
        kind = "collab_character" if marker["kind"] == "角色" else "collab_light_cone"
        banners.append({"bannerName": marker["name"], "poolType": kind,
                        "featured": {"fiveStar": [item_name(five["name"])] if five else [],
                                     "fourStar": []},
                        "time": {"startAt": iso(start), "endAt": None}})
    if not markers:
        issues.append("正文未识别到独立联动跃迁卡池")
    return {"format": "starrail-collab-notice-v1", "game": "starrail", "locale": "zh-CN",
            "version": None, "phase": None, "banners": banners,
            "source": source(post, post_id),
            "review": {"status": "waiting_identity" if not issues else "needs_review",
                       "warnings": issues,
                       "requiredManualIdentity": ["version", "phase"]}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--post-id", required=True)
    p.add_argument("--input", type=Path)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    raw_file = a.input or RAW / (a.post_id + ".json")
    result = build(json.loads(raw_file.read_text(encoding="utf-8")), a.post_id)
    destination = a.output or OUT / ("collab-notice_zh-CN_" + a.post_id + ".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)

if __name__ == "__main__":
    main()
