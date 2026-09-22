from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_cleaner():
    path = PROGRAMS / "pubmed_cleaner" / "pubmed_cleaner.py"
    spec = importlib.util.spec_from_file_location("maintained_pubmed_cleaner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PubMedCleanerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cleaner = load_cleaner()

    def test_pmid_starts_record_without_blank_separator(self):
        lines = (FIXTURES / "pubmed_sample.txt").read_text(encoding="utf-8").splitlines()
        records = self.cleaner.parse_records(lines)
        self.assertEqual([record["PMID"][0] for record in records], ["11111111", "22222222"])
        self.assertEqual(records[0]["TI"], ["First title with continuation"])

    def test_repeated_mesh_and_author_keywords_are_preserved(self):
        rows = self.cleaner.read_pubmed(FIXTURES / "pubmed_sample.txt")
        self.assertEqual(json.loads(rows[0]["mesh_terms"]), ["Germ Cell Tumor", "Humans"])
        self.assertEqual(json.loads(rows[0]["author_keywords"]), ["biomarker", "microRNA"])
        self.assertEqual(json.loads(rows[0]["publication_types"]), ["Journal Article", "Clinical Trial"])

    def test_identifiers_and_dates_are_extracted(self):
        first = self.cleaner.read_pubmed(FIXTURES / "pubmed_sample.txt")[0]
        self.assertEqual(first["publication_year"], "2026")
        self.assertEqual(first["issn"], "1234-5678")
        self.assertEqual(first["eissn"], "8765-4321")
        self.assertEqual(first["doi"], "10.1000/example.1")

    def test_clean_pubmed_writes_expanded_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "nested" / "cleaned.tsv"
            count = self.cleaner.clean_pubmed(FIXTURES / "pubmed_sample.txt", output)
            with output.open(encoding="utf-8", newline="") as source:
                rows = list(csv.reader(source, delimiter="\t"))
        self.assertEqual(count, 2)
        self.assertEqual(tuple(rows[0]), self.cleaner.HEADER)
        self.assertTrue(all(len(row) == len(self.cleaner.HEADER) for row in rows))

    def test_missing_input_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                self.cleaner.read_pubmed(Path(temp_dir) / "missing.txt")


if __name__ == "__main__":
    unittest.main()
