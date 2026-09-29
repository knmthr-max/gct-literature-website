#!/usr/bin/env python3
"""非公開データリポジトリの状況レポート(Markdown)を生成する。

GitHubのプライベートリポジトリ上でMarkdownとして表示される(Safari可)ことを想定し、
表は幅を抑えている。DBは読み取り専用で開くので、DBファイルは一切変更しない。

    python3 scripts/portal_status.py --data-dir /path/to/gct-literature-data/data \
        --output /path/to/gct-literature-data/portal/STATUS.md

出力にはJIFの実数値を含めない(件数とtierのみ)。
"""
import argparse
import csv
import json
import pathlib
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gct_db import existing_shard_paths  # noqa: E402

TRANSLATED = "ai_title_ja IS NOT NULL AND ai_title_ja != '' AND ai_abstract_ja IS NOT NULL AND ai_abstract_ja != ''"
JIF_STATUS_LABELS = (
    ("exact", "照合済み(tier確定)"),
    ("year_not_found", "その年のJIFが参照データに無い"),
    ("journal_not_found", "雑誌が参照データに無い"),
    ("ambiguous_match", "曖昧一致"),
    ("suppressed_or_unavailable", "JIF非開示"),
)


def open_readonly(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def scalar(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def shard_stats(path):
    conn = open_readonly(path)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(papers)")}
    stats = {
        "shard": path.stem.replace("gct_literature_", ""),
        "total": scalar(conn, "SELECT COUNT(*) FROM papers"),
        "pending": scalar(conn, "SELECT COUNT(*) FROM papers WHERE relevance_status IS NULL"),
        "kept": scalar(conn, "SELECT COUNT(*) FROM papers WHERE relevance_status = 'kept'"),
        "needs_review": scalar(conn, "SELECT COUNT(*) FROM papers WHERE relevance_status = 'needs_review'"),
        "excluded": scalar(conn, "SELECT COUNT(*) FROM papers WHERE relevance_status = 'excluded'"),
        "kept_untranslated": scalar(
            conn, f"SELECT COUNT(*) FROM papers WHERE relevance_status = 'kept' AND NOT ({TRANSLATED})"),
        "review_ready": scalar(
            conn,
            f"SELECT COUNT(*) FROM papers WHERE relevance_status = 'kept' AND {TRANSLATED} "
            "AND (published_to_site IS NULL OR published_to_site = 0) AND human_review_status IS NULL"),
        "published": scalar(conn, "SELECT COUNT(*) FROM papers WHERE published_to_site = 1"),
        "rejected": scalar(conn, "SELECT COUNT(*) FROM papers WHERE human_review_status = 'rejected'"),
        "needs_edit": scalar(conn, "SELECT COUNT(*) FROM papers WHERE human_review_status = 'needs_edit'"),
        "jif_status": Counter(), "jif_tier": Counter(),
    }
    if "jif_match_status" in columns:
        for row in conn.execute("SELECT jif_match_status AS s, COUNT(*) AS n FROM papers GROUP BY s"):
            stats["jif_status"][row["s"] or "(未評価)"] += row["n"]
    else:
        stats["jif_status"]["(未評価)"] = stats["total"]
    for row in conn.execute("SELECT jif_tier AS t, COUNT(*) AS n FROM papers GROUP BY t"):
        stats["jif_tier"][row["t"] or "(未評価)"] += row["n"]
    conn.close()
    return stats


def review_runs(data_dir, shard_paths):
    """Each exported review run, and how many of its rows still await an applied decision."""
    runs = []
    for decisions in sorted((data_dir / "processed" / "publish_review").glob("*/decisions_*.tsv"), reverse=True):
        with decisions.open(encoding="utf-8", newline="") as f:
            pmids = [r["pmid"] for r in csv.DictReader(f, delimiter="\t") if r.get("pmid")]
        undecided = 0
        for path in shard_paths:
            conn = open_readonly(path)
            for i in range(0, len(pmids), 500):
                chunk = pmids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                undecided += scalar(
                    conn, f"SELECT COUNT(*) FROM papers WHERE pmid IN ({marks}) AND human_review_status IS NULL", chunk)
            conn.close()
        runs.append({
            "run_id": decisions.parent.name, "rows": len(pmids), "undecided": undecided,
            "has_md": any(decisions.parent.glob("review_*.md")),
        })
    return runs


def reference_summary(data_dir):
    years = Counter()
    files = []
    for tsv in sorted((data_dir / "reference" / "jif").glob("*.tsv")):
        with tsv.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        files.append((tsv.name, len(rows)))
        for row in rows:
            years[row.get("jif_data_year", "")] += 1
    return files, years


def cost_summary(data_dir):
    result = []
    for name in ("batch_cost_log.jsonl", "refill_cost_log.jsonl"):
        path = data_dir / "master" / name
        if not path.is_file():
            continue
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        result.append((name, len(entries), sum(e.get("papers", 0) for e in entries),
                       sum(e.get("cost_usd", 0.0) for e in entries)))
    return result


def latest_jif_backfill(data_dir):
    summaries = sorted((data_dir / "processed" / "jif_backfill").glob("summary_*.json"))
    return json.loads(summaries[-1].read_text(encoding="utf-8")) if summaries else None


def render(data_dir):
    shard_paths = existing_shard_paths(data_dir / "master")
    shards = [shard_stats(p) for p in shard_paths]
    total = Counter()
    jif_status = Counter()
    jif_tier = Counter()
    for s in shards:
        for key in ("total", "pending", "kept", "needs_review", "excluded", "kept_untranslated",
                    "review_ready", "published", "rejected", "needs_edit"):
            total[key] += s[key]
        jif_status.update(s["jif_status"])
        jif_tier.update(s["jif_tier"])

    lines = [
        "# GCT文献データ 状況レポート",
        "",
        f"更新: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        "この画面は自動生成です。実測JIFの数値は含みません。",
        "",
        "## 概況",
        "",
        "| 項目 | 件数 |", "|---|---:|",
        f"| 総件数 | {total['total']:,} |",
        f"| AI判定待ち | {total['pending']:,} |",
        f"| kept(対象) | {total['kept']:,} |",
        f"| needs_review(要確認) | {total['needs_review']:,} |",
        f"| excluded(対象外) | {total['excluded']:,} |",
        f"| kept のうち和訳(タイトル・抄録)未完了 | {total['kept_untranslated']:,} |",
        f"| 公開前レビュー待ち(和訳完了・未公開) | {total['review_ready']:,} |",
        f"| 公開済み | {total['published']:,} |",
        f"| レビューで却下 / 要修正 | {total['rejected']:,} / {total['needs_edit']:,} |",
        "",
        "## シャード(年代)別",
        "",
        "| 年代 | 総数 | 判定待ち | kept | 要確認 | 対象外 | 和訳未完了 |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in shards:
        lines.append(f"| {s['shard']} | {s['total']:,} | {s['pending']:,} | {s['kept']:,} | "
                     f"{s['needs_review']:,} | {s['excluded']:,} | {s['kept_untranslated']:,} |")

    files, years = reference_summary(data_dir)
    lines += ["", "## JIF(インパクトファクター)", ""]
    if files:
        lines.append("参照データ: " + "、".join(f"`{name}`({n}誌)" for name, n in files))
        lines.append("")
        lines.append("参照データがカバーする年: " + "、".join(f"{y}" for y in sorted(years)))
    else:
        lines.append("参照データがありません。")
    lines += ["", "| 照合結果(全文献) | 件数 |", "|---|---:|"]
    known = set()
    for key, label in JIF_STATUS_LABELS:
        known.add(key)
        if jif_status.get(key):
            lines.append(f"| {label} | {jif_status[key]:,} |")
    for key, n in jif_status.items():
        if key not in known:
            lines.append(f"| {key} | {n:,} |")
    lines += ["", "| tier | 件数 |", "|---|---:|"]
    for tier in ("very-high", "high", "moderate", "low", "unknown", "(未評価)"):
        if jif_tier.get(tier):
            lines.append(f"| {tier} | {jif_tier[tier]:,} |")
    last = latest_jif_backfill(data_dir)
    if last:
        lines += ["", f"直近のJIF遡及: {last['run_id']}(反映: {'済' if last.get('applied') else 'ドライランのみ'})"]

    lines += ["", "## 公開前レビュー", ""]
    runs = review_runs(data_dir, shard_paths)
    if runs:
        lines += ["| run_id | 件数 | 未決定 | 状態 |", "|---|---:|---:|---|"]
        for r in runs[:8]:
            state = "**未処理(「4 公開反映」で処理)**" if r["undecided"] else "処理済み"
            lines.append(f"| `{r['run_id']}` | {r['rows']} | {r['undecided']} | {state} |")
    else:
        lines.append("レビュー実行の履歴はありません。")

    costs = cost_summary(data_dir)
    lines += ["", "## AI処理コスト(累計)", ""]
    if costs:
        lines += ["| ログ | 実行回数 | 対象件数 | 累計(USD) |", "|---|---:|---:|---:|"]
        for name, runs_n, papers, cost in costs:
            lines.append(f"| {name} | {runs_n} | {papers:,} | {cost:,.2f} |")
    else:
        lines.append("コストログがありません。")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=pathlib.Path, required=True, help="データリポジトリの data/ ディレクトリ")
    parser.add_argument("--output", type=pathlib.Path, help="省略時は標準出力")
    args = parser.parse_args()
    text = render(args.data_dir)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
