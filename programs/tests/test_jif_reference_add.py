from __future__ import annotations

import argparse
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def csv_for(year: str, rows: str) -> str:
    return (f'"Journal Data Filtered By: Selected JCR Year: {year}"\n\n'
            f"Journal name,JCR Abbreviation,ISSN,eISSN,{year} JIF\n{rows}")


class JifReferenceAddTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.add = load("jif_reference_add")
        cls.gct_db = load("gct_db")

    def args(self, reference_dir, **kw):
        values = dict(reference_dir=reference_dir, apply=True, reference_version="",
                      jcr_release_year="2026", license_note="internal only")
        values.update(kw)
        return argparse.Namespace(**values)

    def put(self, reference_dir: Path, name: str, year: str, rows: str):
        raw = reference_dir / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / name).write_text(csv_for(year, rows), encoding="utf-8")

    def add_cleaner_header(self):
        import sys
        sys.path.insert(0, str(SCRIPTS.parent / "programs" / "literature_pipeline"))
        from jif_reference_cleaner import REFERENCE_HEADER
        return REFERENCE_HEADER

    def tsvs(self, reference_dir):
        return sorted(p.name for p in self.gct_db.jif_reference_files(reference_dir))

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            self.put(ref, "a.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3.0\n")
            code, report = self.add.run(self.args(ref, apply=False, reference_version="t1"))
            self.assertEqual(code, 0, report)
            self.assertEqual(self.tsvs(ref), [])
            self.assertFalse((ref / "processed_raw.tsv").exists())

    def test_apply_converts_new_csv_once_and_rerun_is_a_noop(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            self.put(ref, "a.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3.0\n")
            code, _ = self.add.run(self.args(ref, reference_version="t1"))
            self.assertEqual(code, 0)
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2024_vmerged.tsv"])
            code, report = self.add.run(self.args(ref, reference_version="t2"))
            self.assertEqual(code, 0)
            self.assertIn("新しいCSVはありません", "\n".join(report))
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2024_vmerged.tsv"])  # no duplicate year file

    def test_second_upload_only_converts_the_new_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            self.put(ref, "a.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3.0\n")
            self.add.run(self.args(ref, reference_version="t1"))
            self.put(ref, "b.csv", "2023", "Alpha J,ALPHA J,1111-1111,,2.5\n")
            self.assertEqual(self.add.pending_raw(ref), ["b.csv"])
            code, _ = self.add.run(self.args(ref, reference_version="t2"))
            self.assertEqual(code, 0)
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2023_vmerged.tsv", "jcr_jif_reference_2024_vmerged.tsv"])
            self.assertEqual(self.add.pending_raw(ref), [])

    def test_renamed_reupload_is_recognised_and_modified_raw_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            self.put(ref, "a.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3.0\n")
            self.add.run(self.args(ref, reference_version="t1"))
            self.put(ref, "copy.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3.0\n")
            self.assertEqual(self.add.pending_raw(ref), [])
            self.put(ref, "a.csv", "2024", "Alpha J,ALPHA J,1111-1111,,9.9\n")
            code, report = self.add.run(self.args(ref, reference_version="t3"))
            self.assertEqual(code, 2)
            self.assertIn("上書き禁止", "\n".join(report))

    def rows(self, reference_dir, year):
        with (reference_dir / f"jcr_jif_reference_{year}_vmerged.tsv").open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f, delimiter="\t"))

    def test_repeated_runs_with_new_csvs_never_add_files_for_the_same_year(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            self.put(ref, "a.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3.0\n")
            self.add.run(self.args(ref, reference_version="t1"))
            self.put(ref, "b.csv", "2024", "Beta J,BETA J,2222-2222,,1.5\n")
            self.put(ref, "c.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3\n")  # same fact, written differently
            self.add.run(self.args(ref, reference_version="t1"))  # even the same version label is fine now
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2024_vmerged.tsv"])
            self.assertEqual([r["journal_title"] for r in self.rows(ref, "2024")], ["Alpha J", "Beta J"])
            self.assertEqual(self.add.pending_raw(ref), [])

    def test_existing_version_fragments_and_conflict_files_are_merged_and_removed(self):
        header = "\t".join(self.add_cleaner_header())
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)

            def row(title, issn, jif, version):
                return "\t".join((title, "", issn, "", "2025", "2026", jif, "JCR", version, "", "note"))

            for name, jif, version in (("v1", "2", "v1"), ("v1r2", "2.0", "v1r2")):
                (ref / f"jcr_jif_reference_2025_{name}.tsv").write_text(
                    header + "\n" + row("Alpha J", "1111-1111", jif, version) + "\n", encoding="utf-8")
            (ref / "jcr_jif_reference_conflicts_v1r2.tsv").write_text(
                "jif_data_year\tidentity_key\tconflict_reason\tsource_file\tjournal_title\tjournal_abbreviation\tissn\teissn\tjif\n"
                "2025\tissn:22222222\tconflicting_jif_values\tx.csv\tBeta J\t\t2222-2222\t\t2\n"
                "2025\tissn:22222222\tconflicting_jif_values\ty.csv\tBeta J\t\t2222-2222\t\t2.0\n",
                encoding="utf-8")
            code, report = self.add.run(self.args(ref, apply=False))
            self.assertEqual(code, 0, report)
            self.assertEqual(len(list(ref.glob("*.tsv"))), 3)  # dry run touches nothing
            code, report = self.add.run(self.args(ref))
            self.assertEqual(code, 0, report)
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2025_vmerged.tsv"])
            self.assertEqual(sorted(p.name for p in ref.glob("*.tsv")), ["jcr_jif_reference_2025_vmerged.tsv", "processed_raw.tsv"])
            self.assertEqual([r["journal_title"] for r in self.rows(ref, "2025")], ["Alpha J", "Beta J"])
            code, report = self.add.run(self.args(ref))
            self.assertIn("整理済み", "\n".join(report))

    def test_really_different_values_are_left_out_and_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            self.put(ref, "a.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3.0\nBeta J,BETA J,2222-2222,,1.5\n")
            self.add.run(self.args(ref, reference_version="t1"))
            self.put(ref, "b.csv", "2024", "Alpha J,ALPHA J,1111-1111,,9.9\n")
            code, report = self.add.run(self.args(ref, reference_version="t2"))
            self.assertEqual(code, 0, report)
            self.assertEqual([r["journal_title"] for r in self.rows(ref, "2024")], ["Beta J"])
            self.assertTrue((ref / "jcr_jif_reference_conflicts_vmerged.tsv").is_file())
            self.assertNotIn("conflicts", " ".join(self.tsvs(ref)))

    def test_conflicts_file_is_not_treated_as_a_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            (ref / "jcr_jif_reference_conflicts_vx.tsv").write_text("jif_data_year\tjif\n2024\t1\n", encoding="utf-8")
            (ref / "jcr_jif_reference_2024_vx.tsv").write_text("jif_data_year\tjif\n", encoding="utf-8")
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2024_vx.tsv"])


if __name__ == "__main__":
    unittest.main()
