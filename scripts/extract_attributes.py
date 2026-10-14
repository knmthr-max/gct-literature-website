#!/usr/bin/env python3
"""症例報告より上位のエビデンス(RCT・非ランダム化試験・SR・MA・観察研究・ガイドライン)と、臨床の全論文の「臨床テーマ」を、
AIで抄録から抽出する。DBは変更しない。結果は JSONL に追記(再開可能)。

  共通項目     症例報告(scripts/extract_case_attributes.py)と同じ名前・同じ選択肢。対象の性別・年齢層、原発部位、組織型、
               病期・IGCCCG、治療の種類、症例数(患者数)。集団を対象にする研究では、集団の性質として答える
  デザイン別   RCT・非ランダム化試験(相、治療の位置づけ、比較対照、主要評価項目の種類、施設数)、観察研究(研究の型、データの出所、扱う問い)、
               SR・MA(統合の対象、研究数、定量的な統合の有無)、ガイドライン(発行団体、範囲)
  臨床テーマ   全ての臨床の論文(症例報告・総説・その他を含む)に付ける複数選択の横断項目
  結果の数値   抽出しない(ハザード比・生存率などは対象外。評価項目の「種類」まで)

    python3 scripts/extract_attributes.py extract --db-dir <data>/master --out-dir <data>/processed/attributes --limit-per-design 30 --claude
    python3 scripts/extract_attributes.py stats --out-dir <data>/processed/attributes

出力: <out-dir>/<デザインの識別名>.jsonl(症例報告は themes_case_report.jsonl に臨床テーマだけ)。
"""
import argparse
import collections
import hashlib
import importlib.util
import json
import pathlib
import queue
import sqlite3
import sys
import threading

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from gct_db import existing_shard_paths  # noqa: E402
import study_design as sd  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


process_batch = _load("process_batch")
case = _load("extract_case_attributes")  # 共通項目の選択肢は、症例報告のものをそのまま使う(同じ形にそろえるため)

DISEASE_SETTING = ("localized", "advanced_metastatic", "mixed", "not_stated")
THEMES = ("diagnosis_imaging", "surgery", "chemotherapy", "radiotherapy", "surveillance", "late_effects", "fertility",
          "epidemiology", "pathology_molecular", "prognosis", "qol")

PHASE = ("I", "I/II", "II", "II/III", "III", "other", "not_stated")
LINE = ("first_line", "salvage", "adjuvant", "neoadjuvant", "maintenance", "mixed", "not_stated")
ENDPOINT = ("OS", "PFS", "response_rate", "safety", "other", "not_stated")
CENTERS = ("single_center", "multicenter", "not_stated")
STUDY_TYPE = ("retrospective_cohort", "prospective_cohort", "case_control", "cross_sectional", "registry_epidemiology",
              "diagnostic_accuracy", "prognostic_biomarker", "genetic_association", "survey", "other")
DATA_SOURCE = ("single_center", "multicenter", "registry_database", "not_stated")
QUESTION = ("treatment_outcome", "late_effects_survivorship", "fertility", "diagnosis_imaging", "pathology_molecular",
            "surgical_technique", "epidemiology_incidence", "qol", "other")
REVIEW_SCOPE = ("treatment", "diagnosis", "prognosis", "epidemiology", "other")

