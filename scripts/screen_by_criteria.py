#!/usr/bin/env python3
"""編集基準(2026-11-03)に沿って、論文を「掲載 / 除外」にスクリーニングする(AI。DBは変更しない)。

基準は CRITERIA に書いた(基礎研究・症例報告・総説・臨床論文ごと)。対象は、既定では relevance_status が needs_review の論文。
結果は JSONL に追記する(再開可能。使用量の上限に達したら止まる)。判定のDBへの反映は scripts/apply_status_decisions.py。

  - 基準に当てはまらず迷うときは「掲載」(これまでの判断で、迷う論文の約95%が掲載だったため)。そのうえで confidence を low にし、
    人が見る対象を絞れるようにする
  - 試験(基準の見直し)用に、判断済みの論文を対象にするには --status any と --only-pmids を使い、人の判断との一致を見る

    python3 scripts/screen_by_criteria.py --db-dir <data>/master --out <data>/processed/relevance_review/criteria_screen.jsonl \
        [--status needs_review|any] [--only-pmids FILE] [--limit N] --claude
"""
import argparse
import collections
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

RULES = ("basic_in", "basic_out", "basic_animal_descriptive", "case_animal", "case_unspecified", "case_not_main_gct",
         "case_teratocarcinosarcoma", "case_dermoid_nongonadal", "case_in", "review_not_gct_topic", "review_in",
         "clinical_animal", "clinical_no_gct_analyzed", "clinical_intracranial_no_gct", "clinical_in")
DECISIONS = ("keep", "exclude")
CONFIDENCE = ("high", "medium", "low")

CRITERIA = """\
Decide for each paper whether the website on germ cell tumors (GCT) should KEEP or EXCLUDE it, using ONLY these editorial rules.
Each paper comes with `design` (its study-design tag). Apply the block for that design.

BASIC / TRANSLATIONAL research (design = 基礎・トランスレーショナル)
- KEEP research that leads to models of germ cell tumors, including studies in NON-HUMAN animals, and research related to GCT whatever
  the cell of origin is (embryonic stem cells, iPS cells, embryonal carcinoma cell lines, primordial germ cells, ...) (rule basic_in).
- A study of a germ cell tumor of a NON-HUMAN animal (e.g. a dog) is KEPT only when it is positioned as a model of HUMAN germ cell tumors
  (basic_in). A merely descriptive pathology or epidemiology report on an animal tumor is EXCLUDED (basic_animal_descriptive).
- KEEP basic research that merely uses a choriocarcinoma cell line when its topic is trophoblast biology (basic_in).
- EXCLUDE basic research with no real connection to GCT or to GCT models (basic_out).

CASE REPORT / CASE SERIES (design = 症例報告・集積)
- EXCLUDE reports on germ cell tumors of NON-HUMAN animals (case_animal).
- EXCLUDE a report whose tumor type cannot be identified from the title/abstract (case_unspecified).
- EXCLUDE a human report whose main tumor is NOT a germ cell tumor (e.g. a spermatic cord stromal tumor), even if a germ cell
  tumor is mentioned in the differential diagnosis (case_not_main_gct).
- EXCLUDE teratocarcinosarcoma (case_teratocarcinosarcoma).
- Do NOT exclude fetus in fetu (case_in).
- EXCLUDE ordinary subcutaneous or intracranial dermoid cysts (they are not GCT) (case_dermoid_nongonadal); but do NOT exclude dermoid
  cysts / mature teratomas of the GONADS (ovary, testis) (case_in).
- Otherwise KEEP (case_in).

REVIEW (design = 総説)
- EXCLUDE a review whose topic is not directly about germ cell tumors (review_not_gct_topic). Examples: a review of an anticancer drug
  used in GCT among others = exclude; a review of a disease whose differential includes GCT but whose topic is not GCT = exclude.
- KEEP a review directly about GCT, e.g. a review of BEP or TIP chemotherapy for GCT, or a broad review (e.g. of gonadal tumors) in which
  germ cell tumors are part of the subject (review_in).

OTHER CLINICAL papers (every other design except basic)
- Do NOT exclude a paper merely because its main tumor is not a germ cell tumor: if germ cell tumors are among the tumors analyzed, KEEP
  (clinical_in). EXCLUDE only if germ cell tumors are not part of the analysis at all (clinical_no_gct_analyzed).
- EXCLUDE studies of tumors of NON-HUMAN animals (e.g. a survey of canine testicular tumors) (clinical_animal).
- EXCLUDE a paper on an intracranial disease when neither the title nor the abstract mentions germ cell tumors (clinical_intracranial_no_gct).
- Otherwise KEEP (clinical_in).

If no rule clearly applies, choose KEEP and set confidence to low. Set confidence to high only when a rule clearly applies.
`rule` must be one of the listed rule names; `reason` is one short English sentence naming the deciding fact.
"""

