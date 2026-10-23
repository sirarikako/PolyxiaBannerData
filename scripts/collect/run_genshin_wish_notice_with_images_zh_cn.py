#!/usr/bin/env python3
"""在 Action 运行期间下载并识别指定单篇祈愿公告的图片，最终仅保存候选 JSON。

原始正文只读自 posts/<id>.json；图片仅访问 upload-bbs.miyoushe.com。
使用 TemporaryDirectory，所有图片与图片索引离开上下文后自动删除。
不访问其他文章、不保存图片到仓库、不修改 public/v1/。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.collect.download_genshin_notice_images_zh_cn import download_images
from scripts.transform.build_genshin_wish_notice_zh_cn import (
    ARCHIVE, OUTPUT, main as build_main
)


def process(post_id: str, *, output: Path | None = None) -> Path:
    if not post_id.isdecimal():
        raise ValueError("米游社文章 ID 不是数字")
    raw_file = ARCHIVE / f"{post_id}.json"
    raw = json.loads(raw_file.read_text(encoding="utf-8"))
    try:
        post = raw["data"]["post"]["post"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"原始文章缺少详情：{post_id}") from exc
    if str(post.get("post_id")) != post_id:
        raise ValueError("公告 ID 与指定文章不一致")

    target = output or OUTPUT / f"wish-notice_zh-CN_{post_id}.json"
    with TemporaryDirectory(prefix=f"genshin-wish-notice-zh-CN-{post_id}-") as temporary:
        index = download_images(post, post_id, output_root=Path(temporary))
        args = ["--post-id", post_id, "--input", str(raw_file),
                "--output", str(target), "--force"]
        if index:
            args.extend(["--images-dir", str(index.parent)])
        status = build_main(args)
        if status != 0:
            raise RuntimeError(f"解析失败：公告 {post_id}（退出码 {status}）")
        result = json.loads(target.read_text(encoding="utf-8"))
        if (result.get("locale") != "zh-CN"
                or result.get("noticeType") != "wish_notice"
                or result.get("source", {}).get("postId") != post_id):
            raise ValueError(f"输出结果与公告 {post_id} 不对应")
        if index is not None:
            recognition = result.get("imageTimeRecognition") or {}
            if recognition.get("status") not in ("recognized", "recognized_conditional", "unresolved", "conflict"):
                raise RuntimeError(
                    f"公告 {post_id} 图片 OCR 未成功执行：{recognition.get('warnings')}"
                )
        # 本函数结束后临时图片即删除，不在输出中写入本地路径。
        return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-id", required=True, help="只处理此一篇米游社公告")
    parser.add_argument("--output", type=Path, help="候选 JSON 输出位置")
    args = parser.parse_args(argv)
    try:
        target = process(args.post_id, output=args.output)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(1, f"图片解析失败：{exc}\n")
    print(f"单篇公告已解析，临时图片已清理：{target}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
