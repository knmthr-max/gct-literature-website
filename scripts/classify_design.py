#!/usr/bin/env python3
"""既存の論文に、研究デザイン(9分類。scripts/study_design.py)をAIで判定する。DBは変更しない。

対象: 関連性が kept / needs_review で、PubMed の出版タイプだけでは確実に決まらない論文
(症例報告・総説の出版タイプが付いたものと、出版タイプで決まらない原著論文)。結果は JSONL に追記(再開可能)。
判定結果をDBのタグに反映するのは scripts/retag_categories.py(--ai-results)。

    python3 scripts/classify_design.py --db-dir <data>/master --out <data>/processed/classification/design_ai.jsonl --claude
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
import study_design  # noqa: E402

spec = importlib.util.spec_from_file_location("process_batch", SCRIPTS_DIR / "process_batch.py")
process_batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(process_batch)

CONFIDENCE = ("high", "medium", "low")
SCHEMA = {
    "type": "object",
    "properties": {"papers": {"type": "array", "items": {
        "type": "object",
        "properties": {"pmid": {"type": "string"}, "study_design": {"type": "string", "enum": study_design.DESIGN_ENUM},
                       "n_patients": {"type": ["integer", "null"]},
                       "confidence": {"type": "string", "enum": list(CONFIDENCE)}, "reason": {"type": "string"}},
        "required": ["pmid", "study_design", "n_patients", "confidence", "reason"], "additionalProperties": False}}},
    "required": ["papers"], "additionalProperties": False,
}


def candidates(db_dir):
    rows = []
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT pmid, title, abstract, publication_types FROM papers "
                              "WHERE relevance_status IN ('kept', 'needs_review')"):
            types = json.loads(r["publication_types"] or "[]")
            if study_design.design_from_pubtypes(types) in study_design.TRUSTED:
                continue
            rows.append({"pmid": str(r["pmid"]), "title": r["title"] or "", "abstract": r["abstract"] or "",
                         "types": [t for t in types if not t.startswith("Research Support")]})
        conn.close()
    return rows


def prompt_for(rows):
    payload = [{"pmid": r["pmid"], "title": r["title"], "abstract": r["abstract"][:1800],
                "pubmed_publication_types": r["types"]} for r in rows]
    return (
        "Each paper below is about germ cell tumors. " + study_design.DESIGN_NOTE +
        " n_patients: the number of patients/subjects studied if stated (integer), else null. confidence: high, "
        "medium or low. reason: one short English sentence. Return exactly one result per pmid. Return only a JSON "
        "object that conforms exactly to this JSON Schema; do not use Markdown fences:\n"
        + json.dumps(SCHEMA, separators=(",", ":")) + "\n\nINPUT PAPERS:\n" + json.dumps(payload, ensure_ascii=False))


def read_done(path):
    done = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                done[item["pmid"]] = item
    return done


def run(args):
    for attempt in range(1, args.passes + 1):
        done = read_done(args.out)
        todo = [r for r in candidates(args.db_dir) if r["pmid"] not in done]
        if args.limit:
            todo = todo[:max(0, args.limit - len(done))]
        jobs = queue.Queue()
        for i in range(0, len(todo), args.batch_size):
            jobs.put(todo[i:i + args.batch_size])
        print(f"pass {attempt}: {len(done)} done, {len(todo)} to do in {jobs.qsize()} batches", flush=True)
        if not todo or not args.claude:
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
                except Exception as error:  # noqa: BLE001 - the batch stays undone for the next pass
                    with lock:
                        totals["failed"] += 1
                        print(f"batch failed: {str(error)[:160]}", file=sys.stderr, flush=True)
                    continue
                with lock:
                    with args.out.open("a", encoding="utf-8") as f:
                        for r in batch:
                            item = result.get(r["pmid"])
                            if item and item.get("study_design") in study_design.CATEGORIES:
                                f.write(json.dumps({"pmid": r["pmid"], "design": item["study_design"],
                                                    "n_patients": item.get("n_patients"),
                                                    "confidence": item.get("confidence", ""),
                                                    "reason": item.get("reason", "")}, ensure_ascii=False) + "\n")
                    totals["batches"] += 1
                    totals["cost"] += cost
                    if totals["batches"] % 10 == 0:
                        print(f"  {totals['batches']} batches, ${totals['cost']:.2f}", flush=True)

        threads = [threading.Thread(target=worker) for _ in range(args.workers)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        print(json.dumps({**totals, "cost": round(totals["cost"], 3)}), flush=True)


def stats(args):
    done = read_done(args.out)
    print(f"{len(done)} papers")
    print(dict(collections.Counter(v["design"] for v in done.values()).most_common()))
    print(dict(collections.Counter(v["confidence"] for v in done.values()).most_common()))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--claude", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many papers in total (for a pilot)")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--passes", type=int, default=4, help="Re-run for papers the AI skipped, up to this many passes")
    parser.add_argument("--model", default=process_batch.DEFAULT_MODEL)
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    args = parser.parse_args()
    (stats if args.stats else run)(args)


if __name__ == "__main__":
    main()
