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


class ExtractAttributesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ea = load("extract_attributes")
        cls.gct_db = load("gct_db")
        cls.sd = load("study_design")

    def make_db(self, root: Path):
        db_dir = root / "master"
        conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
        rows = [("1", self.sd.RCT, "kept", "abs"), ("2", self.sd.RCT, "kept", "abs"),
                ("3", self.sd.OBSERVATIONAL, "needs_review", "abs"), ("4", self.sd.RCT, "excluded", "abs"),
                ("5", self.sd.RCT, "kept", "")]
        for pmid, tag, status, abstract in rows:
            conn.execute("INSERT INTO papers (pmid, publication_year, title, abstract, publication_types, ingested_at, "
                         "relevance_status, ai_tags) VALUES (?, 2015, 't', ?, '[]', 'x', ?, ?)",
                         (pmid, abstract, status, json.dumps([tag])))
        conn.commit()
        conn.close()
        return db_dir

    def run_main(self, argv):
        with mock.patch.object(sys, "argv", ["extract_attributes.py", *argv]), redirect_stdout(io.StringIO()):
            self.ea.main()

    def test_shared_fields_use_the_case_report_vocabulary(self):
        props = self.ea.schema_for(self.sd.RCT)["properties"]["papers"]["items"]["properties"]
        case = load("extract_case_attributes")
        for key in ("sex", "age_group", "primary_site", "igcccg"):
            self.assertEqual(props[key]["enum"], case.SCHEMA["properties"]["papers"]["items"]["properties"][key]["enum"])
        self.assertIn("clinical_themes", props)

    def test_only_live_papers_with_abstract_are_extracted_and_runs_resume(self):
        calls = []

        def fake_call(prompt, model="", **_):
            calls.append(prompt)
            return {p: {"pmid": p, "clinical_themes": ["surgery"]} for p in ("1", "2", "3")}, 0.01
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_dir, out = self.make_db(root), root / "attr"
            with mock.patch.object(self.ea.process_batch, "call_claude", fake_call):
                self.run_main(["extract", "--db-dir", str(db_dir), "--out-dir", str(out), "--designs",
                               f"{self.sd.RCT},{self.sd.OBSERVATIONAL}", "--claude", "--workers", "1"])
                self.run_main(["extract", "--db-dir", str(db_dir), "--out-dir", str(out), "--designs",
                               f"{self.sd.RCT},{self.sd.OBSERVATIONAL}", "--claude", "--workers", "1"])
            rct = {json.loads(l)["pmid"] for l in (out / "rct.jsonl").read_text().splitlines()}
            self.assertEqual(rct, {"1", "2"})
            self.assertEqual(len(calls), 2)   # second run finds nothing to do


if __name__ == "__main__":
    unittest.main()