CORE = {
    "n_patients": {"type": ["integer", "null"]},
    "sex": {"type": "string", "enum": list(case.SEX)},
    "age_group": {"type": "string", "enum": list(case.AGE_GROUPS)},
    "primary_site": {"type": "string", "enum": list(case.SITES)},
    "histology": {"type": "array", "items": {"type": "string", "enum": list(case.HISTOLOGY)}},
    "disease_setting": {"type": "string", "enum": list(DISEASE_SETTING)},
    "stage_group": {"type": "string", "enum": list(case.STAGE_GROUPS)},
    "igcccg": {"type": "string", "enum": list(case.IGCCCG)},
    "treatment": {"type": "array", "items": {"type": "string", "enum": list(case.TREATMENT)}},
}
THEME_PROP = {"clinical_themes": {"type": "array", "items": {"type": "string", "enum": list(THEMES)}}}
SPECIFIC = {
    "trial": {"phase": {"type": "string", "enum": list(PHASE)}, "line_of_therapy": {"type": "string", "enum": list(LINE)},
              "has_comparator": {"type": ["boolean", "null"]}, "primary_endpoint": {"type": "string", "enum": list(ENDPOINT)},
              "centers": {"type": "string", "enum": list(CENTERS)}},
    "observational": {"study_type": {"type": "string", "enum": list(STUDY_TYPE)},
                      "data_source": {"type": "string", "enum": list(DATA_SOURCE)},
                      "question_domain": {"type": "array", "items": {"type": "string", "enum": list(QUESTION)}}},
    "review": {"review_scope": {"type": "string", "enum": list(REVIEW_SCOPE)}, "n_studies": {"type": ["integer", "null"]},
               "quantitative_synthesis": {"type": ["boolean", "null"]}},
    "guideline": {"issuing_body": {"type": "string"}, "scope": {"type": "string"}},
}

# デザイン → (出力の識別名, 項目の種類, 共通項目を取るか)。症例報告は臨床テーマだけ(共通項目は既に抽出済み)
DESIGNS = {
    sd.RCT: ("rct", "trial", True), sd.NON_RCT: ("non_rct", "trial", True), sd.SR_MA: ("sr_ma", "review", True),
    sd.OBSERVATIONAL: ("observational", "observational", True), sd.GUIDELINE: ("guideline", "guideline", False),
    sd.REVIEW: ("review", None, False), sd.OTHER: ("other", None, False), sd.CASE: ("themes_case_report", None, False),
}

SPECIFIC_NOTE = {
    "trial": (
        "- phase: clinical trial phase (I, I/II, II, II/III, III), other, or not_stated. line_of_therapy: first_line, "
        "salvage, adjuvant, neoadjuvant, maintenance, mixed, not_stated. has_comparator: true if there is a control/"
        "comparison arm, false for a single-arm study, null if unclear. primary_endpoint: the KIND of the primary "
        "endpoint (OS, PFS, response_rate, safety, other, not_stated; no numbers). centers: single_center, multicenter, "
        "not_stated.\n"),
    "observational": (
        "- study_type: retrospective_cohort, prospective_cohort, case_control, cross_sectional, registry_epidemiology, "
        "diagnostic_accuracy, prognostic_biomarker, genetic_association, survey, other. data_source: single_center, "
        "multicenter, registry_database, not_stated. question_domain: the clinical question(s) addressed "
        "(treatment_outcome, late_effects_survivorship, fertility, diagnosis_imaging, pathology_molecular, "
        "surgical_technique, epidemiology_incidence, qol, other).\n"),
    "review": (
        "- review_scope: what the review/meta-analysis pools (treatment, diagnosis, prognosis, epidemiology, other). "
        "n_studies: number of studies included, if stated (integer) else null. quantitative_synthesis: true if a "
        "meta-analysis (quantitative pooling) was performed, false if narrative only, null if unclear. n_patients: total "
        "patients across the studies, if stated.\n"),
    "guideline": "- issuing_body: the organization that issued it (e.g. EAU, ESMO, NCCN, JSCO), else \"\". scope: a few English words on what it covers.\n",
}
CORE_NOTE = (
    "COMMON FIELDS (describe the study population; use the same meaning as for case reports):\n"
    "- n_patients: number of patients/subjects analyzed (integer) or null. sex: male, female, mixed, unknown. "
    "age_group: the group the study population belongs to (infant <2 y, child 2-12, adolescent 13-17, adult 18-64, "
    "elderly 65+, mixed, unknown).\n"
    "- primary_site: where the germ cell tumors arose (testis, ovary, mediastinum, retroperitoneum, sacrococcygeal, "
    "other_extragonadal, multiple, unknown). histology: every histological type the study covers (seminoma_germinoma, "
    "mature_teratoma, immature_teratoma, teratoma_with_malignant_transformation, yolk_sac_tumor, embryonal_carcinoma, "
    "choriocarcinoma, mixed_gct, spermatocytic_tumor, gonadoblastoma, gct_nos, other, unknown).\n"
    "- disease_setting: localized, advanced_metastatic, mixed, not_stated (disease extent of the study population). "
    "stage_group: I, II, III or IV ONLY if the study is restricted to one stage group; otherwise not_stated. igcccg: good, "
    "intermediate or poor ONLY if the study is restricted to that IGCCCG risk group; otherwise not_stated.\n"
    "- treatment: the modalities studied or used (surgery, chemotherapy, radiotherapy, observation, "
    "high_dose_chemo_transplant, other).\n")
