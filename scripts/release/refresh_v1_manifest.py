#!/usr/bin/env python3
"""Refresh public v1 manifest hashes/counts from the published JSON bytes."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.release.validate_v1 import validate_manifest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public" / "v1"
TZ8 = timezone(timedelta(hours=8))


def refresh_manifest(folder: Path = PUBLIC) -> bool:
    """Validate the release and atomically refresh changed manifest metadata."""
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    changed = False
    for game, entry in manifest["games"].items():
        # The v1 contract currently declares one fixed JSON filename per game.
        filename = f"{game}.json"
        if entry["path"] != filename:
            raise ValueError(f"{game}: unexpected manifest path {entry['path']!r}")

        raw = (folder / filename).read_bytes()
        dataset = json.loads(raw)
        if dataset.get("game") != game:
            raise ValueError(f"{game}: game field mismatch")
        banners = dataset.get("banners")
        if not isinstance(banners, list):
            raise ValueError(f"{game}: banners must be an array")

        digest = hashlib.sha256(raw).hexdigest()
        count = len(banners)
        if entry.get("sha256") != digest or entry.get("bannerCount") != count:
            entry["sha256"] = digest
            entry["bannerCount"] = count
            changed = True

    if changed:
        manifest["generatedAt"] = datetime.now(TZ8).isoformat(timespec="seconds")

    # Run the existing schema, semantic and hash validation before any write.
    # An invalid dataset must never result in a newly published manifest.
    validate_manifest(manifest, folder)
    if not changed:
        print("v1 manifest is already current; nothing to write.")
        return False

    payload = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temp_path = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
        os.replace(temp_path, manifest_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    for game, entry in manifest["games"].items():
        print(f"{game}: {entry['bannerCount']} banners, SHA-256 {entry['sha256']}")
    print("public/v1/manifest.json refreshed.")
    return True


if __name__ == "__main__":
    refresh_manifest()
