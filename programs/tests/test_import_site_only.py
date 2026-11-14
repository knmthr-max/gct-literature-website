import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import import_site_only  # noqa: E402
import papers_store  # noqa: E402
from gct_db import connect, shard_path  # noqa: E402

ENTRY = {"id": "pmid-9", "pmid": "9", "title": "T", "title_ja": "題", "authors": ["A B", "C D"], "journal": "J",
         "year": 2025, "doi": "10.1/x", "tags": ["症例報告・集積"], "summary_en": "s", "summary_ja": "要", "abstract": "ab",
         "abstract_ja": "抄", "added_at": "2026-01-02", "jif_tier": "low", "relevance_status": "kept",
         "relevance_note": "n", "relevance_reviewed_at": ""}


class ImportSiteOnly(unittest.TestCase):
    def test_row_mapping(self):
        row = import_site_only.row_from_entry(ENTRY, "2026-11-13")
        self.assertEqual((row["pmid"], row["first_author"], row["publication_year"], row["published_to_site"]), ("9", "A B", 2025, 1))
        self.assertEqual(row["ai_relevance"], "relevant")
        self.assertEqual(row["ai_abstract_ja"], "抄")
        self.assertEqual(row["added_at"], "2026-01-02")

    def test_excluded_cns_and_other(self):
        cns = dict(ENTRY, relevance_status="excluded", relevance_note="中枢神経系原発のため除外")
        other = dict(ENTRY, relevance_status="excluded", relevance_note="対象外")
        self.assertEqual(import_site_only.row_from_entry(cns, "d")["ai_relevance"], "cns_gct")
        self.assertEqual(import_site_only.row_from_entry(other, "d")["ai_relevance"], "not_relevant")

    def test_apply_adds_only_missing_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            db_dir = tmp / "master"
            conn = connect(shard_path(db_dir, "2020s"))
            conn.execute("INSERT INTO papers (pmid, ingested_at, publication_year) VALUES ('1', 'x', 2024)")
            conn.commit()
            conn.close()
            papers = tmp / "papers"
            papers_store.save(papers, [dict(ENTRY), dict(ENTRY, pmid="1", id="pmid-1")])
            cmd = [sys.executable, str(ROOT / "scripts/import_site_only.py"), "--db-dir", str(db_dir), "--papers", str(papers)]
            subprocess.run(cmd, check=True, capture_output=True)  # dry run
            conn = connect(shard_path(db_dir, "2020s"))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0], 1)
            conn.close()
            for _ in range(2):
                subprocess.run(cmd + ["--apply"], check=True, capture_output=True)
            conn = connect(shard_path(db_dir, "2020s"))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0], 2)
            row = conn.execute("SELECT source_file, published_to_site FROM papers WHERE pmid='9'").fetchone()
            self.assertEqual((row[0], row[1]), ("site_only_import", 1))


if __name__ == "__main__":
    unittest.main()
