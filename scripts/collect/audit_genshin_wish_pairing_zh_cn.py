#!/usr/bin/env python3
"""Non-blocking audit of same-day Genshin character/weapon wish notices.

The date is the official notice publication date in UTC+08, not the release date
or an inferred banner phase. Warnings are checked starting the following day.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

TZ8 = timezone(timedelta(hours=8))
CHECKPOINT = Path("data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json")
WISH_NOTICES = Path("data/derived/genshin/wish-notices")
CHARACTER_TYPES = {"character_event", "character_event_2"}
WEAPON_TYPES = {"weapon_event"}


def pairing_warnings(root: Path, *, today: date | None = None) -> dict[str, dict]:
    """One warning per publication date, without blocking any pipeline stage."""
    today = today or datetime.now(TZ8).date()
    state_path = root / CHECKPOINT
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    try:
        since = date.fromisoformat(state.get("pairingSince") or (today - timedelta(days=3)).isoformat())
    except (ValueError, TypeError):
        since = today - timedelta(days=3)

    groups: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(
        lambda: {"character": [], "weapon": []}
    )
    for path in sorted((root / WISH_NOTICES).glob("wish-notice_zh-CN_*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            kind = item.get("poolType")
            if kind not in CHARACTER_TYPES | WEAPON_TYPES:
                continue
            source = item.get("source") or {}
            published = datetime.fromisoformat(source["publishedAt"]).astimezone(TZ8).date()
            if published < since or published >= today:
                continue
            pid = str(source["postId"])
            if not pid.isdecimal():
                continue
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Invalid individual records are handled by existing validation.
            continue
        category = "character" if kind in CHARACTER_TYPES else "weapon"
        groups[published.isoformat()][category].append(
            (pid, path.relative_to(root).as_posix())
        )

    result = {}
    for day, categories in sorted(groups.items()):
        characters, weapons = categories["character"], categories["weapon"]
        if bool(characters) == bool(weapons):
            continue
        missing = "武器活动祈愿" if characters else "角色活动祈愿"
        present = characters or weapons
        urls = [f"https://www.miyoushe.com/ys/article/{pid}" for pid, _ in present]
        result[f"pairing-{day}"] = {
            "severity": "warning",
            "reasons": [
                f"{day}（北京时间）已解析 {len(present)} 篇"
                f"{'角色' if characters else '武器'}祈愿公告，"
                f"但没有同日的{missing}途中数据；可能是漏抓、解析失败或官方确实未发布。",
                "已解析公告：" + "、".join(urls),
                "仅发提醒，不阻断公告采集、候选整合或 V1 发布。",
            ],
            "files": [rel for _, rel in present],
        }
    return result


def unrecognized_warnings(root: Path) -> dict[str, dict]:
    path = root / CHECKPOINT
    if not path.is_file():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for pid, item in (state.get("unrecognized") or {}).items():
        if not str(pid).isdecimal() or not isinstance(item, dict):
            continue
        result[f"unmatched-{pid}"] = {
            "severity": "warning",
            "reasons": [
                f"发现疑似正式祈愿公告，但标题未匹配现有解析器：{item.get('title') or '未知标题'}",
                f"请核对 https://www.miyoushe.com/ys/article/{pid}；不中断本轮流程。",
            ],
            "files": [str(CHECKPOINT)],
        }
    return result
