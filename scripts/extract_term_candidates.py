#!/usr/bin/env python3
"""Build a candidate terminology table from the translations that already exist in the DB.

  extract    ask the AI (haiku) to list the medical terms in each English text together with the Japanese rendering
             the existing translation actually used. Resume-safe: results are appended to <out>/raw_<mode>.jsonl and
             papers already there are skipped.
  aggregate  group the raw terms by English term, count the Japanese renderings, compare with the glossary, and write
             <out>/candidates_<mode>.tsv (+ a short Markdown summary for human review).

    python3 scripts/extract_term_candidates.py extract   --db-dir <data>/master --out <data>/processed/terminology --mode titles
    python3 scripts/extract_term_candidates.py aggregate --db-dir <data>/master --out <data>/processed/terminology --mode titles

Nothing here changes the DB or the glossary: a human decides which renderings become the standard.
"""
import argparse
import collections
import csv
import hashlib
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

SCHEMA = {
    "type": "object",
    "properties": {"papers": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "pmid": {"type": "string"},
            "terms": {"type": "array", "items": {
                "type": "object",
                "properties": {"en": {"type": "string"}, "ja": {"type": "string"}},
                "required": ["en", "ja"], "additionalProperties": False}},
        },
        "required": ["pmid", "terms"], "additionalProperties": False}}},
    "required": ["papers"], "additionalProperties": False,
}


def rows_for(db_dir, mode):
    """(pmid, english, japanese) for kept papers that have the translation for this mode."""
    field_ja = "ai_title_ja" if mode == "titles" else "ai_abstract_ja"
    field_en = "title" if mode == "titles" else "abstract"
    out = []
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for pmid, en, ja in conn.execute(
                f"SELECT pmid, {field_en}, {field_ja} FROM papers WHERE relevance_status = 'kept' "
                f"AND {field_ja} IS NOT NULL AND {field_ja} != '' AND {field_en} IS NOT NULL AND {field_en} != ''"):
            if ja == process_batch.NO_ABSTRACT_JA:
                continue
            out.append((str(pmid), en, ja))
        conn.close()
    out.sort(key=lambda r: hashlib.sha256(r[0].encode()).hexdigest())  # deterministic, unbiased order
    return out


def prompt_for(batch, mode):
    payload = [{"pmid": pmid, "english": en, "japanese": ja} for pmid, en, ja in batch]
    return (
        "Each item below is an English " + ("title" if mode == "titles" else "abstract") + " of a germ cell tumor "
        "paper with its existing Japanese translation. For each paper, list the medical/scientific TERMS that appear "
        "in the English text (disease and tumor names, anatomy, procedures and operations, drugs and regimens, "
        "genes/markers/biomolecules, tests and imaging, study types, staging/risk terms), each with the Japanese "
        "rendering that the existing translation ACTUALLY used for it. en: the term in lowercase dictionary form "
        "(keep acronyms and proper nouns as written, e.g. 'BEP', 'SALL4', 'Klinefelter syndrome'); ja: the exact "
        "Japanese wording from the translation (copy it; do not improve or standardize it). Skip generic words and "
        "terms you cannot find in the translation. One entry per distinct term per paper. Return only a JSON object "
        "that conforms exactly to this JSON Schema; do not use Markdown fences:\n"
        + json.dumps(SCHEMA, ensure_ascii=False, separators=(",", ":"))
        + "\n\nINPUT:\n" + json.dumps(payload, ensure_ascii=False))


