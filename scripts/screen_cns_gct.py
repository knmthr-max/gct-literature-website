#!/usr/bin/env python3
"""脳・脊髄原発の胚細胞腫瘍(頭蓋内・脊髄内GCT)を、対象外(excluded)にする。

編集方針(2026-10): 中枢神経系に原発する胚細胞腫瘍は、このサイトの対象外。
次の段階で行う(DBは screen では変更しない)。
  screen  キーワードで候補を絞り(kept / needs_review のうち、脳・脊髄に関する語を含む論文)、AIに
          「主題が、脳・脊髄に原発する胚細胞腫瘍か」を1件ずつ判定させる。結果は JSONL に追記(再開可能)
  apply   判定が cns_primary のものを relevance_status='excluded' にする(元の状態は --backup に保存)。
          mixed / uncertain は触らず、一覧に出す。--site-papers で、サイトの該当エントリも
          relevance_status='excluded'(一覧から隠れる)にする。既定はドライラン

    python3 scripts/screen_cns_gct.py screen --db-dir <data>/master --out <data>/processed/scope_screen/cns_gct.jsonl --claude
    python3 scripts/screen_cns_gct.py apply  --db-dir <data>/master --out ... --backup ... [--site-papers data/papers.json] [--apply]
"""
import argparse
import collections
import importlib.util
import json
import pathlib
import queue
import re
import sqlite3
import sys
import threading

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from gct_db import existing_shard_paths  # noqa: E402

spec = importlib.util.spec_from_file_location("process_batch", SCRIPTS_DIR / "process_batch.py")
process_batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(process_batch)

KEYWORDS = re.compile(
    r"intracranial|pineal|suprasellar|sellar|neurohypophys|brain|cerebr|cranial|craniotomy|spinal|intraspinal|"
    r"intramedullary|central nervous|\bcns\b|basal ganglia|hypothalam|thalam|ventric|cerebell|meninge|neurosurg",
    re.I)
VERDICTS = ("cns_primary", "not_cns_primary", "mixed", "uncertain")
NOTE = "対象外: 脳・脊髄原発の胚細胞腫瘍(編集方針 2026-10)"

SCHEMA = {
    "type": "object",
    "properties": {"papers": {"type": "array", "items": {
        "type": "object",
        "properties": {"pmid": {"type": "string"}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                       "reason": {"type": "string"}},
        "required": ["pmid", "verdict", "reason"], "additionalProperties": False}}},
    "required": ["papers"], "additionalProperties": False,
}


def prompt_for(rows):
    payload = [{"pmid": r["pmid"], "title": r["title"] or "", "abstract": (r["abstract"] or "")[:1800]} for r in rows]
    return (
        "For each paper (about germ cell tumors), decide where the tumor that is the paper's main subject ARISES.\n"
        "- cns_primary: the main subject is a germ cell tumor that arises primarily in the central nervous system -- "
        "intracranial (pineal, suprasellar/neurohypophyseal, basal ganglia, thalamus, ventricles, cerebellum, ...) or "
        "intraspinal (e.g. intracranial germinoma, intracranial teratoma, CNS germ cell tumor).\n"
        "- not_cns_primary: the tumor arises elsewhere (testis, ovary, mediastinum, retroperitoneum, sacrococcygeal, "
        "gestational, other extragonadal), even if it metastasizes to the brain, causes neurological complications "
        "(e.g. anti-NMDA receptor encephalitis with an ovarian teratoma), or the paper covers germ cell tumors of all "
        "sites in general with CNS tumors only a minor part.\n"
        "- mixed: CNS germ cell tumors and non-CNS germ cell tumors are BOTH a substantial subject of the paper.\n"
        "- uncertain: the text does not allow a decision.\n"
        "reason: one short sentence in English. Return exactly one result per pmid. Return only a JSON object that "
        "conforms exactly to this JSON Schema; do not use Markdown fences:\n"
        + json.dumps(SCHEMA, separators=(",", ":")) + "\n\nINPUT PAPERS:\n" + json.dumps(payload, ensure_ascii=False))


