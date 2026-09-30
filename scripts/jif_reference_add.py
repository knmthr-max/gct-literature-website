#!/usr/bin/env python3
"""raw/ に置かれた未処理のJCR CSVを、年別のJIF参照TSV(年ごとに1ファイル)へ統合して追加する。

  data/reference/jif/raw/*.csv                     JCRから取得した未改変のCSV(アップロードするだけ。上書き禁止)
  data/reference/jif/jcr_jif_reference_<年>_vmerged.tsv   年ごとの参照TSV(JIF遡及が自動で使う。実行のたびに増えない)
  data/reference/jif/processed_raw.tsv              どのCSVをいつ変換したかの台帳(sha256で識別)

新しいCSVを変換し、既存のTSVと重複を除いて統合して、年ごとに1ファイルへ書き戻す。
何度実行しても、ファイル数は「JIFデータのある年の数」から増えない。

  - 同じ雑誌・同じ年で値が同じ(2 と 2.0 は同じ)なら1行にまとめる。値が食い違うものは除外して記録する
  - 過去の版付きファイル(_v2026.09.30r3 など)や conflicts ファイルも、実行時に統合して片付ける
  - 統合の前後で内容(雑誌・年・JIF値の集合)が一致すること、JIFMatcher で読めることを確認してから書き換える
  - 既に台帳にあるCSV(内容が同じ)は「処理済み」としてスキップ(別名で再アップロードしても検知)
  - 台帳にある名前で内容が変わっているCSVはエラー(rawは上書き禁止。別名でアップロードすること)
  - 既定はドライラン(--apply なしでは何も書かない。結果の件数だけ表示)

    python3 scripts/jif_reference_add.py --reference-dir /path/to/gct-literature-data/data/reference/jif
    python3 scripts/jif_reference_add.py --reference-dir ... --apply
"""
import argparse
import csv
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
PIPELINE_DIR = ROOT / "programs" / "literature_pipeline"
CLEANER = PIPELINE_DIR / "jif_reference_cleaner.py"
for _path in (SCRIPTS_DIR, PIPELINE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

LEDGER_NAME = "processed_raw.tsv"
LEDGER_HEADER = ("raw_file", "sha256", "reference_version", "output_files", "processed_at")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_ledger(reference_dir):
    path = reference_dir / LEDGER_NAME
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def classify_raw(reference_dir):
    """Split raw/*.csv into (new, done, modified) using the ledger."""
    ledger = read_ledger(reference_dir)
    by_name = {row["raw_file"]: row["sha256"] for row in ledger}
    known_hashes = {row["sha256"] for row in ledger}
    new, done, modified = [], [], []
    for path in sorted((reference_dir / "raw").glob("*.csv")):
        digest = sha256(path)
        if by_name.get(path.name) == digest:
            done.append(path)
        elif path.name in by_name:
            modified.append(path)
        elif digest in known_hashes:
            done.append(path)  # same content re-uploaded under another name
        else:
            new.append((path, digest))
    return new, done, modified


def pending_raw(reference_dir):
    """Names of raw CSVs not yet converted (for the status report)."""
    new, _, modified = classify_raw(reference_dir)
    return [p.name for p, _ in new] + [p.name for p in modified]


MERGED_VERSION = "merged"
DEFAULT_SOURCE = "Clarivate Journal Citation Reports"


def merged_name(year):
    return f"jcr_jif_reference_{year}_v{MERGED_VERSION}.tsv"


def conflicts_merged_name():
    return f"jcr_jif_reference_conflicts_v{MERGED_VERSION}.tsv"


def conflict_files(reference_dir):
    return sorted(reference_dir.glob("jcr_jif_reference_conflicts_v*.tsv"))


def read_tsv(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def default_license_note(reference_dir):
    from gct_db import jif_reference_files
    for path in reversed(jif_reference_files(reference_dir)):
        row = next(iter(read_tsv(path)), None)
        if row and row.get("license_note"):
            return row["license_note"]
    return ""


def write_tsv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def promote_conflict_row(row, filename, license_note):
    """A row the cleaner set aside as 'conflicting' becomes an ordinary candidate again; the merge decides."""
    version = re.search(r"_v(.+)\.tsv$", filename)
    return {
        "journal_title": row.get("journal_title", ""), "journal_abbreviation": row.get("journal_abbreviation", ""),
        "issn": row.get("issn", ""), "eissn": row.get("eissn", ""),
        "jif_data_year": row.get("jif_data_year", ""), "jcr_release_year": "",
        "jif": row.get("jif", ""), "source": DEFAULT_SOURCE,
        "reference_version": version.group(1) if version else "", "retrieved_at": "",
        "license_note": license_note, "source_file": row.get("source_file", ""),
    }


def merge_rows(rows):
    """Collapse candidate rows to one row per (JIF data year, journal identity).

    Rows that state the same value (numerically: "2" == "2.0") are one fact; the newest row's fields win and
    blanks are filled from the others. A journal-year with different values is a real conflict: it is left
    out (as the cleaner does; the matcher would call it ambiguous anyway) and returned for the report.
    """
    from jif_reference_cleaner import identity_key, jif_number
    groups = {}
    for row in rows:
        groups.setdefault((row["jif_data_year"], identity_key(row)), []).append(row)
    newest_first = lambda r: (r.get("jcr_release_year", ""), r.get("reference_version", ""))
    merged, conflicts = [], []
    for (year, key), group in groups.items():
        if len({jif_number(r["jif"]) for r in group}) > 1:
            for r in group:
                conflicts.append({**r, "identity_key": key, "conflict_reason": "conflicting_jif_values"})
            continue
        group = sorted(group, key=newest_first, reverse=True)
        chosen = dict(group[0])
        for field in ("journal_abbreviation", "issn", "eissn", "jcr_release_year", "license_note"):
            if not chosen.get(field):
                chosen[field] = next((r[field] for r in group if r.get(field)), "")
        merged.append(chosen)
    merged.sort(key=lambda r: (r["jif_data_year"], r["journal_title"].casefold(), r["issn"], r["eissn"]))
    return merged, conflicts


def fact_set(rows):
    from jif_reference_cleaner import identity_key, jif_number
    return {(r["jif_data_year"], identity_key(r), jif_number(r["jif"])) for r in rows}


def tidy_needed(reference_dir):
    """True while the folder still holds anything other than the one merged file per year."""
    from gct_db import jif_reference_files
    stray = [p for p in jif_reference_files(reference_dir) if not p.name.endswith(f"_v{MERGED_VERSION}.tsv")]
    return bool(stray or [p for p in conflict_files(reference_dir) if p.name != conflicts_merged_name()])


def run(args):
    from gct_db import jif_reference_files
    from jif_reference_cleaner import REFERENCE_HEADER, CONFLICT_HEADER, identity_key
    from pipeline import JIFMatcher
    reference_dir = args.reference_dir
    new, done, modified = classify_raw(reference_dir)
    report = [f"raw CSV: 新規 {len(new)} / 処理済み {len(done)} / 内容が変わっている {len(modified)}"]
    if modified:
        return 2, report + [
            "エラー: 処理済みのCSVと同名で内容が違います(rawは上書き禁止): "
            + ", ".join(p.name for p in modified) + " → 別名でアップロードしてください"]
    old_files = jif_reference_files(reference_dir)
    old_conflicts = conflict_files(reference_dir)
    tidy = tidy_needed(reference_dir)
    if not new and not tidy:
        return 0, report + ["新しいCSVはありません。参照データは整理済みです。何もしません。"]

    license_note = args.license_note or default_license_note(reference_dir)
    with tempfile.TemporaryDirectory() as temp:
        temp = pathlib.Path(temp)
        candidates, version = [], ""
        for path in old_files:
            candidates += [{**dict.fromkeys(REFERENCE_HEADER, ""), **{k: v or "" for k, v in r.items()}}
                           for r in read_tsv(path)]
        for path in old_conflicts:
            candidates += [promote_conflict_row(r, path.name, license_note) for r in read_tsv(path)]
        if new:
            out = temp / "cleaner"
            command = [sys.executable, str(CLEANER), "--output-dir", str(out)]
            for path, _ in new:
                command += ["--input", str(path)]
            for flag, value in (("--reference-version", args.reference_version),
                                ("--jcr-release-year", args.jcr_release_year), ("--license-note", license_note)):
                if value:
                    command += [flag, value]
            result = subprocess.run(command, capture_output=True, text=True)
            output = (result.stdout + result.stderr).strip()
            report += ["", "新規CSV: " + ", ".join(p.name for p, _ in new), "", "--- jif_reference_cleaner.py ---", output]
            if result.returncode:
                return result.returncode, report
            version = re.search(r"^Reference version: (.+)$", result.stdout, re.M).group(1).strip()
            for path in sorted(out.glob("*.tsv")):
                candidates += [promote_conflict_row(r, path.name, license_note) if "conflict_reason" in r
                               else {**dict.fromkeys(REFERENCE_HEADER, ""), **r} for r in read_tsv(path)]
        try:
            merged, conflicts = merge_rows(candidates)
        except ValueError as error:
            return 2, report + [f"エラー: 参照データの行を識別できません(データは変更していません): {error}"]
        excluded = {(c["jif_data_year"], c["identity_key"]) for c in conflicts}
        expected = {f for f in fact_set(candidates) if (f[0], f[1]) not in excluded}
        if fact_set(merged) != expected:
            return 2, report + ["エラー: 統合の前後で参照データの内容が一致しません(データは変更していません)"]

        staged = temp / "merged"
        staged.mkdir()
        by_year = {}
        for row in merged:
            by_year.setdefault(row["jif_data_year"], []).append(row)
        for year, rows in by_year.items():
            write_tsv(staged / merged_name(year), REFERENCE_HEADER, rows)
        if conflicts:
            write_tsv(staged / conflicts_merged_name(), CONFLICT_HEADER, conflicts)
        JIFMatcher(sorted(staged.glob("jcr_jif_reference_[0-9]*_v*.tsv")))  # must load, else abort with nothing changed

        after = len(by_year) + (1 if conflicts else 0)
        before = len(old_files) + len(old_conflicts)
        report += ["", f"参照データ: {before}ファイル → {after}ファイル(年ごとに1つ、{len(by_year)}年 / {len(merged):,}行)",
                   f"重複を除いた行数: {len(candidates):,} → {len(merged):,}"]
        if conflicts:
            groups = len(excluded)
            report.append(f"JIFの値が食い違う雑誌・年(除外して {conflicts_merged_name()} に記録): {groups}件")
        if not args.apply:
            return 0, report + ["", "(ドライラン: 何も書き込んでいません。反映するには apply をオン)"]

        for path in staged.iterdir():           # new files first, so a crash never leaves the folder short of data
            shutil.copyfile(path, reference_dir / path.name)
        keep = {path.name for path in staged.iterdir()}
        for path in [*old_files, *old_conflicts]:
            if path.name not in keep:
                path.unlink()
        if not conflicts and (reference_dir / conflicts_merged_name()).exists():
            (reference_dir / conflicts_merged_name()).unlink()

    ledger = [{**row, "output_files": "merged"} for row in read_ledger(reference_dir)]
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ledger += [{"raw_file": p.name, "sha256": digest, "reference_version": version, "output_files": "merged",
                "processed_at": stamp} for p, digest in new]
    write_tsv(reference_dir / LEDGER_NAME, LEDGER_HEADER, ledger)
    return 0, report + ["", f"反映しました。台帳を更新: {LEDGER_NAME}",
                        "次に Actions「2 JIF遡及」を実行してください(まず反映オフで効果を確認)。"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference-dir", type=pathlib.Path, required=True,
                        help="データリポジトリの data/reference/jif")
    parser.add_argument("--apply", action="store_true", help="実際に書き込む(省略時はドライラン)")
    parser.add_argument("--reference-version", default="", help="省略時は今日の日付 YYYY.MM.DD")
    parser.add_argument("--jcr-release-year", default="", help="省略時はCSV内の著作権表記から推定")
    parser.add_argument("--license-note", default="", help="省略時は既存の参照TSVと同じ文言")
    args = parser.parse_args()
    code, report = run(args)
    print("\n".join(report))
    sys.exit(code)


if __name__ == "__main__":
    main()
