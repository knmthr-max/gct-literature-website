#!/usr/bin/env python3
"""AIが抽出した論文の属性(部位・組織型・性別・年齢区分・治療・臨床テーマなど)を、公開サイトの文献(data/papers/)の
各エントリの "attrs" に入れる。サイトの絞り込み(assets/app.js)と、検索データ(search/list.json)が使う。

  入力  --attributes   extract_attributes.py の出力ディレクトリ(RCT・観察研究などの JSONL と、症例報告の臨床テーマ)
        --case         extract_case_attributes.py の結果(症例報告の共通項目)
  出力  --papers       data/papers/(各エントリに attrs を書く。値が分からない項目は入れない)
  既定はドライラン(--apply なしでは何も書かない)

attrs の項目(短い名前。値は英語の選択肢のまま。assets/app.js が表示名に直す):
  th 臨床テーマ[] / si 原発部位 / hi 組織型[] / sx 性別 / ag 年齢区分 / tr 治療[] / sg 病期 / ig IGCCCG / n 例数
  デザイン別: ln 治療ライン / ep 主要評価項目の種類 / ph 相 (RCT・非ランダム化試験)、sc 統合の対象 / mt メタ解析の有無 (SR・MA)、
              st 研究の型 (観察研究)
「不明」「記載なし」「その他」「空」は入れない(絞り込みの選択肢に出さないため)。結果の数値は持たない。

    python3 scripts/sync_site_attributes.py --papers data/papers --attributes <data>/processed/attributes_v2 \
        --case <data>/processed/case_attributes/full.jsonl [--apply]
"""
import argparse
import collections
import json
import pathlib
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import papers_store  # noqa: E402
import study_design as sd  # noqa: E402

EMPTY = {"unknown", "not_stated", "other", "", None}
# デザイン → そのデザインに固有の項目 (attrs の名前, 抽出結果の名前)
SPECIFIC = {
    sd.RCT: (("ln", "line_of_therapy"), ("ep", "primary_endpoint"), ("ph", "phase")),
    sd.NON_RCT: (("ln", "line_of_therapy"), ("ep", "primary_endpoint"), ("ph", "phase")),
    sd.SR_MA: (("sc", "review_scope"),),
    sd.OBSERVATIONAL: (("st", "study_type"),),
}


def clean_list(values):
    return [v for v in values or [] if v not in EMPTY]


def core_attrs(row):
    out = {}
    for key, src in (("si", "primary_site"), ("sx", "sex"), ("ag", "age_group"), ("sg", "stage_group"), ("ig", "igcccg")):
        if row.get(src) not in EMPTY:
            out[key] = row[src]
    for key, src in (("hi", "histology"), ("tr", "treatment")):
        if clean_list(row.get(src)):
            out[key] = clean_list(row[src])
    if isinstance(row.get("n_patients"), int) and row["n_patients"] > 0:
        out["n"] = row["n_patients"]
    return out


def read_jsonl(path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build(attributes_dir, case_path):
    """pmid -> {"design": 抽出時のデザイン, "core": {...}, "specific": {...}, "themes": [...]}"""
    rows = {}
    for path in sorted(attributes_dir.glob("*.jsonl")):
        for r in read_jsonl(path):
            entry = rows.setdefault(r["pmid"], {})
            entry["themes"] = clean_list(r.get("clinical_themes"))
            if "sex" in r:  # 共通項目を持つデザイン(症例報告の臨床テーマだけの行は持たない)
                entry.update(design=r.get("design"), core=core_attrs(r), row=r)
    for r in read_jsonl(case_path):
        entry = rows.setdefault(r["pmid"], {})
        entry.update(design=sd.CASE, core=core_attrs(r), row=r)
    return rows


def attrs_for(entry, info):
    design = (entry.get("tags") or [""])[0]
    attrs = dict(info.get("core") or {})
    if info.get("themes"):
        attrs["th"] = info["themes"]
    row = info.get("row")
    if row and info.get("design") == design:   # デザイン固有の項目は、今のタグと抽出時のデザインが同じときだけ
        for key, src in SPECIFIC.get(design, ()):
            if row.get(src) not in EMPTY:
                attrs[key] = row[src]
        if design == sd.SR_MA and isinstance(row.get("quantitative_synthesis"), bool):
            attrs["mt"] = "yes" if row["quantitative_synthesis"] else "no"
    return attrs


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--papers", type=pathlib.Path, required=True)
    parser.add_argument("--attributes", type=pathlib.Path, required=True)
    parser.add_argument("--case", type=pathlib.Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    rows = build(args.attributes, args.case)
    papers = papers_store.load(args.papers)
    changed, filled, by_design = 0, 0, collections.Counter()
    for entry in papers:
        info = rows.get(str(entry.get("pmid") or ""))
        attrs = attrs_for(entry, info) if info else {}
        if attrs:
            filled += 1
            by_design[(entry.get("tags") or [""])[0]] += 1
        if (entry.get("attrs") or {}) != attrs:
            changed += 1
            if attrs:
                entry["attrs"] = attrs
            else:
                entry.pop("attrs", None)
    print(f"site entries: {len(papers)} | with attrs: {filled} | to update: {changed}")
    for design, n in by_design.most_common():
        print(f"  {design}: {n}")
    if not args.apply:
        print("(dry run: nothing written; pass --apply)")
        return
    papers_store.save(args.papers, papers)
    print("applied")


if __name__ == "__main__":
    main()
