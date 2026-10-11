from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(module)
    return module


class PapersStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = load("papers_store")

    def papers(self):
        return [{"pmid": "1", "year": 2021}, {"pmid": "2", "year": 1979}, {"pmid": "3", "year": 2019},
                {"pmid": "4", "year": 2023}, {"pmid": "5", "year": None}]

    def test_saving_to_a_directory_splits_by_decade_keeps_order_and_round_trips(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "papers"
            root.mkdir()
            self.store.save(root, self.papers())
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ["index.json", "papers_2010s.json", "papers_2020s.json", "papers_pre1980.json"])
            self.assertEqual(json.loads((root / "index.json").read_text())["shards"],
                             ["papers_pre1980.json", "papers_2010s.json", "papers_2020s.json"])
            loaded = self.store.load(root)
            self.assertEqual(sorted(p["pmid"] for p in loaded), ["1", "2", "3", "4", "5"])
            self.assertEqual([p["pmid"] for p in json.loads((root / "papers_2020s.json").read_text())], ["1", "4"])

    def test_only_changed_shards_are_rewritten_and_emptied_shards_are_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "papers"
            root.mkdir()
            self.store.save(root, self.papers())
            old = (root / "papers_2010s.json").stat().st_mtime_ns
            papers = [p for p in self.store.load(root) if p["pmid"] != "2"] + [{"pmid": "6", "year": 2022}]
            self.store.save(root, papers)
            self.assertEqual((root / "papers_2010s.json").stat().st_mtime_ns, old)    # untouched
            self.assertFalse((root / "papers_1980s.json").exists())
            self.assertEqual([p["pmid"] for p in json.loads((root / "papers_2020s.json").read_text())], ["1", "4", "6"])

    def test_a_single_file_still_works_and_the_old_file_name_finds_the_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            single = Path(temp) / "one.json"
            self.store.save(single, self.papers())
            self.assertEqual(len(self.store.load(single)), 5)
            root = Path(temp) / "papers"
            root.mkdir()
            self.store.save(root, self.papers())
            legacy = Path(temp) / "papers.json"          # does not exist; the directory next to it is used instead
            self.assertTrue(self.store.exists(legacy))
            self.assertEqual(len(self.store.load(legacy)), 5)
            self.store.save(legacy, self.store.load(legacy) + [{"pmid": "9", "year": 1990}])
            self.assertFalse(legacy.exists())
            self.assertTrue((root / "papers_1990s.json").exists())


if __name__ == "__main__":
    unittest.main()
