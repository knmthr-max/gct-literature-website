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

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPERS_PATH = ROOT / "data" / "papers.json"

# PubMedの文献種別(PT)→ 日本語タグ。ここにない種別(Journal Article等)はタグにしない
PT_TAGS = {
    "Case Reports": "症例報告",
    "Review": "総説",
    "Systematic Review": "システマティックレビュー",
    "Meta-Analysis": "メタ解析",
    "Clinical Trial": "臨床試験",
    "Randomized Controlled Trial": "ランダム化比較試験",
    "Observational Study": "観察研究",
    "Multicenter Study": "多施設研究",
    "Comparative Study": "比較研究",
    "Guideline": "ガイドライン",
    "Practice Guideline": "ガイドライン",
    "Editorial": "論説",
    "Letter": "レター",
}

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

    tags = []
    for pt in rec.get("PT", []):
        tag = PT_TAGS.get(pt)
        if tag and tag not in tags:
            tags.append(tag)
    for ot in rec.get("OT", []):
        if ot and ot not in tags:
            tags.append(ot)

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
        "summary": "",
        "abstract": first(rec, "AB"),
        "added_at": today,
    }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1

    papers = json.loads(PAPERS_PATH.read_text(encoding="utf-8"))
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

    PAPERS_PATH.write_text(
        json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n完了: {added}件追加, {skipped}件スキップ, 合計{len(papers)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
