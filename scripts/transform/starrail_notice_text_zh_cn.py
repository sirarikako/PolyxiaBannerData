"""星铁公告纯文本解析基础模块（无 OCR、无外部数据读取）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import re

TZ8 = timezone(timedelta(hours=8))
VERSION = re.compile(r"(?<!\d)(\d{1,2}\.\d{1,2})版本")
PHASES = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
PHASE = re.compile(r"活动跃迁[（(]其([一二三四五六七八九])[）)]")
DATE = r"20\d{2}[/.-]\d{1,2}[/.-]\d{1,2}"
CLOCK = r"\d{1,2}:\d{2}"
RANGE = re.compile(r"(?P<start>(?:" + DATE + r"\s+)?(?:\d{1,2}\.\d{1,2}版本更新后)|" + DATE + r"(?:\s+" + CLOCK + r")?)\s*[-—–~～－]\s*(?P<end>" + DATE + r"\s+" + CLOCK + r")")
TIME = re.compile(r"(?P<year>20\d{2})[/.-](?P<month>\d{1,2})[/.-](?P<day>\d{1,2})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})")
QUOTE = re.compile(r"「([^」]+)」")

class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "li", "br", "div", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "li", "div", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

def plain(value):
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                return plain(json.loads(value))
            except (ValueError, TypeError):
                pass
        return value
    if isinstance(value, list):
        return "".join(plain(x) for x in value)
    if isinstance(value, dict):
        if isinstance(value.get("insert"), str):
            return value["insert"]
        return plain(value.get("ops") or value.get("text") or value.get("content") or "")
    return ""

def post_from_raw(raw, pid):
    if raw.get("retcode") != 0:
        raise ValueError("米游社接口状态非成功")
    try:
        post = raw["data"]["post"]["post"]
    except (TypeError, KeyError):
        raise ValueError("缺少 data.post.post") from None
    if str(post.get("post_id")) != str(pid):
        raise ValueError("文章 ID 与原文不匹配")
    if post.get("game_id") not in (None, "", 0, "0", 6, "6"):
        raise ValueError("并非星铁文章")
    return post

def article_text(post):
    content = post.get("content")
    if isinstance(content, str) and "<" in content:
        parser = TextHTML()
        parser.feed(content)
        result = "\n".join(x.strip() for x in "".join(parser.parts).splitlines() if x.strip())
        if result:
            return result
    result = plain(post.get("structured_content")).strip()
    if result:
        return result
    if isinstance(content, str):
        return content.strip()
    return ""

def timestamp(raw):
    found = TIME.search(raw)
    if not found:
        return None
    try:
        return datetime(*(int(found[k]) for k in ("year", "month", "day", "hour", "minute")), tzinfo=TZ8)
    except ValueError:
        return None

def iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None

def parse_range(value):
    match = RANGE.search(value)
    if not match:
        return None
    raw_start, raw_end = match.group("start"), match.group("end")
    end = timestamp(raw_end)
    if end is None:
        return None
    inferred = "版本更新后" in raw_start
    date_only = re.fullmatch(DATE, raw_start.strip()) is not None
    start = timestamp(raw_start)
    if inferred:
        day = re.match(DATE, raw_start)
        if day:
            start = timestamp(day.group(0) + " 06:00")
    if (start is None and not (inferred or date_only)) or (start is not None and start >= end):
        return None
    # 仅有日期不代表 00:00 或 06:00；必须由版本更新公告补全后才能发布。
    start_date = None
    if date_only:
        y, m, d = (int(x) for x in re.split(r"[/.-]", raw_start))
        start_date = f"{y:04d}-{m:02d}-{d:02d}"
    # 官方 11:59 指截至该分钟；15:00 / 12:00 等整点为边界本身。
    exclusive_end = end + timedelta(minutes=1) if end.minute == 59 else end
    return {"startAt": iso(start), "endAt": iso(exclusive_end),
            "startDate": start_date,
            "startRaw": raw_start, "endRaw": raw_end,
            "startCondition": "after_version_update" if inferred else ("date_only" if date_only else None),
            "startDerived": inferred,
            "endRule": "inclusive_last_minute" if end.minute == 59 else "exact_boundary"}

def item_name(raw):
    return re.sub(r"[（(][^（）()]*[）)]$", "", raw).strip()

def source(post, pid):
    return {"postId": str(pid), "title": post.get("subject"),
            "url": "https://www.miyoushe.com/sr/article/" + str(pid)}
