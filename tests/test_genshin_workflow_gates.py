"""Execute the actual 2-1/2-2 workflow gate scripts with isolated fake inputs.

These checks do not invoke the GitHub API, collect announcements, modify official
checkpoint/V1 data, or publish anything. Any workflow gate refactor is tested from
the YAML it will actually run, not from a reimplemented condition.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
COLLECT_YAML = ROOT / ".github/workflows/genshin-notices-zh-cn-daily-preview.yml"
PUBLISH_YAML = ROOT / ".github/workflows/genshin-v1-auto-publish.yml"
CHECKPOINT = Path("data/derived/genshin/notice-discovery/notice-discovery_zh-CN_checkpoint.json")
RETRY_CRON = "27,37,47,57 6 * * *"
DAILY_CRON = "17 6 * * *"


def gate_script(workflow: Path, job: str) -> str:
    """Return bash source from the real job's gate step; fail on YAML drift."""
    lines = workflow.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  {job}:")
    finish = next(
        (i for i in range(start + 1, len(lines))
         if re.fullmatch(r"  [a-zA-Z0-9_-]+:", lines[i])),
        len(lines),
    )
    gate = next(
        i for i in range(start + 1, finish) if lines[i] == "        id: gate"
    )
    body_start = next(
        i + 1 for i in range(gate + 1, finish)
        if lines[i] == "        run: |"
    )
    body = []
    for line in lines[body_start:finish]:
        if line and not line.startswith("          "):
            break
        body.append(line[10:] if line else "")
    script = "\n".join(body) + "\n"
    assert script.strip(), "Workflow gate shell source is missing"
    return script


def run_gate(tmp_path: Path, script: str, *, extra_env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    output = tmp_path / "github-output.txt"
    summary = tmp_path / "github-summary.txt"
    env = os.environ.copy()
    env.update({
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_REPOSITORY": "sirarikako/CastoriceWishBannerData",
        "PYTHONPATH": str(ROOT) + os.pathsep + env.get("PYTHONPATH", ""),
    })
    env.update(extra_env)
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15,
        check=False,
    )
    reported = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    ) if output.exists() else {}
    return result, reported


def put_checkpoint(tmp_path: Path, errors: list[str | None] | None) -> None:
    if errors is None:
        return  # missing checkpoint
    path = tmp_path / CHECKPOINT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "format": "genshin-notice-discovery-v1",
        "game": "genshin",
        "locale": "zh-CN",
        "pending": {
            str(500 + i): {"lastError": error} for i, error in enumerate(errors)
        },
    }, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("event,cron,retry_only,errors,expected", [
    ("schedule", DAILY_CRON, "false", [], True),
    ("schedule", RETRY_CRON, "false", [], True),
    ("schedule", RETRY_CRON, "false", [None], True),
    ("schedule", RETRY_CRON, "false", ["图片请求临时失败：timeout"], True),
    ("schedule", RETRY_CRON, "false", ["OCR unresolved"], True),
    ("schedule", RETRY_CRON, "false", ["米游社要求验证或出现限流，已停止"], True),
    ("schedule", RETRY_CRON, "false", ["OCR unresolved", "图片请求临时失败：timeout"], True),
    ("workflow_dispatch", "", "true", [], False),
    ("workflow_dispatch", "", "true", [None], True),
    ("workflow_dispatch", "", "false", [], True),
    ("push", "", "false", [], True),
])
def test_21_real_gate_script(tmp_path, event, cron, retry_only, errors, expected):
    put_checkpoint(tmp_path, errors)
    result, reported = run_gate(
        tmp_path, gate_script(COLLECT_YAML, "check-pending"),
        extra_env={"EVENT_NAME": event, "SCHEDULE": cron, "RETRY_ONLY": retry_only},
    )
    assert result.returncode == 0, result.stderr
    assert reported["should_run"] == str(expected).lower()
    assert not (tmp_path / "public/v1/genshin.json").exists()


@pytest.mark.parametrize("errors", [None, ["图片请求临时失败：timeout"]])
def test_21_missing_or_invalid_checkpoint_fails_closed(tmp_path, errors):
    put_checkpoint(tmp_path, errors)
    if errors is not None:
        (tmp_path / CHECKPOINT).write_text('{"pending": "broken"}', encoding="utf-8")
    result, reported = run_gate(
        tmp_path, gate_script(COLLECT_YAML, "check-pending"),
        extra_env={"EVENT_NAME": "workflow_dispatch", "SCHEDULE": "", "RETRY_ONLY": "true"},
    )
    assert result.returncode != 0
    assert "should_run" not in reported


