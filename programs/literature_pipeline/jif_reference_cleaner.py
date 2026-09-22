#!/usr/bin/env python3
"""Convert licensed JCR CSV exports into annual internal JIF reference TSVs.

Supported CSV layouts:

* the JCR journal-list export, with columns such as ``Journal name`` and
  ``<year> JIF``;
* a single-journal ``All Years`` export, with a journal title in the preamble
  and columns ``Year`` and ``Journal impact factor``.

JCR exports are retained unchanged. The program groups normalized records by
JIF data year, removes duplicate journal/category rows, and creates a new,
versioned TSV for each year. Conflicting JIF values are reported and excluded
instead of being selected automatically.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Sequence

__version__ = "1.2.1"

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
ALL_YEARS_COLUMNS = ("Year", "Journal impact factor")
MISSING_JIF_VALUES = {"", "N/A", "NA", "NOT AVAILABLE", "-", "--"}


class UnsupportedJCRLayoutError(ValueError):
    """Raised when a CSV is not one of the supported journal-level layouts."""


def normalise_identifier(value: str) -> str:
    return re.sub(r"[^0-9X]", "", (value or "").upper())


def normalise_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def normalise_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def header_positions(row: Sequence[str]) -> dict[str, int]:
    return {normalise_header(value): index for index, value in enumerate(row)}


def find_header_index(rows: Sequence[Sequence[str]], required: Sequence[str]) -> Optional[int]:
    wanted = {normalise_header(name) for name in required}
    for index, row in enumerate(rows):
        if wanted.issubset(header_positions(row)):
            return index
    return None


def find_jif_column(header: Sequence[str]) -> tuple[int, str]:
    matches: list[tuple[int, str]] = []
    for index, name in enumerate(header):
        match = re.fullmatch(r"\s*((?:19|20)\d{2})\s+JIF\s*", name or "", flags=re.IGNORECASE)
        if match:
            matches.append((index, match.group(1)))
    if len(matches) != 1:
        raise ValueError("JCR journal-list CSV must contain exactly one '<year> JIF' column")
    return matches[0]


def read_csv_rows(path: Path) -> list[list[str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            return list(csv.reader(source))
    except UnicodeDecodeError as error:
        raise ValueError(f"{path}: CSV must be UTF-8 encoded") from error
    except csv.Error as error:
        raise ValueError(f"{path}: invalid CSV: {error}") from error


def row_value(row: Sequence[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def is_available_jif(value: str) -> bool:
    return value.strip().upper() not in MISSING_JIF_VALUES


def parse_journal_list_csv(
    path: Path, rows: Sequence[Sequence[str]], header_index: int
) -> list[dict[str, str]]:
    """Normalize the existing multi-journal/category JCR export layout."""
    header = rows[header_index]
    positions = header_positions(header)
    missing = [name for name in REQUIRED_JCR_COLUMNS if normalise_header(name) not in positions]
    if missing:
        raise ValueError(f"{path}: missing required JCR column(s): {', '.join(missing)}")
    jif_index, jif_year = find_jif_column(header)
    result: list[dict[str, str]] = []
    for raw in rows[header_index + 1 :]:
        title = row_value(raw, positions[normalise_header("Journal name")])
        if not title:
            continue
        jif = row_value(raw, jif_index)
        if not is_available_jif(jif):
            continue
        result.append(
            {
                "journal_title": title,
                "journal_abbreviation": row_value(
                    raw, positions[normalise_header("JCR Abbreviation")]
                ),
                "issn": row_value(raw, positions[normalise_header("ISSN")]),
                "eissn": row_value(raw, positions[normalise_header("eISSN")]),
                "jif_data_year": jif_year,
                "jif": jif,
                "source_file": path.name,
            }
        )
    return result


def all_years_journal_title(
    path: Path, rows: Sequence[Sequence[str]], header_index: int
) -> str:
    """Extract the journal title from the All Years metadata preamble."""
    ignored = {"all years"}
    for row in rows[:header_index]:
        cells = [cell.strip() for cell in row if cell.strip()]
        if len(cells) != 1:
            continue
        value = cells[0]
        folded = normalise_header(value)
        if folded in ignored or re.fullmatch(r"(?:year|edition)\s*:.*", value, re.IGNORECASE):
            continue
        return value
    raise ValueError(f"{path}: journal title was not found in the All Years preamble")


def parse_all_years_csv(
    path: Path, rows: Sequence[Sequence[str]], header_index: int
) -> list[dict[str, str]]:
    """Normalize a single-journal JCR All Years history export."""
    header = rows[header_index]
    positions = header_positions(header)
    title = all_years_journal_title(path, rows, header_index)
    year_index = positions[normalise_header("Year")]
    jif_index = positions[normalise_header("Journal impact factor")]
    result: list[dict[str, str]] = []
    for raw in rows[header_index + 1 :]:
        year = row_value(raw, year_index)
        jif = row_value(raw, jif_index)
        if not re.fullmatch(r"(?:19|20)\d{2}", year):
            continue
        if not is_available_jif(jif):
            continue
        result.append(
            {
                "journal_title": title,
                "journal_abbreviation": "",
                "issn": "",
                "eissn": "",
                "jif_data_year": year,
                "jif": jif,
                "source_file": path.name,
            }
        )
    if not result:
        raise ValueError(f"{path}: no annual JIF records were found")
    return result


def read_jcr_csv(path: Path) -> list[dict[str, str]]:
    """Auto-detect and normalize a supported JCR CSV layout."""
    rows = read_csv_rows(path)
    list_header = find_header_index(rows, REQUIRED_JCR_COLUMNS)
    if list_header is not None:
        return parse_journal_list_csv(path, rows, list_header)
    all_years_header = find_header_index(rows, ALL_YEARS_COLUMNS)
    if all_years_header is not None:
        return parse_all_years_csv(path, rows, all_years_header)
    raise UnsupportedJCRLayoutError(
        f"{path}: unsupported JCR CSV layout; expected a journal-list export or "
        "a single-journal All Years export"
    )


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
    skip_unsupported: bool = False,
    skipped_inputs: Optional[list[tuple[Path, str]]] = None,
) -> tuple[dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for input_path in input_paths:
        try:
            input_rows = read_jcr_csv(input_path)
        except UnsupportedJCRLayoutError as error:
            if not skip_unsupported:
                raise
            if skipped_inputs is not None:
                skipped_inputs.append((input_path, str(error)))
            continue
        for row in input_rows:
            grouped[(row["jif_data_year"], identity_key(row))].append(row)

    output: dict[str, list[dict[str, str]]] = defaultdict(list)
    conflicts: list[dict[str, str]] = []
    for (jif_year, key), rows in grouped.items():
        values = {row["jif"] for row in rows}
        if len(values) != 1:
            for row in rows:
                conflicts.append(
                    {
                        "jif_data_year": jif_year,
                        "identity_key": key,
                        "conflict_reason": "conflicting_jif_values",
                        **row,
                    }
                )
            continue
        chosen = sorted(
            rows, key=lambda row: (row["journal_title"].casefold(), row["source_file"])
        )[0]
        output[jif_year].append(
            {
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
            }
        )
    for year in output:
        output[year].sort(
            key=lambda row: (row["journal_title"].casefold(), row["issn"], row["eissn"])
        )
    return dict(output), conflicts


def write_tsv(path: Path, header: Sequence[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(
            destination,
            fieldnames=header,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def discover_inputs(inputs: Sequence[Path], raw_dir: Optional[Path]) -> list[Path]:
    paths = list(inputs)
    if raw_dir:
        if not raw_dir.is_dir():
            raise FileNotFoundError(f"CSV folder not found: {raw_dir}")
        paths.extend(
            sorted(path for path in raw_dir.iterdir() if path.is_file() and path.suffix.casefold() == ".csv")
        )
    unique = sorted({path.resolve() for path in paths})
    if not unique:
        raise ValueError("The selected folder contains no CSV files")
    missing = [str(path) for path in unique if not path.is_file()]
    if missing:
        raise FileNotFoundError("Input CSV not found: " + ", ".join(missing))
    return unique


def infer_jcr_release_year(input_paths: Sequence[Path]) -> str:
    """Infer the release year from Clarivate copyright text, then current year."""
    years: set[str] = set()
    for path in input_paths:
        for row in read_csv_rows(path):
            for cell in row:
                match = re.search(r"copyright\D+((?:19|20)\d{2})\D+clarivate", cell, re.IGNORECASE)
                if match:
                    years.add(match.group(1))
    if len(years) > 1:
        raise ValueError(
            "CSV files contain different Clarivate copyright years; "
            "specify --jcr-release-year explicitly"
        )
    return next(iter(years), str(date.today().year))


def default_output_dir(folder: Optional[Path], inputs: Sequence[Path]) -> Path:
    if folder is not None:
        return folder / "jif-output"
    parents = {path.parent for path in inputs}
    if len(parents) == 1:
        return next(iter(parents)) / "jif-output"
    return Path("jif-output")


def validate_metadata(
    jcr_release_year: str, reference_version: str, license_note: str
) -> None:
    if not re.fullmatch(r"20\d{2}", jcr_release_year):
        raise ValueError("--jcr-release-year must be a four-digit year")
    if not reference_version.strip():
        raise ValueError("--reference-version cannot be empty")
    if not license_note.strip():
        raise ValueError("--license-note cannot be empty")


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "folder",
        type=Path,
        nargs="?",
        help="Folder containing CSV files; outputs go to its jif-output subfolder",
    )
    command.add_argument("--input", type=Path, action="append", default=[], help="JCR CSV input; may be repeated")
    command.add_argument("--raw-dir", type=Path, help="Legacy alias for the CSV folder")
    command.add_argument("--output-dir", type=Path, help="Override the automatic jif-output folder")
    command.add_argument(
        "--reference-version",
        help="Immutable reference version; defaults to today's YYYY.MM.DD",
    )
    command.add_argument(
        "--jcr-release-year",
        help="JCR release year; inferred from Clarivate copyright text when omitted",
    )
    command.add_argument("--retrieved-at", default=date.today().isoformat(), help="Retrieval date, YYYY-MM-DD")
    command.add_argument("--source", default="Clarivate Journal Citation Reports")
    command.add_argument(
        "--license-note",
        default="JCR institutional use only; do not redistribute",
    )
    command.add_argument("--output-prefix", default="jcr_jif_reference")
    command.add_argument("--dry-run", action="store_true", help="Validate and report without writing files")
    return command


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.folder is not None and args.raw_dir is not None:
            raise ValueError("Specify the CSV folder once, either positionally or with --raw-dir")
        csv_folder = args.folder or args.raw_dir
        inputs = discover_inputs(args.input, csv_folder)
        reference_version = args.reference_version or date.today().strftime("%Y.%m.%d")
        jcr_release_year = args.jcr_release_year or infer_jcr_release_year(inputs)
        validate_metadata(jcr_release_year, reference_version, args.license_note)
        output_dir = args.output_dir or default_output_dir(csv_folder, inputs)
        skipped_inputs: list[tuple[Path, str]] = []
        references, conflicts = build_reference_rows(
            inputs,
            jcr_release_year=jcr_release_year,
            source=args.source,
            reference_version=reference_version,
            retrieved_at=args.retrieved_at,
            license_note=args.license_note,
            skip_unsupported=csv_folder is not None,
            skipped_inputs=skipped_inputs,
        )
        if not references:
            raise ValueError("No supported CSV contained usable journal-level JIF records")
        suffix = re.sub(r"[^A-Za-z0-9._-]", "-", reference_version)
        targets = {
            year: output_dir / f"{args.output_prefix}_{year}_v{suffix}.tsv"
            for year in references
        }
        conflict_path = output_dir / f"{args.output_prefix}_conflicts_v{suffix}.tsv"
        if not args.dry_run:
            existing = [str(path) for path in [*targets.values(), conflict_path] if path.exists()]
            if existing:
                raise FileExistsError("Refusing to overwrite existing output: " + ", ".join(existing))
            output_dir.mkdir(parents=True, exist_ok=True)
            for year, path in targets.items():
                write_tsv(path, REFERENCE_HEADER, references[year])
            if conflicts:
                write_tsv(conflict_path, CONFLICT_HEADER, conflicts)
        print(f"CSV files processed: {len(inputs)}")
        print(f"Supported CSV files: {len(inputs) - len(skipped_inputs)}")
        print(f"Unsupported CSV files skipped: {len(skipped_inputs)}")
        for path, _reason in skipped_inputs:
            print(f"  skipped: {path.name}", file=sys.stderr)
        print(f"JCR release year: {jcr_release_year}")
        print(f"Reference version: {reference_version}")
        for year in sorted(references):
            print(f"JIF data year {year}: {len(references[year])} journal-year rows")
            print(f"  {'would write' if args.dry_run else 'wrote'}: {targets[year]}")
        print(
            "Conflicting identity groups excluded: "
            f"{len({(row['jif_data_year'], row['identity_key']) for row in conflicts})}"
        )
        if conflicts:
            print(f"  {'would write' if args.dry_run else 'wrote'}: {conflict_path}")
        return 0
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
