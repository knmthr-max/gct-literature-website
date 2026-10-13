#!/usr/bin/env python3
"""PubMed/MEDLINE形式(.nbib)のファイルから data/papers.json へ文献を取り込む。

使い方:
    python3 scripts/import_medline.py data/raw/2026-09-07-import.nbib [他のファイル...]

- PMIDで重複判定し、既に papers.json にあるエントリはスキップする
  (手動で書いた title_ja / summary / tags が上書きされることはない)
- 追加された件数と、スキップされた件数を表示する
"""
import datetime
import json
import pathlib
import re
import sys
import papers_store  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPERS_PATH = ROOT / "data" / "papers"

# 公開サイトのタグは、固定の9分類(研究デザイン)だけに限定する(PubMedの著者キーワードや細かい文献種別を
# そのままタグにすると、1件にしか付かないタグが大量発生しタグクラウドが機能しなくなるため)。
# 定義と判定の順序は scripts/study_design.py。出版タイプで決まらない論文(原著論文の多く)は、ここでは None にして、
# AI の判定(process_batch.py の study_design)で補う。
from study_design import design_from_pubtypes  # noqa: E402


def classify(publication_types):
    """PubMedの文献種別(PT)から固定9分類のうち1つを判定する。出版タイプで決まらなければNone。"""
    return design_from_pubtypes(publication_types)


TAG_LINE = re.compile(r"^([A-Z]{1,4})\s*-\s(.*)$")


def parse_records(text):
    """MEDLINE形式のテキストをレコード(タグ→値リストの辞書)の一覧に変換する。"""
    records = []
    rec = None
    last_key = None
    for line in text.splitlines():
        m = TAG_LINE.match(line)
        if m:
            key, value = m.group(1), m.group(2)
            if key == "PMID":
                rec = {}
                records.append(rec)
            if rec is None:
                continue
            rec.setdefault(key, []).append(value.strip())
            last_key = key
        elif rec is not None and last_key and line.startswith("     "):
            # 折り返し行(行頭スペース)は直前のフィールドに連結する
            rec[last_key][-1] += " " + line.strip()
    return records


def first(rec, key, default=""):
    values = rec.get(key)
    return values[0] if values else default


def extract_doi(rec):
    for field in ("LID", "AID"):
        for value in rec.get(field, []):
            if value.endswith("[doi]"):
                return value[: -len("[doi]")].strip()
    return ""


def to_entry(rec, today):
    pmid = first(rec, "PMID")
    year_match = re.search(r"\d{4}", first(rec, "DP"))

    category = classify(rec.get("PT", []))
    tags = [category] if category else []

    return {
        "id": f"pmid-{pmid}",
        "title": first(rec, "TI"),
        "title_ja": "",
        "authors": rec.get("AU", []),
        "journal": first(rec, "TA") or first(rec, "JT"),
        "year": int(year_match.group()) if year_match else None,
        "pmid": pmid,
        "doi": extract_doi(rec),
        "url": "",
        "tags": tags,
        "summary_en": "",
        "summary_ja": "",
        "abstract": first(rec, "AB"),
        "abstract_ja": "",
        "added_at": today,
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1

    papers = papers_store.load(PAPERS_PATH)
    known_pmids = {p.get("pmid") for p in papers if p.get("pmid")}
    today = datetime.date.today().isoformat()

    added = skipped = 0
    for arg in argv[1:]:
        text = pathlib.Path(arg).read_text(encoding="utf-8")
        for rec in parse_records(text):
            entry = to_entry(rec, today)
            if not entry["pmid"] or not entry["title"] or not entry["year"]:
                print(f"警告: 必須情報が欠けているためスキップ: PMID={entry['pmid'] or '不明'}")
                skipped += 1
                continue
            if entry["pmid"] in known_pmids:
                print(f"スキップ(登録済み): PMID={entry['pmid']}")
                skipped += 1
                continue
            papers.append(entry)
            known_pmids.add(entry["pmid"])
            added += 1
            print(f"追加: PMID={entry['pmid']} {entry['title'][:60]}")

    papers_store.save(PAPERS_PATH, papers)
    print(f"\n完了: {added}件追加, {skipped}件スキップ, 合計{len(papers)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
