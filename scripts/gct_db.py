#!/usr/bin/env python3
"""SQLite backing store for the historical GCT literature backlog.

This is the working database for the large (Google Drive-sourced, 1929-2026)
historical import — separate from data/papers.json, which stays the small,
already-reviewed, deployed subset. Nothing in this database is public; it
lives in the private data repo (gct-literature-data), passed in via --db.

Pipeline stages a row moves through:
  ingested (relevance_status IS NULL, ai_relevance IS NULL)
    -> AI-processed by process_batch.py (ai_relevance/ai_tags/ai_summary_*/
       ai_abstract_ja filled in, relevance_status auto-set from the AI
       verdict)
    -> optionally hand-corrected later by editing relevance_status directly
       (sqlite3 the_db.db "UPDATE papers SET relevance_status='kept',
       relevance_note='...' WHERE pmid='...'" -- always reversible)
    -> human-reviewed for publish quality by export_publish_review.py /
       publish_to_site.py (human_review_status set to approved/rejected/
       needs_edit -- a separate gate from relevance_status: relevance_status
       is "is this paper in scope", human_review_status is "is the AI-authored
       content good enough to publish as-is")
    -> published_to_site=1, published_at set once publish_to_site.py has
       copied the row into the public papers.json.
"""
import json
import sqlite3
from pathlib import Path

# The backlog is sharded into one SQLite file per era instead of one giant
# file, so no single file approaches GitHub's 100MB per-blob hard limit as
# the corpus grows (Git LFS is not usable from this environment: its API
# host is blocked by the sandbox's egress policy). Ordered newest-first,
# since that is the order batches are processed in.
SHARDS = [
    ("2020s", 2020, 9999),
    ("2010s", 2010, 2019),
    ("2000s", 2000, 2009),
    ("1990s", 1990, 1999),
    ("1980s", 1980, 1989),
    ("pre1980", 0, 1979),
]


def shard_filename(label: str) -> str:
    return f"gct_literature_{label}.db"


def shard_for_year(year) -> str:
    """Return the shard label a given publication_year belongs to."""
    if year is None:
        return SHARDS[-1][0]  # unknown year -> oldest/catch-all shard
    for label, lo, hi in SHARDS:
        if lo <= year <= hi:
            return label
    return SHARDS[-1][0]


def shard_path(db_dir: Path, label: str) -> Path:
    return db_dir / shard_filename(label)


def existing_shard_paths(db_dir: Path) -> list[Path]:
    """All shard files that already exist under db_dir, newest era first."""
    paths = []
    for label, _lo, _hi in SHARDS:
        path = shard_path(db_dir, label)
        if path.is_file():
            paths.append(path)
    return paths


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  pmid TEXT PRIMARY KEY,
  publication_year INTEGER,
  title TEXT,
  abstract TEXT,
  authors TEXT,
  first_author TEXT,
  journal_abbrev TEXT,
  journal_title TEXT,
  issn TEXT,
  eissn TEXT,
  doi TEXT,
  publication_types TEXT,
  mesh_terms TEXT,
  author_keywords TEXT,
  source_file TEXT,
  ingested_at TEXT NOT NULL,

  ai_relevance TEXT,
  ai_relevance_reason TEXT,
  ai_tags TEXT,
  ai_summary_en TEXT,
  ai_summary_ja TEXT,
  ai_abstract_ja TEXT,
  ai_title_ja TEXT,
  ai_processed_at TEXT,
  batch_id TEXT,

  relevance_status TEXT,
  relevance_note TEXT,
  relevance_reviewed_at TEXT,

  human_review_status TEXT,
  human_review_note TEXT,
  human_reviewed_at TEXT,

  jif_tier TEXT,
  jif_match_status TEXT,
  jif_reference_version TEXT,
  jif_matched_at TEXT,

  published_to_site INTEGER NOT NULL DEFAULT 0,
  published_at TEXT,
  added_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_papers_pending
  ON papers (relevance_status, publication_year);
"""

# Columns added after the original schema. Existing shard files predate
# these, and CREATE TABLE IF NOT EXISTS does not retrofit a table that
# already exists, so connect() adds any that are missing on open.
ADDED_COLUMNS = {
    "ai_abstract_ja": "TEXT",
    "ai_title_ja": "TEXT",
    "human_review_status": "TEXT",
    "human_review_note": "TEXT",
    "human_reviewed_at": "TEXT",
    "published_at": "TEXT",
    "jif_match_status": "TEXT",
    "jif_reference_version": "TEXT",
    "jif_matched_at": "TEXT",
}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(papers)")}
    for column, sql_type in ADDED_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {column} {sql_type}")
    return conn


def json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_load(value: str):
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []
