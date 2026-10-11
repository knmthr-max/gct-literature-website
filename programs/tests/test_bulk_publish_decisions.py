from __future__ import annotations

import csv
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


class BulkPublishDecisionsTests(unittest.TestCase):
    def test_only_complete_unpublished_unreviewed_kept_papers_in_the_year_range_are_approved(self):
        gct_db = load("gct_db")
        bulk = load("bulk_publish_decisions")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_dir = root / "master"
            conn = gct_db.connect(gct_db.shard_path(db_dir, "2010s"))
            base = dict(abstract="a", ai_title_ja="題", ai_abstract_ja="訳", ai_summary_ja="要", ai_summary_en="en",
                        relevance_status="kept", published_to_site=0, human_review_status=None)
            rows = {
                "1": base,                                                      # ok
                "2": {**base, "relevance_status": "needs_review"},               # not kept
                "3": {**base, "published_to_site": 1},                           # already published
                "4": {**base, "human_review_status": "rejected"},                # a human already decided
                "5": {**base, "ai_abstract_ja": ""},                             # translation missing
                "6": {**base},                                                   # ok, but outside the range below
            }
            for pmid, r in rows.items():
                conn.execute(
                    "INSERT INTO papers (pmid, publication_year, title, abstract, publication_types, ingested_at, ai_tags, "
                    "ai_title_ja, ai_abstract_ja, ai_summary_ja, ai_summary_en, relevance_status, published_to_site, "
                    "human_review_status) VALUES (?, ?, 't', ?, '[]', 'x', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (pmid, 2019 if pmid != "6" else 2005, r["abstract"], '["症例報告"]', r["ai_title_ja"], r["ai_abstract_ja"],
                     r["ai_summary_ja"], r["ai_summary_en"], r["relevance_status"], r["published_to_site"],
                     r["human_review_status"]))
            conn.commit()
            conn.close()
            out = root / "d.tsv"
            argv = ["x", "--db-dir", str(db_dir), "--year-from", "2010", "--year-to", "2019", "--out", str(out)]
            with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                bulk.main()
            with out.open(encoding="utf-8") as f:
                result = list(csv.DictReader(f, delimiter="\t"))
        self.assertEqual([r["pmid"] for r in result], ["1"])
        self.assertEqual((result[0]["decision"], result[0]["tags"]), ("approve", "症例報告"))
        self.assertIn("一括公開", result[0]["note"])


if __name__ == "__main__":
    unittest.main()
