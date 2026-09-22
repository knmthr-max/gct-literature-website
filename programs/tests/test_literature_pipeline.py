from __future__ import annotations

import importlib.util
import argparse
import csv
import tempfile
import unittest
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]


def load_pipeline():
    path = PROGRAMS / "literature_pipeline" / "pipeline.py"
    spec = importlib.util.spec_from_file_location("maintained_literature_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_jif_reference_cleaner():
    path = PROGRAMS / "literature_pipeline" / "jif_reference_cleaner.py"
    spec = importlib.util.spec_from_file_location("maintained_jif_reference_cleaner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LiteraturePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load_pipeline()
        cls.jif_cleaner = load_jif_reference_cleaner()

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

    def test_jif_match_requires_same_publication_year(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reference = Path(temp_dir) / "jif.tsv"
            reference.write_text(
                "journal_title\tissn\teissn\tjif_data_year\tjcr_release_year\tjif\tsource\treference_version\n"
                "Test Journal\t1234-5678\t\t2025\t2026\t4.5\tJCR\t2026-v1\n",
                encoding="utf-8",
            )
            matcher = self.pipeline.JIFMatcher(reference)
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
            matcher = self.pipeline.JIFMatcher([first, second])
            match_2024 = matcher.match({"issn": "1234-5678", "publication_year": "2024"})
            match_2025 = matcher.match({"issn": "1234-5678", "publication_year": "2025"})
        self.assertEqual(match_2024["jif"], "4.0")
        self.assertEqual(match_2025["jif"], "5.0")

    def test_search_keywords_keep_mesh_and_author_terms(self):
        result = self.pipeline.search_keywords({
            "mesh_terms": '["Germ Cell Tumor","Humans"]',
            "author_keywords": '["biomarker","Humans"]',
        })
        self.assertEqual(result, '["Germ Cell Tumor","Humans","biomarker"]')

    def test_jif_tiers_have_explicit_boundaries(self):
        self.assertEqual(self.pipeline.jif_tier("0.9"), "low")
        self.assertEqual(self.pipeline.jif_tier("1"), "middle")
        self.assertEqual(self.pipeline.jif_tier("4.99"), "middle")
        self.assertEqual(self.pipeline.jif_tier("5"), "high")
        self.assertEqual(self.pipeline.jif_tier(""), "unknown")

    def test_ai_validation_blocks_short_summaries_and_other_subtype(self):
        problems = self.pipeline.validate_ai_result(
            {"abstract": "A real abstract", "publication_types": '["Journal Article"]'},
            {
                "summary_ja": "短い要約", "summary_en": "Too short.", "type": "Clinical",
                "subtype": "Other", "classification_basis": "abstract",
            },
        )
        self.assertIn("summary_ja_length", problems)
        self.assertIn("summary_en_length", problems)
        self.assertIn("subtype_other_needs_review", problems)

    def test_ai_validation_accepts_exact_missing_abstract_sentinel(self):
        problems = self.pipeline.validate_ai_result(
            {"abstract": "", "publication_types": '["Journal Article"]'},
            {
                "summary_ja": "Abstractなし", "summary_en": "No abstract available.",
                "type": "Clinical", "subtype": "Clinical Study",
                "classification_basis": "metadata_only",
            },
        )
        self.assertEqual(problems, [])

    def test_review_publication_type_conflict_is_not_bulk_approvable(self):
        problems = self.pipeline.validate_ai_result(
            {"abstract": "A", "publication_types": '["Review"]'},
            {
                "summary_ja": "あ" * 120, "summary_en": "word " * 60,
                "type": "Clinical", "subtype": "Clinical Study",
                "classification_basis": "abstract",
            },
        )
        self.assertIn("publication_type_classification_conflict", problems)

    def test_bulk_approval_accepts_only_quality_ok(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate = root / "candidate.tsv"
            output = root / "decisions.tsv"
            with candidate.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, ["pmid", "quality_status"], delimiter="\t")
                writer.writeheader()
                writer.writerows([
                    {"pmid": "1", "quality_status": "ok"},
                    {"pmid": "2", "quality_status": "claude_not_run"},
                ])
            self.pipeline.approve(argparse.Namespace(
                candidate=candidate, output=output, reviewer="test", approve_all_valid=True,
                exceptions=None,
            ))
            decisions = self.pipeline.read_tsv(output)
        self.assertEqual(decisions[0]["decision"], "approved")
        self.assertEqual(decisions[1]["decision"], "needs_edit")

    def test_claude_standard_json_result_is_parsed(self):
        payload = self.pipeline.parse_claude_payload({
            "type": "result",
            "result": '```json\n{"articles": [{"pmid": "1"}]}\n```',
        })
        self.assertEqual(payload["articles"][0]["pmid"], "1")


if __name__ == "__main__":
    unittest.main()
