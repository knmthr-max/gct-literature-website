from __future__ import annotations

import argparse
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
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2024_vt1.tsv"])
            code, report = self.add.run(self.args(ref, reference_version="t2"))
            self.assertEqual(code, 0)
            self.assertIn("新しいCSVはありません", "\n".join(report))
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2024_vt1.tsv"])  # no duplicate year file

    def test_second_upload_only_converts_the_new_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            self.put(ref, "a.csv", "2024", "Alpha J,ALPHA J,1111-1111,,3.0\n")
            self.add.run(self.args(ref, reference_version="t1"))
            self.put(ref, "b.csv", "2023", "Alpha J,ALPHA J,1111-1111,,2.5\n")
            self.assertEqual(self.add.pending_raw(ref), ["b.csv"])
            code, _ = self.add.run(self.args(ref, reference_version="t2"))
            self.assertEqual(code, 0)
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2023_vt2.tsv", "jcr_jif_reference_2024_vt1.tsv"])
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

    def test_conflicts_file_is_not_treated_as_a_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            ref = Path(temp)
            (ref / "jcr_jif_reference_conflicts_vx.tsv").write_text("jif_data_year\tjif\n2024\t1\n", encoding="utf-8")
            (ref / "jcr_jif_reference_2024_vx.tsv").write_text("jif_data_year\tjif\n", encoding="utf-8")
            self.assertEqual(self.tsvs(ref), ["jcr_jif_reference_2024_vx.tsv"])


if __name__ == "__main__":
    unittest.main()
