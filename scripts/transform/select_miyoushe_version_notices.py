#!/usr/bin/env python3
"""Conservative title selection for original Genshin version update notices.

Only selects source notices for archival. These are NOT verified banner
start/end timestamps and never automatically enter public/v1.
"""
from __future__ import annotations

import re

# Do not mix client/platform updates, editor patch notes or public test builds
# into the main Genshin version-maintenance timeline.
EXCLUDE = re.compile(
    r"云[·.]?原神|编辑器和千星沙箱|PC端?启动器|"
    r"充值中心|测试服|启程测试|原神再临测试|"
    r"问题集中反馈|已知问题",
    re.I,
)
EARLY_MAINTENANCE = re.compile(
    r"^\d{1,2}月\d{1,2}日(?:停服)?维护更新(说明|通知)$"
)
LUNAR_RELEASE = re.compile(r"「月之[一二三四五六七八九十]+」更新说明$")
SCHEDULE = re.compile(
    r"版本更新时间说明|版本更新延期(?:补偿说明|通知|说明)|"
    r"版本持续时间说明"
)


def version_notice_kind(title: str) -> str | None:
    """Return stable notice category or None for non-matching titles.

    Categories identify the *kind of source*, not its verified reliability,
    applicable server, effective time, or relationship to any banner.
    """
    if not isinstance(title, str) or not title.strip() or EXCLUDE.search(title):
        return None
    title = title.strip()
    if SCHEDULE.search(title):
        return "schedule_change"
    if ("版本更新说明" in title or LUNAR_RELEASE.search(title)
            or (EARLY_MAINTENANCE.match(title)
                and title.endswith("说明"))):
        return "release_notes"
    if ("版本更新维护预告" in title or "版本更新通知" in title
            or "版本更新停服维护公告" in title
            or (EARLY_MAINTENANCE.match(title)
                and title.endswith("通知"))):
        return "maintenance_notice"
    return None


def version_notice_candidate(title: str) -> bool:
    return version_notice_kind(title) is not None