def extract(args):
    raw_path = args.out / f"raw_{args.mode}.jsonl"
    args.out.mkdir(parents=True, exist_ok=True)
    done = set()
    if raw_path.is_file():
        done = {json.loads(line)["pmid"] for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = [r for r in rows_for(args.db_dir, args.mode) if r[0] not in done]
    if args.limit:
        rows = rows[:args.limit]
    batches = queue.Queue()
    for i in range(0, len(rows), args.batch_size):
        batches.put(rows[i:i + args.batch_size])
    print(f"{len(done)} papers already extracted, {len(rows)} to do in {batches.qsize()} batches")
    if not args.claude:
        print("(dry run: pass --claude to call the AI)")
        return
    lock = threading.Lock()
    totals = {"batches": 0, "cost": 0.0, "failed": 0}

    def worker():
        while True:
            try:
                batch = batches.get_nowait()
            except queue.Empty:
                return
            try:
                result, cost = process_batch.call_claude(prompt_for(batch, args.mode), args.model)
            except Exception as error:  # noqa: BLE001 - keep going; the batch stays "not done" for the next run
                with lock:
                    totals["failed"] += 1
                    print(f"batch failed: {str(error)[:200]}", file=sys.stderr)
                continue
            with lock:
                with raw_path.open("a", encoding="utf-8") as f:
                    for pmid, _, _ in batch:
                        item = result.get(pmid)
                        if item is not None:
                            f.write(json.dumps({"pmid": pmid, "terms": item.get("terms", [])}, ensure_ascii=False) + "\n")
                totals["batches"] += 1
                totals["cost"] += cost
                print(f"batch {totals['batches']} done, ${totals['cost']:.2f} so far", flush=True)

    threads = [threading.Thread(target=worker) for _ in range(args.workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print(json.dumps({**totals, "cost": round(totals["cost"], 3)}))


def read_glossary(path):
    """{lowercase english -> (japanese main, [alt japanese])} from the markdown tables."""
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$", line)
        if not m or m.group(1) in ("英語",) or set(m.group(1)) <= set("-| "):
            continue
        en, ja = m.groups()
        ja_main = re.sub(r"\(.*?\)", "", ja).strip()
        ja_alt = re.findall(r"\((.+?)\)", ja)
        names = [re.sub(r"\([^)]*\)", "", e).strip().lower() for e in re.split(r"\s*/\s*", en)]
        names += [a.lower() for a in re.findall(r"\(([A-Za-z0-9/\-]{2,})\)", en)]
        for name in names:
            if name:
                entries[name] = (ja_main, ja_alt)
    return entries


def norm_ja(text):
    return re.sub(r"\s+", "", text or "").strip("、。,. ")


def aggregate(args):
    modes = ["titles", "abstracts"] if args.mode == "all" else [args.mode]
    glossary = read_glossary(args.glossary)
    by_term = collections.defaultdict(lambda: collections.defaultdict(set))  # en -> ja -> {pmid}
    papers = 0
    for mode in modes:
        raw_path = args.out / f"raw_{mode}.jsonl"
        if not raw_path.is_file():
            continue
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            papers += 1
            for term in item["terms"]:
                en, ja = (term.get("en") or "").strip().lower(), norm_ja(term.get("ja"))
                if len(en) >= 3 and ja:
                    by_term[en][ja].add(item["pmid"])
    rows = []
    for en, variants in by_term.items():
        counts = collections.Counter({ja: len(p) for ja, p in variants.items()})
        n = len({pmid for p in variants.values() for pmid in p})
        top, top_n = counts.most_common(1)[0]
        in_glossary = en in glossary
        standard = glossary[en][0] if in_glossary else ""
        standard_ok = [standard] + glossary[en][1] if in_glossary else []
        off_standard = sum(c for ja, c in counts.items() if in_glossary and not any(s and s in ja for s in standard_ok))
        status = ("glossary-drift" if in_glossary and off_standard else "glossary-ok" if in_glossary
                  else "variants" if len(counts) > 1 and sorted(counts.values())[-2] >= max(2, 0.15 * n)
                  else "new")
        rows.append({"status": status, "en": en, "papers": n, "proposed_ja": standard or top,
                     "variants": " | ".join(f"{ja} ×{c}" for ja, c in counts.most_common(6)),
                     "glossary_ja": standard, "decision": ""})
    rank = {"variants": 0, "glossary-drift": 1, "new": 2, "glossary-ok": 3}
    rows.sort(key=lambda r: (rank[r["status"]], -r["papers"], r["en"]))
    tsv = args.out / f"candidates_{args.mode}.tsv"
    with tsv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    counts = collections.Counter(r["status"] for r in rows)
    print(f"{papers} papers, {len(rows)} terms: {dict(counts)} -> {tsv}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["extract", "aggregate"])
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--mode", choices=["titles", "abstracts", "all"], default="titles", help="all: aggregate only")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="Only the first N not-yet-extracted papers")
    parser.add_argument("--model", default="claude-haiku-4-5")
    parser.add_argument("--claude", action="store_true", help="Actually call the AI (extract only)")
    parser.add_argument("--glossary", type=pathlib.Path, help="aggregate: default <db-dir>/../reference/terminology/terminology_ja.md")
    args = parser.parse_args()
    args.batch_size = args.batch_size or (30 if args.mode == "titles" else 4)
    args.glossary = args.glossary or process_batch.default_glossary_path(args.db_dir)
    {"extract": extract, "aggregate": aggregate}[args.command](args)


if __name__ == "__main__":
    main()
