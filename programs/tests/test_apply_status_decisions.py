from __future__ import annotations

import importlib.util
import io
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
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


class ApplyStatusDecisionsTests(unittest.TestCase):
    def test_only_needs_review_rows_change_and_cns_is_labelled(self):
        gct_db, apply = load("gct_db"), load("apply_status_decisions")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_dir = root / "master"
            conn = gct_db.connect(gct_db.shard_path(db_dir, "2010s"))
            for pmid, status in (("1", "needs_review"), ("2", "needs_review"), ("3", "needs_review"), ("4", "excluded")):
                conn.execute("INSERT INTO papers (pmid, publication_year, title, abstract, publication_types, ingested_at, "
                             "relevance_status, relevance_note) VALUES (?, 2015, 't', '', '[]', 'x', ?, 'AI reason')", (pmid, status))
            conn.commit()
            conn.close()
            files = {}
            for name, ids in (("kept", "1 4"), ("excluded", "2"), ("cns", "3")):
                files[name] = root / f"{name}.txt"
                files[name].write_text(ids, encoding="utf-8")
            argv = ["apply_status_decisions.py", "--db-dir", str(db_dir), "--kept", str(files["kept"]),
                    "--excluded", str(files["excluded"]), "--cns", str(files["cns"]), "--backup", str(root / "b.jsonl"), "--apply"]
            with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                apply.main()
            conn = gct_db.connect(gct_db.shard_path(db_dir, "2010s"))
            rows = {r["pmid"]: dict(r) for r in conn.execute("SELECT * FROM papers")}
            conn.close()
        self.assertEqual(rows["1"]["relevance_status"], "kept")
        self.assertIn("AI reason", rows["1"]["relevance_note"])
        self.assertEqual(rows["2"]["relevance_status"], "excluded")
        self.assertEqual((rows["3"]["relevance_status"], rows["3"]["ai_relevance"]), ("excluded", "cns_gct"))
        self.assertEqual(rows["3"]["relevance_note"], apply.process_batch.CNS_NOTE)
        self.assertEqual(rows["4"]["relevance_status"], "excluded")   # not needs_review: left alone


if __name__ == "__main__":
    unittest.main()
