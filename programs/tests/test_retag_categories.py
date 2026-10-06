from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RetagCategoriesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retag = load("retag_categories")
        cls.medline = load("import_medline")
        cls.gct_db = load("gct_db")

    def test_systematic_reviews_and_meta_analyses_are_clinical_research_but_case_reports_still_win(self):
        classify = self.medline.classify
        self.assertEqual(classify(["Journal Article", "Review", "Systematic Review"]), "臨床研究")
        self.assertEqual(classify(["Meta-Analysis"]), "臨床研究")
        self.assertEqual(classify(["Review"]), "総説")
        self.assertEqual(classify(["Case Reports", "Review", "Systematic Review"]), "症例報告")
        self.assertIsNone(classify(["Journal Article"]))

    def make_db(self, root):
        db_dir = root / "master"
        conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2020s"))
        rows = [("1", ["Review", "Systematic Review"], ["総説"]),    # rule change: becomes 臨床研究
                ("2", ["Review"], ["総説"]),                         # a true review: unchanged
                ("3", ["Review"], ["総説"]),                         # overridden by hand
                ("4", ["Journal Article"], []),                     # no category
                ("5", ["Review"], None)]                            # not processed yet (ai_tags NULL): untouched
        for pmid, pt, tags in rows:
            conn.execute("INSERT INTO papers (pmid, publication_types, ai_tags, ingested_at) VALUES (?, ?, ?, 'x')",
                         (pmid, json.dumps(pt), None if tags is None else json.dumps(tags, ensure_ascii=False)))
        conn.commit()
        conn.close()
        return db_dir

    def test_retag_updates_the_db_and_only_the_site_entries_whose_tags_were_not_edited_by_hand(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_dir = self.make_db(root)
            overrides_path = root / "overrides.tsv"
            overrides_path.write_text("pmid\ttag\treason\n3\t臨床研究\tcase series\n", encoding="utf-8")
            overrides = self.retag.read_overrides(overrides_path)
            changes = self.retag.plan_db(db_dir, overrides)
            self.assertEqual(sorted((pmid, new) for _, pmid, _, new in changes),
                             [("1", ["臨床研究"]), ("3", ["臨床研究"])])
            papers = [{"pmid": "1", "tags": ["総説"]}, {"pmid": "3", "tags": ["症例報告"]}, {"pmid": "2", "tags": ["総説"]}]
            updates, manual = self.retag.plan_site(papers, changes)
            self.assertEqual([e["pmid"] for e, _ in updates], ["1"])
            self.assertEqual(manual, ["3"])  # edited by hand on the site: left alone and reported
            backup = root / "backup.jsonl"
            self.retag.apply_db(changes, backup)
            self.assertEqual(self.retag.plan_db(db_dir, overrides), [])  # idempotent
            self.assertEqual(len(backup.read_text().splitlines()), 2)

    def test_unknown_override_tags_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "o.tsv"
            path.write_text("pmid\ttag\treason\n9\tなんでも\tx\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.retag.read_overrides(path)


if __name__ == "__main__":
    unittest.main()
