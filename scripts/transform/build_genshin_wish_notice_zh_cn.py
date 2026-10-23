#!/usr/bin/env python3
"""从单篇米游社原神简体中文「祈愿公告」提取内部候选 JSON。

默认优先读取已经归档的 posts/<post_id>.json；不存在时只请求这篇文章的
https://bbs-api.miyoushe.com/post/wapi/getPostFull，不请求公告列表或其他文章。
接受采集器提供的临时图片目录（可选）；仅本地 OCR，不保存图片、不使用第三方数据、不修改 public/v1。
默认输出：data/derived/genshin/wish-notices/wish-notice_zh-CN_<post_id>.json。

python -m scripts.transform.build_genshin_wish_notice_zh_cn --post-id 78782590
python -m scripts.transform.build_genshin_wish_notice_zh_cn --post-id 78782590 --offline
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "data/announcements/genshin/zh-cn/miyoushe/posts"
OUTPUT = ROOT / "data/derived/genshin/wish-notices"
DETAIL_API = "https://bbs-api.miyoushe.com/post/wapi/getPostFull"
TZ8 = timezone(timedelta(hours=8))

TITLE = re.compile(r"^(?:「(?P<name>[^」]{1,100})」\s*祈愿\s*[：:]|「神铸赋形」\s*[：:]|祈愿\s*[：:])")
UP_GROUP = re.compile(
    r"(?P<limited>限定)?\s*(?P<rarity>[45])星(?P<kind>角色|武器)\s*"
    r"(?P<labels>(?:「[^」\n]{1,120}」\s*)+)"
)
SELECTABLE_LINE = re.compile(r"^(?P<rarity>[45])星(?P<kind>角色|武器)[：:]\s*(?P<items>.+)$")
QUOTED = re.compile(r"「([^」]+)」")
ELEMENT = re.compile(r"^(?P<label>.+?)[（(](?P<element>[风火水雷冰草岩])[)）]$")
WEAPONS = ("单手剑", "双手剑", "长柄武器", "法器", "弓")
POOL_TYPE = {
    "角色活动祈愿": "character_event",
    "角色活动祈愿-2": "character_event_2",
    "武器活动祈愿": "weapon_event",
    "集录祈愿": "chronicled",
    "溯光祈愿": "chronicled",
    "常驻祈愿": "standard",
    "新手祈愿": "beginner",
}
TIME_RANGE = re.compile(
    r"(?:本期(?:活动)?祈愿时间|(?:活动)?祈愿(?:开放|开启)?时间)\s*[：:]\s*"
    r"(?P<start>[^。；;\n]{3,100}?)\s*[~～—–]\s*(?P<end>[^。；;\n]{3,100})"
)
TIME = re.compile(
    r"(?P<year>20\d{2})[年/.-](?P<month>\d{1,2})[月/.-](?P<day>\d{1,2})日?"
    r"\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
)


class ArticleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("p", "li", "br", "div"):
            self.parts.append("\n")
        if tag == "img":
            values = dict(attrs)
            for key in ("src", "data-src", "data-original"):
                url = values.get(key)
                if isinstance(url, str) and url.startswith("https://"):
                    self.images.append(url)
                    break

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "li", "div"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def delta_text(value: object) -> str:
    if isinstance(value, str):
        if value.lstrip().startswith(("[", "{")):
            try:
                return delta_text(json.loads(value))
            except (ValueError, TypeError):
                pass
        return value
    if isinstance(value, list):
        return "".join(delta_text(part) for part in value)
    if isinstance(value, dict):
        if "insert" in value:
            return delta_text(value["insert"]) if isinstance(value["insert"], str) else ""
        return delta_text(value.get("ops") or value.get("content") or value.get("text") or "")
    return ""


def article_text(post: dict) -> tuple[str, str, list[str]]:
    html = post.get("content")
    parser = ArticleHTML()
    if isinstance(html, str) and re.search(r"<\s*[a-zA-Z][^>]*>", html):
        parser.feed(html)
        text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
        if text:
            return text, "html", parser.images
    structured = delta_text(post.get("structured_content")).strip()
    if structured:
        return structured, "structured_content", parser.images
    if isinstance(html, str) and html.strip() and not re.search(r"<\s*[a-zA-Z]", html):
        return html.strip(), "content", parser.images
    return "", "missing", parser.images


def published_time(value: object) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        try:
            return datetime.fromtimestamp(value, TZ8).isoformat(timespec="seconds")
        except (OverflowError, ValueError, OSError):
            pass
    return None


def parse_time(raw: str) -> str | None:
    match = TIME.search(raw)
    if match is None:
        return None
    try:
        return datetime(int(match["year"]), int(match["month"]), int(match["day"]),
                        int(match["hour"]), int(match["minute"]), int(match["second"] or 0),
                        tzinfo=TZ8).isoformat(timespec="seconds")
    except ValueError:
        return None


def event_time(text: str) -> dict:
    result = {"startRaw": None, "endRaw": None, "startAt": None, "endAt": None,
              "startCondition": None}
    match = TIME_RANGE.search(text)
    if match is None:
        return result
    start, end = match["start"].strip(), match["end"].strip()
    result["startRaw"], result["endRaw"] = start, end
    if "版本更新后" in start:
        result["startCondition"] = "after_version_update"
    else:
        result["startAt"] = parse_time(start)
    result["endAt"] = parse_time(end)
    return result


def item_from_label(label: str, kind: str, rarity: int, limited: bool | None) -> dict:
    element = ELEMENT.fullmatch(label)
    name_label = element["label"] if element else label
    if kind == "角色":
        subtitle, sep, name = name_label.rpartition("·")
        return {"name": name.strip() if sep else name_label.strip(),
                "title": subtitle.strip() if sep else None,
                "element": element["element"] if element else None,
                "rarity": rarity, "limited": limited}
    prefix, sep, name = name_label.partition("·")
    return {"name": name.strip() if sep and prefix in WEAPONS else name_label.strip(),
            "weaponType": prefix if sep and prefix in WEAPONS else None,
            "rarity": rarity, "limited": limited}


def up_items(text: str) -> dict:
    """仅提取明确说「祈愿获取概率将大幅提升」的物品，其他列表不算固定 UP。"""
    out = {"fiveStarCharacters": [], "fourStarCharacters": [],
           "fiveStarWeapons": [], "fourStarWeapons": []}
    keys = {(5, "角色"): "fiveStarCharacters", (4, "角色"): "fourStarCharacters",
            (5, "武器"): "fiveStarWeapons", (4, "武器"): "fourStarWeapons"}
    for line in text.splitlines():
        # 同一句可能是「限定4星武器 A、4星武器 B」，不能只取最后一组。
        if "祈愿获取概率将" not in line or not ("提升" in line or "提高" in line):
            continue
        for match in UP_GROUP.finditer(line):
            rarity, kind = int(match["rarity"]), match["kind"]
            key = keys[(rarity, kind)]
            for label in QUOTED.findall(match["labels"]):
                item = item_from_label(label, kind, rarity, True if match["limited"] else None)
                if item["name"] and item not in out[key]:
                    out[key].append(item)
    return out


def selectable_items(text: str) -> dict:
    """集录、溯光公告的可选物品范围，不误报成全体固定 UP。"""
    out = {"fiveStarCharacters": [], "fourStarCharacters": [],
           "fiveStarWeapons": [], "fourStarWeapons": []}
    keys = {(5, "角色"): "fiveStarCharacters", (4, "角色"): "fourStarCharacters",
            (5, "武器"): "fiveStarWeapons", (4, "武器"): "fourStarWeapons"}
    for line in text.splitlines():
        match = SELECTABLE_LINE.match(line.strip())
        if match is None:
            continue
        key = keys[(int(match["rarity"]), match["kind"])]
        names = [name.strip() for name in re.split(r"[/／、，,]", match["items"]) if name.strip()]
        for name in names:
            if name not in out[key]:
                out[key].append(name)
    return out


def notice_type(text: str, title: str) -> tuple[str | None, str | None]:
    found = re.search(r"本祈愿属于\s*「([^」]+)」", text)
    official = found.group(1) if found else None
    if official is None:
        second = re.search(r"本(?:次|期)为\s*「([^」]+)」", text)
        official = second.group(1) if second else None
    if official is None and (
        "在「神铸赋形」活动祈愿中" in text
        and "5星武器" in text and "概率将" in text
        and ("神铸赋形" in title or title.startswith("祈愿："))
    ):
        official = "武器活动祈愿"
    return official, POOL_TYPE.get(official)


def rules(text: str) -> dict:
    return {
        "limitedNotInStandard": True if "限定角色不会进入「奔行世间」常驻祈愿" in text
        or "限定武器不会进入「奔行世间」常驻祈愿" in text else None,
        "characterEventPityShared": True if "祈愿次数保底完全共享" in text else None,
        "characterTrial": True if "「且试身手」角色试用活动" in text else None,
    }


def image_urls(post: dict, html_images: list[str]) -> list[str]:
    # 顺序必须与官方临时图片下载器一致：post.images -> HTML img -> cover。
    candidates = [*(post.get("images") or []), *html_images]
    if isinstance(post.get("cover"), str):
        candidates.append(post["cover"])
    return list(dict.fromkeys(u for u in candidates if isinstance(u, str) and u.startswith("https://")))


def read_temporary_images(directory: Path, post_id: str, expected_urls: list[str]) -> int:
    """读取并验证采集器提供的临时图片，绝不把临时路径写进候选 JSON。

    仅校验图片传递与完整性；实际时间 OCR 在 main 中按需执行。
    """
    from scripts.collect.download_genshin_notice_images_zh_cn import detect_image

    manifest_path = directory / f"images_zh-CN_{post_id}.json"
    index = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(index, dict) or index.get("postId") != post_id
            or index.get("game") != "genshin" or index.get("locale") != "zh-CN"
            or index.get("complete") is not True or not isinstance(index.get("images"), list)):
        raise ValueError("临时公告图片索引不完整或文章 ID 不一致")
    recorded = index["images"]
    if len(recorded) != len(index.get("sourceUrls", [])):
        raise ValueError("临时图片索引数量不一致")
    if not set(expected_urls).issubset(set(index["sourceUrls"])):
        raise ValueError("临时图片与原始公告 URL 不对应")
    for item in recorded:
        filename = item["file"]
        if (not isinstance(filename, str) or Path(filename).name != filename
                or not filename.startswith(f"image_zh-CN_{post_id}_")):
            raise ValueError("临时图片文件名无效")
        image = (directory / filename).read_bytes()
        if (len(image) != item["bytes"] or sha256(image).hexdigest() != item["sha256"]
                or detect_image(image)[1] != item["mimeType"]):
            raise ValueError(f"临时图片校验失败：{filename}")
    return len(recorded)


def build(data: dict, *, post_id: str, source_file: str, images_dir: Path | None = None) -> dict:
    if not isinstance(data, dict) or data.get("retcode") != 0:
        raise ValueError("米游社 API 未返回成功结果")
    try:
        post = data["data"]["post"]["post"]
    except (KeyError, TypeError):
        raise ValueError("缺少 data.post.post 正文") from None
    if not isinstance(post, dict) or not post_id.isdecimal() or str(post.get("post_id")) != post_id:
        raise ValueError("公告 post_id 与指定 ID 不匹配")
    if post.get("game_id") not in (None, "", 0, "0", 2, "2"):
        raise ValueError("不是原神公告")
    if (post.get("post_status") or {}).get("is_official") is False:
        raise ValueError("该文章明确标记为非官方文章")
    title = post.get("subject")
    name_match = TITLE.match(title) if isinstance(title, str) else None
    if not name_match or "预告" in title or not ("祈愿" in title or "概率UP" in title):
        raise ValueError("只处理单篇祈愿公告，不处理祈愿预告或其他公告")
    text, text_source, html_images = article_text(post)
    if not text:
        raise ValueError("文章缺少可识别的文字正文，不能凭图片推测物品")
    official_type, pool_type = notice_type(text, title)
    items = up_items(text)
    selectable = selectable_items(text) if official_type in ("集录祈愿", "溯光祈愿") else None
    times = event_time(text)
    images = image_urls(post, html_images)
    received_images = (read_temporary_images(images_dir, post_id, images)
                       if images_dir is not None else 0)
    warnings: list[str] = []
    if official_type is None:
        warnings.append("正文未明确写出本祈愿所属类型")
    elif pool_type is None:
        warnings.append("出现未知的祈愿类型，未做自动映射")
    if not any(items.values()) and not (selectable and any(selectable.values())):
        warnings.append("正文没有识别出明确的概率 UP 或可定轨物品")
    if times["startAt"] is None and times["startCondition"] is None:
        warnings.append("正文未明确给出祈愿开始时间")
    if times["endAt"] is None:
        warnings.append("正文未明确给出祈愿结束时间")
    if images and (times["startAt"] is None or times["endAt"] is None):
        warnings.append("文章含图片，已收到临时图片，等待 OCR 时间核验"
                        if received_images else "文章含图片，但未识别图片；时间可能只出现在配图中")
    return {
        "format": "genshin-wish-notice-v1",
        "game": "genshin",
        "locale": "zh-CN",
        "noticeType": "wish_notice",
        "bannerName": name_match["name"] or ("神铸赋形" if official_type == "武器活动祈愿" else None),
        "officialWishType": official_type,
        "poolType": pool_type,
        "version": None,
        "phase": None,
        "variant": ("special_recollection" if official_type == "溯光祈愿" else
                    "chronicled" if official_type == "集录祈愿" else None),
        "up": items,
        "selectable": selectable,
        "time": times,
        "rules": rules(text),
        "imageUrls": images,
        "source": {"postId": post_id, "title": title,
                   "url": f"https://www.miyoushe.com/ys/article/{post_id}",
                   "publishedAt": published_time(post.get("created_at")),
                   "updatedAt": published_time(post.get("updated_at")),
                   "rawFile": source_file, "textSource": text_source},
        "review": {"status": "pending_manual_review", "warnings": warnings,
                   "note": "仅处理指定单篇祈愿公告；若提供临时图片目录则执行本地 OCR，并保留图片 SHA-256 作为证据；未访问其他文章、未匹配 itemId 或推断版本期数，不得直接发布到 v1"}
    }


def load_or_fetch(post_id: str, *, input_path: Path | None = None,
                  offline: bool = False, refresh: bool = False) -> tuple[dict, Path]:
    path = input_path or ARCHIVE / f"{post_id}.json"
    if input_path or (path.is_file() and not refresh):
        return json.loads(path.read_text(encoding="utf-8")), path
    if offline:
        raise FileNotFoundError(f"缺少已归档的公告：{path}")
    # 只有一个米游社详情请求；复用现有的验证码/限流检查，不查询列表。
    from scripts.collect.collect_miyoushe_announcements import fetch, save_json
    data = fetch(DETAIL_API, {"post_id": post_id, "gids": 2})
    build(data, post_id=post_id, source_file=path.as_posix())  # 验证后才保存原始数据
    save_json(path, data)
    return data, path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-id", required=True, help="本次仅提取的米游社祈愿公告 ID，如 78782590")
    parser.add_argument("--input", type=Path, help="指定已保存的单篇公告原始 JSON")
    parser.add_argument("--output", type=Path, help="指定候选结果输出路径")
    parser.add_argument("--images-dir", type=Path, help="采集器创建的临时图片目录；本地 OCR 后删除图片")
    parser.add_argument("--offline", action="store_true", help="只读取本地数据，不联网")
    parser.add_argument("--refresh", action="store_true", help="仅重新请求指定文章，不请求公告列表")
    parser.add_argument("--force", action="store_true", help="允许覆盖内容不同的旧候选结果")
    args = parser.parse_args(argv)
    if not args.post_id.isdecimal():
        parser.error("--post-id 必须为数字")
    if args.input and args.refresh:
        parser.error("--input 与 --refresh 不可同时使用")
    try:
        raw, source = load_or_fetch(args.post_id, input_path=args.input,
                                    offline=args.offline, refresh=args.refresh)
        try:
            source_file = source.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            source_file = str(source.resolve())
        result = build(raw, post_id=args.post_id, source_file=source_file, images_dir=args.images_dir)
        if args.images_dir is not None:
            from scripts.transform.recognize_genshin_wish_image_zh_cn import recognize_time
            try:
                recognized = recognize_time(args.images_dir, args.post_id, result["imageUrls"])
            except (OSError, ValueError, RuntimeError) as exc:
                recognized = {"status": "error", "times": None, "imageCount": None,
                              "warnings": [f"图片识别失败：{exc}"]}
            result["imageTimeRecognition"] = recognized
            evidence = recognized["times"]
            if evidence is not None:
                existing = result["time"]
                if ((existing["startAt"] is not None and existing["startAt"] != evidence["startAt"])
                        or (existing["endAt"] is not None and existing["endAt"] != evidence["endAt"])):
                    result["imageTimeRecognition"]["status"] = "conflict"
                    result["review"]["warnings"].append("正文和图片时间有冲突，未自动覆盖正文")
                else:
                    for key in ("startRaw", "endRaw", "startAt", "endAt", "startCondition"):
                        if existing[key] is None:
                            existing[key] = evidence[key]
                    result["review"]["warnings"] = [w for w in result["review"]["warnings"]
                         if not w.startswith("正文未明确给出祈愿")
                         and not w.startswith("文章含图片")]
            result["review"]["warnings"].extend(recognized["warnings"])

        output = args.output or OUTPUT / f"wish-notice_zh-CN_{args.post_id}.json"
        content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if output.is_file():
            if output.read_text(encoding="utf-8") == content:
                print(f"无变化：{output}")
                return 0
            if not args.force:
                raise FileExistsError(f"已有不同内容的候选结果：{output}（用 --force 覆盖）")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(output)
        print(f"已生成祈愿公告：{output}（{result['bannerName']}）")
        if result["review"]["warnings"]:
            print("待复核：" + "；".join(result["review"]["warnings"]))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        parser.exit(1, f"提取失败：{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
