#!/usr/bin/env python3
"""和訳の誤った表記を、機械的に置換する(DBの ai_title_ja / ai_summary_ja / ai_abstract_ja と、サイトの title_ja / summary_ja / abstract_ja)。

用語集(terminology_ja.md)の「避ける訳」に入れた表記を、標準の訳に直すときに使う。置換は単純な文字列の置き換え。
既定はドライラン(--apply なしでは何も書かない)。--backup に、変えた行の元の値を JSONL で保存する(元に戻せる)。

    python3 scripts/replace_terms.py --db-dir <data>/master --papers data/papers \
        --replace 淋巴節=リンパ節 --replace コリオカルシノーマ=絨毛癌 --backup <data>/processed/terminology/replace_backup.jsonl [--apply]
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

DB_FIELDS = ("ai_title_ja", "ai_summary_ja", "ai_abstract_ja")
SITE_FIELDS = ("title_ja", "summary_ja", "abstract_ja")


def apply_pairs(text, pairs):
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path)
    parser.add_argument("--papers", type=pathlib.Path)
    parser.add_argument("--replace", action="append", required=True, metavar="旧=新")
    parser.add_argument("--backup", type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    pairs = [tuple(item.split("=", 1)) for item in args.replace]
    if any(not old or "=" not in item for (old, _), item in zip(pairs, args.replace)):
        raise SystemExit("--replace は 旧=新 の形で指定してください")
    counts, backups, db_changes = collections.Counter(), [], []
    if args.db_dir:
        for path in existing_shard_paths(args.db_dir):
            conn = sqlite3.connect(path)
            for field in DB_FIELDS:
                for pmid, value in conn.execute(f"SELECT pmid, {field} FROM papers WHERE {field} IS NOT NULL AND {field} != ''"):
                    new = apply_pairs(value, pairs)
                    if new != value:
                        counts[f"DB {field}"] += 1
                        db_changes.append((path, field, str(pmid), new))
                        backups.append({"where": "db", "field": field, "pmid": str(pmid), "old": value})
            conn.close()
    papers = None
    if args.papers:
        papers = papers_store.load(args.papers)
        for entry in papers:
            for field in SITE_FIELDS:
                value = entry.get(field)
                if isinstance(value, str) and apply_pairs(value, pairs) != value:
                    counts[f"site {field}"] += 1
                    backups.append({"where": "site", "field": field, "pmid": str(entry.get("pmid") or ""), "old": value})
                    if args.apply:
                        entry[field] = apply_pairs(value, pairs)
    print(json.dumps(dict(counts), ensure_ascii=False) if counts else "該当なし")
    if not args.apply:
        print("(dry run: nothing written; pass --apply)")
        return
    if args.backup and backups:
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        with args.backup.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(b, ensure_ascii=False) + "\n" for b in backups)
    by_path = collections.defaultdict(list)
    for path, field, pmid, new in db_changes:
        by_path[path].append((field, pmid, new))
    for path, items in by_path.items():
        conn = sqlite3.connect(path)
        for field, pmid, new in items:
            conn.execute(f"UPDATE papers SET {field} = ? WHERE pmid = ?", (new, pmid))
        conn.commit()
        conn.close()
    if papers is not None and any(k.startswith("site") for k in counts):
        papers_store.save(args.papers, papers)
    print("applied")


if __name__ == "__main__":
    main()
