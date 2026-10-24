#!/usr/bin/env python3
"""识别一篇原神祈愿公告已经下载的图片中的时间。

仅读取调用方提供的临时图片目录与 images_zh-CN_<文章ID>.json；
不联网、不依赖仓库永久保存图片。不识别图片中的物品名称（仍以正文为准）。
支持两种图片证据：明确的双日期范围，或“版本更新后～唯一结束日期”。
后者只记录 startCondition，不会猜测版本维护结束的具体时间。
依赖本机 Tesseract CLI；建议安装 tesseract-ocr 和 tesseract-ocr-chi-sim。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess

TZ8 = timezone(timedelta(hours=8))
TIME_RE = re.compile(
    r"(?<!\d)(20\d{2})\s*[/.-]\s*(\d(?:[ \t]{0,2}\d)?)\s*[/.-]\s*(\d(?:[ \t]{0,2}\d)?)"
    r"\s+(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)"
)
MAX_BYTES = 20 * 1024 * 1024
VERSION_UPDATE_AFTER = re.compile(r"(?P<label>(?:(?:\d+(?:\.\d+)?|月之[一二三四五六七八九十]+)\s*)?版本\s*更新后)")
MAX_IMAGES = 60


def dates_in_text(text: str) -> list[tuple[str, str]]:
    """返回 [(原文时间, +08:00 时间)]；只容忍 OCR 拆开的月、日数字，不猜日期。"""
    found: list[tuple[str, str]] = []
    for match in TIME_RE.finditer(text):
        year, month, day, hour, minute = (int(part.replace(" ", "").replace("\t", ""))
                                          for part in match.groups())
        try:
            date = datetime(year, month, day, hour, minute, tzinfo=TZ8)
        except ValueError:
            continue
        value = (match.group(0).strip(), date.isoformat(timespec="seconds"))
        if value not in found:
            found.append(value)
    return found


def validate_images(folder: Path, post_id: str, urls: list[str]) -> list[dict]:
    """用官方图片索引校验临时图片，拒绝文章混用、文件越界和损坏。"""
    if not post_id.isdecimal():
        raise ValueError("文章 ID 必须为数字")
    path = folder / f"images_zh-CN_{post_id}.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(index, dict) or index.get("format") != "genshin-notice-images-v1"
            or index.get("game") != "genshin" or index.get("locale") != "zh-CN"
            or index.get("postId") != post_id or index.get("sourceUrls") != urls
            or index.get("complete") is not True):
        raise ValueError("临时图片索引与原始公告不一致，或下载尚未完成")
    images = index.get("images")
    if not isinstance(images, list) or len(images) != len(urls) or len(images) > MAX_IMAGES:
        raise ValueError("图片索引数量与公告图片不符")
    confirmed = []
    for i, (url, rec) in enumerate(zip(urls, images), 1):
        if not isinstance(rec, dict) or rec.get("url") != url:
            raise ValueError(f"第 {i} 张图片来源 URL 不匹配")
        name = rec.get("file")
        if (not isinstance(name, str) or Path(name).name != name
                or not re.fullmatch(rf"image_zh-CN_{re.escape(post_id)}_{i:02d}\.(?:png|jpg|webp|gif)", name)):
            raise ValueError(f"第 {i} 张图片文件名不符合索引规范")
        image = folder / name
        if not image.is_file() or image.is_symlink():
            raise ValueError(f"第 {i} 张图片缺失或是符号链接")
        raw = image.read_bytes()
        digest = sha256(raw).hexdigest()
        if not raw or len(raw) > MAX_BYTES or len(raw) != rec.get("bytes") or digest != rec.get("sha256"):
            raise ValueError(f"第 {i} 张图片文件与 SHA-256 索引不符")
        confirmed.append({"path": image, "url": url, "sha256": digest, "ordinal": i})
    return confirmed


def tesseract_text(image: Path, psm: int) -> str:
    if shutil.which("tesseract") is None:
        raise RuntimeError("未安装 Tesseract OCR；请在 Runner 安装 tesseract-ocr 和 tesseract-ocr-chi-sim")
    # 图片本地识别；没有网络请求、云端 OCR 或外部 API。
    try:
        run = subprocess.run(
            ["tesseract", str(image), "stdout", "--psm", str(psm), "-l", "chi_sim+eng"],
            capture_output=True, text=True, timeout=45, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"图片 OCR 超时：{image.name}") from exc
    if run.returncode:
        raise RuntimeError(f"图片 OCR 失败：{image.name}：{run.stderr.strip()[-250:]}")
    return run.stdout


def parse_candidate(text: str) -> dict | None:
    """从同一张公告图的 OCR 文本生成一种有证据的时间解释。"""
    dates = dates_in_text(text)
    if len(dates) == 2 and dates[0][1] < dates[1][1]:
        return {"startRaw": dates[0][0], "endRaw": dates[1][0],
                "startAt": dates[0][1], "endAt": dates[1][1],
                "startCondition": None}
    condition = VERSION_UPDATE_AFTER.search(text)
    if len(dates) == 1 and condition is not None:
        return {"startRaw": condition["label"], "endRaw": dates[0][0],
                "startAt": None, "endAt": dates[0][1],
                "startCondition": "after_version_update"}
    return None


def recognize_time(folder: Path, post_id: str, urls: list[str]) -> dict:
    """只使用同一图片内相互匹配的时间证据，不跨图猜测或混用日期。"""
    images = validate_images(folder, post_id, urls)
    candidates: list[dict] = []
    warnings: list[str] = []
    for info in images:
        recognized: list[dict] = []
        for psm in (6, 11):
            text = tesseract_text(info["path"], psm)
            candidate = parse_candidate(text)
            if candidate is not None:
                recognized.append(candidate)
        if not recognized:
            continue
        keys = {(
            item["startCondition"], item["startAt"], item["endAt"]
        ) for item in recognized}
        if len(keys) != 1:
            warnings.append(f"第 {info['ordinal']} 张图片两种OCR模式得出不同的祈愿时间")
            continue
        item = recognized[0]
        candidates.append({
            **item,
            "imageUrl": info["url"], "imageSha256": info["sha256"],
            "imageOrdinal": info["ordinal"], "method": "tesseract-chi_sim+eng",
        })

    unique = {(
        item["startCondition"], item["startAt"], item["endAt"]
    ) for item in candidates}
    if len(unique) != 1 or warnings:
        if len(unique) > 1:
            warnings.append("不同图片中有不一致的时间信息，已拒绝自动填写")
        elif not warnings:
            warnings.append("图片中没有识别出唯一可靠的双日期或版本更新后条件时间")
        return {"status": "unresolved", "times": None,
                "imageCount": len(images), "warnings": warnings}
    result = candidates[0]
    status = "recognized_conditional" if result["startCondition"] else "recognized"
    return {"status": status, "times": result,
            "imageCount": len(images), "warnings": warnings}
