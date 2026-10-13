#!/usr/bin/env python3
"""公開サイトの文献(data/papers/)のタグを、DBの研究デザイン(ai_tags)に合わせる。

2026-10-12 の9分類(scripts/study_design.py)への移行で使う。サイトの各エントリ(pmidで対応)について、
DBのタグが9分類のいずれかで、サイトのタグと違えば、DBのタグで置き換える。DBに無い文献や、DBのタグが空の文献は
触らずに、件数を表示する。既定はドライラン(--apply なしでは何も書かない)。

    python3 scripts/sync_site_tags.py --db-dir <data>/master --papers data/papers [--apply]
"""
import argparse
import collections
import json
import pathlib
import sqlite3
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from gct_db import existing_shard_paths  # noqa: E402
import papers_store  # noqa: E402
import study_design  # noqa: E402


def read_db_tags(db_dir):
    tags = {}
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for pmid, raw in conn.execute("SELECT pmid, ai_tags FROM papers WHERE ai_tags IS NOT NULL"):
            tags[str(pmid)] = json.loads(raw or "[]")
        conn.close()
    return tags


def plan(papers, db_tags):
    """(updates [(entry, new tags)], not_in_db [pmid], db_empty [pmid])"""
    updates, not_in_db, db_empty = [], [], []
    for entry in papers:
        pmid = str(entry.get("pmid") or "")
        if pmid not in db_tags:
            not_in_db.append(pmid)
            continue
        new = db_tags[pmid]
        if not new or new[0] not in study_design.CATEGORIES:
            db_empty.append(pmid)
        elif (entry.get("tags") or []) != new:
            updates.append((entry, new))
    return updates, not_in_db, db_empty


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--papers", type=pathlib.Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    papers = papers_store.load(args.papers)
    updates, not_in_db, db_empty = plan(papers, read_db_tags(args.db_dir))
    print(f"site entries: {len(papers)} | to update: {len(updates)} | not in DB: {len(not_in_db)} | DB tag empty: {len(db_empty)}")
    by_new = collections.Counter(new[0] for _, new in updates)
    for tag, n in by_new.most_common():
        print(f"  {n:6d}  -> {tag}")
    if not args.apply:
        print("(dry run: nothing written; pass --apply)")
        return
    for entry, new in updates:
        entry["tags"] = new
    papers_store.save(args.papers, papers)
    print("applied")


if __name__ == "__main__":
    main()
