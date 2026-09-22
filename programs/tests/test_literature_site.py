from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]


def load_builder():
    path = PROGRAMS / "literature_site" / "build_site.py"
    spec = importlib.util.spec_from_file_location("maintained_literature_site", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LiteratureSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load_builder()

    def test_build_site_generates_public_tsv_without_jif_or_abstract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "master.tsv"
            fields = list(self.builder.PUBLIC_FIELDS) + ["review_status", "abstract", "jif"]
            row = {field: "" for field in fields}
            row.update({
                "pmid": "111", "publication_year": "2026", "publication_date": "2026 Jan",
                "title": "Example", "summary_ja": "日本語要約", "summary_en": "English summary",
                "first_author": "Alpha A", "journal_title": "Journal", "type": "Clinical",
                "subtype": "Clinical Study", "mesh_terms": '["Germ Cell Tumor"]',
                "author_keywords": '["biomarker"]', "added_at": "2026-07-20T00:00:00+00:00",
                "review_status": "approved", "abstract": "Secret internal abstract", "jif": "9.9",
            })
            with master.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fields, delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerow(row)
            years, articles = self.builder.build_site(master, root / "site")
            with (root / "site/data/literature_2026.tsv").open(encoding="utf-8", newline="") as source:
                public_rows = list(csv.DictReader(source, delimiter="\t"))
            index = json.loads((root / "site/data/search_index.json").read_text(encoding="utf-8"))
            deployment = (root / "site/deployment_manifest.tsv").read_text(encoding="utf-8")

        self.assertEqual((years, articles), (1, 1))
        self.assertNotIn("jif", public_rows[0])
        self.assertNotIn("abstract", public_rows[0])
        self.assertNotIn("summary_ja", index[0])
        self.assertIn("Germ Cell Tumor", index[0]["k"])
        self.assertIn("no_until_sso_configured", deployment)

    def test_sso_portal_is_built_without_common_jif_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "master.tsv"
            with master.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, ["pmid", "review_status"], delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerow({"pmid": "1", "review_status": "approved"})
            self.builder.build_site(master, root / "site")
            portal = (root / "site/sso-jif/index.html").read_text(encoding="utf-8")
            common_jif = root / "site/sso-jif/data/common_jif.tsv"
        self.assertIn("jifStatus", portal)
        self.assertFalse(common_jif.exists())


if __name__ == "__main__":
    unittest.main()
