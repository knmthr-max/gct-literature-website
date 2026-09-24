#!/usr/bin/env python3
"""data/papers.json の各文献を、非公開のJIF参照TSVに照合してjif_tierを書き戻す。

実数値のJIFは公開リポジトリに一切書き込まない(jif_tierのみ)。マッチングの
詳細(実測JIF・突合結果の理由)は非公開リポジトリ側に監査用CSVとして出力する。

使い方:
    python3 scripts/match_jif.py \
      --reference /path/to/gct-literature-data/data/reference/jif/jcr_jif_reference_2025_v2026.09.24.tsv \
      --audit-output /path/to/gct-literature-data/data/processed/jif_match_audit/2026-09-24.csv

複数年のデータがある場合は --reference を複数回指定する。

マッチングは programs/literature_pipeline/pipeline.py の JIFMatcher をそのまま
再利用する(ISSN/eISSN+年 → 誌名/略称(正規化)+年 の順でフォールバック)。
papers.json にはISSNを保持していないため、実際には誌名(PubMed略称)フォール
バックのみで照合される。参照TSVに当該誌・当該年のデータが無い場合は
jif_match_status に理由(journal_not_found/year_not_found等)が残るが、公開側の
jif_tier は一律 "unknown" とし、値を推測・代入しない。
"""
import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPERS_PATH = ROOT / "data" / "papers.json"
PIPELINE_DIR = ROOT / "programs" / "literature_pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from pipeline import JIFMatcher, jif_tier  # noqa: E402

AUDIT_HEADER = (
    "id", "pmid", "journal", "year", "jif_match_status", "jif_match_key",
    "jif", "jif_data_year", "jcr_release_year", "jif_reference_version", "jif_tier",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=pathlib.Path, action="append", required=True,
                         help="JIF参照TSV(非公開)。複数年ある場合は繰り返し指定")
    parser.add_argument("--audit-output", type=pathlib.Path, required=True,
                         help="実測JIFを含む監査用CSVの出力先(非公開リポジトリ側)")
    parser.add_argument("--papers", type=pathlib.Path, default=PAPERS_PATH)
    args = parser.parse_args()

    papers = json.loads(args.papers.read_text(encoding="utf-8"))
    matcher = JIFMatcher(args.reference)

    audit_rows = []
    status_counts = {}
    for paper in papers:
        article = {
            "publication_year": str(paper.get("year", "")),
            "journal_title": paper.get("journal", ""),
            "issn": "",
            "eissn": "",
        }
        result = matcher.match(article)
        status = result["jif_match_status"]
        status_counts[status] = status_counts.get(status, 0) + 1

        tier = jif_tier(result["jif"]) if status == "exact" else "unknown"
        paper["jif_tier"] = tier

        audit_rows.append({
            "id": paper.get("id", ""),
            "pmid": paper.get("pmid", ""),
            "journal": paper.get("journal", ""),
            "year": paper.get("year", ""),
            "jif_match_status": status,
            "jif_match_key": result["jif_match_key"],
            "jif": result["jif"],
            "jif_data_year": result["jif_data_year"],
            "jcr_release_year": result["jcr_release_year"],
            "jif_reference_version": result["jif_reference_version"],
            "jif_tier": tier,
        })

    args.papers.write_text(
        json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    with args.audit_output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_HEADER)
        writer.writeheader()
        writer.writerows(audit_rows)

    print(f"papers processed: {len(papers)}")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    print(f"wrote: {args.papers}")
    print(f"wrote (private audit, contains exact JIF): {args.audit_output}")


if __name__ == "__main__":
    main()
