#!/usr/bin/env python3
"""raw/ に置かれた未処理のJCR CSVだけを、年別のJIF参照TSVに変換して追加する。

  data/reference/jif/raw/*.csv      JCRから取得した未改変のCSV(アップロードするだけ。上書き禁止)
  data/reference/jif/*_v*.tsv       生成された年別の参照TSV(以後、JIF遡及が自動で使う)
  data/reference/jif/processed_raw.tsv   どのCSVをいつ変換したかの台帳(sha256で識別)

jif_reference_cleaner.py は実行のたびにフォルダ内の全CSVを新バージョンで再変換するため、
そのまま繰り返すと同じ年のTSVが重複する。このスクリプトは台帳に無いCSVだけを渡すので、
何度実行しても、追加したCSV分だけが増える。

  - 既に台帳にあるCSV(内容が同じ)は「処理済み」としてスキップ(別名で再アップロードしても検知)
  - 台帳にある名前で内容が変わっているCSVはエラー(rawは上書き禁止。別名でアップロードすること)
  - 既定はドライラン(--apply なしでは何も書かない。CSVの検証と、追加される件数だけ表示)
  - 生成したTSV群が JIFMatcher で読めることを確認してから台帳を更新する

    python3 scripts/jif_reference_add.py --reference-dir /path/to/gct-literature-data/data/reference/jif
    python3 scripts/jif_reference_add.py --reference-dir ... --apply
"""
import argparse
import csv
import hashlib
import pathlib
import re
import subprocess
import sys
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


def default_license_note(reference_dir):
    from gct_db import jif_reference_files
    for path in reversed(jif_reference_files(reference_dir)):
        with path.open(encoding="utf-8", newline="") as f:
            row = next(csv.DictReader(f, delimiter="\t"), None)
        if row and row.get("license_note"):
            return row["license_note"]
    return ""


def run(args):
    reference_dir = args.reference_dir
    new, done, modified = classify_raw(reference_dir)
    report = [f"raw CSV: 新規 {len(new)} / 処理済み {len(done)} / 内容が変わっている {len(modified)}"]
    if modified:
        return 2, report + [
            "エラー: 処理済みのCSVと同名で内容が違います(rawは上書き禁止): "
            + ", ".join(p.name for p in modified) + " → 別名でアップロードしてください"]
    if not new:
        return 0, report + ["新しいCSVはありません。何もしません。"]

    command = [sys.executable, str(CLEANER), "--output-dir", str(reference_dir)]
    for path, _ in new:
        command += ["--input", str(path)]
    for flag, value in (("--reference-version", args.reference_version),
                        ("--jcr-release-year", args.jcr_release_year),
                        ("--license-note", args.license_note or default_license_note(reference_dir))):
        if value:
            command += [flag, value]
    if not args.apply:
        command.append("--dry-run")
    result = subprocess.run(command, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    report += ["", "新規CSV: " + ", ".join(p.name for p, _ in new), "", "--- jif_reference_cleaner.py ---", output]
    if result.returncode:
        return result.returncode, report
    if not args.apply:
        return 0, report + ["", "(ドライラン: 何も書き込んでいません。反映するには apply をオン)"]

    outputs = [pathlib.Path(m.group(1)).name
               for m in re.finditer(r"^\s+wrote: (.+)$", result.stdout, re.M)]
    version = re.search(r"^Reference version: (.+)$", result.stdout, re.M).group(1).strip()
    from gct_db import jif_reference_files
    from pipeline import JIFMatcher
    JIFMatcher(jif_reference_files(reference_dir))  # must still load after adding; else abort before the ledger

    ledger_path = reference_dir / LEDGER_NAME
    write_header = not ledger_path.is_file()
    with ledger_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        if write_header:
            writer.writerow(LEDGER_HEADER)
        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for path, digest in new:
            writer.writerow((path.name, digest, version, ";".join(outputs), stamp))
    return 0, report + ["", f"台帳を更新しました: {LEDGER_NAME}", "次に Actions「2 JIF遡及」を実行してください(まず反映オフで効果を確認)。"]


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
