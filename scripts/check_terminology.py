#!/usr/bin/env python3
"""和訳が用語集どおりかを点検する(読み取り専用。DBも用語集も変更しない)。

英語の原文(タイトル・抄録・要約)に用語集の用語があるのに、日本語訳に標準の訳が無い箇所を探す。
  avoid  用語集が「避ける訳」としている訳が使われている(不統一・誤字。直す対象)
  check  標準の訳が無く、避ける訳も無い(言い換え・略語・未登録の訳。目視確認用)

    python3 scripts/check_terminology.py --db-dir <data>/master --out <data>/processed/terminology/check.tsv
"""
import argparse
import collections
import csv
import pathlib
import sqlite3
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
for path in (SCRIPTS_DIR, ROOT / "programs" / "literature_pipeline"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import glossary as glossary_lib  # noqa: E402
from gct_db import existing_shard_paths  # noqa: E402

SENTINELS = {"Abstractなし", "No abstract available."}
# (english column, japanese column, label): the English text is the source, or the AI's English summary
PAIRS = (("title", "ai_title_ja", "title"), ("abstract", "ai_abstract_ja", "abstract"),
         ("ai_summary_en", "ai_summary_ja", "summary"))


def check_db(db_dir, entries):
    """Yield (pmid, field, status, english term, expected, found-avoid) for every problem."""
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT pmid, title, abstract, ai_title_ja, ai_abstract_ja, ai_summary_en, "
                                "ai_summary_ja FROM papers WHERE relevance_status = 'kept'"):
            for en_col, ja_col, label in PAIRS:
                english, japanese = row[en_col] or "", row[ja_col] or ""
                if not english or not japanese or japanese in SENTINELS or english in SENTINELS:
                    continue
                for entry, status, avoided in glossary_lib.check_pair(entries, english, japanese):
                    expected = "(keep in English)" if entry["keep_english"] else entry["main"]
                    yield row["pmid"], label, status, entry["english"], expected, "、".join(avoided)
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--glossary", type=pathlib.Path,
                        help="default: <db-dir>/../reference/terminology/terminology_ja.md")
    parser.add_argument("--out", type=pathlib.Path, help="Write every problem as TSV here")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    path = args.glossary or args.db_dir.parent / "reference" / "terminology" / "terminology_ja.md"
    entries = glossary_lib.parse(path.read_text(encoding="utf-8"))
    problems = list(check_db(args.db_dir, entries))
    by_status = collections.Counter(p[2] for p in problems)
    papers = {p[0] for p in problems if p[2] == "avoid"}
    print(f"glossary: {len(entries)} terms | problems: {dict(by_status)} | papers with an 'avoid' problem: {len(papers)}")
    for status in ("avoid", "check"):
        top = collections.Counter((p[3], p[4], p[5]) for p in problems if p[2] == status).most_common(args.top)
        print(f"\n-- {status}: top terms")
        for (english, expected, avoided), n in top:
            print(f"  {n:4d}  {english} => {expected}" + (f"   (found: {avoided})" if avoided else ""))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(("pmid", "field", "status", "english_term", "expected", "found_avoid"))
            writer.writerows(sorted(problems, key=lambda p: (p[2] != "avoid", p[3], p[0])))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