SCHEMA = {
    "type": "object",
    "properties": {"papers": {"type": "array", "items": {
        "type": "object",
        "properties": {"pmid": {"type": "string"}, "decision": {"type": "string", "enum": list(DECISIONS)},
                       "rule": {"type": "string", "enum": list(RULES)}, "confidence": {"type": "string", "enum": list(CONFIDENCE)},
                       "reason": {"type": "string"}},
        "required": ["pmid", "decision", "rule", "confidence", "reason"], "additionalProperties": False}}},
    "required": ["papers"], "additionalProperties": False,
}


def design_of(tags_json):
    tags = json.loads(tags_json or "[]")
    return tags[0] if tags else ""


def candidates(db_dir, status="needs_review", only=None):
    rows = []
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        where = "relevance_status = 'needs_review'" if status == "needs_review" else "1"
        for pmid, title, abstract, tags in conn.execute(f"SELECT pmid, title, abstract, ai_tags FROM papers WHERE {where}"):
            if only is not None and str(pmid) not in only:
                continue
            rows.append({"pmid": str(pmid), "title": title or "", "abstract": (abstract or "")[:2500], "design": design_of(tags)})
        conn.close()
    return rows


def prompt_for(rows):
    payload = [{"pmid": r["pmid"], "design": r["design"], "title": r["title"], "abstract": r["abstract"]} for r in rows]
    return (CRITERIA + "\nReturn exactly one result per pmid. Return only a JSON object that conforms exactly to this JSON Schema; do not use "
            "Markdown fences:\n" + json.dumps(SCHEMA, separators=(",", ":")) + "\n\nINPUT PAPERS:\n" + json.dumps(payload, ensure_ascii=False))


def read_done(path):
    if not path.is_file():
        return {}
    return {i["pmid"]: i for i in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}


def screen(args):
    done = read_done(args.out)
    only = set(args.only_pmids.read_text(encoding="utf-8").split()) if args.only_pmids else None
    todo = [r for r in candidates(args.db_dir, args.status, only) if r["pmid"] not in done]
    if args.limit:
        todo = todo[:max(0, args.limit - len(done))]
    jobs = queue.Queue()
    for i in range(0, len(todo), args.batch_size):
        jobs.put(todo[i:i + args.batch_size])
    print(f"{len(done)} already screened, {len(todo)} to screen in {jobs.qsize()} batches")
    if not args.claude:
        print("(dry run: pass --claude to call the AI)")
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    lock, totals, stop = threading.Lock(), {"batches": 0, "cost": 0.0, "failed": 0, "consecutive": 0}, threading.Event()

    def worker():
        while not stop.is_set():
            try:
                batch = jobs.get_nowait()
            except queue.Empty:
                return
            try:
                result, cost = process_batch.call_claude(prompt_for(batch), args.model, effort=args.effort)
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
                with args.out.open("a", encoding="utf-8") as f:
                    for r in batch:
                        item = result.get(r["pmid"])
                        if isinstance(item, dict) and item.get("decision") in DECISIONS and item.get("rule") in RULES:
                            f.write(json.dumps({**item, "pmid": r["pmid"], "design": r["design"]}, ensure_ascii=False) + "\n")
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
    items = list(read_done(args.out).values())
    print(f"{len(items)} papers: {dict(collections.Counter(i['decision'] for i in items))}")
    print("rule:", dict(collections.Counter(i["rule"] for i in items).most_common()))
    print("confidence:", dict(collections.Counter(i["confidence"] for i in items)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="screen", choices=["screen", "stats"])
    parser.add_argument("--db-dir", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--status", choices=["needs_review", "any"], default="needs_review")
    parser.add_argument("--only-pmids", type=pathlib.Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--model", default=process_batch.DEFAULT_MODEL)
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--claude", action="store_true")
    args = parser.parse_args()
    if args.command == "screen" and not args.db_dir:
        parser.error("screen needs --db-dir")
    {"screen": screen, "stats": stats}[args.command](args)


if __name__ == "__main__":
    main()
