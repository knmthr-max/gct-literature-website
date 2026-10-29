from __future__ import annotations

import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def load(name: str):
    path = PROGRAMS / "literature_pipeline" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"maintained_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class JifMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jif = load("jif_matcher")
        cls.jif_cleaner = load("jif_reference_cleaner")

    def test_jcr_cleaner_collapses_category_duplicates_and_skips_footer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "jcr.csv"
            source.write_text(
                '"Journal Data Filtered By: Selected JCR Year: 2024"\n\n'
                'Journal name,JCR Abbreviation,Publisher,ISSN,eISSN,Category,2024 JIF\n'
                'Example Journal,EX J,Publisher,1234-5678,8765-4321,ONCOLOGY,4.2\n'
                'Example Journal,EX J,Publisher,1234-5678,8765-4321,MEDICINE,4.2\n'
                'Second Journal,SECOND J,Publisher,1111-2222,,ONCOLOGY,1.5\n'
                'By exporting the selected data; you agree to the Terms of Use\n',
                encoding="utf-8",
            )
            references, conflicts = self.jif_cleaner.build_reference_rows(
                [source], jcr_release_year="2026", source="JCR", reference_version="test-v1",
                retrieved_at="2026-07-23", license_note="internal only",
            )
        self.assertEqual(len(references["2024"]), 2)
        self.assertEqual(references["2024"][0]["jif"], "4.2")
        self.assertEqual(conflicts, [])

    def test_jcr_cleaner_excludes_conflicting_jif_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.csv"
            second = Path(temp_dir) / "second.csv"
            header = 'Journal name,JCR Abbreviation,ISSN,eISSN,2024 JIF\n'
            first.write_text(header + 'Example Journal,EX J,1234-5678,,4.2\n', encoding="utf-8")
            second.write_text(header + 'Example Journal,EX J,1234-5678,,5.0\n', encoding="utf-8")
            references, conflicts = self.jif_cleaner.build_reference_rows(
                [first, second], jcr_release_year="2026", source="JCR", reference_version="test-v1",
                retrieved_at="2026-07-23", license_note="internal only",
            )
        self.assertEqual(references, {})
        self.assertEqual(len(conflicts), 2)

    def test_jcr_cleaner_treats_2_and_2_point_0_as_the_same_jif(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.csv"
            second = Path(temp_dir) / "second.csv"
            header = 'Journal name,JCR Abbreviation,ISSN,eISSN,2024 JIF\n'
            first.write_text(header + 'Example Journal,EX J,1234-5678,,2\n', encoding="utf-8")
            second.write_text(header + 'Example Journal,EX J,1234-5678,,2.0\n', encoding="utf-8")
            references, conflicts = self.jif_cleaner.build_reference_rows(
                [first, second], jcr_release_year="2026", source="JCR", reference_version="test-v1",
                retrieved_at="2026-07-23", license_note="internal only",
            )
        self.assertEqual(len(references["2024"]), 1)
        self.assertEqual(conflicts, [])

    def test_jif_match_requires_same_publication_year(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reference = Path(temp_dir) / "jif.tsv"
            reference.write_text(
                "journal_title\tissn\teissn\tjif_data_year\tjcr_release_year\tjif\tsource\treference_version\n"
                "Test Journal\t1234-5678\t\t2025\t2026\t4.5\tJCR\t2026-v1\n",
                encoding="utf-8",
            )
            matcher = self.jif.JIFMatcher(reference)
            exact = matcher.match({"issn": "1234-5678", "publication_year": "2025"})
            missing = matcher.match({"issn": "1234-5678", "publication_year": "2024"})
        self.assertEqual(exact["jif"], "4.5")
        self.assertEqual(exact["jif_match_status"], "exact")
        self.assertEqual(missing["jif"], "")
        self.assertEqual(missing["jif_match_status"], "year_not_found")

    def test_jif_matcher_loads_multiple_annual_references(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "2024.tsv"
            second = root / "2025.tsv"
            header = "journal_title\tissn\tjif_data_year\tjif\n"
            first.write_text(header + "Test Journal\t1234-5678\t2024\t4.0\n", encoding="utf-8")
            second.write_text(header + "Test Journal\t1234-5678\t2025\t5.0\n", encoding="utf-8")
            matcher = self.jif.JIFMatcher([first, second])
            match_2024 = matcher.match({"issn": "1234-5678", "publication_year": "2024"})
            match_2025 = matcher.match({"issn": "1234-5678", "publication_year": "2025"})
        self.assertEqual(match_2024["jif"], "4.0")
        self.assertEqual(match_2025["jif"], "5.0")

    def test_jif_match_is_not_ambiguous_when_issn_equals_eissn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reference = Path(temp_dir) / "jif.tsv"
            reference.write_text(
                "journal_title\tissn\teissn\tjif_data_year\tjif\n"
                "Test Journal\t2234-943X\t2234-943X\t2025\t3.3\n",
                encoding="utf-8",
            )
            matcher = self.jif.JIFMatcher(reference)
            result = matcher.match({"issn": "2234-943X", "publication_year": "2025"})
        self.assertEqual(result["jif_match_status"], "exact")
        self.assertEqual(result["jif"], "3.3")

    def test_jif_duplicate_rows_across_reference_files_collapse_only_when_they_agree(self):
        header = "journal_title\tissn\tjif_data_year\tjif\treference_version\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "onc.tsv").write_text(header + "Test Journal\t1234-5678\t2025\t4.0\tv1\n", encoding="utf-8")
            (root / "surg.tsv").write_text(header + "Test Journal\t1234-5678\t2025\t4.0\tv2\n", encoding="utf-8")
            (root / "odd.tsv").write_text(header + "Test Journal\t1234-5678\t2025\t4.5\tv3\n", encoding="utf-8")
            agree = self.jif.JIFMatcher([root / "onc.tsv", root / "surg.tsv"]).match(
                {"issn": "1234-5678", "publication_year": "2025"})
            conflict = self.jif.JIFMatcher([root / "onc.tsv", root / "odd.tsv"]).match(
                {"issn": "1234-5678", "publication_year": "2025"})
        self.assertEqual(agree["jif_match_status"], "exact")
        self.assertEqual(agree["jif_reference_version"], "v2")
        self.assertEqual(conflict["jif_match_status"], "ambiguous_match")

    def test_title_only_reference_links_to_pubmed_decorated_titles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reference = Path(temp_dir) / "jif.tsv"
            reference.write_text(
                "journal_title\tissn\teissn\tjif_data_year\tjif\n"
                "JOURNAL OF UROLOGY\t\t\t2020\t5.9\n"
                "JOURNAL OF CLINICAL ONCOLOGY\t\t\t2020\t44.5\n"
                "UROLOGY\t\t\t2020\t2.6\n"
                "Urology Case Reports\t\t\t2020\t0.4\n",
                encoding="utf-8",
            )
            matcher = self.jif.JIFMatcher(reference)
            def status(title, abbrev=""):
                return matcher.match({"publication_year": "2020", "journal_title": title, "journal_abbrev": abbrev})
            self.assertEqual(status("The Journal of urology", "J Urol")["jif"], "5.9")
            self.assertEqual(status(
                "Journal of clinical oncology : official journal of the American Society of Clinical Oncology"
            )["jif"], "44.5")
            # a different journal whose name merely starts with the same words must not link
            self.assertEqual(status("Urology")["jif"], "2.6")
            self.assertEqual(status("Urology case reports")["jif"], "0.4")
            self.assertEqual(status("Urologic oncology")["jif_match_status"], "journal_not_found")

    def test_jif_tiers_have_explicit_boundaries(self):
        self.assertEqual(self.jif.jif_tier("0.9"), "low")
        self.assertEqual(self.jif.jif_tier("1"), "moderate")
        self.assertEqual(self.jif.jif_tier("2.99"), "moderate")
        self.assertEqual(self.jif.jif_tier("3"), "high")
        self.assertEqual(self.jif.jif_tier("4.99"), "high")
        self.assertEqual(self.jif.jif_tier("5"), "very-high")
        self.assertEqual(self.jif.jif_tier(""), "unknown")


if __name__ == "__main__":
    unittest.main()
