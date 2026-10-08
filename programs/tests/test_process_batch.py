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


class ProcessBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = load("process_batch")
        cls.gct_db = load("gct_db")

    def make_db(self, root: Path):
        db_dir = root / "master"
        glossary = root / "reference" / "terminology" / "terminology_ja.md"
        glossary.parent.mkdir(parents=True)
        glossary.write_text("| 英語 | 日本語 |\n|---|---|\n| Seminoma | セミノーマ |\n", encoding="utf-8")
        conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
        rows = [
            ("1", 2019, "Relevant paper", "An abstract about a testicular germ cell tumor."),
            ("2", 2018, "Unrelated paper", "An abstract about something else entirely."),
            ("3", 2017, "Uncertain paper", "An abstract that could go either way."),
            ("4", 2016, "Unrelated, no abstract", ""),
        ]
        for pmid, year, title, abstract in rows:
            conn.execute(
                "INSERT INTO papers (pmid, publication_year, title, abstract, publication_types, ingested_at) "
                "VALUES (?, ?, ?, ?, '[]', 'x')", (pmid, year, title, abstract))
        conn.commit()
        conn.close()
        return db_dir

    def run_batch(self, db_dir: Path, model_output: dict):
        def fake_call(prompt, model="", **_):
            return model_output, 0.01
        argv = ["process_batch.py", "--claude", "--db-dir", str(db_dir), "--batch-size", "10"]
        with mock.patch.object(self.batch, "call_claude", fake_call), mock.patch.object(sys, "argv", argv), \
                redirect_stdout(io.StringIO()):
            self.batch.main()
        conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
        result = {r["pmid"]: dict(r) for r in conn.execute("SELECT * FROM papers")}
        conn.close()
        return result

    def test_abstract_is_not_translated_for_not_relevant_papers_even_if_the_model_returns_one(self):
        def item(pmid, relevance):
            return {"pmid": pmid, "relevance": relevance, "relevance_reason": "r", "summary_en": "en",
                    "summary_ja": "ja", "title_ja": "題", "abstract_ja": "全文訳"}
        output = {pmid: item(pmid, rel) for pmid, rel in
                  (("1", "relevant"), ("2", "not_relevant"), ("3", "uncertain"), ("4", "not_relevant"))}
        with tempfile.TemporaryDirectory() as temp:
            rows = self.run_batch(self.make_db(Path(temp)), output)
        self.assertEqual(rows["1"]["ai_abstract_ja"], "全文訳")
        self.assertEqual(rows["3"]["ai_abstract_ja"], "全文訳")           # uncertain keeps its translation
        self.assertEqual(rows["2"]["ai_abstract_ja"], "")                # not_relevant: not stored
        self.assertEqual(rows["2"]["ai_title_ja"], "題")                 # the title is always written
        self.assertEqual(rows["2"]["relevance_status"], "excluded")
        self.assertEqual(rows["4"]["ai_abstract_ja"], self.batch.NO_ABSTRACT_JA)  # no-abstract sentinel unchanged

    def test_a_cns_gct_paper_is_excluded_with_its_own_label_note_and_no_abstract_translation(self):
        def item(pmid, relevance):
            return {"pmid": pmid, "relevance": relevance, "relevance_reason": "r", "summary_en": "en",
                    "summary_ja": "ja", "title_ja": "題", "abstract_ja": "全文訳"}
        output = {"1": item("1", "relevant"), "2": item("2", "cns_gct"), "3": item("3", "not_relevant"),
                  "4": item("4", "cns_gct")}
        with tempfile.TemporaryDirectory() as temp:
            rows = self.run_batch(self.make_db(Path(temp)), output)
        self.assertEqual((rows["2"]["ai_relevance"], rows["2"]["relevance_status"]), ("cns_gct", "excluded"))
        self.assertEqual(rows["2"]["relevance_note"], self.batch.CNS_NOTE)
        self.assertEqual((rows["2"]["ai_abstract_ja"], rows["2"]["ai_title_ja"], rows["2"]["ai_summary_ja"]), ("", "題", ""))
        self.assertEqual(rows["2"]["ai_summary_en"], "en")      # cns_gct: English summary only
        self.assertIsNone(rows["3"]["relevance_note"])          # plain not_relevant carries no CNS note
        self.assertIsNone(rows["1"]["relevance_note"])
        self.assertIn("cns_gct", self.batch.claude_prompt([{"pmid": "1", "title": "t", "journal_abbrev": "J",
                                                           "journal_title": "J", "publication_year": 2019,
                                                           "abstract": "a"}]))

    def run_main(self, argv_extra, db_dir):
        argv = ["process_batch.py", "--db-dir", str(db_dir), *argv_extra]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as out:
            self.batch.main()
        return out.getvalue()

    def test_the_glossary_is_in_both_prompts_and_its_id_is_logged(self):
        glossary = "| 英語 | 日本語 |\n|---|---|\n| Seminoma | セミノーマ |\n"
        row = {"pmid": "1", "title": "A seminoma case", "journal_abbrev": "J", "journal_title": "J",
               "publication_year": 2019, "abstract": "a", "ai_summary_en": "", "ai_summary_ja": ""}
        other = {**row, "title": "An unrelated paper"}
        self.assertIn("セミノーマ", self.batch.claude_prompt([row], glossary))
        self.assertIn("セミノーマ", self.batch.refill_prompt([row], glossary))
        self.assertNotIn("セミノーマ", self.batch.claude_prompt([row]))
        self.assertNotIn("セミノーマ", self.batch.claude_prompt([other], glossary))  # only terms found in the batch
        self.assertEqual(self.batch.glossary_terms(glossary), 1)
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "cost.jsonl"
            with redirect_stdout(io.StringIO()):
                self.batch._append_cost_log(log, "b", 1, "m", 0.1, glossary)
            self.assertEqual(json.loads(log.read_text())["glossary"], self.batch.glossary_id(glossary))

    def test_a_missing_glossary_stops_the_run_unless_no_glossary_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            db_dir = self.make_db(Path(temp))
            (Path(temp) / "reference" / "terminology" / "terminology_ja.md").unlink()
            with self.assertRaises(SystemExit) as caught:
                self.run_main(["--batch-size", "1"], db_dir)
            self.assertIn("Glossary not found", str(caught.exception))
            self.run_main(["--batch-size", "1", "--no-glossary"], db_dir)  # explicit opt-out: a dry run proceeds

    def test_retranslate_replaces_only_the_translations_keeps_a_backup_and_skips_no_abstract_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_dir = self.make_db(root)
            self.run_batch(db_dir, {
                "1": {"pmid": "1", "relevance": "relevant", "relevance_reason": "r", "summary_en": "english one",
                      "summary_ja": "旧要約", "title_ja": "旧題", "abstract_ja": "旧訳"},
                "4": {"pmid": "4", "relevance": "relevant", "relevance_reason": "r", "summary_en": "x",
                      "summary_ja": "y", "title_ja": "旧題4", "abstract_ja": ""}})
            backup = root / "backup.jsonl"

            def fake_call(prompt, model="", **_):
                self.assertIn("summary_en", prompt)
                self.assertIn("セミノーマ", prompt)  # glossary terms of the batch are injected
                return {"1": {"pmid": "1", "title_ja": "新題", "abstract_ja": "新訳", "summary_ja": "新要約"},
                        "4": {"pmid": "4", "title_ja": "新題4", "abstract_ja": "垂れ流し", "summary_ja": "垂れ流し"}}, 0.02
            conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
            conn.execute("UPDATE papers SET title = 'A seminoma case' WHERE pmid = '1'")
            conn.commit()
            conn.close()
            argv = ["process_batch.py", "--claude", "--retranslate", "--pmids", "1,4,2", "--backup", str(backup),
                    "--db-dir", str(db_dir)]
            with mock.patch.object(self.batch, "call_claude", fake_call), mock.patch.object(sys, "argv", argv), \
                    redirect_stdout(io.StringIO()):
                self.batch.main()
            conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
            rows = {r["pmid"]: dict(r) for r in conn.execute("SELECT * FROM papers")}
            conn.close()
            old = {json.loads(line)["pmid"]: json.loads(line)["old"] for line in backup.read_text().splitlines()}
        self.assertEqual((rows["1"]["ai_title_ja"], rows["1"]["ai_abstract_ja"], rows["1"]["ai_summary_ja"]),
                         ("新題", "新訳", "新要約"))
        self.assertEqual(rows["1"]["ai_summary_en"], "english one")  # English and review state untouched
        self.assertEqual(rows["1"]["relevance_status"], "kept")
        self.assertEqual(old["1"], {"title_ja": "旧題", "abstract_ja": "旧訳", "summary_ja": "旧要約"})
        # no source abstract: only the title is redone, the sentinels stay
        self.assertEqual(rows["4"]["ai_title_ja"], "新題4")
        self.assertEqual(rows["4"]["ai_abstract_ja"], self.batch.NO_ABSTRACT_JA)
        self.assertNotIn("2", old)  # pmid 2 was never translated: not touched, not backed up

    def test_the_first_json_object_is_used_even_if_the_model_adds_trailing_text(self):
        parse = self.batch.parse_claude_payload
        self.assertEqual(parse({"result": '{"papers": []}\n\nNote: done.'}), {"papers": []})
        self.assertEqual(parse({"result": '```json\n{"papers": [1]}\n```\nextra'}), {"papers": [1]})
        self.assertEqual(parse({"result": '{"papers": []}\n{"papers": [2]}'}), {"papers": []})
        with self.assertRaises(ValueError):
            parse({"result": "no json here"})

    def test_prompt_tells_the_model_to_skip_the_abstract_for_not_relevant(self):
        prompt = self.batch.claude_prompt([{
            "pmid": "1", "title": "t", "journal_abbrev": "J", "journal_title": "J", "publication_year": 2019,
            "abstract": "a"}])
        self.assertIn("if relevance is not_relevant or cns_gct, set abstract_ja to an empty string", prompt)

    def test_a_not_relevant_paper_flipped_to_kept_is_completed_by_refill_without_touching_other_rows(self):
        def refill_call(prompt, model="", **_):
            self.assertIn("needs_summary", prompt)
            return {"2": {"pmid": "2", "title_ja": "題2", "abstract_ja": "全文訳2", "summary_en": "SUM-EN",
                          "summary_ja": "要約2"},
                    "1": {"pmid": "1", "title_ja": "NEW", "abstract_ja": "NEW", "summary_en": "NEW",
                          "summary_ja": "NEW"}}, 0.01
        with tempfile.TemporaryDirectory() as temp:
            db_dir = self.make_db(Path(temp))
            self.run_batch(db_dir, {
                "1": {"pmid": "1", "relevance": "relevant", "relevance_reason": "r", "summary_en": "en1",
                      "summary_ja": "ja1", "title_ja": "題1", "abstract_ja": "訳1"},
                "2": {"pmid": "2", "relevance": "not_relevant", "relevance_reason": "r", "summary_en": "",
                      "summary_ja": "", "title_ja": "題", "abstract_ja": "x"}})
            conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
            conn.execute("UPDATE papers SET relevance_status = 'kept' WHERE pmid = '2'")
            conn.commit()
            conn.close()
            argv = ["process_batch.py", "--claude", "--refill-missing-translations", "--db-dir", str(db_dir)]
            with mock.patch.object(self.batch, "call_claude", refill_call), mock.patch.object(sys, "argv", argv), \
                    redirect_stdout(io.StringIO()):
                self.batch.main()
            conn = self.gct_db.connect(self.gct_db.shard_path(db_dir, "2010s"))
            rows = {r["pmid"]: dict(r) for r in conn.execute("SELECT * FROM papers")}
            conn.close()
        self.assertEqual((rows["2"]["ai_abstract_ja"], rows["2"]["ai_summary_en"], rows["2"]["ai_summary_ja"]),
                         ("全文訳2", "SUM-EN", "要約2"))
        # a complete kept row is not selected, so nothing about it changes
        self.assertEqual((rows["1"]["ai_title_ja"], rows["1"]["ai_abstract_ja"], rows["1"]["ai_summary_ja"]),
                         ("題1", "訳1", "ja1"))

if __name__ == "__main__":
    unittest.main()
