#!/usr/bin/env python3
"""Audit legacy raw PubMed files against the current data/raw/pubmed_alerts layout.

Step 7 of the workspace restructuring (see DIRECTORY_MANIFEST.md) requires
source/destination SHA-256 verification and explicit approval before any
legacy raw file is reorganized or removed. This program performs the
verification step only: it never moves, copies, or deletes a file, and it
never overwrites an existing audit output.

Input: a legacy directory (for example "2026 raw data") and the current raw
directory it should be checked against (for example
data/raw/pubmed_alerts/2026).

Output: one new, non-overwritable audit TSV recording, for every legacy
file, whether an identical copy (by SHA-256) already exists under the
current raw directory, whether a same-named-but-different file exists
there, or whether no equivalent file has been migrated yet.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

__version__ = "1.0.0"

AUDIT_HEADER = (
    "legacy_path",
    "legacy_filename",
    "legacy_size",
    "legacy_sha256",
    "status",
    "matched_current_path",
    "audited_at",
)

STATUS_ALREADY_MIGRATED = "already_migrated"
STATUS_NOT_YET_MIGRATED = "not_yet_migrated"
STATUS_NAME_CONFLICT = "name_conflict_diff_content"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def build_current_index(current_dir: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    """Return (sha256 -> path, filename -> path) indexes for the current raw directory."""
    by_hash: dict[str, Path] = {}
    by_name: dict[str, Path] = {}
    for path in iter_files(current_dir):
        digest = sha256(path)
        by_hash.setdefault(digest, path)
        by_name.setdefault(path.name, path)
    return by_hash, by_name


def audit_row(
    path: Path,
    by_hash: dict[str, Path],
    by_name: dict[str, Path],
    now: str,
) -> dict[str, str]:
    digest = sha256(path)
    if digest in by_hash:
        status = STATUS_ALREADY_MIGRATED
        matched = str(by_hash[digest])
    elif path.name in by_name:
        status = STATUS_NAME_CONFLICT
        matched = str(by_name[path.name])
    else:
        status = STATUS_NOT_YET_MIGRATED
        matched = ""
    return {
        "legacy_path": str(path),
        "legacy_filename": path.name,
        "legacy_size": str(path.stat().st_size),
        "legacy_sha256": digest,
        "status": status,
        "matched_current_path": matched,
        "audited_at": now,
    }


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    if path.exists():
        raise FileExistsError(
            f"{path} already exists. Audit manifests are append-only; use a new "
            "filename (for example with today's date or a run id)."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(
            destination, fieldnames=AUDIT_HEADER, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_audit(legacy_dir: Path, current_dir: Path, output: Path) -> list[dict[str, str]]:
    by_hash, by_name = build_current_index(current_dir)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = [audit_row(path, by_hash, by_name, now) for path in iter_files(legacy_dir)]
    write_tsv(output, rows)
    return rows


def summarize(rows: list[dict[str, str]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    lines = [f"legacy files scanned: {len(rows)}"]
    for status in (STATUS_ALREADY_MIGRATED, STATUS_NOT_YET_MIGRATED, STATUS_NAME_CONFLICT):
        lines.append(f"  {status}: {counts.get(status, 0)}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-dir",
        required=True,
        type=Path,
        help="Legacy raw directory to audit, e.g. '2026 raw data'.",
    )
    parser.add_argument(
        "--current-dir",
        required=True,
        type=Path,
        help="Current raw directory to compare against, e.g. data/raw/pubmed_alerts/2026.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path for the new audit TSV. Must not already exist.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.legacy_dir.is_dir():
        raise SystemExit(f"legacy dir not found: {args.legacy_dir}")
    if not args.current_dir.is_dir():
        raise SystemExit(f"current dir not found: {args.current_dir}")
    rows = run_audit(args.legacy_dir, args.current_dir, args.output)
    print(summarize(rows))
    print(f"audit written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
