from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


class ScreenCnsGctTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.screen = load("screen_cns_gct")
        cls.gct_db = load("gct_db")

    def make_db(self, root: Path):
        db_dir = root / "master"
        conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
        rows = [
            ("1", "Intracranial germinoma in children", "kept"),
            ("2", "Testicular seminoma outcomes", "kept"),                      # no CNS keyword: never a candidate
            ("3", "Brain metastases of testicular GCT", "needs_review"),
            ("4", "Pineal germ cell tumor", "excluded"),                        # already excluded: left alone
        ]
        for pmid, title, status in rows:
            conn.execute("INSERT INTO papers (pmid, publication_year, title, abstract, publication_types, ingested_at, "
                         "relevance_status) VALUES (?, 2015, ?, '', '[]', 'x', ?)", (pmid, title, status))
        conn.commit()
        conn.close()
        return db_dir

    def run_main(self, argv):
        with mock.patch.object(sys, "argv", ["screen_cns_gct.py", *argv]), redirect_stdout(io.StringIO()) as out:
            self.screen.main()
        return out.getvalue()

    def test_only_kept_or_review_papers_with_a_cns_keyword_are_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            pmids = {r["pmid"] for r in self.screen.candidates(self.make_db(Path(temp)))}
        self.assertEqual(pmids, {"1", "3"})

    def test_screen_records_verdicts_and_resumes_without_asking_again(self):
        calls = []

        def fake_call(prompt, model=""):
            calls.append(prompt)
            return {"1": {"pmid": "1", "verdict": "cns_primary", "reason": "r"},
                    "3": {"pmid": "3", "verdict": "bogus", "reason": "r"}}, 0.01
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_dir, out = self.make_db(root), root / "v.jsonl"
            with mock.patch.object(self.screen.process_batch, "call_claude", fake_call):
                self.run_main(["screen", "--db-dir", str(db_dir), "--out", str(out), "--claude"])
                self.assertEqual(list(self.screen.read_verdicts(out)), ["1"])   # an invalid verdict is not recorded
                self.run_main(["screen", "--db-dir", str(db_dir), "--out", str(out), "--claude"])
        self.assertEqual(len(calls), 2)   # the second run only asks about the paper that is still undecided
        self.assertNotIn("Intracranial germinoma", calls[1])

    def test_apply_excludes_only_cns_primary_keeps_a_backup_and_hides_site_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_dir, out, backup, site = self.make_db(root), root / "v.jsonl", root / "b.jsonl", root / "papers.json"
            out.write_text("".join(json.dumps(v) + "\n" for v in (
                {"pmid": "1", "verdict": "cns_primary", "reason": "r"},
                {"pmid": "3", "verdict": "not_cns_primary", "reason": "r"})), encoding="utf-8")
            site.write_text(json.dumps([{"pmid": "1", "title": "a"}, {"pmid": "3", "title": "b"}]), encoding="utf-8")
            args = ["apply", "--db-dir", str(db_dir), "--out", str(out), "--backup", str(backup),
                    "--site-papers", str(site)]
            self.run_main(args)                                        # dry run
            self.assertFalse(backup.exists())
            self.run_main([*args, "--apply"])
            conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
            status = {r["pmid"]: (r["relevance_status"], r["relevance_note"]) for r in conn.execute("SELECT * FROM papers")}
            conn.close()
            self.assertEqual(status["1"], ("excluded", self.screen.NOTE))
            self.assertEqual(status["3"][0], "needs_review")
            self.assertEqual(json.loads(backup.read_text())["old_status"], "kept")
            entries = {e["pmid"]: e for e in json.loads(site.read_text())}
            self.assertEqual(entries["1"]["relevance_status"], "excluded")
            self.assertNotIn("relevance_status", entries["3"])


if __name__ == "__main__":
    unittest.main()
