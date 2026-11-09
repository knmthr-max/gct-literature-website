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
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


class ScreenByCriteriaTests(unittest.TestCase):
    def test_screens_needs_review_only_resumes_and_ignores_invalid_results(self):
        gct_db, sc = load("gct_db"), load("screen_by_criteria")
        calls = []

        def fake_call(prompt, model="", **_):
            calls.append(prompt)
            return {"1": {"pmid": "1", "decision": "exclude", "rule": "case_animal", "confidence": "high", "reason": "dog"},
                    "2": {"pmid": "2", "decision": "keep", "rule": "bogus", "confidence": "low", "reason": "x"}}, 0.01
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_dir, out = root / "master", root / "s.jsonl"
            conn = gct_db.connect(gct_db.shard_path(db_dir, "2010s"))
            for pmid, status, tag in (("1", "needs_review", '["症例報告・集積"]'), ("2", "needs_review", '["総説"]'), ("3", "kept", '["総説"]')):
                conn.execute("INSERT INTO papers (pmid, publication_year, title, abstract, publication_types, ingested_at, relevance_status, ai_tags) "
                             "VALUES (?, 2015, 't', 'a', '[]', 'x', ?, ?)", (pmid, status, tag))
            conn.commit()
            conn.close()
            argv = ["screen_by_criteria.py", "--db-dir", str(db_dir), "--out", str(out), "--claude", "--workers", "1"]
            with mock.patch.object(sc.process_batch, "call_claude", fake_call), mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                sc.main()
                sc.main()
            done = sc.read_done(out)
        self.assertEqual(list(done), ["1"])           # pmid 2 had an invalid rule (not recorded); pmid 3 is not needs_review
        self.assertEqual(done["1"]["design"], "症例報告・集積")
        self.assertIn("teratocarcinosarcoma", calls[0])
        self.assertEqual(len(calls), 2)               # the second run only asks about pmid 2 again


if __name__ == "__main__":
    unittest.main()
