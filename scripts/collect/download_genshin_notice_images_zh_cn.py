#!/usr/bin/env python3
"""米游社原神简体中文公告图片的临时下载工具。

仅在公告解析期间由 collect_genshin_notices_zh_cn 调用；调用方传入
tempfile.TemporaryDirectory() 路径。图片和临时索引不写入 Git 仓库，
退出解析作用域后由调用方删除；不会写入 public/v1。
图片仍只从米游社官方图片 CDN 获取。
"""
from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from scripts.collect.collect_miyoushe_announcements import RateLimited, save_json
OFFICIAL_IMAGE_HOST = "upload-bbs.miyoushe.com"
MAX_IMAGES = 60
MAX_IMAGE_BYTES = 20 * 1024 * 1024

SIGNATURES = {
    "png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    "jpg": ("image/jpeg", b"\xff\xd8\xff"),
    "gif": ("image/gif", b"GIF8"),
    "webp": ("image/webp", b"RIFF"),
}


class ImageArchiveError(RuntimeError):
    """图片来源不受支持、文件校验失败或下载失败。"""


class ImageTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "img":
            values = dict(attrs)
            for key in ("src", "data-src", "data-original"):
                if isinstance(values.get(key), str) and values[key].startswith("https://"):
                    self.urls.append(values[key])
                    break


def image_urls(post: dict) -> list[str]:
    """优先采用官方 images 数组，补充正文 img 与 cover，按 URL 去重。"""
    raw = post.get("images") or []
    if not isinstance(raw, list):
        raise ImageArchiveError("原始公告 images 字段不是数组")
    candidate = list(raw)
    html = post.get("content")
    if isinstance(html, str) and "<img" in html.lower():
        parser = ImageTags()
        parser.feed(html)
        candidate.extend(parser.urls)
    if isinstance(post.get("cover"), str) and post["cover"]:
        candidate.append(post["cover"])
    urls: list[str] = []
    for url in candidate:
        if not isinstance(url, str) or not url:
            raise ImageArchiveError("原始公告中存在非字符串图片 URL")
        if url not in urls:
            urls.append(url)
    if len(urls) > MAX_IMAGES:
        raise ImageArchiveError(f"公告图片超过上限 {MAX_IMAGES} 张，需人工处理")
    for url in urls:
        validate_url(url)
    return urls


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != OFFICIAL_IMAGE_HOST
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or not parsed.path.startswith("/upload/") or parsed.fragment):
        raise ImageArchiveError(f"拒绝非官方米游社上传图片 URL：{url[:200]}")


def detect_image(data: bytes) -> tuple[str, str]:
    """检查真实图片签名，防止把 HTML 错误页存成图片。"""
    for ext, (mime, magic) in SIGNATURES.items():
        if not data.startswith(magic):
            continue
        if ext == "webp" and data[8:12] != b"WEBP":
            break
        if ext == "gif" and data[:6] not in (b"GIF87a", b"GIF89a"):
            break
        return ext, mime
    raise ImageArchiveError("响应数据不是支持的 PNG/JPEG/GIF/WebP 图片")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ImageArchiveError("图片请求发生重定向；未跟随其他域名")


def download_image(url: str) -> tuple[bytes, str, str]:
    validate_url(url)
    opener = build_opener(NoRedirect())
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; CastoriceWishBannerData/1.0)",
        "Accept": "image/png,image/jpeg,image/webp,image/gif",
        "Referer": "https://www.miyoushe.com/",
    })
    try:
        with opener.open(request, timeout=25) as response:
            if (response.headers.get("Content-Length")
                    and int(response.headers["Content-Length"]) > MAX_IMAGE_BYTES):
                raise ImageArchiveError("图片超过单张 20 MiB 限制")
            data = response.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise ImageArchiveError("图片超过单张 20 MiB 限制")
    except HTTPError as exc:
        if exc.code == 429:
            raise RateLimited("米游社图片下载遇到 HTTP 429") from exc
        raise ImageArchiveError(f"图片下载 HTTP {exc.code}") from exc
    if not data:
        raise ImageArchiveError("图片内容为空")
    ext, mime = detect_image(data)
    return data, ext, mime


def download_images(post: dict, post_id: str, *, output_root: Path) -> Path | None:
    """在指定的临时目录下载图片，写入临时索引供本轮解析器使用。"""
    if not post_id.isdecimal() or str(post.get("post_id")) != post_id:
        raise ImageArchiveError("原始公告文章 ID 不匹配")
    urls = image_urls(post)
    if not urls:
        return None
    folder = output_root / post_id
    index_path = folder / f"images_zh-CN_{post_id}.json"
    index = {
        "format": "genshin-notice-images-v1",
        "game": "genshin",
        "locale": "zh-CN",
        "postId": post_id,
        "sourceUrls": urls,
        "complete": False,
        "images": [],
    }
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if (not isinstance(index, dict)
                or index.get("format") != "genshin-notice-images-v1"
                or index.get("postId") != post_id or index.get("locale") != "zh-CN"
                or index.get("sourceUrls") != urls
                or not isinstance(index.get("images"), list)):
            raise ImageArchiveError("已保存的图片索引与当前原始公告不匹配，拒绝覆盖")
    prior = {entry["url"]: entry for entry in index["images"]}
    for number, url in enumerate(urls, 1):
        saved = prior.get(url)
        if saved is not None:
            name = saved.get("file")
            if (not isinstance(name, str)
                    or not name.startswith(f"image_zh-CN_{post_id}_{number:02d}.")
                    or Path(name).name != name):
                raise ImageArchiveError("图片索引包含非法文件名")
            path = folder / name
            if path.is_file():
                data = path.read_bytes()
                if (sha256(data).hexdigest() != saved["sha256"]
                        or len(data) != saved["bytes"]
                        or len(data) > MAX_IMAGE_BYTES):
                    raise ImageArchiveError(f"已下载图片损坏，拒绝覆盖：{name}")
                continue
        data, extension, mime = download_image(url)
        name = f"image_zh-CN_{post_id}_{number:02d}.{extension}"
        path = folder / name
        if path.exists() and (saved is None or saved.get("file") != name):
            raise ImageArchiveError(f"目标图片已存在但未在索引中确认：{path}")
        folder.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        record = {"url": url, "file": name, "mimeType": mime,
                  "bytes": len(data), "sha256": sha256(data).hexdigest()}
        if saved is None:
            index["images"].append(record)
        else:
            index["images"][index["images"].index(saved)] = record
        prior[url] = record
        save_json(index_path, index)
    index["complete"] = True
    save_json(index_path, index)
    return index_path


