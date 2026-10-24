#!/usr/bin/env python3
"""检查原神简中公告是否存在可以自动重试的 pending；仅依赖标准库。"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / "data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json"

# 仅允许网络临时故障或尚未执行的条目自动重试。
# OCR/解析错误已移入 manualReview；验证/限流也不在这里盲目重试。
TRANSIENT_PREFIXES = (
    "公告详情暂时获取失败：",
    "图片来源临时故障：",
    "图片请求临时失败：",
)


def is_retryable_pending(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    error = entry.get("lastError")
    return error is None or (
        isinstance(error, str) and error.startswith(TRANSIENT_PREFIXES)
    )


def pending_counts(path: Path = CHECKPOINT) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    state = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(state, dict)
            or state.get("format") != "genshin-notice-discovery-v1"
            or state.get("game") != "genshin"
            or state.get("locale") != "zh-CN"
            or not isinstance(state.get("pending"), dict)):
        raise ValueError("公告 checkpoint 格式异常，不允许把损坏状态当作空队列")
    items = state["pending"]
    return len(items), sum(is_retryable_pending(item) for item in items.values())


def main() -> int:
    total, retryable = pending_counts()
    print(f"checkpoint pending：{total}，可自动重试：{retryable}")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as output:
            output.write(f"has_retryable={'true' if retryable else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