THEME_NOTE = (
    "- clinical_themes: every theme the paper substantially addresses (diagnosis_imaging, surgery, chemotherapy, "
    "radiotherapy, surveillance, late_effects, fertility, epidemiology, pathology_molecular, prognosis, qol; an empty "
    "list if none fits).\n")
RULES = (
    "Extract ONLY what the TITLE/ABSTRACT STATE EXPLICITLY. Never guess: use unknown / not_stated / null / an empty list when "
    "not stated. Do NOT extract numerical results (hazard ratios, survival or response rates, p-values): only the "
    "kinds of endpoints or outcomes.\n")


def schema_for(design):
    _, kind, with_core = DESIGNS[design]
    props = {"pmid": {"type": "string"}}
    if with_core:
        props.update(CORE)
    if kind:
        props.update(SPECIFIC[kind])
    props.update(THEME_PROP)
    return {"type": "object", "properties": {"papers": {"type": "array", "items": {
        "type": "object", "properties": props, "required": list(props), "additionalProperties": False}}},
        "required": ["papers"], "additionalProperties": False}


def prompt_for(design, rows):
    _, kind, with_core = DESIGNS[design]
    payload = [{"pmid": r["pmid"], "title": r["title"], "abstract": r["abstract"][:2500]} for r in rows]
    return (
        f"Each paper below is a germ cell tumor paper whose study design was judged to be: {design}. " + RULES
        + (CORE_NOTE if with_core else "") + (SPECIFIC_NOTE[kind] if kind else "") + THEME_NOTE
        + "Return exactly one result per pmid. Return only a JSON object that conforms exactly to this JSON Schema; do "
          "not use Markdown fences:\n" + json.dumps(schema_for(design), separators=(",", ":"))
        + "\n\nINPUT PAPERS:\n" + json.dumps(payload, ensure_ascii=False))


def rows_by_design(db_dir, designs):
    out = {d: [] for d in designs}
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for pmid, title, abstract, tags in conn.execute(
                "SELECT pmid, title, abstract, ai_tags FROM papers WHERE relevance_status IN ('kept', 'needs_review') "
                "AND abstract IS NOT NULL AND abstract != ''"):
            tag = (json.loads(tags or "[]") or [""])[0]
            if tag in out:
                out[tag].append({"pmid": str(pmid), "title": title or "", "abstract": abstract})
        conn.close()
    for rows in out.values():
        rows.sort(key=lambda r: hashlib.sha256(r["pmid"].encode()).hexdigest())  # 決まった順(偏りのない試験用)
    return out


def read_done(path):
    if not path.is_file():
        return {}
    return {i["pmid"]: i for i in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())}


