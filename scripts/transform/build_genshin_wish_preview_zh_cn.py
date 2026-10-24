#!/usr/bin/env python3
"""从米游社简体中文「活动祈愿预告」提取版本、期数、时间和 UP 候选。

只处理一篇指定文章，不扫描公告列表，也不修改 public/v1。
优先复用已有的米游社原始公告或官方账号归档；若没有缓存，再通过米游社 post/wapi/getPostFull 获取。

python -m scripts.transform.build_genshin_wish_preview_zh_cn --post-id 78879329
python -m scripts.transform.build_genshin_wish_preview_zh_cn --post-id 78879329 --offline
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "data/announcements/genshin/zh-cn/miyoushe/posts"
ACCOUNT_ARCHIVE = ROOT / "data/announcements/genshin/zh-cn/miyoushe-account-75276539/posts"
OUTPUT = ROOT / "data/derived/genshin/wish-previews"
OUTPUT_FILENAME_PREFIX = "wish-preview_zh-CN_"
DETAIL_API = "https://bbs-api.miyoushe.com/post/wapi/getPostFull"
TZ8 = timezone(timedelta(hours=8))


def output_filename(version: str, phase: int) -> str:
    """按版本更新公告约定，以类型_语言_版本-期数命名。"""
    if not isinstance(version, str) or not version or "/" in version or "\\" in version:
        raise ValueError("不合法的版本标记")
    if not isinstance(phase, int) or phase < 1:
        raise ValueError("不合法的祈愿期数")
    return f"{OUTPUT_FILENAME_PREFIX}{version}-phase-{phase}.json"

TITLE = re.compile(
    r"^(?:「)?(?P<version>\d{1,2}\.\d{1,2}|月之[一二三四五六七八九十]+)(?:」)?"
    r"版本活动祈愿预告第(?P<phase>[一二三四五六七八九十]+)期(?:[！!。\s]*)$"
)
NUMERAL = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
           "七": 7, "八": 8, "九": 9, "十": 10}
GROUP = re.compile(
    r"(?P<rarity>[45])星(?P<kind>角色|武器)"
    r"(?P<items>(?:\s*「[^」\n]{1,120}」[\s、，,]*)+)"
)
QUOTED = re.compile(r"「([^」]+)」")
ELEMENT = re.compile(r"^(.*?)[(（]([风火水雷冰草岩])[_ ]?[)）]$")
WEAPON_TYPES = ("单手剑", "双手剑", "长柄武器", "法器", "弓")
TIME = re.compile(
    r"(?P<year>20\d{2})[/.-](?P<month>\d{1,2})[/.-](?P<day>\d{1,2})"
    r"\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
)
# 读取结束的完整时间，避免当日期后缺少句号时误吞 UP 名单。
RANGE = re.compile(
    r"本期活动祈愿时间(?:为|：|:)\s*(?P<start>.*?)\s*[~～]\s*"
    r"(?P<end>20\d{2}[/.-]\d{1,2}[/.-]\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)"
)
EXTRA = re.compile(r"(?:开启|开放|上线|推出)\s*「([^」]+)」\s*(集录祈愿|溯光祈愿)")


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("p", "li", "br", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "li", "div"):
            self.parts.append("\n")

    def handle_data(self, text: str) -> None:
        self.parts.append(text)


def delta_text(obj: object) -> str:
    if isinstance(obj, str):
        if obj.lstrip().startswith(("[", "{")):
            try:
                return delta_text(json.loads(obj))
            except (ValueError, TypeError):
                pass
        return obj
    if isinstance(obj, list):
        return "".join(delta_text(item) for item in obj)
    if isinstance(obj, dict):
        if "insert" in obj:
            return delta_text(obj["insert"]) if isinstance(obj["insert"], str) else ""
        return delta_text(obj.get("ops") or obj.get("content") or obj.get("text") or "")
    return ""


def body_text(post: dict) -> tuple[str, str]:
    html = post.get("content")
    if isinstance(html, str) and re.search(r"<\s*[a-zA-Z][^>]*>", html):
        parser = VisibleText()
        parser.feed(html)
        text = "\n".join(s.strip() for s in "".join(parser.parts).splitlines() if s.strip())
        if text:
            return text, "html"
    for key in ("structured_content",):
        # If the HTML field contains only images, do not mistake the tags for readable text.
        text = delta_text(post.get(key)).strip()
        if text:
            return text, key
    if isinstance(html, str) and not re.search(r"<\s*[a-zA-Z][^>]*>", html):
        text = delta_text(html).strip()
        if text:
            return text, "content"
    return "", "missing"


def timestamp(value: object) -> str | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, TZ8).isoformat(timespec="seconds")
    return None


def local_time(text: str) -> str | None:
    found = TIME.search(text)
    if not found:
        return None
    try:
        return datetime(int(found["year"]), int(found["month"]), int(found["day"]),
                        int(found["hour"]), int(found["minute"]),
                        int(found["second"] or 0), tzinfo=TZ8).isoformat(timespec="seconds")
    except ValueError:
        return None


def get_times(text: str, warnings: list[str]) -> dict:
    merged = " ".join(text.split())
    match = RANGE.search(merged)
    result = {"startRaw": None, "endRaw": None, "startAt": None, "endAt": None,
              "startCondition": None}
    if not match:
        warnings.append("未找到明确的本期活动祈愿时间范围")
        return result
    start, end = match["start"].strip(), match["end"].strip()
    result["startRaw"], result["endRaw"] = start, end
    if "版本更新后" in start:
        result["startCondition"] = "after_version_update"
    else:
        result["startAt"] = local_time(start)
        if result["startAt"] is None:
            warnings.append("无法解析预告中的开始时间")
    result["endAt"] = local_time(end)
    if result["endAt"] is None:
        warnings.append("无法解析预告中的结束时间")
    return result


def split_item(label: str, kind: str) -> dict:
    label = label.strip()
    if kind == "角色":
        found = ELEMENT.fullmatch(label)
        clean = found.group(1).strip() if found else label
        title, separator, name = clean.rpartition("·")
        return {"name": name.strip() if separator else clean,
                "title": title.strip() if separator else None,
                "element": found.group(2) if found else None}
    prefix, separator, name = label.partition("·")
    if separator and prefix in WEAPON_TYPES:
        return {"name": name.strip(), "weaponType": prefix}
    return {"name": label, "weaponType": None}


def get_up(text: str, warnings: list[str]) -> dict:
    result = {"fiveStarCharacters": [], "fourStarCharacters": [],
              "fiveStarWeapons": [], "fourStarWeapons": []}
    keys = {("5", "角色"): "fiveStarCharacters", ("4", "角色"): "fourStarCharacters",
            ("5", "武器"): "fiveStarWeapons", ("4", "武器"): "fourStarWeapons"}
    normalized = " ".join(text.split())
    for match in GROUP.finditer(normalized):
        key = keys[(match["rarity"], match["kind"])]
        for label in QUOTED.findall(match["items"]):
            item = split_item(label, match["kind"])
            if item["name"] and item not in result[key]:
                result[key].append(item)
    if not result["fiveStarCharacters"] and not result["fiveStarWeapons"]:
        warnings.append("没有在文本中识别到五星角色或武器，可能需要检查图片")
    return result


def phase_number(s: str) -> int:
    if s in NUMERAL:
        return NUMERAL[s]
    if s.startswith("十") and len(s) == 2 and s[1] in NUMERAL:
        return 10 + NUMERAL[s[1]]
    if len(s) == 2 and s[0] in NUMERAL and s[1] == "十":
        return NUMERAL[s[0]] * 10
    raise ValueError(f"不支持的期数：{s}")


def post_from_archive(data: dict, post_id: str) -> dict:
    """兼容米游社详情响应和官方账号历史列表归档，严格拒绝缺失正文的记录。"""
    if "data" in data:
        try:
            post = data["data"]["post"]["post"]
        except (KeyError, TypeError):
            raise ValueError("详情响应缺少 data.post.post") from None
        if data.get("retcode") != 0 or not isinstance(post, dict):
            raise ValueError("米游社详情 API 没有返回有效文章")
        return post
    archive_id = str(data.get("postId") or data.get("post_id") or "")
    if archive_id != post_id:
        raise ValueError("账号归档的文章 ID 与指定 ID 不符")
    entry = data.get("rawListEntry") or data.get("raw_list_entry")
    if not isinstance(entry, dict) or not isinstance(entry.get("post"), dict):
        raise ValueError("账号归档缺少米游社原始 post 数据")
    post = entry["post"]
    if str(post.get("uid")) != "75276539":
        raise ValueError("账号归档不是指定官方账号的原始文章")
    if not (data.get("bodyComplete") is True or data.get("body_status") == "text"):
        raise ValueError("账号归档正文尚未确认完整，拒绝依据摘要生成结果")
    if not post.get("structured_content"):
        raise ValueError("账号归档缺少 structured_content，拒绝使用可能截断的正文")
    return post


def build(data: dict, *, post_id: str, source_file: str) -> dict:
    post = post_from_archive(data, post_id)
    if not post_id.isdecimal() or str(post.get("post_id")) != post_id:
        raise ValueError("文章 post_id 与指定 ID 不匹配")
    if post.get("game_id") not in (None, 0, "0", 2, "2"):
        raise ValueError("该文章不属于原神")
    title = post.get("subject")
    matched = TITLE.fullmatch(title) if isinstance(title, str) else None
    if not matched:
        raise ValueError("只接受带有版本和第几期的「活动祈愿预告」，不接受正式祈愿公告")
    text, text_source = body_text(post)
    if not text:
        raise ValueError("文章没有可解析正文；仅有图片的预告不能推测 UP 内容")
    warnings: list[str] = []
    times = get_times(text, warnings)
    up = get_up(text, warnings)
    extra = [{"name": name, "kind": "chronicled" if kind == "集录祈愿" else "recollection",
              "noticeType": kind} for name, kind in EXTRA.findall(" ".join(text.split()))]
    # 不按公告文本中角色与武器的排列顺序推断彼此对应关系。
    return {
        "format": "genshin-wish-preview-v1",
        "game": "genshin",
        "locale": "zh-CN",
        "noticeType": "wish_preview",
        "version": matched["version"],
        "phase": phase_number(matched["phase"]),
        "time": times,
        "up": up,
        "additionalWishes": extra,
        "source": {"postId": post_id, "title": title,
                   "url": f"https://www.miyoushe.com/ys/article/{post_id}",
                   "listUrl": "https://www.miyoushe.com/ys/home/28?type=3",
                   "publishedAt": timestamp(post.get("created_at")),
                   "updatedAt": timestamp(post.get("updated_at")),
                   "rawFile": source_file, "textSource": text_source},
        "review": {"status": "pending_manual_review", "warnings": warnings,
                   "note": "预告是整期汇总，不含可靠的单独祈愿池名称、角色武器配对或 itemId；不得直接发布到 v1"}
    }


def load_or_fetch(post_id: str, *, input_path: Path | None = None, offline: bool = False,
                  refresh: bool = False) -> tuple[dict, Path]:
    path = input_path or ARCHIVE / f"{post_id}.json"
    if input_path:
        return json.loads(path.read_text(encoding="utf-8")), path
    if not refresh:
        for cached in (path, ACCOUNT_ARCHIVE / f"{post_id}.json"):
            if cached.is_file():
                return json.loads(cached.read_text(encoding="utf-8")), cached
    if offline:
        raise FileNotFoundError(f"未找到已归档的预告：{path} 或官方账号归档中的同 ID 文件")
    # 复用已有的限流 / 验证码检测。不可通过替换 API 域名绕过限制。
    from scripts.collect.collect_miyoushe_announcements import fetch, save_json
    data = fetch(DETAIL_API, {"post_id": post_id, "gids": 2})
    # 校验与 build() 共用同一层级解析；米游社 ID 在 data.post.post.post_id。
    fetched_post = post_from_archive(data, post_id)
    if str(fetched_post.get("post_id")) != post_id:
        raise ValueError("米游社 API 返回的文章 ID 不匹配")
    save_json(path, data)
    return data, path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-id", required=True, help="米游社文章 ID，如 78879329")
    parser.add_argument("--input", type=Path, help="指定已有的完整公告 JSON")
    parser.add_argument("--output", type=Path, help="输出路径；默认写入 wish-preview_zh-CN_<版本>-phase-<期数>.json")
    parser.add_argument("--offline", action="store_true", help="只读取本地归档，不访问网络")
    parser.add_argument("--refresh", action="store_true", help="重新获取原始公告（仅默认输入路径）")
    parser.add_argument("--force", action="store_true", help="允许覆盖内容不同的候选结果")
    args = parser.parse_args(argv)
    if not args.post_id.isdecimal():
        parser.error("--post-id 必须为数字")
    if args.input and args.refresh:
        parser.error("--input 不能和 --refresh 同时使用")
    try:
        data, source = load_or_fetch(args.post_id, input_path=args.input,
                                     offline=args.offline, refresh=args.refresh)
        try:
            raw_file = source.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            raw_file = str(source.resolve())
        result = build(data, post_id=args.post_id, source_file=raw_file)
        output = args.output or OUTPUT / output_filename(result["version"], result["phase"])
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if output.is_file():
            if output.read_text(encoding="utf-8") == serialized:
                print(f"无变化：{output}")
                return 0
            if not args.force:
                raise FileExistsError(f"已有不同内容的结果：{output}（用 --force 覆盖）")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(output)
        print(f"已生成祈愿预告：{output}（{result['version']} 第{result['phase']}期）")
        if result["review"]["warnings"]:
            print("需要复核：" + "；".join(result["review"]["warnings"]))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        parser.exit(1, f"处理失败：{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
