#!/usr/bin/env python3
"""官方 ItemID 日更 Issue 生命周期：新增时指派仓库所有者，校验无冲突后自动关闭。

只根据经过更新器完整检查的 JSON 报告处理；接口两类未全部返回可靠数据时
不自动关闭旧 Issue。已存在且无人负责的 Issue 自动补指派。
关闭评论必须依据原 Issue 明细及最终映射写出处理结论，否则保持开放。
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import subprocess
from typing import Callable

GAMES = ("genshin", "starrail")
TITLE_PREFIX = "官方 ItemID 映射冲突"
ROOT = Path(__file__).resolve().parents[2]


def title_for(game: str) -> str:
    return f"{TITLE_PREFIX}（{game}）"


def verified_complete(report: dict, game: str) -> bool:
    """必须成功得到该游戏两类官方物品目录，并且无冲突，才可关闭旧问题。"""
    if game in report.get("blockedGames", {}):
        return False
    categories = {
        row.get("category"): row.get("source")
        for row in report.get("catalogs", [])
        if isinstance(row, dict) and row.get("category", "").startswith(f"{game}-")
    }
    expected = {f"{game}-characters", f"{game}-weapons"} if game == "genshin" else {
        "starrail-characters", "starrail-lightcones"
    }
    return set(categories) == expected and all(categories[key] in ("cn", "international") for key in expected)


def closure_comment(issue: dict, game: str, run_url: str, mapping_root: Path) -> str | None:
    """用原始 Issue 的冲突明细 + 当前映射给出可审计的处理结论。

    映射只能证明目前选用的名称，不能推断由谁做出决定或自动修改历史 v1。
    无原始 ID、ID 不在映射中或 ID 对应多个名称，都不能擅自宣布解决。
    """
    conflict = []
    seen: set[int] = set()
    for line in str(issue.get("body") or "").splitlines():
        match = re.search(r"同\s*ID\s*不同名称\s+([1-9]\d*)\s*:", line)
        if match:
            item_id = int(match.group(1))
            if item_id not in seen:
                conflict.append((item_id, line.strip().lstrip("- ").strip()))
                seen.add(item_id)
    if not conflict:
        return None
    path = mapping_root / "public" / "item-mappings" / game / "zh-CN.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    by_id: dict[int, str] = {}
    for name, item_id in data.items():
        if not isinstance(name, str) or not name or type(item_id) is not int or item_id <= 0:
            return None
        if item_id in by_id and by_id[item_id] != name:
            return None
        by_id[item_id] = name
    if not all(item_id in by_id for item_id, _ in conflict):
        return None
    original = "\n".join(f"- {line}" for _, line in conflict)
    selected = "\n".join(
        f"- ItemID `{item_id}`：最终采用 **`{by_id[item_id]}`**，"
        f"ID 保持 `{item_id}` 不变。"
        for item_id, _ in conflict
    )
    return (
        "## 冲突处理结论\n\n"
        "### 原始冲突\n"
        f"{original}\n\n"
        "### 最终采用的映射（以当前仓库对照表为准）\n"
        f"{selected}\n\n"
        "### 修改范围与验证\n"
        f"- 处理目标：`public/item-mappings/{game}/zh-CN.json`；"
        "本每日更新工作流不会修改已发布的 v1 或 Manifest。\n"
        "- 已重新读取本游戏角色与武器/光锥两类官方目录，"
        "完成校验，未发现同 ID 不同名称冲突。\n"
        "- 已确认所有原冲突 ID 在当前对照表中有唯一名称，按处理完成自动关闭本 Issue。\n\n"
        f"验证运行：{run_url}"
    )


def actions(report: dict, open_issues: list[dict], owner: str, run_url: str,
            mapping_root: Path | None = None) -> list[list[str]]:
    """返回 gh CLI 命令列表，便于脱离网络进行回归测试。"""
    if not owner:
        raise ValueError("必须确定 GitHub 仓库所有者，不能创建无负责人 Issue")
    if not isinstance(report.get("blockedGames"), dict):
        raise ValueError("缺少 blockedGames，不能根据不完整报告修改 Issue")
    issues_by_title = {item["title"]: item for item in open_issues if item.get("title")}
    mapping_root = mapping_root or ROOT
    commands: list[list[str]] = []
    for game in GAMES:
        title = title_for(game)
        issue = issues_by_title.get(title)
        errors = report["blockedGames"].get(game)
        if errors:
            if not isinstance(errors, list) or not all(isinstance(x, str) and x for x in errors):
                raise ValueError(f"{game}: 非法冲突清单")
            if issue:
                assignees = {user.get("login") for user in issue.get("assignees", [])}
                if owner not in assignees:
                    commands.append(["gh", "issue", "edit", str(issue["number"]), "--add-assignee", owner])
            else:
                body = (
                    "每日官方 ItemID 更新发现同一游戏内 ID 对应不同名称，已阻断该游戏文件更新。\n\n"
                    + "\n".join(f"- {error}" for error in errors)
                    + "\n\n请人工确认后修订对照表；下一次完整校验无冲突时将自动关闭本 Issue。\n"
                    + f"\n工作流：{run_url}\n"
                )
                commands.append(["gh", "issue", "create", "--title", title,
                                 "--body", body, "--assignee", owner])
        elif issue and verified_complete(report, game):
            body = closure_comment(issue, game, run_url, mapping_root)
            if body is None:
                print(f"{game}: 无法从 Issue 和当前对照表确定原冲突 ID 的最终处理结论，保留开放状态。")
                continue
            commands.append(["gh", "issue", "close", str(issue["number"]),
                             "--reason", "completed", "--comment", body])
    return commands


def summarize(report: dict) -> str:
    lines = ["### ItemID 官方接口每日更新", ""]
    for row in report.get("catalogs", []):
        lines.append(f"- {row['category']}: {row['source']}，{row.get('uniqueItemIds', 0)} IDs；"
                     f"回退原因：{row.get('fallbackReason') or row.get('error') or '无'}")
    for game, row in report.get("games", {}).items():
        lines.append(f"- {game}: 原有 {row['oldCount']}，新增 {row['newEntries']}；"
                     f"同名不同 ID 允许 {row['allowedSameNameDifferentId']}；阻断={row['blocked']}")
    for game, errors in report.get("blockedGames", {}).items():
        lines.append(f"- **{game} 同 ID 不同名称**: {'; '.join(errors)}")
    return "\n".join(lines) + "\n"


def notify(
    report: dict, *, owner: str, repository: str, run_id: str,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[list[str]]:
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    found = runner(["gh", "issue", "list", "--state", "open", "--limit", "100",
                    "--json", "number,title,assignees,body"],
                   check=True, text=True, capture_output=True)
    issues = json.loads(found.stdout)
    commands = actions(report, issues, owner, run_url)
    for command in commands:
        runner(command, check=True)
    return commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as out:
            out.write(summarize(report))
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or os.environ["GITHUB_REPOSITORY"].split("/")[0]
    commands = notify(report, owner=owner,
                      repository=os.environ["GITHUB_REPOSITORY"],
                      run_id=os.environ["GITHUB_RUN_ID"])
    for cmd in commands:
        print("ItemID Issue 操作:", cmd[:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
