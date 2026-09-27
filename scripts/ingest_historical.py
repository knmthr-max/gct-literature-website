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
      --db-dir /path/to/gct-literature-data/data/master

The database is sharded into one SQLite file per era (see gct_db.py's
SHARDS) rather than one giant file, so no single file approaches GitHub's
100MB blob limit as the corpus grows. Each record is written to the shard
matching its publication_year; shard files are created on demand.

Safe to re-run: PMIDs already in any shard, or already published to the
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
from gct_db import connect, json_dump, shard_for_year, shard_path, existing_shard_paths  # noqa: E402

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
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--papers", type=pathlib.Path, default=PAPERS_PATH)
    args = parser.parse_args()

    raw_files = sorted(p for p in args.raw_dir.glob("*.txt") if p.is_file())
    if not raw_files:
        raise FileNotFoundError(f"No .txt files found under {args.raw_dir}")

    published_pmids = load_published_pmids(args.papers)
    shard_conns = {path: connect(path) for path in existing_shard_paths(args.db_dir)}
    existing_pmids: set[str] = set()
    for conn in shard_conns.values():
        existing_pmids.update(row["pmid"] for row in conn.execute("SELECT pmid FROM papers"))

    def conn_for_year(year):
        path = shard_path(args.db_dir, shard_for_year(year))
        if path not in shard_conns:
            shard_conns[path] = connect(path)
        return shard_conns[path]

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
            conn_for_year(row["publication_year"]).execute(
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

    for conn in shard_conns.values():
        conn.commit()

    total_pending = sum(
        conn.execute("SELECT COUNT(*) FROM papers WHERE relevance_status IS NULL").fetchone()[0]
        for conn in shard_conns.values()
    )
    stats = {
        "raw_files": len(raw_files),
        "records_seen": total_records,
        "inserted": inserted,
        "skipped_already_in_db": skipped_already_in_db,
        "skipped_already_published_in_papers_json": skipped_already_published,
        "skipped_duplicate_within_this_run": skipped_duplicate_in_run,
        "skipped_no_pmid": skipped_no_pmid,
        "total_pending_across_shards": total_pending,
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
