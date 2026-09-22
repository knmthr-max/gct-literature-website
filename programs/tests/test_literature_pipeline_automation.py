"""Regression tests for pipeline.py 1.2.0's automation additions.

Covers what test_literature_pipeline.py does not: the mechanical/AI split
of Step 1 (step1_ingest / step1_classify), run_state.json stage tracking,
--from-run/--latest resolution, the raw_ingest_ledger duplicate-processing
guard, and that approve/step2 still work with plain positional arguments
(the pre-1.2.0 call style) unchanged.

Like test_literature_pipeline.py, this file dynamically loads
programs/literature_pipeline/pipeline.py by file path rather than
importing it as a package, and never calls the real Claude Code CLI
(claude=False everywhere), so it can run offline/in CI.

Run this after pipeline_1.2.0_STAGED_REPLACE_ME.py has been swapped in to
replace pipeline.py -- see programs/literature_pipeline/ for the staged
file and its swap-in instructions.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_pipeline():
    path = PROGRAMS / "literature_pipeline" / "pipeline.py"
    spec = importlib.util.spec_from_file_location("maintained_literature_pipeline_automation", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CollectCandidateRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load_pipeline()

    def test_two_fixture_records_become_two_pending_claude_candidates(self):
        matcher = self.pipeline.JIFMatcher(None)
        candidates, stats = self.pipeline.collect_candidate_rows(
            [FIXTURES / "pubmed_sample.txt"], matcher, {}
        )
        self.assertEqual(stats["unique_pmid"], 2)
        self.assertEqual(stats["candidates"], 2)
        self.assertEqual(stats["conflicts"], 0)
        self.assertEqual({row["pmid"] for row in candidates}, {"11111111", "22222222"})
        self.assertTrue(all(row["quality_status"] == "pending_claude" for row in candidates))
        self.assertTrue(all(row["jif_match_status"] == "reference_not_loaded" for row in candidates))

    def test_row_already_identical_in_master_is_skipped(self):
        matcher = self.pipeline.JIFMatcher(None)
        rows = self.pipeline.cleaner.read_pubmed(FIXTURES / "pubmed_sample.txt")
        master_by_pmid = {row["pmid"]: row for row in rows}
        candidates, stats = self.pipeline.collect_candidate_rows(
            [FIXTURES / "pubmed_sample.txt"], matcher, master_by_pmid
        )
        self.assertEqual(stats["existing_master_skipped"], 2)
        self.assertEqual(candidates, [])


class RunStateResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load_pipeline()

    def _write_state(self, intermediate_dir: Path, run_id: str, stage: str) -> Path:
        run_dir = intermediate_dir / run_id
        state = {"run_id": run_id, "stage": stage}
        self.pipeline.write_run_state(run_dir / "run_state.json", state)
        return run_dir

    def test_find_runs_by_stage_filters_correctly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            intermediate_dir = Path(temp_dir)
            self._write_state(intermediate_dir, "20260101T000000+0900", "awaiting_review")
            self._write_state(intermediate_dir, "20260102T000000+0900", "approved")
            matches = self.pipeline.find_runs_by_stage(intermediate_dir, "awaiting_review")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0][1]["run_id"], "20260101T000000+0900")

    def test_resolve_run_with_explicit_from_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            intermediate_dir = Path(temp_dir)
            self._write_state(intermediate_dir, "20260101T000000+0900", "awaiting_review")
            _run_dir, state = self.pipeline.resolve_run(
                intermediate_dir, "20260101T000000+0900", False, "awaiting_review"
            )
            self.assertEqual(state["run_id"], "20260101T000000+0900")

    def test_resolve_run_rejects_wrong_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            intermediate_dir = Path(temp_dir)
            self._write_state(intermediate_dir, "20260101T000000+0900", "approved")
            with self.assertRaises(ValueError):
                self.pipeline.resolve_run(
                    intermediate_dir, "20260101T000000+0900", False, "awaiting_review"
                )

    def test_resolve_run_requires_latest_flag_when_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            intermediate_dir = Path(temp_dir)
            self._write_state(intermediate_dir, "20260101T000000+0900", "awaiting_review")
            self._write_state(intermediate_dir, "20260102T000000+0900", "awaiting_review")
            with self.assertRaises(ValueError):
                self.pipeline.resolve_run(intermediate_dir, "", False, "awaiting_review")
            _run_dir, state = self.pipeline.resolve_run(intermediate_dir, "", True, "awaiting_review")
            self.assertEqual(state["run_id"], "20260102T000000+0900")

    def test_resolve_run_reports_missing_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(FileNotFoundError):
                self.pipeline.resolve_run(Path(temp_dir), "", True, "awaiting_review")


class IngestLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load_pipeline()

    def test_write_ingest_ledger_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifests_dir = Path(temp_dir)
            ledger_path = manifests_dir / "raw_ingest_ledger_run1.json"
            self.pipeline.write_ingest_ledger(ledger_path, "run1", [{"path": "a.txt", "sha256": "abc"}])
            with self.assertRaises(FileExistsError):
                self.pipeline.write_ingest_ledger(ledger_path, "run1", [{"path": "a.txt", "sha256": "abc"}])

    def test_load_ingested_hashes_unions_all_ledger_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifests_dir = Path(temp_dir)
            self.pipeline.write_ingest_ledger(
                manifests_dir / "raw_ingest_ledger_run1.json", "run1", [{"path": "a.txt", "sha256": "hash-a"}]
            )
            self.pipeline.write_ingest_ledger(
                manifests_dir / "raw_ingest_ledger_run2.json", "run2", [{"path": "b.txt", "sha256": "hash-b"}]
            )
            hashes = self.pipeline.load_ingested_hashes(manifests_dir)
            self.assertEqual(hashes, {"hash-a", "hash-b"})


class Step1IngestClassifyLifecycleTests(unittest.TestCase):
    """Walk step1-ingest -> step1-classify (claude=False) -> approve --latest
    -> step2 --latest against temp directories, using the shared
    pubmed_sample.txt fixture (2 PMIDs, no JIF reference).
    """

    @classmethod
    def setUpClass(cls):
        cls.pipeline = load_pipeline()

    def _ingest_args(self, base: Path, raw_dir: Path) -> argparse.Namespace:
        return argparse.Namespace(
            raw_dir=raw_dir,
            jif_reference=[],
            master=None,
            master_dir=base / "data" / "master" / "literature",
            run_id="",
            intermediate_dir=base / "data" / "intermediate",
            manifests_dir=base / "data" / "manifests",
            log_dir=base / "logs" / "runs",
        )

    def _classify_args(self, base: Path, latest: bool = True, claude: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            from_run="",
            latest=latest,
            intermediate_dir=base / "data" / "intermediate",
            claude=claude,
            claude_model="",
            claude_batch_size=5,
            output_dir=base / "data" / "processed" / "literature_candidates",
            review_dir=base / "data" / "processed" / "review_reports",
            log_dir=base / "logs" / "runs",
        )

    def _approve_args(self, base: Path) -> argparse.Namespace:
        return argparse.Namespace(
            candidate=None,
            output=None,
            reviewer="Test Reviewer",
            approve_all_valid=True,
            exceptions=None,
            from_run="",
            latest=True,
            intermediate_dir=base / "data" / "intermediate",
        )

    def _step2_args(self, base: Path) -> argparse.Namespace:
        return argparse.Namespace(
            candidate=None,
            decisions=None,
            run_id="",
            master_dir=base / "data" / "master" / "literature",
            private_jif_dir=base / "data" / "processed" / "private_jif_export",
            from_run="",
            latest=True,
            intermediate_dir=base / "data" / "intermediate",
        )

    def test_full_lifecycle_without_claude(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            raw_dir = base / "data" / "raw" / "pubmed_alerts" / "2026"
            raw_dir.mkdir(parents=True)
            (raw_dir / "sample.txt").write_text(
                (FIXTURES / "pubmed_sample.txt").read_text(encoding="utf-8"), encoding="utf-8"
            )

            # step1-ingest: mechanical half, no AI.
            self.pipeline.step1_ingest(self._ingest_args(base, raw_dir))
            runs = self.pipeline.find_runs_by_stage(base / "data" / "intermediate", "awaiting_ai_start")
            self.assertEqual(len(runs), 1)
            _run_dir, state = runs[0]
            self.assertEqual(len(state["raw_inputs"]), 1)
            ledger_files = list((base / "data" / "manifests").glob("raw_ingest_ledger_*.json"))
            self.assertEqual(len(ledger_files), 1)

            # Re-running step1-ingest on the same raw file must be a no-op
            # (ledger-based dedup guards against repeated launchd triggers).
            self.pipeline.step1_ingest(self._ingest_args(base, raw_dir))
            ledger_files_after = list((base / "data" / "manifests").glob("raw_ingest_ledger_*.json"))
            self.assertEqual(
                len(ledger_files_after), 1, "a second ingest of the same raw file must not add a ledger"
            )

            # step1-classify: AI half, claude=False -> claude_not_run.
            self.pipeline.step1_classify(self._classify_args(base))
            runs = self.pipeline.find_runs_by_stage(base / "data" / "intermediate", "awaiting_review")
            self.assertEqual(len(runs), 1)
            _run_dir, state = runs[0]
            candidate_rows = self.pipeline.read_tsv(Path(state["candidate_path"]))
            self.assertEqual(len(candidate_rows), 2)
            self.assertTrue(all(row["quality_status"] == "claude_not_run" for row in candidate_rows))
            self.assertTrue(Path(state["review_path"]).is_file())

            # latest-review-path helper prints exactly the resolved run's review path.
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.pipeline.print_review_path(
                    argparse.Namespace(from_run="", intermediate_dir=base / "data" / "intermediate")
                )
            self.assertEqual(buffer.getvalue().strip(), state["review_path"])

            # approve --latest: claude_not_run rows are not quality_status
            # "ok", so --approve-all-valid must approve nothing here.
            self.pipeline.approve(self._approve_args(base))
            runs = self.pipeline.find_runs_by_stage(base / "data" / "intermediate", "approved")
            self.assertEqual(len(runs), 1)
            _run_dir, state = runs[0]
            self.assertEqual(state["approved_count"], 0)

            # step2 --latest still runs even with zero approvals; master file
            # is created (no new rows) and the run reaches its final stage.
            self.pipeline.step2(self._step2_args(base))
            runs = self.pipeline.find_runs_by_stage(base / "data" / "intermediate", "master_promoted")
            self.assertEqual(len(runs), 1)
            _run_dir, state = runs[0]
            self.assertEqual(state["master_added"], 0)
            self.assertTrue(Path(state["master_path"]).is_file())

    def test_approve_and_step2_still_work_with_plain_positional_arguments(self):
        """Backward compatibility: the pre-1.2.0 call style (no --from-run/--latest) must be unchanged."""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            candidate_path = base / "candidate.tsv"
            matcher = self.pipeline.JIFMatcher(None)
            candidates, _stats = self.pipeline.collect_candidate_rows(
                [FIXTURES / "pubmed_sample.txt"], matcher, {}
            )
            for row in candidates:
                row["quality_status"] = "ok"
            self.pipeline.write_tsv(candidate_path, candidates, self.pipeline.CANDIDATE_HEADER)

            decisions_path = base / "decisions.tsv"
            approve_args = argparse.Namespace(
                candidate=candidate_path, output=decisions_path, reviewer="Test Reviewer",
                approve_all_valid=True, exceptions=None, from_run="", latest=False,
                intermediate_dir=base / "data" / "intermediate",
            )
            self.pipeline.approve(approve_args)
            decisions = self.pipeline.read_tsv(decisions_path)
            self.assertEqual(len(decisions), 2)
            self.assertTrue(all(row["decision"] == "approved" for row in decisions))

            master_dir = base / "data" / "master" / "literature"
            private_dir = base / "data" / "processed" / "private_jif_export"
            step2_args = argparse.Namespace(
                candidate=candidate_path, decisions=decisions_path, run_id="v1",
                master_dir=master_dir, private_jif_dir=private_dir, from_run="", latest=False,
                intermediate_dir=base / "data" / "intermediate",
            )
            self.pipeline.step2(step2_args)
            master_path = master_dir / "literature_master_v1.tsv"
            self.assertTrue(master_path.is_file())
            master_rows = self.pipeline.read_tsv(master_path)
            self.assertEqual(len(master_rows), 2)


if __name__ == "__main__":
    unittest.main()
