#!/usr/bin/env python3
"""公開サイト(data/papers.json)の和訳を、DBの再和訳の結果に合わせて更新する。

再和訳(process_batch.py --retranslate)はDBだけを書き換えるので、すでに公開した論文のサイト側の訳は古いまま残る。
このスクリプトは、サイトの各エントリ(pmidで対応)について title_ja / summary_ja / abstract_ja を比べ、
  - サイトの値が「再和訳の前のDBの値」(--backup に保存されている)と同じ → DBの新しい値に更新する
  - サイトの値がDBと同じ → 何もしない
  - それ以外(サイト側で手動編集されたと見られる) → 上書きせず、一覧に出す
既定はドライラン(--apply なしでは何も書かない)。

    python3 scripts/sync_site_translations.py --db-dir <data>/master --papers data/papers.json \
        --backup <data>/processed/terminology/retranslate_backup_2026-10-03.jsonl [--apply]
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

# site field -> (DB column, key in the backup's "old")
FIELDS = {"title_ja": ("ai_title_ja", "title_ja"), "summary_ja": ("ai_summary_ja", "summary_ja"),
          "abstract_ja": ("ai_abstract_ja", "abstract_ja")}


def read_backup(path):
    """pmid -> the translations before the FIRST retranslation (later ones are not the site's old values)."""
    old = {}
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                old.setdefault(str(item["pmid"]), item["old"])
    return old


def read_db(db_dir, pmids):
    rows = {}
    for shard in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{shard}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for pmid in pmids:
            row = conn.execute("SELECT ai_title_ja, ai_summary_ja, ai_abstract_ja FROM papers "
                               "WHERE pmid = ? AND relevance_status = 'kept'", (pmid,)).fetchone()
            if row:
                rows[pmid] = dict(row)
        conn.close()
    return rows


def plan(papers, db, old):
    """(updates, kept_manual, same): updates = [(entry, field, new value)], kept_manual = [(pmid, field)]."""
    updates, manual, same = [], [], 0
    for entry in papers:
        pmid = str(entry.get("pmid") or "")
        if pmid not in db:
            continue
        for field, (column, key) in FIELDS.items():
            new, current = db[pmid][column] or "", entry.get(field) or ""
            if not new or new == current:
                same += 1
            elif pmid in old and current == (old[pmid].get(key) or ""):
                updates.append((entry, field, new))
            else:
                manual.append((pmid, field))
    return updates, manual, same


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--papers", type=pathlib.Path, required=True)
    parser.add_argument("--backup", type=pathlib.Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    papers = json.loads(args.papers.read_text(encoding="utf-8"))
    db = read_db(args.db_dir, [str(p.get("pmid")) for p in papers if p.get("pmid")])
    updates, manual, same = plan(papers, db, read_backup(args.backup))
    by_field = collections.Counter(field for _, field, _ in updates)
    print(f"site entries: {len(papers)} | in DB (kept): {len(db)} | fields to update: {len(updates)} {dict(by_field)} "
          f"| unchanged: {same} | left alone (site differs from both old and new DB value): {len(manual)}")
    for pmid, field in manual[:20]:
        print(f"  left alone: pmid {pmid} {field}")
    if args.apply and updates:
        for entry, field, new in updates:
            entry[field] = new
        args.papers.write_text(json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.papers}")
    elif not args.apply:
        print("(dry run: nothing written; pass --apply)")


if __name__ == "__main__":
    main()
