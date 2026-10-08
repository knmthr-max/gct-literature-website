#!/usr/bin/env python3
"""症例報告(タグ「症例報告」)から、年齢・性別・原発部位・組織型などを抽出する。

  extract  AI(haiku)に、抄録から患者の属性を決まった選択肢で抽出させる。結果は JSONL に追記(再開可能)。
           DBは変更しない。まず --limit 50 などで精度を確認する
  stats    抽出結果の集計(選択肢ごとの件数、不明の割合)を表示する

    python3 scripts/extract_case_attributes.py extract --db-dir <data>/master --out <data>/processed/case_attributes/pilot.jsonl --limit 50 --claude
    python3 scripts/extract_case_attributes.py stats --out <data>/processed/case_attributes/pilot.jsonl

抽出するのは抄録に書かれていることだけ。書かれていなければ unknown / null(推測しない)。
複数症例の報告は n_patients に人数を入れ、年齢・性別は単一症例のときだけ埋める(複数なら age_years=null, sex='mixed' など)。
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

spec = importlib.util.spec_from_file_location("process_batch", SCRIPTS_DIR / "process_batch.py")
process_batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(process_batch)

SEX = ("male", "female", "mixed", "unknown")
AGE_GROUPS = ("infant", "child", "adolescent", "adult", "elderly", "mixed", "unknown")  # <2y, 2-12, 13-17, 18-64, 65+
SITES = ("testis", "ovary", "mediastinum", "retroperitoneum", "sacrococcygeal", "other_extragonadal", "multiple",
         "unknown")
HISTOLOGY = ("seminoma_germinoma", "mature_teratoma", "immature_teratoma", "teratoma_with_malignant_transformation",
             "yolk_sac_tumor", "embryonal_carcinoma", "choriocarcinoma", "mixed_gct", "spermatocytic_tumor",
             "gonadoblastoma", "gct_nos", "other", "unknown")
TREATMENT = ("surgery", "chemotherapy", "radiotherapy", "observation", "high_dose_chemo_transplant", "other")
OUTCOME = ("alive_no_evidence", "alive_with_disease", "dead", "unknown")

SCHEMA = {
    "type": "object",
    "properties": {"papers": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "pmid": {"type": "string"},
            "is_case_report": {"type": "boolean"},
            "n_patients": {"type": ["integer", "null"]},
            "age_years": {"type": ["number", "null"]},
            "age_group": {"type": "string", "enum": list(AGE_GROUPS)},
            "sex": {"type": "string", "enum": list(SEX)},
            "primary_site": {"type": "string", "enum": list(SITES)},
            "site_detail": {"type": "string"},
            "histology": {"type": "array", "items": {"type": "string", "enum": list(HISTOLOGY)}},
            "metastatic": {"type": ["boolean", "null"]},
            "treatment": {"type": "array", "items": {"type": "string", "enum": list(TREATMENT)}},
            "outcome": {"type": "string", "enum": list(OUTCOME)},
        },
        "required": ["pmid", "is_case_report", "n_patients", "age_years", "age_group", "sex", "primary_site",
                     "site_detail", "histology", "metastatic", "treatment", "outcome"],
        "additionalProperties": False}}},
    "required": ["papers"], "additionalProperties": False,
}


def rows_for(db_dir):
    """(pmid, title, abstract) of kept papers tagged 症例報告 that have an abstract, in a fixed pseudo-random order."""
    out = []
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for pmid, title, abstract, tags in conn.execute(
                "SELECT pmid, title, abstract, ai_tags FROM papers WHERE relevance_status = 'kept' "
                "AND abstract IS NOT NULL AND abstract != ''"):
            if "症例報告" in json.loads(tags or "[]"):
                out.append({"pmid": str(pmid), "title": title or "", "abstract": abstract})
        conn.close()
    out.sort(key=lambda r: hashlib.sha256(r["pmid"].encode()).hexdigest())
    return out


def prompt_for(rows):
    payload = [{"pmid": r["pmid"], "title": r["title"], "abstract": r["abstract"][:2500]} for r in rows]
    return (
        "Each paper below is (tagged as) a case report or case series about germ cell tumors. Extract the patient "
        "attributes that the TITLE/ABSTRACT STATE EXPLICITLY. Never guess: use unknown / null when not stated.\n"
        "- is_case_report: false if it is clearly not a report of individual patients (e.g. a review or a cohort study).\n"
        "- n_patients: number of patients reported (integer) or null.\n"
        "- age_years: the patient's age in years (a number; months as a fraction, e.g. 8 months = 0.67), only for a "
        "single patient; otherwise null. age_group: infant (<2 y), child (2-12), adolescent (13-17), adult (18-64), "
        "elderly (65+), mixed (patients of different groups), unknown.\n"
        "- sex: male, female, mixed (both sexes in a series), unknown.\n"
        "- primary_site: where the germ cell tumor arose: testis, ovary, mediastinum, retroperitoneum, sacrococcygeal, "
        "other_extragonadal (e.g. pelvis, uterus, vagina, bladder, neck, stomach), multiple (a series covering several "
        "sites), unknown. site_detail: a few English words with the specific location if stated (else \"\").\n"
        "- histology: every histological type stated: seminoma_germinoma (seminoma/dysgerminoma/germinoma), "
        "mature_teratoma, immature_teratoma, teratoma_with_malignant_transformation (somatic-type malignancy), "
        "yolk_sac_tumor, embryonal_carcinoma, choriocarcinoma, mixed_gct, spermatocytic_tumor, gonadoblastoma, "
        "gct_nos (germ cell tumor, not otherwise specified), other, unknown.\n"
        "- metastatic: true if metastases are stated, false if explicitly localized/no metastasis, null if not stated.\n"
        "- treatment: modalities stated: surgery, chemotherapy, radiotherapy, observation, "
        "high_dose_chemo_transplant, other (empty list if not stated).\n"
        "- outcome: alive_no_evidence (disease-free), alive_with_disease, dead, unknown.\n"
        "Return exactly one result per pmid. Return only a JSON object that conforms exactly to this JSON Schema; "
        "do not use Markdown fences:\n" + json.dumps(SCHEMA, separators=(",", ":")) + "\n\nINPUT PAPERS:\n"
        + json.dumps(payload, ensure_ascii=False))


def read_done(path):
    if not path.is_file():
        return {}
    return {item["pmid"]: item for item in
            (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}


def extract(args):
    done = read_done(args.out)
    todo = [r for r in rows_for(args.db_dir) if r["pmid"] not in done]
    if args.limit:
        todo = todo[:max(0, args.limit - len(done))]
    jobs = queue.Queue()
    for i in range(0, len(todo), args.batch_size):
        jobs.put(todo[i:i + args.batch_size])
    print(f"{len(done)} already extracted, {len(todo)} to do in {jobs.qsize()} batches")
    if not args.claude:
        print("(dry run: pass --claude to call the AI)")
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lock, totals = threading.Lock(), {"batches": 0, "cost": 0.0, "failed": 0}

    def worker():
        while True:
            try:
                batch = jobs.get_nowait()
            except queue.Empty:
                return
            try:
                result, cost = process_batch.call_claude(prompt_for(batch), args.model, effort=args.effort)
            except Exception as error:  # noqa: BLE001 - the batch stays undone for the next run
                with lock:
                    totals["failed"] += 1
                    print(f"batch failed: {str(error)[:160]}", file=sys.stderr)
                continue
            with lock:
                with args.out.open("a", encoding="utf-8") as f:
                    for r in batch:
                        item = result.get(r["pmid"])
                        if isinstance(item, dict):
                            f.write(json.dumps({**item, "pmid": r["pmid"]}, ensure_ascii=False) + "\n")
                totals["batches"] += 1
                totals["cost"] += cost
                print(f"batch {totals['batches']} done, ${totals['cost']:.2f}", flush=True)

    threads = [threading.Thread(target=worker) for _ in range(args.workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print(json.dumps({**totals, "cost": round(totals["cost"], 3)}))


def stats(args):
    items = list(read_done(args.out).values())
    print(f"{len(items)} papers")
    for key in ("is_case_report", "sex", "age_group", "primary_site", "outcome", "metastatic"):
        print(f"\n{key}: {dict(collections.Counter(str(i.get(key)) for i in items).most_common())}")
    for key in ("histology", "treatment"):
        print(f"\n{key}: {dict(collections.Counter(v for i in items for v in i.get(key, [])).most_common())}")
    ages = sum(1 for i in items if i.get("age_years") is not None)
    print(f"\nage_years filled: {ages}/{len(items)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["extract", "stats"])
    parser.add_argument("--db-dir", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="Total papers to have in --out (for a pilot)")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--model", default=process_batch.DEFAULT_MODEL)
    parser.add_argument("--effort", default=process_batch.DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--claude", action="store_true")
    args = parser.parse_args()
    if args.command == "extract" and not args.db_dir:
        parser.error("extract needs --db-dir")
    {"extract": extract, "stats": stats}[args.command](args)


if __name__ == "__main__":
    main()
