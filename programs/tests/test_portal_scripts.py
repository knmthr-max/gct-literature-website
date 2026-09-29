from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
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


def run_script(name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / name), *args], capture_output=True, text=True)


class PortalScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gct_db = load_module("gct_db_portal_test", SCRIPTS / "gct_db.py")

    def make_data(self, root: Path):
        data_dir = root / "data"
        conn = self.gct_db.connect(self.gct_db.shard_path(data_dir / "master", "2020s"))
        for pmid, status, translated in (("1", "kept", True), ("2", "kept", True), ("3", "kept", False), ("4", None, False)):
            conn.execute(
                "INSERT INTO papers (pmid, publication_year, title, journal_abbrev, relevance_status, ai_title_ja, "
                "ai_abstract_ja, ai_summary_ja, ai_summary_en, ai_tags, ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,'x')",
                (pmid, 2025, f"Title {pmid}", "J Test", status,
                 f"題名{pmid}" if translated else None, "抄録" if translated else None,
                 "要約", "summary", "[]"),
            )
        conn.commit()
        conn.close()
        papers = root / "papers.json"
        papers.write_text("[]\n", encoding="utf-8")
        return data_dir, papers

    def digest(self, data_dir: Path) -> str:
        return hashlib.sha256((data_dir / "master" / "gct_literature_2020s.db").read_bytes()).hexdigest()

    def test_status_report_counts_and_never_modifies_the_database(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir, _ = self.make_data(Path(temp))
            before = self.digest(data_dir)
            status = load_module("portal_status_test", SCRIPTS / "portal_status.py")
            text = status.render(data_dir)
            self.assertEqual(self.digest(data_dir), before)
        self.assertIn("| 総件数 | 4 |", text)
        self.assertIn("| AI判定待ち | 1 |", text)
        self.assertIn("| kept のうち和訳(タイトル・抄録)未完了 | 1 |", text)
        self.assertIn("| 公開前レビュー待ち(和訳完了・未公開) | 2 |", text)

    def test_review_export_skips_untranslated_rows_and_writes_markdown(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir, _ = self.make_data(Path(temp))
            result = run_script(
                "export_publish_review.py", "--db-dir", str(data_dir / "master"),
                "--review-dir", str(data_dir / "processed" / "publish_review"), "--run-id", "t1",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            run_dir = data_dir / "processed" / "publish_review" / "t1"
            markdown = (run_dir / "review_t1.md").read_text(encoding="utf-8")
            tsv = (run_dir / "decisions_t1.tsv").read_text(encoding="utf-8")
        self.assertIn("pubmed.ncbi.nlm.nih.gov/1/", markdown)
        self.assertIn("題名2", markdown)
        self.assertNotIn("Title 3", markdown)  # untranslated -> not review-ready
        self.assertEqual(len(tsv.strip().splitlines()), 3)

    def publish(self, temp, *extra):
        root = Path(temp)
        data_dir, papers = self.make_data(root)
        run_script("export_publish_review.py", "--db-dir", str(data_dir / "master"),
                   "--review-dir", str(data_dir / "processed" / "publish_review"), "--run-id", "t1")
        decisions = data_dir / "processed" / "publish_review" / "t1" / "decisions_t1.tsv"
        result = run_script("publish_to_site.py", "--decisions", str(decisions), "--db-dir",
                            str(data_dir / "master"), "--papers", str(papers), *extra)
        conn = self.gct_db.connect(self.gct_db.shard_path(data_dir / "master", "2020s"))
        states = {r["pmid"]: (r["human_review_status"], r["published_to_site"])
                  for r in conn.execute("SELECT pmid, human_review_status, published_to_site FROM papers")}
        conn.close()
        return result, json.loads(papers.read_text(encoding="utf-8")), states

    def test_publish_approves_everything_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            result, papers, states = self.publish(temp)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p["pmid"] for p in papers), ["1", "2"])
        self.assertEqual(states["1"], ("approved", 1))

    def test_reject_and_hold_pmids_override_the_decisions_file(self):
        with tempfile.TemporaryDirectory() as temp:
            result, papers, states = self.publish(temp, "--reject-pmids", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([p["pmid"] for p in papers], ["2"])
        self.assertEqual(states["1"], ("rejected", 0))
        with tempfile.TemporaryDirectory() as temp:
            result, papers, states = self.publish(temp, "--hold-pmids", "2")
        self.assertEqual([p["pmid"] for p in papers], ["1"])
        self.assertEqual(states["2"], ("needs_edit", 0))

    def test_unknown_override_pmid_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            result, papers, states = self.publish(temp, "--reject-pmids", "999")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(papers, [])
        self.assertEqual(states["1"], (None, 0))


if __name__ == "__main__":
    unittest.main()
