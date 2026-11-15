"""Append an audit entry for each V1 pool creation/patch after successful import.

This runs after a successful V1 import in the production workflow, with the
importer's JSON report. It does not alter V1. The caller must commit the journal
together with the V1 file; a failed push must retry both.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scripts.collect.collect_genshin_webstatic import ROOT, _load, _encoded, _write_if_changed
from scripts.release.generate_genshin_source_report import _actual_fields

OUTPUT = Path("data/derived/genshin/source-traces/publication-events.json")
TZ8 = timezone(timedelta(hours=8))


def record(root: Path, import_report: dict, *, observed_at: str | None = None) -> dict:
    if import_report.get("mode") != "write":
        raise ValueError("Only a successfully executed --write import report is accepted")
    observed_at = observed_at or datetime.now(TZ8).isoformat(timespec="seconds")
    journal = _load(root / OUTPUT, {"format": "genshin-publication-events-v1", "events": []})
    events = journal.setdefault("events", [])
    if not isinstance(events, list):
        raise ValueError("Malformed publication event journal")
    candidate_map = {}
    all_candidates = []
    for path in sorted((root / "data/derived/genshin/v1-candidates").glob("v1-candidate_zh-CN_*.json")):
        candidate = _load(path)
        key = str(candidate.get("sourceKey") or candidate.get("postId") or "")
        if candidate.get("status") == "ready_candidate":
            pair = (candidate, path.relative_to(root).as_posix())
            all_candidates.append(pair)
            if key:
                candidate_map[key] = pair

    existing_keys = {(str(x.get("action")), str(x.get("v1Id")),
                      str(x.get("candidateSourceKey")), str(x.get("publishedV1GeneratedAt")))
                     for x in events}
    updated = 0
    published = _load(root / "public/v1/genshin.json", {})
    generation = published.get("generatedAt")
    ids = {b["id"] for b in published.get("banners", [])}
    for action, changes in (("created", import_report.get("appended", [])),
                            ("patched", import_report.get("updatedExistingIds", []))):
        for row in changes:
            bid = row.get("id") if isinstance(row, dict) else str(row)
            if bid not in ids:
                raise ValueError(f"Cannot trace an ID absent from V1: {bid}")
            post_id = str(row.get("postId") or "") if isinstance(row, dict) else ""
            candidate = candidate_map.get(post_id)
            actual = next(b for b in published["banners"] if b["id"] == bid)
            if candidate is None and action == "created":
                options = [
                    pair for pair in all_candidates
                    if (pair[0].get("v1Draft", {}).get("poolType"),
                        pair[0].get("v1Draft", {}).get("names", {}).get("zh-CN"),
                        pair[0].get("version"), pair[0].get("phase"))
                    == (actual.get("poolType"), actual.get("names", {}).get("zh-CN"),
                        actual.get("gameVersion"), actual.get("phase"))
                ]
                if len(options) == 1:
                    candidate = options[0]
            source_key = str(candidate[0].get("sourceKey") or "") if candidate else ""
            dedup = (action, bid, source_key, str(generation))
            if dedup in existing_keys:
                continue
            fields = _actual_fields(candidate[0]) if candidate else (
                {"manualPatch": ["manual"]} if action == "patched" else {})
            if action == "created" and candidate:
                draft = candidate[0].get("v1Draft", {})
                if (actual.get("poolType"), actual.get("names", {}).get("zh-CN")) != (
                        draft.get("poolType"), draft.get("names", {}).get("zh-CN")):
                    candidate = None
                    fields = {"unattributed": ["candidate-identity-conflict"]}
            events.append({
                "action": action, "v1Id": bid, "recordedAt": observed_at,
                "publishedV1GeneratedAt": generation, "candidateSourceKey": source_key or None,
                "candidateFile": candidate[1] if candidate else None,
                "fieldSources": fields,
                "attributionStatus": "matched_candidate" if candidate else "needs_review",
                "sourceRefs": candidate[0].get("provenance", {}) if candidate else {},
                "note": "recordedAt is journal observation time; not exact Git push time",
            })
            existing_keys.add(dedup)
            updated += 1
    # Delayed official raw backfill is not a manual patch: retain precise
    # Webstatic evidence and the independent verified UIGF mapping in journal.
    for item in import_report.get("rawBackfilled", []):
        bid, gid = item["id"], item["gachaId"]
        if bid not in ids:
            raise ValueError(f"Raw backfill absent from V1: {bid}")
        actual = next(b for b in published["banners"] if b["id"] == bid)
        if actual.get("gachaTypes", {}).get("raw") != [item["raw"]]:
            raise ValueError(f"Raw backfill journal mismatch: {bid}")
        key = ("raw_backfilled", bid, gid, str(generation))
        if key in existing_keys:
            continue
        events.append({
            "action": "raw_backfilled", "v1Id": bid, "recordedAt": observed_at,
            "publishedV1GeneratedAt": generation, "candidateSourceKey": None,
            "candidateFile": None, "fieldSources": {
                "gachaTypes.raw": ["webstatic:" + gid],
                "gachaTypes.uigf": ["uigf-rule"],
            },
            "attributionStatus": "verified_official",
            "sourceRefs": {"webstaticGachaId": gid,
                           "detailSha256": item["detailSha256"]},
            "note": "Official raw backfill of previously null value",
        })
        existing_keys.add(key)
        updated += 1

    if updated:
        _write_if_changed(root / OUTPUT, _encoded(journal))
    return {"recorded": updated, "total": len(events), "file": OUTPUT.as_posix()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    print(json.dumps(record(args.root.resolve(), report), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
