#!/usr/bin/env python3
"""人が決めた採否(掲載 / 除外 / CNS-GCT)を、needs_review の論文に反映する。

PMIDを1行(または空白区切り)で書いたファイルを渡す。反映するのは、いま relevance_status が needs_review の論文だけ
(ほかの状態の論文は触らず、一覧に出す。たとえば CNS-GCT として除外済みの論文を、誤って掲載に戻さないため)。
  --kept      → relevance_status = 'kept'
  --excluded  → 'excluded'
  --cns       → 'excluded' + ai_relevance = 'cns_gct' + relevance_note = CNS の決まった文言(CNS-GCT として除外。データは残る)
relevance_note には、元のAIの理由を残し、先頭に「人の判断(日付)」を付ける。元の値は --backup に JSONL で保存する。
公開済みの論文(published_to_site=1)が対象に含まれる場合は、件数を出す(サイトからの非表示は別の手順)。
既定はドライラン(--apply なしでは何も書かない)。

    python3 scripts/apply_status_decisions.py --db-dir <data>/master --kept kept.txt --excluded excluded.txt --cns cns.txt \
        --backup <data>/processed/relevance_review/status_backup_<日付>.jsonl [--apply]
"""
import argparse
import collections
import datetime
import importlib.util
import json
import pathlib
import sqlite3
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from gct_db import existing_shard_paths  # noqa: E402

spec = importlib.util.spec_from_file_location("process_batch", SCRIPTS_DIR / "process_batch.py")
process_batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(process_batch)


def read_ids(path):
    return set(path.read_text(encoding="utf-8").split()) if path else set()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--kept", type=pathlib.Path)
    parser.add_argument("--excluded", type=pathlib.Path)
    parser.add_argument("--cns", type=pathlib.Path)
    parser.add_argument("--backup", type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    today = datetime.date.today().isoformat()
    wanted = {}
    for kind, path in (("kept", args.kept), ("excluded", args.excluded), ("cns", args.cns)):
        for pmid in read_ids(path):
            if pmid in wanted and wanted[pmid] != kind:
                raise SystemExit(f"{pmid} is in two decision files ({wanted[pmid]} and {kind})")
            wanted[pmid] = kind
    changes, skipped, seen = [], [], set()
    for path in existing_shard_paths(args.db_dir):
        conn = sqlite3.connect(path)
        for pmid, status, note, ai_rel, published in conn.execute(
                "SELECT pmid, relevance_status, relevance_note, ai_relevance, published_to_site FROM papers"):
            pmid = str(pmid)
            if pmid not in wanted:
                continue
            seen.add(pmid)
            if status != "needs_review":
                skipped.append((pmid, status, wanted[pmid]))
                continue
            changes.append((path, pmid, wanted[pmid], note, ai_rel, published))
        conn.close()
    missing = sorted(set(wanted) - seen)
    print("to apply:", dict(collections.Counter(c[2] for c in changes)), "| published among them:", sum(1 for c in changes if c[5]))
    print(f"skipped (not needs_review): {len(skipped)}", *[f"\n  {p} is {s} (decision: {d})" for p, s, d in skipped])
    print(f"not found in the DB: {len(missing)}", *missing)
    if not args.apply:
        print("(dry run: nothing written; pass --apply)")
        return
    if args.backup:
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        with args.backup.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps({"pmid": p, "old_status": "needs_review", "old_note": n, "old_ai_relevance": a,
                                     "decision": d, "date": today}, ensure_ascii=False) + "\n"
                         for _, p, d, n, a, _ in changes)
    by_shard = collections.defaultdict(list)
    for item in changes:
        by_shard[item[0]].append(item)
    for path, items in by_shard.items():
        conn = sqlite3.connect(path)
        for _, pmid, kind, note, _, _ in items:
            if kind == "cns":
                conn.execute("UPDATE papers SET relevance_status='excluded', ai_relevance='cns_gct', relevance_note=?, "
                             "relevance_reviewed_at=datetime('now') WHERE pmid=?", (process_batch.CNS_NOTE, pmid))
                continue
            label = "掲載" if kind == "kept" else "除外"
            conn.execute("UPDATE papers SET relevance_status=?, relevance_note=?, relevance_reviewed_at=datetime('now') "
                         "WHERE pmid=?", (kind, f"人の判断({today}): {label}。{note or ''}".strip(), pmid))
        conn.commit()
        conn.close()
    print("applied")


if __name__ == "__main__":
    main()
