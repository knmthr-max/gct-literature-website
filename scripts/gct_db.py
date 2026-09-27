#!/usr/bin/env python3
"""SQLite backing store for the historical GCT literature backlog.

This is the working database for the large (Google Drive-sourced, 1929-2026)
historical import — separate from data/papers.json, which stays the small,
already-reviewed, deployed subset. Nothing in this database is public; it
lives in the private data repo (gct-literature-data), passed in via --db.

Pipeline stages a row moves through:
  ingested (relevance_status IS NULL, ai_relevance IS NULL)
    -> AI-processed by process_batch.py (ai_relevance/ai_tags/ai_summary_*
       filled in, relevance_status auto-set from the AI verdict)
    -> optionally hand-corrected later by editing relevance_status directly
       (sqlite3 the_db.db "UPDATE papers SET relevance_status='kept',
       relevance_note='...' WHERE pmid='...'" -- always reversible)
    -> published_to_site=1 once exported into the public papers.json by a
       separate export step (not implemented yet; out of scope until the
       backlog itself is in good shape).
"""
import json
import sqlite3
from pathlib import Path

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
  ai_processed_at TEXT,
  batch_id TEXT,

  relevance_status TEXT,
  relevance_note TEXT,
  relevance_reviewed_at TEXT,

  jif_tier TEXT,

  published_to_site INTEGER NOT NULL DEFAULT 0,
  added_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_papers_pending
  ON papers (relevance_status, publication_year);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
