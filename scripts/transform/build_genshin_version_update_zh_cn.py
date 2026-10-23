#!/usr/bin/env python3
"""从已归档的米游社简体中文「版本更新说明」生成内部候选 JSON。

只读取指定的完整公告，不联网、不遍历公告列表、不修改 public/ 或 schemas/。
从原始 HTML 而不是 structured_content 提取：后者可能省略折叠栏目内的新角色和装备。

python -m scripts.transform.build_genshin_version_update_zh_cn --post-id 78335167
python -m scripts.transform.build_genshin_version_update_zh_cn --post-id 78335167 --force
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from .select_miyoushe_version_notices import version_notice_kind

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = REPO_ROOT / "data/announcements/genshin/zh-cn/miyoushe/posts"
OUTPUT_DIR = REPO_ROOT / "data/derived/genshin/version-updates"
OUTPUT_FILENAME_PREFIX = "version-update_zh-CN_"


def output_filename(version: str) -> str:
    """版本公告候选文件：公告类型 + 来源语言 + 版本号。"""
    return f"{OUTPUT_FILENAME_PREFIX}{version}.json"


TZ8 = timezone(timedelta(hours=8))
VERSION = re.compile(r"(?<!\d)(\d{1,2}\.\d{1,2})\s*版本")
LUNAR = re.compile(r"月之[一二三四五六七八九十]+")
HEADING = re.compile(r"^[一二三四五六七八九十]+、(?P<name>.+)$")
WEAPON_LABEL = re.compile(r"^「(?P<label>[^」]{1,100})」\s*[：:](?!.*★)")
ITEM_LINE = re.compile(r"^「(?P<label>[^」]{1,100})」\s*[（(]\s*[★☆]\s*(?P<rarity>[45])\s*[)）]$")
TIME = re.compile(r"(?P<year>20\d{2})[年/.-](?P<month>\d{1,2})[月/.-](?P<day>\d{1,2})日?\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?")
DURATION = re.compile(r"预计\s*(\d+(?:\.\d+)?)\s*个?小时(?:内)?(?:完成|结束)?")
ELEMENT = re.compile(r"^(?P<name>.+?)\s*[（(](?P<element>[风火水雷冰草岩])[)）]$")
WEAPON_TYPES = ("单手剑", "双手剑", "长柄武器", "法器", "弓")


class VisibleText(HTMLParser):
    """保留段落换行；不可只取 Delta，因为公告折叠栏目不一定在 Delta 中。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("p", "li", "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "li"):
            self.parts.append("\n")

    def handle_data(self, text: str) -> None:
        self.parts.append(text)

    def lines(self) -> list[str]:
        return [x.strip() for x in "".join(self.parts).splitlines() if x.strip()]


def html_lines(post: dict) -> list[str]:
    html = post.get("content")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("缺少完整 HTML 正文；不能用可能丢失折叠内容的 structured_content 代替")
    parser = VisibleText()
    parser.feed(html)
    return parser.lines()


def section(lines: list[str], heading: str, *, end: str | None = None) -> list[str] | None:
    """只读取命名章节，避免匹配其他玩法、补偿或角色修复说明。"""
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return None
    if end and end in lines[start:]:
        return lines[start:lines.index(end, start)]
    if heading.startswith("〓"):
        stop = next((i for i in range(start, len(lines))
                     if lines[i].startswith("〓") and lines[i].endswith("〓")), len(lines))
    else:
        stop = next((i for i in range(start, len(lines))
                     if re.match(r"^[一二三四五六七八九十]+、", lines[i])), len(lines))
    return lines[start:stop]


def get_maintenance(lines: list[str]) -> dict:
    segment = section(lines, "〓更新时间〓")
    result = {"startAt": None, "estimatedDurationHours": None, "estimatedEndAt": None}
    if not segment:
        return result
    hit = TIME.search(" ".join(segment[:3]))
    if hit is None:
        return result
    try:
        start = datetime(int(hit["year"]), int(hit["month"]), int(hit["day"]),
                         int(hit["hour"]), int(hit["minute"]), int(hit["second"] or 0), tzinfo=TZ8)
    except ValueError:
        return result
    result["startAt"] = start.isoformat(timespec="seconds")
    estimate = DURATION.search(" ".join(segment[:4]))
    if estimate:
        duration = float(estimate.group(1))
        if 0 < duration <= 24:
            result["estimatedDurationHours"] = int(duration) if duration.is_integer() else duration
            result["estimatedEndAt"] = (start + timedelta(hours=duration)).isoformat(timespec="seconds")
    return result


def new_characters(lines: list[str]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for n, line in enumerate(lines):
        match = ITEM_LINE.fullmatch(line)
        if match is None:
            continue
        label = match["label"]
        elemental = ELEMENT.fullmatch(label)
        label_name = elemental["name"] if elemental else label
        name = label_name.rsplit("·", 1)[-1].strip()
        if not name or name in seen:
            continue
        seen.add(name)
        weapon_type = next((entry.split("：", 1)[1].strip()
                            for entry in lines[n + 1:next((j for j in range(n + 1, len(lines))
                                                          if ITEM_LINE.fullmatch(lines[j])), len(lines))]
                            if entry.startswith("◇武器：")), None)
        items.append({"name": name, "rarity": int(match["rarity"]),
                      "title": label_name.rsplit("·", 1)[0] if "·" in label_name else None,
                      "element": elemental["element"] if elemental else None,
                      "weaponType": weapon_type})
    return items


def named_section(lines: list[str], name: str) -> list[str] | None:
    start = next((i for i, line in enumerate(lines)
                  if (m := HEADING.fullmatch(line)) and m["name"] == name), None)
    if start is None:
        return None
    stop = next((i for i in range(start + 1, len(lines))
                 if HEADING.fullmatch(lines[i]) or lines[i].startswith("〓")), len(lines))
    return lines[start + 1:stop]


def new_weapons(lines: list[str]) -> list[dict]:
    """提取新装备章节的武器，不包括圣遗物与装备说明里提到的旧武器。"""
    items: list[dict] = []
    seen: set[str] = set()
    acquisition = "unknown"
    default_rarity: int | None = None
    for i, line in enumerate(lines):
        if "圣遗物" in line and (line.startswith("全新") or re.match(r"^\d+[.、．]", line)):
            break
        if re.match(r"^\d+[.、．]\s*限定武器$", line):
            acquisition, default_rarity = "wish", None
            continue
        if re.match(r"^\d+[.、．]\s*活动武器$", line):
            acquisition, default_rarity = "event", None
            continue
        if re.match(r"^\d+[.、．]\s*特殊武器$", line):
            acquisition, default_rarity = "quest", None
            continue
        if re.match(r"^\d+[.、．]\s*锻造武器$", line):
            acquisition, default_rarity = "craft", None
            continue
        if re.match(r"^\d+[.、．]\s*纪行武器$", line):
            acquisition, default_rarity = "battle_pass", None
            continue
        default_match = re.search(r"全新(?:锻造|纪行)武器（★([45])）", line)
        if default_match:
            default_rarity = int(default_match[1])
            continue
        match = ITEM_LINE.fullmatch(line)
        if match:
            label, rarity = match["label"], int(match["rarity"])
        elif default_rarity and (found := WEAPON_LABEL.match(line)):
            label, rarity = found["label"], default_rarity
        else:
            continue
        prefix, sep, tail = label.partition("·")
        weapon_type = prefix if sep and prefix in WEAPON_TYPES else None
        name = tail.strip() if weapon_type else label.strip()
        if not name or name in seen or not weapon_type:
            continue
        seen.add(name)
        # Some historical articles have no subheadings; limit to a direct
        # official "可通过祈愿获得" statement near the new weapon.
        inferred = acquisition
        if inferred == "unknown":
            context = " ".join(lines[i + 1:next((j for j in range(i + 1, len(lines))
                                                   if ITEM_LINE.fullmatch(lines[j])), len(lines))])
            if "可通过祈愿获得" in context and name in context:
                inferred = "wish"
        items.append({"name": name, "rarity": rarity,
                      "weaponType": weapon_type, "acquisition": inferred})
    return items


def iso_timestamp(value: object) -> str | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, TZ8).isoformat(timespec="seconds")
    return None


def build(data: dict, *, post_id: str, source_file: str) -> dict:
    try:
        post = data["data"]["post"]["post"]
    except (KeyError, TypeError):
        raise ValueError("公告 JSON 缺少 data.post.post") from None
    if data.get("retcode") != 0 or not isinstance(post, dict):
        raise ValueError("公告 API 未成功返回完整数据")
    if str(post.get("post_id")) != post_id or not post_id.isdecimal():
        raise ValueError("公告 post_id 与指定 ID 不匹配")
    if post.get("game_id") not in (None, "", 0, "0", 2, "2"):
        raise ValueError("该公告不是原神数据")
    title = post.get("subject")
    if not isinstance(title, str) or version_notice_kind(title) != "release_notes":
        raise ValueError("只接受原神版本更新说明，不处理其他类型公告")
    version_match = VERSION.search(title)
    lunar_match = LUNAR.search(title)
    if not version_match and not lunar_match:
        raise ValueError("标题未包含已支持的版本号")
    version = version_match.group(1) if version_match else lunar_match.group(0)
    # Lunar titles contain nested quoted version names; use the opening quote
    # that is NOT the quoted lunar version marker.
    quoted = re.search(r"「((?:[^「」]|「[^「」]+」)+)」", title)
    name = quoted.group(1) if quoted else None
    if name == version:
        name = None
    lines = html_lines(post)
    chars = named_section(lines, "全新角色")
    weapons = named_section(lines, "全新装备")
    maintenance = get_maintenance(lines)
    warnings: list[str] = []
    if not maintenance["startAt"]:
        warnings.append("未从「更新时间」章节提取到明确维护开始时间")
    if chars is None:
        warnings.append("未找到「全新角色」章节；角色信息未确认")
    if weapons is None:
        warnings.append("未找到「全新装备」章节；武器信息未确认")
    character_items = new_characters(chars or [])
    weapon_items = new_weapons(weapons or [])
    if chars and not character_items:
        warnings.append("角色章节存在但未识别出角色，请人工查看是否由图片承载")
    if weapons and not weapon_items:
        warnings.append("武器章节存在但未识别出武器，请人工查看是否由图片承载")
    if weapons is not None and "武器" in " ".join(weapons) and not weapon_items:
        warnings.append("新装备章节包含武器文字但未识别到武器，请人工复核")
    if any(w["acquisition"] == "unknown" for w in weapon_items):
        warnings.append("有武器无法确认获取方式，不能视为祈愿武器")
    return {
        "format": "genshin-version-update-v1",
        "game": "genshin",
        "locale": "zh-CN",
        "version": version,
        "versionName": name,
        "maintenance": maintenance,
        "newCharacters": character_items,
        "newWeapons": weapon_items,
        "source": {"postId": post_id, "title": title,
                   "url": f"https://www.miyoushe.com/ys/article/{post_id}",
                   "publishedAt": iso_timestamp(post.get("created_at")),
                   "updatedAt": iso_timestamp(post.get("updated_at")),
                   "rawFile": source_file},
        "review": {"status": "pending_manual_review", "warnings": warnings}
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-id", required=True, help="米游社公告 ID，如 78335167")
    parser.add_argument("--input", type=Path, help="已保存的完整公告 JSON；默认从官方公告归档读取")
    parser.add_argument("--output", type=Path, help="输出路径；默认写入 version-update_zh-CN_<版本>.json")
    parser.add_argument("--force", action="store_true", help="允许覆盖不同内容的现有候选 JSON")
    args = parser.parse_args(argv)
    if not args.post_id.isdecimal():
        parser.error("--post-id 必须为数字")
    input_path = args.input or ARCHIVE / f"{args.post_id}.json"
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        try:
            source_file = input_path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            source_file = str(input_path.resolve())
        result = build(data, post_id=args.post_id, source_file=source_file)
        output_path = args.output or OUTPUT_DIR / output_filename(result["version"])
        content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if output_path.is_file():
            if output_path.read_text(encoding="utf-8") == content:
                print(f"无变化：{output_path}")
                return 0
            if not args.force:
                raise FileExistsError(f"已有不同内容的输出：{output_path}（需要 --force 才能覆盖）")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp = output_path.with_name(output_path.name + ".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(output_path)
        print(f"已生成：{output_path}（角色 {len(result['newCharacters'])}，武器 {len(result['newWeapons'])}）")
        if result["review"]["warnings"]:
            print("待复核：" + "；".join(result["review"]["warnings"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"生成失败：{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
