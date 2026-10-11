#!/usr/bin/env python3
"""個別レビューを省略して公開する(一括公開)ための decisions TSV を作る。

通常の公開前レビュー(export_publish_review.py)は25件ずつ人が確認する。方針として「needs_review だけ人が確認し、
relevant 判定(kept)は個別レビューなしで公開する」場合に、年の範囲を指定して、公開候補を全件 approve にした
decisions TSV を作る。出力は publish_to_site.py にそのまま渡せる(DBには「一括公開」の注記が残るので、後で探せる)。

候補: relevance_status='kept' / 未公開 / 人手レビュー未実施 / 題名・抄録・要約の和訳が揃っている

    python3 scripts/bulk_publish_decisions.py --db-dir <data>/master --year-from 1990 --year-to 1999 --out decisions.tsv
    python3 scripts/publish_to_site.py --decisions decisions.tsv --db-dir <data>/master
"""
import argparse
import csv
import json
import pathlib
import sqlite3
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from export_publish_review import DECISION_HEADER  # noqa: E402
from gct_db import existing_shard_paths  # noqa: E402

NOTE = "一括公開(個別レビューなし。needs_review のみ人が確認する方針、2026-10)"
CANDIDATE_WHERE = (
    "relevance_status = 'kept' AND COALESCE(published_to_site, 0) = 0 AND human_review_status IS NULL "
    "AND COALESCE(ai_title_ja, '') != '' AND COALESCE(ai_abstract_ja, '') != '' AND COALESCE(ai_summary_ja, '') != '' "
    "AND COALESCE(ai_summary_en, '') != ''"
)


def candidates(db_dir, year_from, year_to):
    rows = []
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows += [dict(r) for r in conn.execute(
            f"SELECT pmid, title, journal_abbrev, journal_title, publication_year, ai_tags FROM papers "
            f"WHERE {CANDIDATE_WHERE} AND publication_year BETWEEN ? AND ?", (year_from, year_to))]
        conn.close()
    rows.sort(key=lambda r: (-(r["publication_year"] or 0), r["pmid"]))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--year-from", type=int, required=True)
    parser.add_argument("--year-to", type=int, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    rows = candidates(args.db_dir, args.year_from, args.year_to)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DECISION_HEADER, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "pmid": r["pmid"], "title": (r["title"] or "").replace("\t", " ").replace("\n", " "),
                "journal": r["journal_abbrev"] or r["journal_title"] or "", "year": r["publication_year"],
                "tags": ",".join(json.loads(r["ai_tags"] or "[]")), "decision": "approve", "reviewer": "bulk",
                "reviewed_at": "", "note": NOTE})
    print(f"{len(rows)} candidates ({args.year_from}-{args.year_to}) -> {args.out}")


if __name__ == "__main__":
    main()