def extract(args):
    designs = args.designs.split(",") if args.designs else list(DESIGNS)
    unknown = [d for d in designs if d not in DESIGNS]
    if unknown:
        raise SystemExit(f"unknown design(s): {unknown}; choose from {list(DESIGNS)}")
    rows = rows_by_design(args.db_dir, designs)
    jobs, plan = queue.Queue(), []
    for design in designs:
        out = args.out_dir / f"{DESIGNS[design][0]}.jsonl"
        done = read_done(out)
        todo = [r for r in rows[design] if r["pmid"] not in done]
        if args.limit_per_design:
            todo = todo[:max(0, args.limit_per_design - len(done))]
        plan.append((design, len(done), len(todo)))
        for i in range(0, len(todo), args.batch_size):
            jobs.put((design, todo[i:i + args.batch_size]))
    for design, d, t in plan:
        print(f"{design}: {d} already extracted, {t} to do")
    print(f"{jobs.qsize()} batches")
    if not args.claude:
        print("(dry run: pass --claude to call the AI)")
        return
    args.out_dir.mkdir(parents=True, exist_ok=True)
    lock, totals, stop = threading.Lock(), {"batches": 0, "cost": 0.0, "failed": 0, "consecutive": 0}, threading.Event()

    def worker():
        while not stop.is_set():
            try:
                design, batch = jobs.get_nowait()
            except queue.Empty:
                return
            try:
                result, cost = process_batch.call_claude(prompt_for(design, batch), args.model, effort=args.effort)
            except Exception as error:  # noqa: BLE001 - the batch stays undone for the next run
                with lock:
                    totals["failed"] += 1
                    totals["consecutive"] += 1
                    print(f"batch failed: {str(error)[:160]}", file=sys.stderr, flush=True)
                    if totals["consecutive"] >= 6 or any(w in str(error).lower() for w in ("usage limit", "rate limit", "limit reached")):
                        if not stop.is_set():
                            print("STOP: usage limit or repeated failures; resume later with the same command", flush=True)
                        stop.set()
                continue
            with lock:
                with (args.out_dir / f"{DESIGNS[design][0]}.jsonl").open("a", encoding="utf-8") as f:
                    for r in batch:
                        item = result.get(r["pmid"])
                        if isinstance(item, dict):
                            f.write(json.dumps({**item, "pmid": r["pmid"], "design": design}, ensure_ascii=False) + "\n")
                totals["batches"] += 1
                totals["consecutive"] = 0
                totals["cost"] += cost
                if totals["batches"] % 10 == 0:
                    print(f"batch {totals['batches']} done, ${totals['cost']:.2f}", flush=True)

    threads = [threading.Thread(target=worker) for _ in range(args.workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print(json.dumps({**totals, "cost": round(totals["cost"], 3)}))


def stats(args):
    for design, (name, kind, _) in DESIGNS.items():
        done = read_done(args.out_dir / f"{name}.jsonl")
        if not done:
            continue
        print(f"\n== {design}: {len(done)} papers")
        keys = [k for k in (list(CORE) if DESIGNS[design][2] else []) + list(SPECIFIC.get(kind, {})) + list(THEME_PROP)]
        for key in keys:
            if key in ("n_patients", "n_studies", "issuing_body", "scope"):
                filled = sum(1 for v in done.values() if v.get(key) not in (None, ""))
                print(f"  {key}: filled {filled}/{len(done)}")
                continue
            c = collections.Counter(x for v in done.values() for x in (v.get(key) if isinstance(v.get(key), list) else [v.get(key)]))
            print(f"  {key}: {dict(c.most_common(8))}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["extract", "stats"])
    parser.add_argument("--db-dir", type=pathlib.Path)
    parser.add_argument("--out-dir", type=pathlib.Path, required=True)
    parser.add_argument("--designs", help="comma-separated study designs (default: all)")
    parser.add_argument("--limit-per-design", type=int, default=0, help="for a pilot: total papers per design in the output")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--model", default=process_batch.DEFAULT_MODEL)
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--claude", action="store_true")
    args = parser.parse_args()
    if args.command == "extract" and not args.db_dir:
        parser.error("extract needs --db-dir")
    {"extract": extract, "stats": stats}[args.command](args)


if __name__ == "__main__":
    main()
