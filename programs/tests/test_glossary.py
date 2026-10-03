from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1] / "literature_pipeline"

TEXT = """# 用語集

| 英語 | 日本語 |
|---|---|
| Germ cell tumor (GCT) | 胚細胞腫瘍 |
| Dysgerminoma | ディスジャーミノーマ（未分化胚細胞腫） |
| Testicular cancer / Testis cancer | 精巣がん |
| Metastasis / Metastatic | 転移(性) |
| Stage I | 病期I |
| Stage II | 病期II |
| Growing teratoma syndrome | (原語のまま) |
| Alpha-fetoprotein (AFP) | αフェトプロテイン(AFP) |

| 英語 | 避ける訳 |
|---|---|
| germ cell tumor | 生殖細胞腫瘍、胚細胞性腫瘍 |
| testicular cancer | 精巣癌 |
| growing teratoma syndrome | 増殖性奇形腫症候群 |

- 文章の行は無視される
"""


def load():
    spec = importlib.util.spec_from_file_location("glossary_under_test", PIPELINE / "glossary.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GlossaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = load()
        cls.entries = cls.g.parse(TEXT)

    def entry(self, english):
        return next(e for e in self.entries if e["english"].startswith(english))

    def test_parse_reads_names_acronyms_alternatives_keep_english_and_avoid_lists(self):
        self.assertEqual(len(self.entries), 8)
        gct = self.entry("Germ cell tumor")
        self.assertEqual((gct["names"], gct["acronyms"], gct["main"]), (["germ cell tumor"], ["GCT"], "胚細胞腫瘍"))
        self.assertEqual(gct["avoid"], ["生殖細胞腫瘍", "胚細胞性腫瘍"])
        dys = self.entry("Dysgerminoma")
        self.assertEqual((dys["main"], dys["alts"]), ("ディスジャーミノーマ", ["未分化胚細胞腫"]))
        self.assertEqual(self.entry("Testicular cancer")["names"], ["testicular cancer", "testis cancer"])
        self.assertEqual(self.entry("Metastasis")["alts"], [])  # "(性)" is a suffix, not an alternative
        grow = self.entry("Growing teratoma")
        self.assertTrue(grow["keep_english"])
        self.assertEqual(grow["avoid"], ["増殖性奇形腫症候群"])

    def test_select_finds_terms_in_the_text_including_plurals_variants_and_acronyms(self):
        def found(text):
            return sorted(e["english"].split(" /")[0].split(" (")[0] for e in self.g.terms_in(self.entries, [text]))
        self.assertEqual(found("Testicular germ-cell tumours in children"), ["Germ cell tumor"])
        self.assertEqual(found("Elevated AFP and metastases"), ["Alpha-fetoprotein"])  # acronym, case-sensitive
        self.assertEqual(found("an afp-like protein"), [])
        self.assertEqual(found("Stage III disease"), [])  # 'stage i' must not match 'stage iii'
        self.assertEqual(found("Stage II disease"), ["Stage II"])
        self.assertEqual(found("nothing relevant"), [])

    def test_render_note_lists_only_the_given_entries_with_keep_and_avoid_markers(self):
        picked = self.g.terms_in(self.entries, ["growing teratoma syndrome; testis cancer"])
        note = self.g.render_note(picked)
        self.assertIn("- Testicular cancer / Testis cancer => 精巣がん   [do not use: 精巣癌]", note)
        self.assertIn("Growing teratoma syndrome => (keep in English, as written)", note)
        self.assertNotIn("胚細胞腫瘍", note)
        self.assertEqual(self.g.render_note([]), "")

    def test_check_pair_flags_avoided_renderings_even_next_to_the_standard_one(self):
        check = self.g.check_pair
        self.assertEqual(check(self.entries, "Testicular cancer", "精巣がんの研究"), [])
        flagged = check(self.entries, "Testicular cancer", "精巣癌の研究")
        self.assertEqual([(s, a) for _, s, a in flagged], [("avoid", ["精巣癌"])])
        mixed = check(self.entries, "Testicular cancer", "精巣がんと精巣癌")
        self.assertEqual([s for _, s, _ in mixed], ["avoid"])
        missing = check(self.entries, "Testicular cancer", "睾丸の疾患")
        self.assertEqual([s for _, s, _ in missing], ["check"])
        self.assertEqual(check(self.entries, "elevated AFP", "AFPが上昇"), [])  # the acronym is accepted
        self.assertEqual(check(self.entries, "Dysgerminoma", "未分化胚細胞腫"), [])  # an allowed alternative
        self.assertEqual(check(self.entries, "Growing teratoma syndrome", "growing teratoma syndromeの1例"), [])
        self.assertEqual([s for _, s, _ in check(self.entries, "Growing teratoma syndrome", "増殖性奇形腫症候群")],
                         ["avoid"])


if __name__ == "__main__":
    unittest.main()
