#!/usr/bin/env python3
"""Read-only extraction of Genshin wish-banner notice CANDIDATES.

This is an internal review index, NOT a published banner feed.
Never infer start/end times from publication timestamps or unparsed images.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT / "data/announcements/genshin/zh-cn/miyoushe"
OUTPUT_NAME = "banner-candidates.json"
DEFAULT_OUTPUT = REPO_ROOT / "data/derived/genshin/miyoushe-zh-cn" / OUTPUT_NAME
# Keep identical with the existing manually reviewed 308-candidate shortlist.
# New/changed titles are suggestions, not proof of wish-banner identity.
TITLE_PATTERN = re.compile(r"祈愿|祈願|概率\s*UP|神铸赋形|角色活动祈愿", re.I)
DATE_PATTERN = re.compile(
    r"20\d{2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{1,2}\s+\d{1,2}:\d{2}"
    r"|20\d{2}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}"
)
QUOTED = re.compile(r"「([^」]{1,60})」")
FIVE_STAR_SEGMENT = re.compile(r"5\s*星(?:角色|武器)[^。！\n]{0,220}")
WEAPON_HINTS = ("神铸赋形", "武器活动祈愿", "5星武器")
CHRONICLED_HINTS = ("集录祈愿", "集录祈願")


def banner_candidate(title: str) -> bool:
    return isinstance(title, str) and bool(TITLE_PATTERN.search(title))


def category_hint(title: str) -> str:
    if any(t in title for t in CHRONICLED_HINTS):
        return "chronicled_candidate"
    if any(t in title for t in WEAPON_HINTS):
        return "weapon_candidate"
    if "祈愿" in title or "祈願" in title:
        return "character_or_other_wish_candidate"
    return "unknown_wish_candidate"


class BodyText(HTMLParser):
    """Extract visible text without treating IMG alt text as banner evidence."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("p", "br", "li"):
            self.fragments.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "li"):
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        self.fragments.append(data)

    def result(self) -> str:
        return "\n".join(line.strip() for line in "".join(self.fragments).splitlines()
                         if line.strip())


def detail_body(post: dict) -> str:
    # Prefer structured-content Delta if available; HTML is a fallback.
    structured = post.get("structured_content")
    if structured:
        try:
            delta = json.loads(structured) if isinstance(structured, str) else structured
            if isinstance(delta, list):
                chunks = [entry["insert"] for entry in delta if isinstance(entry, dict)
                          and isinstance(entry.get("insert"), str)]
                if chunks:
                    return "".join(chunks).strip()
        except (ValueError, TypeError):
            pass
    parser = BodyText()
    parser.feed(post.get("content") if isinstance(post.get("content"), str) else "")
    return parser.result()


def media_urls(post: dict) -> list[str]:
    urls = []
    seen = set()

    def add(url):
        if isinstance(url, str) and url.startswith("https://") and url not in seen:
            seen.add(url)
            urls.append(url)

    for value in post.get("images") or []:
        if isinstance(value, dict):
            add(value.get("url") or value.get("src"))
        else:
            add(value)
    structured = post.get("structured_content")
    if structured:
        try:
            entries = json.loads(structured) if isinstance(structured, str) else structured
            if isinstance(entries, list):
                for entry in entries:
                    obj = entry.get("insert") if isinstance(entry, dict) else None
                    if isinstance(obj, dict):
                        add(obj.get("image"))
        except (ValueError, TypeError):
            pass
    return urls


def time_mentions(body: str) -> list[dict]:
    mentions = []
    for match in DATE_PATTERN.finditer(body):
        raw = match.group()
        context = body[max(0, match.start()-42):min(len(body), match.end()+42)]
        mentions.append({"raw": raw, "context": " ".join(context.split())[:140],
                         "source": "notice_body"})
    return mentions[:60]


def five_star_name_candidates(body: str) -> list[str]:
    names = []
    for match in FIVE_STAR_SEGMENT.finditer(body):
        # Only a nearby five-star sentence counts; titles/4-star sections alone
        # must never be asserted as verified featured items.
        for quoted in QUOTED.findall(match.group()):
            if quoted not in names:
                names.append(quoted)
    return names[:30]