def test_21_schedule_does_not_require_checkpoint(tmp_path):
    result, reported = run_gate(
        tmp_path, gate_script(COLLECT_YAML, "check-pending"),
        extra_env={"EVENT_NAME": "schedule", "SCHEDULE": RETRY_CRON, "RETRY_ONLY": "false"},
    )
    assert result.returncode == 0, result.stderr
    assert reported["should_run"] == "true"


def install_fake_gh(tmp_path: Path) -> Path:
    """Emulate only the expected gh api job query, never a real GitHub action."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "query = '.jobs[] | select(.name == \"collect-and-preview\") | .conclusion'\n"
        "expected = ['api', 'repos/sirarikako/CastoriceWishBannerData/actions/runs/1234/jobs?per_page=100', '--paginate', '--jq', query]\n"
        "if sys.argv[1:] != expected:\n"
        "    print('Unexpected gh api request: ' + repr(sys.argv[1:]), file=sys.stderr)\n"
        "    sys.exit(4)\n"
        "if os.environ.get('FAKE_GH_FAIL') == 'true':\n"
        "    print('Simulated GitHub API outage', file=sys.stderr)\n"
        "    sys.exit(5)\n"
        "for item in json.loads(os.environ['FAKE_GH_JOBS']):\n"
        "    if item.get('name') == 'collect-and-preview':\n"
        "        print(item.get('conclusion') or '')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return bin_dir


@pytest.mark.parametrize("event,upstream,jobs,expected", [
    ("push", "", [], True),
    ("workflow_dispatch", "", [], True),
    ("workflow_run", "failure", [], False),
    ("workflow_run", "cancelled", [], False),
    ("workflow_run", "success", [], False),
    ("workflow_run", "success", [
        {"name": "check-pending", "conclusion": "success"},
        {"name": "collect-and-preview", "conclusion": "skipped"},
    ], False),
    ("workflow_run", "success", [
        {"name": "check-pending", "conclusion": "success"},
        {"name": "collect-and-preview", "conclusion": "failure"},
    ], False),
    ("workflow_run", "success", [
        {"name": "check-pending", "conclusion": "success"},
        {"name": "collect-and-preview", "conclusion": "success"},
    ], True),
])
def test_22_real_gate_script(tmp_path, event, upstream, jobs, expected):
    bin_dir = install_fake_gh(tmp_path)
    result, reported = run_gate(
        tmp_path, gate_script(PUBLISH_YAML, "verify-upstream"),
        extra_env={
            "EVENT_NAME": event,
            "UPSTREAM_RUN_ID": "1234",
            "UPSTREAM_CONCLUSION": upstream,
            "FAKE_GH_JOBS": json.dumps(jobs),
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        },
    )
    assert result.returncode == 0, result.stderr
    assert reported["should_publish"] == str(expected).lower()
    assert not (tmp_path / "public/v1/genshin.json").exists()


def test_22_github_api_failure_does_not_allow_publish(tmp_path):
    bin_dir = install_fake_gh(tmp_path)
    result, reported = run_gate(
        tmp_path, gate_script(PUBLISH_YAML, "verify-upstream"),
        extra_env={
            "EVENT_NAME": "workflow_run",
            "UPSTREAM_RUN_ID": "1234",
            "UPSTREAM_CONCLUSION": "success",
            "FAKE_GH_JOBS": "[]",
            "FAKE_GH_FAIL": "true",
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        },
    )
    assert result.returncode != 0
    assert "should_publish" not in reported


def test_real_workflow_dependencies_are_wired_correctly():
    collect = COLLECT_YAML.read_text(encoding="utf-8")
    publish = PUBLISH_YAML.read_text(encoding="utf-8")
    assert f"cron: '{DAILY_CRON}'" in collect
    assert f"cron: '{RETRY_CRON}'" in collect
    assert "if: needs.check-pending.outputs.should_run == 'true'" in collect
    assert "python -m scripts.collect.collect_genshin_notices_zh_cn --retry-only" in collect
    assert "python -m scripts.collect.collect_genshin_notices_zh_cn --max-pages 15" in collect
    assert "SCHEDULE" not in collect.split("id: collect", 1)[1].split("id: assemble", 1)[0]
    assert "  verify-upstream:\n" in publish
    assert "    needs: verify-upstream\n" in publish
    assert "    if: needs.verify-upstream.outputs.should_publish == 'true'" in publish
    assert "      - '2-1_原神公告每日自动采集与解析'" in publish
    assert not (ROOT / ".github/workflows/genshin-notice-pending-retry.yml").exists()
