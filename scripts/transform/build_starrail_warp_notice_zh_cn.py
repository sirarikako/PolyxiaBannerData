"""星铁活动跃迁单篇文字解析；一篇拆成多个卡池，失败项待人工复核。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
from .starrail_notice_text_zh_cn import (VERSION, PHASE, PHASES, QUOTE, RANGE,
    article_text, item_name, parse_range, post_from_raw, source)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/announcements/starrail/zh-cn/miyoushe/posts"
OUT = ROOT / "data/derived/starrail/warp-notices"
# 匹配每个独立的活动池，而不是每组头部或全文 UP 汇总。
POOL = re.compile(r"[●•]\s*「(?P<name>[^」]+)」\s*(?P<type>角色|光锥)活动跃迁期间")
UP = re.compile(r"(?P<grade>[45])星(?P<type>角色|光锥)\s*(?P<items>(?:「[^」]+」\s*)+)")
EXPECTED = {"character_event": (1, 3), "light_cone_event": (1, 3)}

def names_of(section, grade, kind):
    result = []
    for m in UP.finditer(section):
        if int(m.group("grade")) == grade and m.group("type") == kind:
            result.extend(item_name(x) for x in QUOTE.findall(m.group("items")))
    # 保留顺序；同一个条目内重复不是有效的 UP 列表。
    return result

def summary_time_by_five_star(text):
    """仅从同一句包含明确五星名称的时间说明关联单池；不得把全文首个时间套给所有池。"""
    found = {}
    for time_match in RANGE.finditer(text):
        start_line = text.rfind("\n", 0, time_match.start()) + 1
        start_sentence = text.rfind("。", start_line, time_match.start()) + 1
        sentence = text[max(start_line, start_sentence):time_match.start()]
        schedule = parse_range(time_match.group(0))
        if schedule is None:
            continue
        # 官方一条时间说明可能写多个五星，例如：
        # 「长夜月」「海瑟音」「黑天鹅」与多把光锥共用同一结束时刻。
        # 每个五星对象均需与该说明的时间建立对应，不能只取第一名。
        for group in re.finditer(r"5星(?:角色|光锥)\s*((?:「[^」]+」\s*)+)", sentence):
            for label in QUOTE.findall(group.group(1)):
                name = item_name(label)
                if name in found and found[name] != schedule:
                    found[name] = None
                else:
                    found[name] = schedule
    return found

def build(raw, post_id):
    post = post_from_raw(raw, post_id)
    title = post.get("subject") or ""
    version, phase = VERSION.search(title), PHASE.search(title)
    if not version or not phase:
        raise ValueError("不是支持的「x.x版本活动跃迁（其N）」公告")
    text = article_text(post)
    markers = list(POOL.finditer(text))
    preamble = text[:markers[0].start()] if markers else text
    ranges = list(RANGE.finditer(preamble))
    fallback = parse_range(ranges[0].group(0)) if len(ranges) == 1 else None
    by_five = summary_time_by_five_star(preamble)
    banners, warnings = [], []
    for index, m in enumerate(markers):
        limit = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        fragment = text[m.start():limit]
        # 防止意外把下一节的时间或 UP 混入本池。
        fragment = re.split(r"(?:\n\s*▌|\n\s*※)", fragment, maxsplit=1)[0]
        kind = "character" if m.group("type") == "角色" else "light_cone"
        pool_type = kind + "_event"
        local = RANGE.search(fragment)
        five, four = names_of(fragment, 5, m.group("type")), names_of(fragment, 4, m.group("type"))
        referenced = by_five.get(five[0]) if len(five) == 1 else None
        schedule = parse_range(local.group(0)) if local else (referenced or fallback)
        if len(five) != 1 or len(four) != 3 or len(set(five + four)) != 4:
            warnings.append("卡池 " + m.group("name") + " 的 UP 数量或唯一性无法核实")
        if schedule is None:
            warnings.append("卡池 " + m.group("name") + " 缺少合法时间区间")
        banners.append({"bannerName": m.group("name"), "poolType": pool_type,
                        "featured": {"fiveStar": five, "fourStar": four},
                        "time": schedule})
    if not markers:
        warnings.append("正文未提供可解析的独立卡池标题和 UP 段落，需要人工补足（不从名称猜测）")
    if not text:
        warnings.append("缺少可解析正文")
    return {"format": "starrail-warp-notice-v1", "game": "starrail", "locale": "zh-CN",
            "version": version.group(1), "phase": PHASES[phase.group(1)],
            "banners": banners, "source": source(post, post_id),
            "review": {"warnings": warnings, "status": "needs_review" if warnings else "parsed"}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--post-id", required=True)
    p.add_argument("--input", type=Path)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    row = build(json.loads((a.input or RAW / (a.post_id + ".json")).read_text(encoding="utf-8")), a.post_id)
    dst = a.output or OUT / ("warp-notice_zh-CN_" + a.post_id + ".json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(dst)

if __name__ == "__main__":
    main()
