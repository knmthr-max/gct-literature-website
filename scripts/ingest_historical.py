#!/usr/bin/env python3
"""Parse the historical GCT literature backlog (MEDLINE .txt exports, one file
per publication year, 1929-2026) into the SQLite working database.

This is the mechanical, no-AI half of the pipeline: parse, dedupe by PMID
(both across the raw files and against PMIDs already in the public
data/papers.json), and insert with relevance_status left NULL ("pending").
Nothing here calls Claude or costs API tokens.

Usage:
    python3 scripts/ingest_historical.py \
      --raw-dir /path/to/gct-literature-data/data/raw/historical_bulk \
      --db /path/to/gct-literature-data/data/master/gct_literature.db

Safe to re-run: PMIDs already in the database, or already published to the
public site, are skipped rather than duplicated.
"""
import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBMED_CLEANER_DIR = ROOT / "programs"
if str(PUBMED_CLEANER_DIR) not in sys.path:
    sys.path.insert(0, str(PUBMED_CLEANER_DIR))

from pubmed_cleaner import pubmed_cleaner as cleaner  # noqa: E402
from gct_db import connect, json_dump  # noqa: E402

PAPERS_PATH = ROOT / "data" / "papers.json"


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def record_to_row(record, source_file):
    issn, eissn = cleaner.issn_values(record.get("IS", []))
    year_str = cleaner.publication_year(record)
    return {
        "pmid": (record.get("PMID") or [""])[0],
        "publication_year": int(year_str) if year_str.isdigit() else None,
        "title": " ".join(record.get("TI", [])),
        "abstract": " ".join(record.get("AB", [])),
        "authors": json_dump(record.get("AU", [])),
        "first_author": (record.get("AU") or [""])[0],
        "journal_abbrev": " ".join(record.get("TA", [])),
        "journal_title": " ".join(record.get("JT", [])),
        "issn": issn,
        "eissn": eissn,
        "doi": cleaner.doi_value(record),
        "publication_types": json_dump(record.get("PT", [])),
        "mesh_terms": json_dump(record.get("MH", [])),
        "author_keywords": json_dump(record.get("OT", [])),
        "source_file": source_file,
    }


def load_published_pmids(papers_path: pathlib.Path) -> set[str]:
    if not papers_path.is_file():
        return set()
    papers = json.loads(papers_path.read_text(encoding="utf-8"))
    return {str(p["pmid"]) for p in papers if p.get("pmid")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=pathlib.Path, required=True)
    parser.add_argument("--db", type=pathlib.Path, required=True)
    parser.add_argument("--papers", type=pathlib.Path, default=PAPERS_PATH)
    args = parser.parse_args()

    raw_files = sorted(p for p in args.raw_dir.glob("*.txt") if p.is_file())
    if not raw_files:
        raise FileNotFoundError(f"No .txt files found under {args.raw_dir}")

    published_pmids = load_published_pmids(args.papers)
    conn = connect(args.db)
    existing_pmids = {row["pmid"] for row in conn.execute("SELECT pmid FROM papers")}

    seen_this_run: set[str] = set()
    total_records = 0
    inserted = 0
    skipped_already_in_db = 0
    skipped_already_published = 0
    skipped_duplicate_in_run = 0
    skipped_no_pmid = 0
    ingested_at = now_utc()

    for raw_file in raw_files:
        text = raw_file.read_text(encoding="utf-8-sig")
        records = cleaner.parse_records(text.splitlines())
        for record in records:
            total_records += 1
            row = record_to_row(record, raw_file.name)
            pmid = row["pmid"]
            if not pmid:
                skipped_no_pmid += 1
                continue
            if pmid in published_pmids:
                skipped_already_published += 1
                continue
            if pmid in existing_pmids:
                skipped_already_in_db += 1
                continue
            if pmid in seen_this_run:
                skipped_duplicate_in_run += 1
                continue
            seen_this_run.add(pmid)
            conn.execute(
                """INSERT INTO papers (
                    pmid, publication_year, title, abstract, authors, first_author,
                    journal_abbrev, journal_title, issn, eissn, doi,
                    publication_types, mesh_terms, author_keywords,
                    source_file, ingested_at
                ) VALUES (
                    :pmid, :publication_year, :title, :abstract, :authors, :first_author,
                    :journal_abbrev, :journal_title, :issn, :eissn, :doi,
                    :publication_types, :mesh_terms, :author_keywords,
                    :source_file, :ingested_at
                )""",
                {**row, "ingested_at": ingested_at},
            )
            inserted += 1

    conn.commit()
    stats = {
        "raw_files": len(raw_files),
        "records_seen": total_records,
        "inserted": inserted,
        "skipped_already_in_db": skipped_already_in_db,
        "skipped_already_published_in_papers_json": skipped_already_published,
        "skipped_duplicate_within_this_run": skipped_duplicate_in_run,
        "skipped_no_pmid": skipped_no_pmid,
        "total_pending_in_db": conn.execute(
            "SELECT COUNT(*) FROM papers WHERE relevance_status IS NULL"
        ).fetchone()[0],
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
