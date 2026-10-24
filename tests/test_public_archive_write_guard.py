"""Legacy archiver is permitted to commit raw historical posts in Private only.

These tests are offline and never invoke git add/commit/push or a network API.
"""
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from scripts.collect import collect_miyoushe_announcements as archive


@pytest.mark.parametrize("name", [
    "sirarikako/PolyxiaBannerData", "another-owner/PolyxiaBannerData",
    "other/repository",
])
def test_github_action_context_other_than_private_rejects_git_writes(monkeypatch, name, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", name)
    with patch.object(archive.subprocess, "run") as command:
        assert archive.archive_git_write_allowed() is False
        with pytest.raises(PermissionError, match="Private"):
            archive.Collector(tmp_path, commit_progress=True)
        # Direct invocation must not bypass the CLI or constructor guard.
        no_commit = archive.Collector(tmp_path, commit_progress=False)
        with pytest.raises(PermissionError, match="Public"):
            no_commit.git_commit()
        with pytest.raises(SystemExit) as stopped:
            archive.main(["--commit-progress", "--output", str(tmp_path)])
        assert stopped.value.code == 2
        command.assert_not_called()


@pytest.mark.parametrize("origin", [
    "https://github.com/sirarikako/PolyxiaBannerData.git",
    "git@github.com:sirarikako/PolyxiaBannerData.git",
    "https://github.com/another-owner/CastoriceWishBannerData.git",
    "https://github.com/sirarikako/CastoriceWishBannerData-extra",
    "",
])
def test_without_actions_env_public_or_unknown_remote_fails_closed(monkeypatch, origin):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    response = CompletedProcess(["git"], 0 if origin else 1, stdout=origin + "\n")
    with patch.object(archive.subprocess, "run", return_value=response) as command:
        assert archive.archive_git_write_allowed() is False
        command.assert_called_once()


@pytest.mark.parametrize("origin", [
    "https://github.com/sirarikako/CastoriceWishBannerData.git",
    "git@github.com:sirarikako/CastoriceWishBannerData.git",
    "ssh://git@github.com/sirarikako/CastoriceWishBannerData.git",
])
def test_private_repository_can_retain_explicit_archive_commit_mode(monkeypatch, origin, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "sirarikako/CastoriceWishBannerData")
    reply = CompletedProcess(["git"], 0, stdout=origin + "\n")
    with patch.object(archive.subprocess, "run", return_value=reply):
        assert archive.archive_git_write_allowed() is True
        obj = archive.Collector(tmp_path, commit_progress=True)
        assert obj.commit_progress


def test_git_remote_errors_also_fail_closed(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    with patch.object(archive.subprocess, "run", side_effect=OSError("git missing")):
        assert archive.archive_git_write_allowed() is False


def test_public_archive_still_can_be_used_for_temporary_local_processing(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "sirarikako/PolyxiaBannerData")
    with patch.object(archive.subprocess, "run") as command:
        obj = archive.Collector(tmp_path, commit_progress=False)
        assert obj.commit_progress is False
        command.assert_not_called()
