#!/usr/bin/env python3
"""多语言物品表异常 Issue：按游戏+语言跟踪业务阻断，临时网络故障不创建 Issue。

旧简中 Issue 由 notify_official_itemid_conflicts.py 管理，二者互不关闭。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "官方 ItemID 多语言映射冲突"
MARKER = "由多语言 ItemID 更新器生成"


def title_for(game: str, locale: str) -> str:
    return f"{PREFIX}（{game}/{locale}）"


def old_conflicted_ids(body: str) -> list[int]:
    return sorted({
        int(m.group(1))
        for m in re.finditer(r"同\s*ID\s*不同名称\s+([1-9]\d*)\s*:", body)
    })


def verified_closure(row: dict, issue: dict, root: Path, run_url: str) -> str | None:
    """接口双目录完整且现存映射自洽，才能生成包含处理结论的关闭回复。"""
    body = str(issue.get("body", ""))
    if MARKER not in body or row.get("status") != "ready":
        return None
    if len(row.get("catalogs", [])) != 2 or any(
        r.get("source") != "international" for r in row["catalogs"]
    ):
        return None
    game, locale = row["game"], row["locale"]
    path = root / "public" / "item-mappings" / game / f"{locale}.json"
    if not path.is_file():
        return None
    try:
        mapping = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(mapping, dict):
        return None
    by_id = {}
    for name, item_id in mapping.items():
        if not isinstance(name, str) or not name or type(item_id) is not int or item_id <= 0:
            return None
        if item_id in by_id and by_id[item_id] != name:
            return None
        by_id[item_id] = name
    ids = old_conflicted_ids(body)
    if "同 ID 不同名称" in body and not ids:
        return None
    if any(item_id not in by_id for item_id in ids):
        return None
    expected = row.get("newCount")
    if type(expected) is not int or len(mapping) != expected:
        return None
    results = [f"- 原冲突 ItemID `{item_id}`：最终采用 `{by_id[item_id]}`，ID 未修改。"
               for item_id in ids]
    if not results:
        results = ["- 原阻断为名称语种校验或覆盖率不足；目前已通过对应门槛。"]
    return (
        f"## 多语言映射阻断处理结论\n\n"
        f"原问题：{body.splitlines()[0]}\n\n"
        f"### 最终采用的映射\n"
        + "\n".join(results) + "\n\n"
        f"### 完整验证\n"
        f"- 目标文件：`public/item-mappings/{game}/{locale}.json`\n"
        f"- 两类国际服官方物品目录均成功，当前文件共 {len(mapping)} 条。\n"
        f"- 对照简中 ItemID 覆盖率 {row.get('baselineCoverage')}，"
        f"简中同名比例 {row.get('identicalNameRatio')}。\n"
        f"- 更新器状态为 `ready`；本次未修改历史 v1 或 Manifest。\n"
        f"- 验证运行：{run_url}\n"
    )


def actions(report: dict, issues: list[dict], owner: str, run_url: str,
            root: Path = ROOT) -> list[list[str]]:
    if not owner:
        raise ValueError("仓库所有者不能为空")
    localized = report.get("localized")
    if not isinstance(localized, dict):
        return []
    open_by_title = {x.get("title"): x for x in issues if x.get("title")}
    output = []
    for row in localized.get("results", []):
        if not isinstance(row, dict):
            continue
        game, locale = row.get("game"), row.get("locale")
        if game not in ("genshin", "starrail") or locale not in ("zh-TW", "en-US", "ja-JP"):
            continue
        title = title_for(game, locale)
        existing = open_by_title.get(title)
        status = row.get("status")
        if status in ("conflict", "incomplete", "suspicious-language"):
            if existing:
                if owner not in {x.get("login") for x in existing.get("assignees", [])}:
                    output.append(["gh", "issue", "edit", str(existing["number"]), "--add-assignee", owner])
            else:
                details = [str(row.get("reason") or status)]
                details += [str(x["error"]) for x in row.get("catalogs", []) if x.get("error")]
                body = (
                    f"{MARKER}：{game}/{locale}\n\n"
                    f"阻断类型：`{status}`，本语言文件未被更新。\n\n"
                    + "\n".join(f"- {x}" for x in dict.fromkeys(details)) + "\n\n"
                    "请核对该语言官方名称与 ItemID，确认后下次成功校验会附结论关闭。"
                    f"\n运行：{run_url}"
                )
                output.append(["gh", "issue", "create", "--title", title,
                               "--body", body, "--assignee", owner])
        elif status == "ready" and existing:
            resolution = verified_closure(row, existing, root, run_url)
            if resolution is not None:
                output.append(["gh", "issue", "close", str(existing["number"]),
                               "--reason", "completed", "--comment", resolution])
        # 网络不可用时不新建、不自动关闭，避免接口抖动造成误通知。
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    repository = os.environ["GITHUB_REPOSITORY"]
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or repository.split("/")[0]
    run_url = f"https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    existing = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", "100",
                               "--json", "number,title,assignees,body"],
                              check=True, capture_output=True, text=True)
    commands = actions(report, json.loads(existing.stdout), owner, run_url)
    for command in commands:
        subprocess.run(command, check=True)
        print(f"多语言 ItemID Issue 操作：{command[:4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
