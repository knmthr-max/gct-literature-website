from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


REFERENCE_HEADER = "journal_title\tissn\teissn\tjif_data_year\tjcr_release_year\tjif\treference_version\n"


class BackfillJifTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backfill = load_module("backfill_jif_under_test", SCRIPTS / "backfill_jif.py")
        cls.gct_db = load_module("gct_db_under_test", SCRIPTS / "gct_db.py")

    def make_env(self, root: Path):
        db_dir = root / "data" / "master"
        conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2020s"))
        rows = [
            # pmid, year, issn, eissn, journal
            ("1", 2025, "1111-1111", "", "Alpha J"),
            ("2", 2024, "1111-1111", "", "Alpha J"),
            ("3", 2024, "2222-222X", "2222-222X", "Beta J"),
            ("4", 2025, "9999-9999", "", "Unlisted J"),
        ]
        for pmid, year, issn, eissn, journal in rows:
            conn.execute(
                "INSERT INTO papers (pmid, publication_year, issn, eissn, journal_abbrev, journal_title, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'x')",
                (pmid, year, issn, eissn, journal, journal),
            )
        conn.commit()
        conn.close()
        ref_dir = root / "data" / "reference" / "jif"
        ref_dir.mkdir(parents=True)
        (ref_dir / "jcr_jif_reference_2025_vt.tsv").write_text(
            REFERENCE_HEADER + "Alpha J\t1111-1111\t\t2025\t2026\t6.0\tv1\n", encoding="utf-8"
        )
        papers = root / "papers.json"
        papers.write_text(json.dumps([
            {"id": "pmid-1", "pmid": "1", "journal": "Alpha J", "year": 2025, "jif_tier": "unknown"},
            {"id": "pmid-2", "pmid": "2", "journal": "Alpha J", "year": 2024, "jif_tier": "unknown"},
            {"id": "hand-1", "pmid": "500", "journal": "Gamma J", "year": 2025, "jif_tier": "moderate"},
        ], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return db_dir, ref_dir, papers

    def args(self, db_dir, papers, **overrides):
        values = dict(
            db_dir=db_dir, reference=None, papers=papers, no_papers=False, audit_dir=None,
            apply=True, allow_downgrade=False, top_gaps=10,
        )
        values.update(overrides)
        return argparse.Namespace(**values)

    def tiers(self, db_dir):
        conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2020s"))
        result = {r["pmid"]: (r["jif_tier"], r["jif_match_status"]) for r in conn.execute(
            "SELECT pmid, jif_tier, jif_match_status FROM papers")}
        conn.close()
        return result

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            db_dir, _, papers = self.make_env(Path(temp))
            before = papers.read_text(encoding="utf-8")
            summary, _, _ = self.backfill.run(self.args(db_dir, papers, apply=False))
            self.assertFalse(summary["applied"])
            self.assertEqual(papers.read_text(encoding="utf-8"), before)
            self.assertEqual(set(self.tiers(db_dir).values()), {(None, None)})
            self.assertFalse((Path(temp) / "data" / "processed").exists())

    def test_apply_fills_db_and_only_tier_in_public_json(self):
        with tempfile.TemporaryDirectory() as temp:
            db_dir, _, papers = self.make_env(Path(temp))
            summary, _, _ = self.backfill.run(self.args(db_dir, papers))
            tiers = self.tiers(db_dir)
            self.assertEqual(tiers["1"], ("very-high", "exact"))
            self.assertEqual(tiers["2"], ("unknown", "year_not_found"))
            self.assertEqual(tiers["4"], ("unknown", "journal_not_found"))
            published = json.loads(papers.read_text(encoding="utf-8"))
            self.assertEqual([p["jif_tier"] for p in published], ["very-high", "unknown", "moderate"])
            self.assertNotIn('"jif"', papers.read_text(encoding="utf-8"))
            audit = Path(summary["audit_dir"])
            self.assertIn("6.0", next(audit.glob("changes_*.csv")).read_text(encoding="utf-8"))

    def test_second_reference_year_fills_past_papers_retroactively_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            db_dir, ref_dir, papers = self.make_env(Path(temp))
            self.backfill.run(self.args(db_dir, papers))
            (ref_dir / "jcr_jif_reference_2024_vt.tsv").write_text(
                REFERENCE_HEADER
                + "Alpha J\t1111-1111\t\t2024\t2025\t2.0\tv1\n"
                + "Beta J\t2222-222X\t2222-222X\t2024\t2025\t3.5\tv1\n",
                encoding="utf-8",
            )
            summary, gap_years, _ = self.backfill.run(self.args(db_dir, papers))
            tiers = self.tiers(db_dir)
            self.assertEqual(tiers["1"][0], "very-high")
            self.assertEqual(tiers["2"], ("moderate", "exact"))
            self.assertEqual(tiers["3"], ("high", "exact"))
            self.assertEqual(json.loads(papers.read_text(encoding="utf-8"))[1]["jif_tier"], "moderate")
            self.assertEqual(summary["db"]["tier_changed"], 2)
            again, _, _ = self.backfill.run(self.args(db_dir, papers))
            self.assertEqual(again["db"].get("changed", 0), 0)
            self.assertEqual(again["papers_json"].get("tier_changed", 0), 0)

    def test_partial_reference_set_does_not_erase_known_tiers_unless_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            db_dir, ref_dir, papers = self.make_env(Path(temp))
            self.backfill.run(self.args(db_dir, papers))
            empty_ref = Path(temp) / "other.tsv"
            empty_ref.write_text(REFERENCE_HEADER + "Zed J\t0000-0000\t\t2025\t2026\t1.0\tv9\n", encoding="utf-8")
            self.backfill.run(self.args(db_dir, papers, reference=[empty_ref]))
            self.assertEqual(self.tiers(db_dir)["1"][0], "very-high")
            self.assertEqual(json.loads(papers.read_text(encoding="utf-8"))[0]["jif_tier"], "very-high")
            self.backfill.run(self.args(db_dir, papers, reference=[empty_ref], allow_downgrade=True))
            self.assertEqual(self.tiers(db_dir)["1"][0], "unknown")

    def test_issn_equal_to_eissn_matches_instead_of_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp:
            db_dir, ref_dir, papers = self.make_env(Path(temp))
            (ref_dir / "jcr_jif_reference_2024_vt.tsv").write_text(
                REFERENCE_HEADER + "Beta J\t2222-222X\t2222-222X\t2024\t2025\t3.5\tv1\n", encoding="utf-8"
            )
            self.backfill.run(self.args(db_dir, papers))
            self.assertEqual(self.tiers(db_dir)["3"], ("high", "exact"))


if __name__ == "__main__":
    unittest.main()
