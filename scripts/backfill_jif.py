#!/usr/bin/env python3
"""JIF参照データを後から追加・更新した際に、過去の全文献へ jif_tier を遡及反映する。

対象は2か所:
  1. 非公開DB(gct-literature-data/data/master の全シャード)の全行 -- jif_tier と、
     照合の根拠(jif_match_status / jif_reference_version / jif_matched_at)
  2. 公開済みの data/papers.json -- jif_tier のみ(実数値のJIFは一切書かない)

照合は programs/literature_pipeline/pipeline.py の JIFMatcher をそのまま使う
(ISSN/eISSN+発行年 → 誌名/略称+発行年)。**発行年と同じ年のJIFしか使わない**ため、
参照TSVに新しい年(例: 2024年版)を足すたびに、その年に発行された過去の文献が新たに埋まる。
DBにはISSNがあるので papers.json 単独の match_jif.py より照合精度が高い。

冪等: 何度実行しても、同じ参照TSV群なら同じ結果になる。既定は --apply なしのドライラン
(何も書かず、件数と「どの年・どの雑誌を参照データに足すと埋まるか」だけ表示する)。

  - 既に既知のtier(low/moderate/high/very-high)が入っている行は、今回の参照データで
    照合できなくても "unknown" に戻さない(参照TSVを一部だけ指定して実行した時に、
    過去の結果を消さないため)。戻したい場合のみ --allow-downgrade。
  - exact一致した場合は常に上書きする(JCRの再公開でJIFが変わった場合の追随)。

使い方:
    # 1. 何が埋まるかの確認(書き込みなし)
    python3 scripts/backfill_jif.py --db-dir /path/to/gct-literature-data/data/master

    # 2. 反映(DB更新 + papers.json更新 + 非公開の監査CSV出力)
    python3 scripts/backfill_jif.py --db-dir /path/to/gct-literature-data/data/master --apply

--reference を省略すると <db-dir>/../reference/jif/*.tsv を全部読む。
監査CSV(実測JIFを含む)は <db-dir>/../processed/jif_backfill/ に出力される。これは
非公開リポジトリ側のみに置くこと(ライセンス上、実測JIFは公開不可)。

注: DBを開くとき gct_db.connect() が未追加の列(jif_match_status等)を自動追加する。
初回のみ各シャードのバイナリが変わるが、他のスクリプトと同じ挙動。
"""
import argparse
import csv
import json
import pathlib
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
PIPELINE_DIR = ROOT / "programs" / "literature_pipeline"
for _path in (SCRIPTS_DIR, PIPELINE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from gct_db import connect, existing_shard_paths  # noqa: E402
from pipeline import JIFMatcher, jif_tier  # noqa: E402

PAPERS_PATH = ROOT / "data" / "papers.json"
KNOWN_TIERS = {"low", "moderate", "high", "very-high"}
PUBLIC_TIERS = KNOWN_TIERS | {"unknown"}
GAP_STATUSES = ("year_not_found", "journal_not_found", "ambiguous_match", "suppressed_or_unavailable")

CHANGES_HEADER = (
    "pmid", "shard", "journal", "year", "old_tier", "new_tier", "jif_match_status",
    "jif_match_key", "jif", "jif_data_year", "jcr_release_year", "jif_reference_version",
)
GAPS_HEADER = ("kind", "key", "status", "papers")
GAP_JOURNAL_LIMIT = 500  # the long tail of one-off journals isn't actionable


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def decide(old_tier, result, allow_downgrade):
    """Return (tier, status, reference_version, keep_existing) for one evaluation.

    keep_existing=True means the stored jif_* columns must be left untouched.
    """
    status = result["jif_match_status"]
    if status == "exact":
        return jif_tier(result["jif"]), status, result["jif_reference_version"], False
    if old_tier in KNOWN_TIERS and not allow_downgrade:
        return old_tier, status, "", True
    return "unknown", status, "", False


def backfill_db(matcher, shard_conns, allow_downgrade, apply):
    matched_at = now_utc()
    stats = Counter()
    status_counts = Counter()
    changes = []
    gap_years = Counter()
    gap_journals = Counter()
    tier_by_pmid = {}

    for shard_path, conn in shard_conns.items():
        shard = shard_path.stem.replace("gct_literature_", "")
        updates = []
        for row in conn.execute(
            "SELECT pmid, publication_year, issn, eissn, journal_title, journal_abbrev, "
            "jif_tier, jif_match_status, jif_reference_version FROM papers"
        ).fetchall():
            year = row["publication_year"]
            result = matcher.match({
                "publication_year": str(year or ""),
                "issn": row["issn"] or "",
                "eissn": row["eissn"] or "",
                "journal_title": row["journal_title"] or "",
                "journal_abbrev": row["journal_abbrev"] or "",
            })
            status_counts[result["jif_match_status"]] += 1
            tier, status, version, keep_existing = decide(row["jif_tier"], result, allow_downgrade)
            tier_by_pmid[row["pmid"]] = tier
            stats["rows"] += 1

            if result["jif_match_status"] == "year_not_found":
                gap_years[year] += 1
            elif result["jif_match_status"] == "journal_not_found":
                gap_journals[(row["journal_abbrev"] or row["journal_title"] or "(none)", row["issn"] or row["eissn"] or "")] += 1

            if keep_existing:
                stats["kept_existing"] += 1
                continue
            if (tier, status, version) == (row["jif_tier"], row["jif_match_status"], row["jif_reference_version"] or ""):
                stats["unchanged"] += 1
                continue
            stats["changed"] += 1
            updates.append((tier, status, version, matched_at, row["pmid"]))
            if tier != (row["jif_tier"] or "unknown"):
                stats["tier_changed"] += 1
                changes.append({
                    "pmid": row["pmid"], "shard": shard,
                    "journal": row["journal_abbrev"] or row["journal_title"] or "", "year": year,
                    "old_tier": row["jif_tier"] or "unknown", "new_tier": tier, "jif_match_status": status,
                    "jif_match_key": result["jif_match_key"], "jif": result["jif"],
                    "jif_data_year": result["jif_data_year"], "jcr_release_year": result["jcr_release_year"],
                    "jif_reference_version": version,
                })
        if apply and updates:
            conn.executemany(
                "UPDATE papers SET jif_tier = ?, jif_match_status = ?, jif_reference_version = ?, "
                "jif_matched_at = ? WHERE pmid = ?",
                updates,
            )
            conn.commit()
    return stats, status_counts, changes, gap_years, gap_journals, tier_by_pmid


def backfill_papers(matcher, papers_path, tier_by_pmid, allow_downgrade, apply):
    papers = json.loads(papers_path.read_text(encoding="utf-8"))
    stats = Counter()
    for paper in papers:
        old_tier = paper.get("jif_tier", "unknown")
        pmid = str(paper.get("pmid", ""))
        if pmid in tier_by_pmid:
            new_tier = tier_by_pmid[pmid]
            stats["from_db"] += 1
            if new_tier == "unknown" and old_tier in KNOWN_TIERS and not allow_downgrade:
                # e.g. a hand-published entry tiered earlier by match_jif.py whose DB row was never
                # backfilled: "unknown" here means "not evaluated", not "known to have no JIF".
                new_tier = old_tier
        else:
            # Hand-published entries that never went through the DB: papers.json has only the
            # PubMed journal abbreviation and year, so this is the same fallback match_jif.py uses.
            journal = paper.get("journal", "")
            result = matcher.match({
                "publication_year": str(paper.get("year", "")), "issn": "", "eissn": "",
                "journal_title": journal, "journal_abbrev": journal,
            })
            new_tier = decide(old_tier, result, allow_downgrade)[0]
            stats["journal_name_fallback"] += 1
        if new_tier not in PUBLIC_TIERS:
            raise ValueError(f"refusing to write non-tier value {new_tier!r} to the public papers.json")
        if new_tier != old_tier:
            stats["tier_changed"] += 1
            paper["jif_tier"] = new_tier
    stats["entries"] = len(papers)
    if apply and stats["tier_changed"]:
        papers_path.write_text(json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


def write_audit(audit_dir, run_id, changes, gap_years, gap_journals, summary):
    audit_dir.mkdir(parents=True, exist_ok=True)
    with (audit_dir / f"changes_{run_id}.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CHANGES_HEADER)
        writer.writeheader()
        writer.writerows(changes)
    with (audit_dir / f"gaps_{run_id}.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(GAPS_HEADER)
        for year, count in sorted(gap_years.items(), key=lambda kv: -kv[1]):
            writer.writerow(("publication_year", year, "year_not_found", count))
        for (name, issn), count in gap_journals.most_common(GAP_JOURNAL_LIMIT):
            writer.writerow(("journal", f"{name} [{issn}]" if issn else name, "journal_not_found", count))
    (audit_dir / f"summary_{run_id}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run(args):
    shard_paths = existing_shard_paths(args.db_dir)
    if not shard_paths:
        raise SystemExit(f"No shard database files found under {args.db_dir}")
    references = args.reference or sorted((args.db_dir.parent / "reference" / "jif").glob("*.tsv"))
    if not references:
        raise SystemExit(
            f"No JIF reference TSV found (looked in {args.db_dir.parent / 'reference' / 'jif'}); pass --reference."
        )
    matcher = JIFMatcher(references)
    shard_conns = {path: connect(path) for path in shard_paths}

    stats, status_counts, changes, gap_years, gap_journals, tier_by_pmid = backfill_db(
        matcher, shard_conns, args.allow_downgrade, args.apply
    )
    papers_stats = None
    if not args.no_papers and args.papers.is_file():
        papers_stats = backfill_papers(matcher, args.papers, tier_by_pmid, args.allow_downgrade, args.apply)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        "run_id": run_id, "applied": args.apply,
        "references": [str(p) for p in references],
        "db": dict(stats), "match_status": dict(status_counts),
        "papers_json": dict(papers_stats) if papers_stats else None,
        "fillable_by_adding_jcr_year": dict(sorted((str(y), n) for y, n in gap_years.items())),
    }
    if args.apply:
        audit_dir = args.audit_dir or (args.db_dir.parent / "processed" / "jif_backfill")
        write_audit(audit_dir, run_id, changes, gap_years, gap_journals, summary)
        summary["audit_dir"] = str(audit_dir)
    return summary, gap_years, gap_journals


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--reference", type=pathlib.Path, action="append",
                        help="JIF参照TSV(非公開)。複数回指定可。省略時は <db-dir>/../reference/jif/*.tsv 全部")
    parser.add_argument("--papers", type=pathlib.Path, default=PAPERS_PATH)
    parser.add_argument("--no-papers", action="store_true", help="公開側 papers.json は更新しない")
    parser.add_argument("--audit-dir", type=pathlib.Path,
                        help="監査CSV(実測JIFを含む)の出力先。非公開リポジトリ側に置くこと")
    parser.add_argument("--apply", action="store_true", help="実際に書き込む(省略時はドライラン)")
    parser.add_argument("--allow-downgrade", action="store_true",
                        help="今回照合できない行の既存tierを unknown に戻すことを許可する")
    parser.add_argument("--top-gaps", type=int, default=10, help="未照合の上位N件を表示")
    args = parser.parse_args()

    summary, gap_years, gap_journals = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if gap_years:
        print("\n参照データに追加すると埋まる発行年(その年の雑誌がリストにあるのに、その年のJIFが無い行):")
        for year, count in sorted(gap_years.items(), key=lambda kv: -kv[1])[: args.top_gaps]:
            print(f"  {year}: {count}件")
    if gap_journals:
        print("\n参照データに存在しない雑誌(件数上位):")
        for (name, issn), count in gap_journals.most_common(args.top_gaps):
            print(f"  {count:5d}  {name} [{issn}]")
    if not args.apply:
        print("\n(ドライラン: 何も書き込んでいません。反映するには --apply)")


if __name__ == "__main__":
    main()