def candidates(db_dir):
    rows = []
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT pmid, title, abstract FROM papers WHERE relevance_status IN ('kept', 'needs_review')"):
            if KEYWORDS.search(f"{r['title'] or ''} {r['abstract'] or ''}"):
                rows.append(dict(r))
        conn.close()
    return rows


def read_verdicts(path):
    verdicts = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                verdicts[item["pmid"]] = item
    return verdicts


def screen(args):
    done = read_verdicts(args.out)
    todo = [r for r in candidates(args.db_dir) if r["pmid"] not in done]
    jobs = queue.Queue()
    for i in range(0, len(todo), args.batch_size):
        jobs.put(todo[i:i + args.batch_size])
    print(f"{len(done)} already judged, {len(todo)} to judge in {jobs.qsize()} batches")
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
                result, cost = process_batch.call_claude(prompt_for(batch), args.model)
            except Exception as error:  # noqa: BLE001 - the batch stays undone for the next run
                with lock:
                    totals["failed"] += 1
                    print(f"batch failed: {str(error)[:160]}", file=sys.stderr)
                continue
            with lock:
                with args.out.open("a", encoding="utf-8") as f:
                    for r in batch:
                        item = result.get(r["pmid"])
                        if item and item.get("verdict") in VERDICTS:
                            f.write(json.dumps({"pmid": r["pmid"], "verdict": item["verdict"],
                                                "reason": item.get("reason", "")}, ensure_ascii=False) + "\n")
                totals["batches"] += 1
                totals["cost"] += cost
                print(f"batch {totals['batches']} done, ${totals['cost']:.2f}", flush=True)

    threads = [threading.Thread(target=worker) for _ in range(args.workers)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print(json.dumps({**totals, "cost": round(totals["cost"], 3)}))


def apply(args):
    verdicts = read_verdicts(args.out)
    counts = collections.Counter(v["verdict"] for v in verdicts.values())
    targets = {pmid for pmid, v in verdicts.items() if v["verdict"] == "cns_primary"}
    print(f"verdicts: {dict(counts)}")
    changes = []
    for path in existing_shard_paths(args.db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for pmid, status, note, published in conn.execute(
                "SELECT pmid, relevance_status, relevance_note, published_to_site FROM papers "
                "WHERE relevance_status IN ('kept', 'needs_review')"):
            if str(pmid) in targets:
                changes.append((path, str(pmid), status, note, published))
        conn.close()
    published = [c for c in changes if c[4]]
    print(f"DB rows to exclude: {len(changes)} (of which published on the site: {len(published)})")
    papers = site_hits = None
    if args.site_papers:
        papers = json.loads(args.site_papers.read_text(encoding="utf-8"))
        site_hits = [e for e in papers if str(e.get("pmid") or "") in targets and e.get("relevance_status") != "excluded"]
        print(f"site entries to hide: {len(site_hits)}")
    for kind in ("mixed", "uncertain"):
        ids = [pmid for pmid, v in verdicts.items() if v["verdict"] == kind]
        print(f"{kind}: {len(ids)} (left as they are; for human review)")
    if not args.apply:
        print("(dry run: nothing written; pass --apply)")
        return
    if args.backup:
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        with args.backup.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps({"pmid": pmid, "old_status": status, "old_note": note}, ensure_ascii=False) + "\n"
                         for _, pmid, status, note, _ in changes)
    by_shard = collections.defaultdict(list)
    for path, pmid, status, note, _ in changes:
        by_shard[path].append(pmid)
    for path, pmids in by_shard.items():
        conn = sqlite3.connect(path)
        conn.executemany("UPDATE papers SET relevance_status = 'excluded', relevance_note = ?, "
                         "relevance_reviewed_at = datetime('now') WHERE pmid = ?", [(NOTE, p) for p in pmids])
        conn.commit()
        conn.close()
    if papers is not None and site_hits:
        for entry in site_hits:
            entry["relevance_status"] = "excluded"
            entry["relevance_note"] = NOTE
        args.site_papers.write_text(json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("applied")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["screen", "apply"])
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True, help="verdicts JSONL")
    parser.add_argument("--claude", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--backup", type=pathlib.Path)
    parser.add_argument("--site-papers", type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    {"screen": screen, "apply": apply}[args.command](args)


if __name__ == "__main__":
    main()
