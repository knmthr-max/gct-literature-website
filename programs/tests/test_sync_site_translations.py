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


class SyncSiteTranslationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sync = load("sync_site_translations")

    def test_updates_only_what_still_matches_the_pre_retranslation_value(self):
        old = {"1": {"title_ja": "旧題", "summary_ja": "旧要約", "abstract_ja": "旧訳"},
               "2": {"title_ja": "旧題2", "summary_ja": "旧要約2", "abstract_ja": "旧訳2"}}
        db = {"1": {"ai_title_ja": "新題", "ai_summary_ja": "新要約", "ai_abstract_ja": "新訳"},
              "2": {"ai_title_ja": "新題2", "ai_summary_ja": "新要約2", "ai_abstract_ja": "新訳2"},
              "3": {"ai_title_ja": "題3", "ai_summary_ja": "要約3", "ai_abstract_ja": "訳3"}}
        papers = [
            {"pmid": "1", "title_ja": "旧題", "summary_ja": "旧要約", "abstract_ja": "旧訳"},           # untouched since export
            {"pmid": "2", "title_ja": "旧題2", "summary_ja": "手で直した要約", "abstract_ja": "旧訳2"},  # summary edited by hand
            {"pmid": "3", "title_ja": "題3", "summary_ja": "要約3", "abstract_ja": "訳3"},              # never retranslated: same
            {"pmid": "9", "title_ja": "DBにない"},
        ]
        updates, manual, same = self.sync.plan(papers, db, old)
        self.assertEqual(sorted((e["pmid"], f) for e, f, _ in updates),
                         [("1", "abstract_ja"), ("1", "summary_ja"), ("1", "title_ja"),
                          ("2", "abstract_ja"), ("2", "title_ja")])
        self.assertEqual(manual, [("2", "summary_ja")])  # the hand-edited text is left alone and reported
        self.assertEqual(same, 3)

    def test_the_first_backup_entry_is_the_sites_old_value(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "backup.jsonl"
            path.write_text(
                json.dumps({"pmid": "1", "old": {"title_ja": "最初"}}) + "\n" +
                json.dumps({"pmid": "1", "old": {"title_ja": "二回目"}}) + "\n", encoding="utf-8")
            self.assertEqual(self.sync.read_backup(path), {"1": {"title_ja": "最初"}})
            self.assertEqual(self.sync.read_backup(Path(temp) / "missing.jsonl"), {})


if __name__ == "__main__":
    unittest.main()
