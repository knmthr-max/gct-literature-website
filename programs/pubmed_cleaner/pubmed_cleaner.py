#!/usr/bin/env python3
"""Convert PubMed MEDLINE text exports into loss-aware structured TSV data.

Input: one PubMed MEDLINE ``.txt`` export.
Output: one UTF-8 TSV row per PMID. Repeated MEDLINE values such as PT, MH,
OT, and IS are stored as JSON arrays inside TSV cells so no value is dropped.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Iterable, Mapping, Sequence

__version__ = "3.0.0"

FIELDS = (
    "PMID", "DP", "DEP", "TI", "AB", "AU", "PT", "TA", "JT", "IS",
    "MH", "OT", "AID", "LID",
)
HEADER = (
    "pmid",
    "publication_date",
    "epub_date",
    "publication_year",
    "title",
    "abstract",
    "first_author",
    "publication_types",
    "journal_abbrev",
    "journal_title",
    "issn",
    "eissn",
    "doi",
    "mesh_terms",
    "author_keywords",
    "source_file",
)
FIELD_PATTERN = re.compile(r"^([A-Z0-9]{2,4})\s*-\s?(.*)$")
YEAR_PATTERN = re.compile(r"\b(18|19|20|21)\d{2}\b")
ISSN_PATTERN = re.compile(r"\b(\d{4}-[\dXx]{4})\b")


def new_record() -> dict[str, list[str]]:
    return {field: [] for field in FIELDS}


def normalize(value: str) -> str:
    """Return a single-line value that cannot break a TSV row."""
    return " ".join(value.replace("\t", " ").replace("\r", " ").replace("\n", " ").split())


def parse_records(lines: Iterable[str]) -> list[dict[str, list[str]]]:
    """Parse MEDLINE records using PMID, not blank lines, as the boundary."""
    records: list[dict[str, list[str]]] = []
    record = new_record()
    current_field: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        match = FIELD_PATTERN.match(line)
        if match:
            field, value = match.groups()
            if field == "PMID" and record["PMID"]:
                records.append(record)
                record = new_record()
            if field in record:
                record[field].append(normalize(value))
                current_field = field
            else:
                current_field = None
            continue

        if line[:1].isspace() and current_field and record[current_field]:
            continuation = normalize(line)
            if continuation:
                record[current_field][-1] = normalize(
                    f"{record[current_field][-1]} {continuation}"
                )
        elif not line.strip():
            current_field = None

    if record["PMID"]:
        records.append(record)
    return records


def json_values(values: Sequence[str]) -> str:
    """Encode a repeated MEDLINE field without discarding order or duplicates."""
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def first(values: Sequence[str]) -> str:
    return values[0] if values else ""


def publication_year(record: Mapping[str, Sequence[str]]) -> str:
    """Use print/publication date first, then electronic publication date."""
    for value in (*record.get("DP", []), *record.get("DEP", [])):
        match = YEAR_PATTERN.search(value)
        if match:
            return match.group(0)
    return ""


def issn_values(values: Sequence[str]) -> tuple[str, str]:
    """Return print/linking ISSN and electronic ISSN from MEDLINE IS values."""
    print_or_linking = ""
    electronic = ""
    for value in values:
        match = ISSN_PATTERN.search(value)
        if not match:
            continue
        issn = match.group(1).upper()
        lowered = value.lower()
        if "electronic" in lowered:
            electronic = electronic or issn
        elif "print" in lowered or "linking" in lowered:
            print_or_linking = print_or_linking or issn
        else:
            print_or_linking = print_or_linking or issn
    return print_or_linking, electronic


def doi_value(record: Mapping[str, Sequence[str]]) -> str:
    for value in (*record.get("AID", []), *record.get("LID", [])):
        if "[doi]" in value.lower():
            return normalize(re.sub(r"\s*\[doi\]\s*$", "", value, flags=re.IGNORECASE))
    return ""


def record_to_dict(record: Mapping[str, Sequence[str]], source_file: str = "") -> dict[str, str]:
    issn, eissn = issn_values(record.get("IS", []))
    return {
        "pmid": first(record.get("PMID", [])),
        "publication_date": " ".join(record.get("DP", [])),
        "epub_date": " ".join(record.get("DEP", [])),
        "publication_year": publication_year(record),
        "title": " ".join(record.get("TI", [])),
        "abstract": " ".join(record.get("AB", [])),
        "first_author": first(record.get("AU", [])),
        "publication_types": json_values(record.get("PT", [])),
        "journal_abbrev": " ".join(record.get("TA", [])),
        "journal_title": " ".join(record.get("JT", [])),
        "issn": issn,
        "eissn": eissn,
        "doi": doi_value(record),
        "mesh_terms": json_values(record.get("MH", [])),
        "author_keywords": json_values(record.get("OT", [])),
        "source_file": source_file,
    }


def read_pubmed(input_path: Path) -> list[dict[str, str]]:
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file was not found: {input_path}")
    records = parse_records(input_path.read_text(encoding="utf-8-sig").splitlines())
    if not records:
        raise ValueError(f"No PubMed records with a PMID were found in {input_path}")
    return [record_to_dict(record, input_path.as_posix()) for record in records]


def write_tsv(rows: Sequence[Mapping[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=HEADER, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def clean_pubmed(input_path: Path, output_path: Path) -> int:
    rows = read_pubmed(input_path)
    write_tsv(rows, output_path)
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert PubMed MEDLINE text to an expanded, loss-aware TSV file."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    count = clean_pubmed(args.input, args.output)
    print(f"Completed: {args.output} ({count} records, {len(HEADER)} columns)")


if __name__ == "__main__":
    main()