def read_post(folder: Path, record: dict) -> dict | None:
    if record.get("rawFile") is None:
        return None
    pid = record["postId"]
    expected = f"posts/{pid}.json"
    if record["rawFile"] != expected:
        raise ValueError(f"Unexpected raw detail path for {pid}")
    full = folder / expected
    if not full.is_file():
        raise ValueError(f"Missing marked-as-present detail: {pid}")
    obj = json.loads(full.read_text(encoding="utf-8"))
    post = obj["data"]["post"]["post"]
    if str(post.get("post_id")) != pid:
        raise ValueError(f"Wrong full-detail ID for {pid}")
    if post.get("game_id") not in (None, "", "0", 0, "2", 2):
        raise ValueError(f"Wrong game for {pid}")
    return post


def analyze(folder: Path) -> dict:
    index_path = folder / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("game") != "genshin" or index.get("language") != "zh-cn":
        raise ValueError("Expected a Genshin zh-cn notice index")
    candidates = []
    counts = Counter()
    source_ids = set()
    for record in index.get("posts", []):
        pid = str(record["postId"])
        if pid in source_ids:
            raise ValueError("Duplicate ID in archived notice index")
        source_ids.add(pid)
        title = record.get("title") or ""
        if not banner_candidate(title):
            continue
        post = read_post(folder, record)
        urls = media_urls(post) if post is not None else []
        if post is None:
            # index v2 stores title/date/ID only. Missing full details have
            # no trustworthy image URLs or text evidence at this stage.
            status = "full_detail_missing"
            times, names = [], []
        else:
            body = detail_body(post)
            times = time_mentions(body)
            names = five_star_name_candidates(body)
            if times:
                status = "body_time_candidates_need_review"
            elif urls:
                status = "time_in_images_or_not_present"
            else:
                status = "no_time_found_in_body"
        counts[status] += 1
        candidates.append({
            "postId": pid,
            "title": title,
            "publishedAtUtc8": record.get("createdAtUtc8"),
            "officialUrl": record.get("sourceUrl"),
            "categoryHint": category_hint(title),
            "status": status,
            "fullDetailAvailable": post is not None,
            "rawFile": record.get("rawFile"),
            "titleQuotedCandidates": QUOTED.findall(title)[:15],
            "fiveStarTextCandidates": names,
            "bodyTimeMentions": times,
            "imageUrls": urls,
            "imageRecognitionNeeded": bool(urls and not times),
            "reviewRequired": True,
        })
    candidates.sort(key=lambda r: (r["publishedAtUtc8"] or "", r["postId"]))
    saved = sum(r["fullDetailAvailable"] for r in candidates)
    return {
        "format": "genshin-miyoushe-banner-candidates-v1",
        "game": "genshin",
        "language": "zh-cn",
        "source": "data/announcements/genshin/zh-cn/miyoushe/index.json",
        "publishable": False,
        "approval": "pending_manual_review",
        "timesVerified": False,
        "imageFilesDownloaded": False,
        "ocrPerformed": False,
        "candidateRule": TITLE_PATTERN.pattern,
        "summary": {
            "totalArchivedNotices": len(source_ids),
            "candidateNotices": len(candidates),
            "detailsAvailable": saved,
            "detailsMissing": len(candidates) - saved,
            "statusCounts": dict(sorted(counts.items())),
            "candidatesWithTextTimes": sum(bool(r["bodyTimeMentions"]) for r in candidates),
            "candidatesNeedingImageReview": sum(r["imageRecognitionNeeded"] for r in candidates),
        },
        "candidates": candidates,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output or (DEFAULT_OUTPUT if args.root == ROOT else args.root / 'derived' / OUTPUT_NAME)
    result = analyze(args.root)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic output, no run timestamp to avoid meaningless Git commits.
    contents = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if not output.exists() or output.read_text(encoding="utf-8") != contents:
        output.write_text(contents, encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
