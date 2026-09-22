"""Regression tests for programs/pubmed_cleaner/step7_legacy_raw_audit.py.

Uses only temporary directories and synthetic fixtures; never touches the
real data/raw or legacy folders.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROGRAMS_ROOT = Path(__file__).resolve().parents[1]
if str(PROGRAMS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAMS_ROOT))

from pubmed_cleaner import step7_legacy_raw_audit as audit  # noqa: E402


class Step7LegacyRawAuditTest(unittest.TestCase):
    def test_classifies_migrated_pending_and_conflicting_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy"
            current = root / "current"
            legacy.mkdir()
            current.mkdir()

            # Already migrated: identical content is present under a different filename.
            (legacy / "a.txt").write_text("same content", encoding="utf-8")
            (current / "20260101_a.txt").write_text("same content", encoding="utf-8")

            # Not yet migrated: no equivalent content anywhere in the current dir.
            (legacy / "b.txt").write_text("only in legacy", encoding="utf-8")

            # Name conflict: same filename, different content.
            (legacy / "c.txt").write_text("legacy version", encoding="utf-8")
            (current / "c.txt").write_text("current version", encoding="utf-8")

            output = root / "audit.tsv"
            rows = audit.run_audit(legacy, current, output)

            status_by_name = {row["legacy_filename"]: row["status"] for row in rows}
            self.assertEqual(status_by_name["a.txt"], audit.STATUS_ALREADY_MIGRATED)
            self.assertEqual(status_by_name["b.txt"], audit.STATUS_NOT_YET_MIGRATED)
            self.assertEqual(status_by_name["c.txt"], audit.STATUS_NAME_CONFLICT)
            self.assertTrue(output.is_file())

    def test_never_overwrites_an_existing_audit_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy"
            current = root / "current"
            legacy.mkdir()
            current.mkdir()
            (legacy / "a.txt").write_text("x", encoding="utf-8")

            output = root / "audit.tsv"
            audit.run_audit(legacy, current, output)

            with self.assertRaises(FileExistsError):
                audit.run_audit(legacy, current, output)

    def test_legacy_dir_with_no_files_produces_header_only_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy"
            current = root / "current"
            legacy.mkdir()
            current.mkdir()

            output = root / "audit.tsv"
            rows = audit.run_audit(legacy, current, output)

            self.assertEqual(rows, [])
            content = output.read_text(encoding="utf-8")
            self.assertEqual(content.strip("\n").split("\n"), ["\t".join(audit.AUDIT_HEADER)])


if __name__ == "__main__":
    unittest.main()
