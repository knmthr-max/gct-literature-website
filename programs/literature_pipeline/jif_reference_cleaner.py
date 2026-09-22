#!/usr/bin/env python3
"""Convert licensed JCR CSV exports into annual internal JIF reference TSVs.

JCR exports are retained unchanged in ``data/reference/jif/raw/``.  This
program reads one or more exports, groups records by the JIF data year found in
the CSV header, removes category-level duplicates, and creates a new,
versioned TSV for each year.  Conflicting values are reported and excluded
instead of being selected automatically.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

__version__ = "1.0.0"

REFERENCE_HEADER = (
    "journal_title",
    "journal_abbreviation",
    "issn",
    "eissn",
    "jif_data_year",
    "jcr_release_year",
    "jif",
    "source",
    "reference_version",
    "retrieved_at",
    "license_note",
)
CONFLICT_HEADER = (
    "jif_data_year",
    "identity_key",
    "conflict_reason",
    "source_file",
    "journal_title",
    "journal_abbreviation",
    "issn",
    "eissn",
    "jif",
)
REQUIRED_JCR_COLUMNS = ("Journal name", "JCR Abbreviation", "ISSN", "eISSN")


def normalise_identifier(value: str) -> str:
    return re.sub(r"[^0-9X]", "", (value or "").upper())


def normalise_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def find_jif_column(header: Sequence[str]) -> tuple[str, str]:
    matches = []
    for name in header:
        match = re.fullmatch(r"\s*(20\d{2})\s+JIF\s*", name or "", flags=re.IGNORECASE)
        if match:
            matches.append((name, match.group(1)))
    if len(matches) != 1:
        raise ValueError("JCR CSV must contain exactly one '<year> JIF' column")
    return matches[0]


def read_jcr_csv(path: Path) -> tuple[str, list[dict[str, str]]]:
    """Read a JCR export with its metadata preamble and terms footer."""
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))
    header_index = next(
        (index for index, row in enumerate(rows) if "Journal name" in row and "JCR Abbreviation" in row),
        None,
    )
    if header_index is None:
        raise ValueError(f"{path}: JCR header row was not found")
    header = rows[header_index]
    missing = [name for name in REQUIRED_JCR_COLUMNS if name not in header]
    if missing:
        raise ValueError(f"{path}: missing required JCR column(s): {', '.join(missing)}")
    jif_column, jif_year = find_jif_column(header)
    records: list[dict[str, str]] = []
    for raw in rows[header_index + 1:]:
        if not raw or not any(cell.strip() for cell in raw):
            continue
        # The JCR terms footer has one cell and is not a journal record.
        if len(raw) < len(header):
            continue
        record = {header[index]: raw[index].strip() if index < len(raw) else "" for index in range(len(header))}
        if not record.get("Journal name", "").strip():
            continue
        records.append({
            "journal_title": record["Journal name"],
            "journal_abbreviation": record["JCR Abbreviation"],
            "issn": record["ISSN"],
            "eissn": record["eISSN"],
            "jif": record[jif_column],
            "source_file": path.name,
        })
    return jif_year, records


def identity_key(row: dict[str, str]) -> str:
    issn = normalise_identifier(row.get("issn", ""))
    eissn = normalise_identifier(row.get("eissn", ""))
    title = normalise_title(row.get("journal_title", ""))
    if issn:
        return f"issn:{issn}"
    if eissn:
        return f"eissn:{eissn}"
    if title:
        return f"title:{title}"
    raise ValueError("Journal record has no ISSN, eISSN, or journal title")


def build_reference_rows(
    input_paths: Iterable[Path],
    *,
    jcr_release_year: str,
    source: str,
    reference_version: str,
    retrieved_at: str,
    license_note: str,
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for input_path in input_paths:
        jif_year, rows = read_jcr_csv(input_path)
        for row in rows:
            if not row["jif"]:
                continue
            grouped[(jif_year, identity_key(row))].append(row)

    output: dict[str, list[dict[str, str]]] = defaultdict(list)
    conflicts: list[dict[str, str]] = []
    for (jif_year, key), rows in grouped.items():
        values = {row["jif"] for row in rows}
        if len(values) != 1:
            for row in rows:
                conflicts.append({
                    "jif_data_year": jif_year,
                    "identity_key": key,
                    "conflict_reason": "conflicting_jif_values",
                    **row,
                })
            continue
        chosen = sorted(rows, key=lambda row: (row["journal_title"].casefold(), row["source_file"]))[0]
        output[jif_year].append({
            "journal_title": chosen["journal_title"],
            "journal_abbreviation": chosen["journal_abbreviation"],
            "issn": chosen["issn"],
            "eissn": chosen["eissn"],
            "jif_data_year": jif_year,
            "jcr_release_year": jcr_release_year,
            "jif": chosen["jif"],
            "source": source,
            "reference_version": reference_version,
            "retrieved_at": retrieved_at,
            "license_note": license_note,
        })
    for year in output:
        output[year].sort(key=lambda row: (row["journal_title"].casefold(), row["issn"], row["eissn"]))
    return dict(output), conflicts


def write_tsv(path: Path, header: Sequence[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=header, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def discover_inputs(inputs: Sequence[Path], raw_dir: Optional[Path]) -> list[Path]:
    paths = list(inputs)
    if raw_dir:
        paths.extend(sorted(raw_dir.rglob("*.csv")))
    unique = sorted({path.resolve() for path in paths})
    if not unique:
        raise ValueError("Provide at least one --input CSV or a --raw-dir containing CSV files")
    missing = [str(path) for path in unique if not path.is_file()]
    if missing:
        raise FileNotFoundError("Input CSV not found: " + ", ".join(missing))
    return unique


def validate_metadata(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"20\d{2}", args.jcr_release_year):
        raise ValueError("--jcr-release-year must be a four-digit year")
    if not args.reference_version.strip():
        raise ValueError("--reference-version is required")
    if not args.license_note.strip():
        raise ValueError("--license-note is required; record the applicable JCR usage terms")


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--input", type=Path, action="append", default=[], help="JCR CSV input; may be repeated")
    command.add_argument("--raw-dir", type=Path, help="Read every CSV recursively from this raw-data directory")
    command.add_argument("--output-dir", type=Path, default=Path("data/reference/jif"))
    command.add_argument("--reference-version", required=True, help="Immutable reference version, e.g. 2026.07.0")
    command.add_argument("--jcr-release-year", required=True, help="JCR release year, not the JIF data year")
    command.add_argument("--retrieved-at", default=date.today().isoformat(), help="Retrieval date, YYYY-MM-DD")
    command.add_argument("--source", default="Clarivate Journal Citation Reports")
    command.add_argument("--license-note", required=True)
    command.add_argument("--output-prefix", default="jcr_jif_reference")
    command.add_argument("--dry-run", action="store_true", help="Validate and report without writing files")
    return command


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        validate_metadata(args)
        inputs = discover_inputs(args.input, args.raw_dir)
        references, conflicts = build_reference_rows(
            inputs,
            jcr_release_year=args.jcr_release_year,
            source=args.source,
            reference_version=args.reference_version,
            retrieved_at=args.retrieved_at,
            license_note=args.license_note,
        )
        suffix = re.sub(r"[^A-Za-z0-9._-]", "-", args.reference_version)
        targets = {
            year: args.output_dir / f"{args.output_prefix}_{year}_v{suffix}.tsv"
            for year in references
        }
        conflict_path = args.output_dir / f"{args.output_prefix}_conflicts_v{suffix}.tsv"
        if not args.dry_run:
            existing = [str(path) for path in [*targets.values(), conflict_path] if path.exists()]
            if existing:
                raise FileExistsError("Refusing to overwrite existing output: " + ", ".join(existing))
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for year, path in targets.items():
                write_tsv(path, REFERENCE_HEADER, references[year])
            if conflicts:
                write_tsv(conflict_path, CONFLICT_HEADER, conflicts)
        for year in sorted(references):
            print(f"JIF data year {year}: {len(references[year])} journal-year rows")
            print(f"  {'would write' if args.dry_run else 'wrote'}: {targets[year]}")
        print(f"Conflicting identity groups excluded: {len({(row['jif_data_year'], row['identity_key']) for row in conflicts})}")
        if conflicts:
            print(f"  {'would write' if args.dry_run else 'wrote'}: {conflict_path}")
        return 0
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
