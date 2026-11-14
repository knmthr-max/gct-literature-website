#!/usr/bin/env python3
"""サイトに載っているが DB(データリポジトリの SQLite)に行が無い文献を、DB に取り込む。

データリポジトリを作る前に、サイトへ直接載せた文献(PMID で DB に見つからないもの)が対象。
サイト側のエントリはそのままで、DB に行を足すだけ(サイトのデータは書き換えない)。
取り込んだ行は、出所が分かるように次の値を持つ:
  source_file = 'site_only_import' / batch_id = 'site_only_import_<日付>' / published_to_site = 1 /
  human_review_status = 'approved' / human_review_note = 'サイトに先に載っていた文献を DB に取り込み(<日付>)'
サイトのエントリにある項目(題名・抄録・要約・和訳・著者・タグ・状態など)を、DB の列に写す。
サイトに無い項目(MeSH・ISSN・出版タイプなど)は空のまま(原データが無いので、作らない)。
既定はドライラン(--apply なしでは何も書かない)。

    python3 scripts/import_site_only.py --db-dir <data>/master --papers data/papers [--apply]
"""
import argparse
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import papers_store  # noqa: E402
from gct_db import connect, existing_shard_paths, json_dump, shard_for_year, shard_path  # noqa: E402

CNS_MARK = "中枢神経"


def row_from_entry(entry, today):
    authors = entry.get("authors") or []
    status = entry.get("relevance_status") or "kept"
    note = entry.get("relevance_note") or ""
    if status == "excluded":
        relevance = "cns_gct" if CNS_MARK in note else "not_relevant"
    else:
        relevance = "relevant"
    year = entry.get("year")
    return {
        "pmid": str(entry["pmid"]),
        "publication_year": int(year) if str(year or "").isdigit() else None,
        "title": entry.get("title") or "",
        "abstract": entry.get("abstract") or "",
        "authors": json_dump(authors),
        "first_author": authors[0] if authors else "",
        "journal_abbrev": entry.get("journal") or "",
        "journal_title": entry.get("journal") or "",
        "doi": entry.get("doi") or "",
        "source_file": "site_only_import",
        "ingested_at": f"{today}T00:00:00+00:00",
        "ai_relevance": relevance,
        "ai_relevance_reason": note,
        "ai_tags": json_dump(entry.get("tags") or []),
        "ai_summary_en": entry.get("summary_en") or "",
        "ai_summary_ja": entry.get("summary_ja") or "",
        "ai_abstract_ja": entry.get("abstract_ja") or "",
        "ai_title_ja": entry.get("title_ja") or "",
        "batch_id": f"site_only_import_{today}",
        "relevance_status": status,
        "relevance_note": note,
        "relevance_reviewed_at": entry.get("relevance_reviewed_at") or "",
        "human_review_status": "approved",
        "human_review_note": f"サイトに先に載っていた文献を DB に取り込み({today})",
        "human_reviewed_at": f"{today}T00:00:00+00:00",
        "jif_tier": entry.get("jif_tier") or "unknown",
        "published_to_site": 1,
        "published_at": entry.get("added_at") or today,
        "added_at": entry.get("added_at") or today,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--papers", type=pathlib.Path, default=pathlib.Path("data/papers"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    known = set()
    for path in existing_shard_paths(args.db_dir):
        conn = connect(path)
        known |= {r[0] for r in conn.execute("SELECT pmid FROM papers")}
        conn.close()
    today = datetime.date.today().isoformat()
    todo = [e for e in papers_store.load(args.papers) if e.get("pmid") and str(e["pmid"]) not in known]
    no_pmid = [e for e in papers_store.load(args.papers) if not e.get("pmid")]
    by_status = {}
    for e in todo:
        by_status[e.get("relevance_status") or "kept"] = by_status.get(e.get("relevance_status") or "kept", 0) + 1
    print(f"site entries not in the DB: {len(todo)} {by_status} (entries without a pmid, skipped: {len(no_pmid)})")
    if not args.apply:
        print("(dry run: nothing written; pass --apply)")
        return
    for e in todo:
        row = row_from_entry(e, today)
        conn = connect(shard_path(args.db_dir, shard_for_year(row["publication_year"])))
        cols = ", ".join(row)
        conn.execute(f"INSERT OR IGNORE INTO papers ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        conn.commit()
        conn.close()
    print(f"imported {len(todo)} rows")


if __name__ == "__main__":
    main()
