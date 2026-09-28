#!/usr/bin/env python3
"""Stage 2 of the historical-backlog publish pipeline: human review before
publish.

process_batch.py already judges relevance and writes AI-authored bilingual
content (ai_summary_en/ja, ai_abstract_ja). relevance_status='kept' means
"AI thinks this is in scope" -- it does NOT mean the AI-authored content is
good enough to publish as-is. This script is the second, separate gate: it
picks the next --batch-size 'kept' papers not yet reviewed for publish,
across shards newest publication year first, and writes:

  - review_<run_id>.html   a human-readable table to skim
  - decisions_<run_id>.tsv one row per paper, decision defaulted to
                           "approve" (edit to "reject" or "needs_edit" for
                           any row that shouldn't go out as-is)

Nothing is published by this script. Feed the (possibly edited) decisions
TSV to publish_to_site.py to actually apply it.

Usage:
    python3 scripts/export_publish_review.py \
      --db-dir /path/to/gct-literature-data/data/master \
      --review-dir /path/to/gct-literature-data/data/processed/publish_review \
      --batch-size 25
"""
import argparse
import csv
import html
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gct_db import connect, json_load, existing_shard_paths  # noqa: E402

DECISION_HEADER = (
    "pmid", "title", "journal", "year", "tags", "decision", "reviewer", "reviewed_at", "note",
)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id():
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def render_review_html(path, rows):
    table_rows = []
    for row in rows:
        table_rows.append(
            "<tr>" + "".join(
                f"<td>{html.escape(str(value))}</td>"
                for value in (
                    row["pmid"], row["year"], row["journal"], row["title"], row["tags"],
                    row["summary_en"], row["summary_ja"], row["abstract_ja_preview"],
                )
            ) + "</tr>"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>公開前レビュー</title><style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#202124}} table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccd1d8;padding:6px;vertical-align:top;max-width:340px}} th{{position:sticky;top:0;background:#eef2f7}}
</style></head><body><h1>公開前レビュー ({len(rows)}件)</h1>
<p>これはAIが relevance_status=kept と判定した文献です。decisions TSV の decision 列
(approve/reject/needs_edit)を確認・修正してから publish_to_site.py を実行してください。</p>
<table><thead><tr><th>PMID</th><th>Year</th><th>Journal</th><th>Title</th><th>Tags</th>
<th>Summary EN</th><th>Summary JA</th><th>Abstract JA(冒頭)</th></tr></thead>
<tbody>{''.join(table_rows)}</tbody></table></body></html>""", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--review-dir", type=pathlib.Path, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()

    shard_paths = existing_shard_paths(args.db_dir)
    if not shard_paths:
        print("No shard database files found under --db-dir. Nothing to do.")
        return

    rows = []
    for path in shard_paths:
        if len(rows) >= args.batch_size:
            break
        conn = connect(path)
        remaining = args.batch_size - len(rows)
        for row in conn.execute(
            """SELECT * FROM papers
               WHERE relevance_status = 'kept'
                 AND (published_to_site IS NULL OR published_to_site = 0)
                 AND human_review_status IS NULL
               ORDER BY publication_year DESC, pmid DESC LIMIT ?""",
            (remaining,),
        ).fetchall():
            rows.append(dict(row))

    if not rows:
        print("No 'kept' papers awaiting publish review. Nothing to do.")
        return

    identifier = args.run_id or run_id()
    run_dir = args.review_dir / identifier
    review_path = run_dir / f"review_{identifier}.html"
    decisions_path = run_dir / f"decisions_{identifier}.tsv"

    decision_rows = []
    html_rows = []
    for row in rows:
        tags = ", ".join(json_load(row.get("ai_tags")))
        journal = row.get("journal_abbrev") or row.get("journal_title") or ""
        decision_rows.append({
            "pmid": row["pmid"], "title": row["title"], "journal": journal,
            "year": row["publication_year"], "tags": tags,
            "decision": "approve", "reviewer": "", "reviewed_at": "", "note": "",
        })
        html_rows.append({
            "pmid": row["pmid"], "title": row["title"], "journal": journal,
            "year": row["publication_year"], "tags": tags,
            "summary_en": row.get("ai_summary_en") or "",
            "summary_ja": row.get("ai_summary_ja") or "",
            "abstract_ja_preview": (row.get("ai_abstract_ja") or "")[:200],
        })

    run_dir.mkdir(parents=True, exist_ok=True)
    with decisions_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DECISION_HEADER, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(decision_rows)
    render_review_html(review_path, html_rows)

    print(json.dumps({"reviewed": len(rows), "run_id": identifier}, ensure_ascii=False, indent=2))
    print(f"wrote: {review_path}")
    print(f"wrote: {decisions_path}")
    print("Edit the 'decision' column (approve/reject/needs_edit) as needed, then run:")
    print(f"  python3 scripts/publish_to_site.py --decisions {decisions_path} --db-dir {args.db_dir}")


if __name__ == "__main__":
    main()
