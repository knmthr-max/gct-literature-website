#!/usr/bin/env python3
"""DBの分類タグ(ai_tags)を、現在の分類ルールと個別の上書き表から再計算する。

分類ルールは scripts/import_medline.py の CATEGORY_RULES(PubMedの文献種別 PT による固定7分類)。
PubMedの PT が実態と合わない文献は、上書き表 data/reference/classification/tag_overrides.tsv
(pmid, tag, reason)で個別に直す。上書き表は、ルールより優先する。

  - 既定はドライラン(--apply なしでは何も書かない)
  - --backup に、変更したDB行の元のタグを JSONL で保存する(元に戻せる)
  - --site-papers を付けると、公開サイトの papers.json の tags も更新する。サイトのタグが「DBの元のタグ」と
    同じ場合だけ更新し、違う(手動で直した)ものは触らずに一覧に出す

    python3 scripts/retag_categories.py --db-dir <data>/master --overrides <data>/reference/classification/tag_overrides.tsv \
        --site-papers data/papers.json --backup <data>/processed/classification/retag_backup.jsonl [--apply]
"""
import argparse
import collections
import csv
import json
import pathlib
import sqlite3
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from gct_db import existing_shard_paths  # noqa: E402
from import_medline import classify  # noqa: E402

CATEGORIES = {"症例報告", "臨床研究", "基礎研究", "総説", "ガイドライン", "論説", "レター"}


def read_overrides(path):
    """pmid -> tag (an empty tag means 'no category')."""
    overrides = {}
    if path and path.is_file():
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                pmid, tag = (row.get("pmid") or "").strip(), (row.get("tag") or "").strip()
                if not pmid or pmid.startswith("#"):
                    continue
                if tag and tag not in CATEGORIES:
                    raise SystemExit(f"tag_overrides: pmid {pmid} has an unknown tag {tag!r}")
                overrides[pmid] = tag
    return overrides


def wanted_tags(publication_types, pmid, overrides):
    if pmid in overrides:
        return [overrides[pmid]] if overrides[pmid] else []
    tag = classify(publication_types)
    return [tag] if tag else []


def plan_db(db_dir, overrides):
    """[(shard path, pmid, old tags, new tags)] for processed rows whose tag differs from the rules."""
    changes = []
    for path in existing_shard_paths(db_dir):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for pmid, pt, tags in conn.execute(
                "SELECT pmid, publication_types, ai_tags FROM papers WHERE ai_tags IS NOT NULL"):
            old = json.loads(tags or "[]")
            new = wanted_tags(json.loads(pt or "[]"), str(pmid), overrides)
            if old != new:
                changes.append((path, str(pmid), old, new))
        conn.close()
    return changes


def apply_db(changes, backup):
    by_shard = collections.defaultdict(list)
    for path, pmid, old, new in changes:
        by_shard[path].append((pmid, old, new))
    if backup:
        backup.parent.mkdir(parents=True, exist_ok=True)
        with backup.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps({"pmid": pmid, "old": old, "new": new}, ensure_ascii=False) + "\n"
                         for items in by_shard.values() for pmid, old, new in items)
    for path, items in by_shard.items():
        conn = sqlite3.connect(path)
        conn.executemany("UPDATE papers SET ai_tags = ? WHERE pmid = ?",
                         [(json.dumps(new, ensure_ascii=False), pmid) for pmid, _, new in items])
        conn.commit()
        conn.close()


def plan_site(papers, changes):
    """(updates [(entry, new tags)], left alone [pmid]) for the site entries of the changed papers."""
    by_pmid = {pmid: (old, new) for _, pmid, old, new in changes}
    updates, manual = [], []
    for entry in papers:
        pmid = str(entry.get("pmid") or "")
        if pmid not in by_pmid:
            continue
        old, new = by_pmid[pmid]
        if (entry.get("tags") or []) == old:
            updates.append((entry, new))
        elif (entry.get("tags") or []) != new:
            manual.append(pmid)
    return updates, manual


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--overrides", type=pathlib.Path)
    parser.add_argument("--site-papers", type=pathlib.Path)
    parser.add_argument("--backup", type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    overrides = read_overrides(args.overrides)
    changes = plan_db(args.db_dir, overrides)
    kinds = collections.Counter((tuple(old), tuple(new)) for _, _, old, new in changes)
    print(f"overrides: {len(overrides)} | DB rows to retag: {len(changes)}")
    for (old, new), n in kinds.most_common():
        print(f"  {n:5d}  {list(old) or '(none)'} -> {list(new) or '(none)'}")
    site_updates, site_manual = [], []
    papers = None
    if args.site_papers:
        papers = json.loads(args.site_papers.read_text(encoding="utf-8"))
        site_updates, site_manual = plan_site(papers, changes)
        print(f"site: {len(site_updates)} entries to update, {len(site_manual)} left alone (tags edited by hand)")
    if not args.apply:
        print("(dry run: nothing written; pass --apply)")
        return
    apply_db(changes, args.backup)
    if papers is not None and site_updates:
        for entry, new in site_updates:
            entry["tags"] = new
        args.site_papers.write_text(json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("applied")


if __name__ == "__main__":
    main()
