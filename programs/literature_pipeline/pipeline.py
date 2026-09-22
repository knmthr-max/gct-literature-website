#!/usr/bin/env python3
"""Run the review-gated PubMed-to-literature-master workflow.

Step 1 reads immutable PubMed MEDLINE text files, enriches rows from an
optional annual JIF reference, optionally asks Claude Code for bilingual
summaries and controlled classification, and writes review candidates.

Version 1.2.0 adds an automation-friendly split of Step 1 into a mechanical
half (``step1-ingest``: cleaning and JIF matching only, no AI, safe to run
unattended from a file watcher) and an AI half (``step1-classify``: Claude
classification plus candidate/anomaly/review generation, meant to be
triggered deliberately, for example by a one-click launcher). The original
one-shot ``step1`` command is unchanged and still does both halves in a
single run. ``approve`` and ``step2`` gained optional ``--from-run``/
``--latest`` resolution so a click-to-approve launcher does not need to know
file paths. A new ``latest-review-path`` command prints the review HTML path
for the run currently awaiting review, so a launcher script can open it
automatically.

Approval writes a separate decision file. Step 2 accepts only approved rows,
creates a versioned master TSV, and prepares a local-only exact-JIF export.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PROGRAMS_ROOT = Path(__file__).resolve().parents[1]
if str(PROGRAMS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAMS_ROOT))

from pubmed_cleaner import pubmed_cleaner as cleaner  # noqa: E402

__version__ = "1.2.0"

PIPELINE_DIR = Path(__file__).resolve().parent
TYPE_VALUES = ("Clinical", "Basic", "Review", "Unclassified")
JIF_FIELDS = (
    "jif",
    "jif_data_year",
    "jcr_release_year",
    "jif_source",
    "jif_reference_version",
    "jif_match_status",
    "jif_match_key",
)
AI_FIELDS = (
    "summary_ja",
    "summary_en",
    "type",
    "subtype",
    "classification_basis",
    "ai_warning",
    "model_name",
    "prompt_version",
)
REVIEW_FIELDS = (
    "search_keywords",
    "duplicate_status",
    "quality_status",
    "review_status",
    "added_at",
)
CANDIDATE_HEADER = tuple(cleaner.HEADER) + JIF_FIELDS + AI_FIELDS + REVIEW_FIELDS
MASTER_HEADER = CANDIDATE_HEADER + ("reviewer", "reviewed_at", "master_version")
DECISION_HEADER = ("pmid", "decision", "reviewer", "reviewed_at", "note")
JIF_REFERENCE_REQUIRED = ("jif_data_year", "jif")
PROMPT_VERSION = "gct-literature-bilingual-v1.0.0"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as source:
        return [dict(row) for row in csv.DictReader(source, delimiter="\t")]


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(
            destination, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def normalize_issn(value: str) -> str:
    return re.sub(r"[^0-9X]", "", (value or "").upper())


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def json_list(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    return [str(item) for item in parsed] if isinstance(parsed, list) else [str(parsed)]


def search_keywords(row: Mapping[str, str]) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in json_list(row.get("mesh_terms", "")) + json_list(row.get("author_keywords", "")):
        key = value.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def core_fingerprint(row: Mapping[str, str]) -> str:
    core = {key: row.get(key, "") for key in (
        "pmid", "publication_year", "title", "abstract", "first_author", "journal_abbrev", "issn", "eissn"
    )}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class JIFMatcher:
    def __init__(self, reference: Path | Sequence[Path] | None):
        if reference is None:
            self.reference_paths: list[Path] = []
        elif isinstance(reference, Path):
            self.reference_paths = [reference]
        else:
            self.reference_paths = list(reference)
        self.rows: list[dict[str, str]] = []
        self.by_identifier: dict[tuple[str, str], list[dict[str, str]]] = {}
        self.by_title: dict[tuple[str, str], list[dict[str, str]]] = {}
        for reference_path in self.reference_paths:
            reference_rows = read_tsv(reference_path)
            self.rows.extend(reference_rows)
        if self.rows:
            missing = [field for field in JIF_REFERENCE_REQUIRED if field not in self.rows[0]]
            if missing:
                raise ValueError(f"JIF reference lacks required columns: {', '.join(missing)}")
        for row in self.rows:
            year = row.get("jif_data_year", "").strip()
            for identifier in (row.get("issn", ""), row.get("eissn", "")):
                normalized = normalize_issn(identifier)
                if normalized and year:
                    self.by_identifier.setdefault((normalized, year), []).append(row)
            for title_field in ("journal_title", "journal_abbreviation"):
                title = normalize_title(row.get(title_field, ""))
                if title and year:
                    bucket = self.by_title.setdefault((title, year), [])
                    if row not in bucket:
                        bucket.append(row)

    def match(self, article: Mapping[str, str]) -> dict[str, str]:
        year = article.get("publication_year", "").strip()
        empty = {field: "" for field in JIF_FIELDS}
        empty["jif_data_year"] = year
        if not self.reference_paths:
            empty["jif_match_status"] = "reference_not_loaded"
            return empty
        if not year:
            empty["jif_match_status"] = "publication_year_missing"
            return empty

        candidates: list[dict[str, str]] = []
        match_key = ""
        for field in ("issn", "eissn"):
            identifier = normalize_issn(article.get(field, ""))
            if identifier:
                matches = self.by_identifier.get((identifier, year), [])
                if matches:
                    candidates = matches
                    match_key = f"{field}:{identifier}"
                    break
        if not candidates:
            for field in ("journal_title", "journal_abbrev"):
                title = normalize_title(article.get(field, ""))
                if title:
                    matches = self.by_title.get((title, year), [])
                    if matches:
                        candidates = matches
                        match_key = f"{field}:{title}"
                        break

        if len(candidates) > 1:
            empty["jif_match_status"] = "ambiguous_match"
            empty["jif_match_key"] = match_key
            return empty
        if not candidates:
            identifiers = [normalize_issn(article.get(key, "")) for key in ("issn", "eissn")]
            journal_exists = any(
                identifier and any(key[0] == identifier for key in self.by_identifier)
                for identifier in identifiers
            )
            empty["jif_match_status"] = "year_not_found" if journal_exists else "journal_not_found"
            return empty

        reference = candidates[0]
        empty.update({
            "jif": reference.get("jif", ""),
            "jif_data_year": reference.get("jif_data_year", year),
            "jcr_release_year": reference.get("jcr_release_year", ""),
            "jif_source": reference.get("source", ""),
            "jif_reference_version": reference.get("reference_version", ""),
            "jif_match_status": "exact" if reference.get("jif", "").strip() else "suppressed_or_unavailable",
            "jif_match_key": match_key,
        })
        return empty


def subtype_values() -> list[str]:
    data = json.loads((PIPELINE_DIR / "subtype_vocabulary.json").read_text(encoding="utf-8"))
    return list(data["values"])


def claude_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pmid": {"type": "string"},
                        "summary_ja": {"type": "string"},
                        "summary_en": {"type": "string"},
                        "type": {"type": "string", "enum": list(TYPE_VALUES[:3])},
                        "subtype": {"type": "string", "enum": subtype_values()},
                        "classification_basis": {"type": "string", "enum": ["abstract", "metadata_only"]},
                        "ai_warning": {"type": "string"},
                    },
                    "required": [
                        "pmid", "summary_ja", "summary_en", "type", "subtype",
                        "classification_basis", "ai_warning"
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["articles"],
        "additionalProperties": False,
    }


def claude_prompt(rows: Sequence[Mapping[str, str]]) -> str:
    payload = []
    for row in rows:
        payload.append({
            "pmid": row.get("pmid", ""),
            "title": row.get("title", ""),
            "abstract": row.get("abstract", ""),
            "publication_types": json_list(row.get("publication_types", "")),
            "mesh_terms": json_list(row.get("mesh_terms", "")),
            "author_keywords": json_list(row.get("author_keywords", "")),
        })
    return (
        "You classify already-screened germ-cell-tumor literature. All records must be included. "
        "Use only supplied metadata. For records with an abstract, write a faithful Japanese summary of "
        "120-200 Japanese characters and an English summary of 60-100 words. Never add facts not stated. "
        "If abstract is empty, set summary_ja to 'Abstractなし', summary_en to 'No abstract available.', "
        "classification_basis to 'metadata_only', and ai_warning to 'abstract_missing'. Otherwise use "
        "classification_basis 'abstract'. Choose type from Clinical, Basic, Review and subtype from the "
        "provided schema enum. Use Other only if no listed subtype fits. Return one result per PMID. "
        "Return only a JSON object that conforms exactly to this JSON Schema; do not use Markdown fences:\n"
        + json.dumps(claude_schema(), ensure_ascii=False, separators=(",", ":"))
        + "\n\nINPUT ARTICLES:\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def parse_claude_payload(response: Mapping[str, Any]) -> dict[str, Any]:
    structured = response.get("structured_output")
    if isinstance(structured, dict):
        return structured
    result = response.get("result")
    if not isinstance(result, str):
        raise ValueError("Claude Code JSON response did not contain a textual result")
    text = result.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Claude result must be a JSON object")
    return parsed


def call_claude(rows: Sequence[Mapping[str, str]], model: str = "") -> dict[str, dict[str, str]]:
    if shutil.which("claude") is None:
        raise RuntimeError("Claude Code executable was not found. Install/login before using --claude.")
    command = [
        "claude", "-p", "Complete the JSON classification task supplied on standard input.",
        "--output-format", "json", "--max-turns", "1",
    ]
    if model:
        command.extend(["--model", model])
    completed = subprocess.run(
        command, input=claude_prompt(rows), capture_output=True, text=True, check=False
    )
    if completed.returncode:
        raise RuntimeError(f"Claude Code failed ({completed.returncode}): {completed.stderr.strip()}")
    response = json.loads(completed.stdout)
    structured = parse_claude_payload(response)
    model_name = str(response.get("model", model or "claude-code-pro-default"))
    result = {}
    for article in structured.get("articles", []):
        item = {key: str(value) for key, value in article.items()}
        item["model_name"] = model_name
        item["prompt_version"] = PROMPT_VERSION
        result[item["pmid"]] = item
    return result


def default_ai_fields(row: Mapping[str, str]) -> dict[str, str]:
    missing = not row.get("abstract", "").strip()
    return {
        "summary_ja": "Abstractなし" if missing else "",
        "summary_en": "No abstract available." if missing else "",
        "type": "Unclassified",
        "subtype": "Other",
        "classification_basis": "metadata_only" if missing else "abstract",
        "ai_warning": "abstract_missing;claude_not_run" if missing else "claude_not_run",
        "model_name": "",
        "prompt_version": PROMPT_VERSION,
    }


def validate_ai_result(source: Mapping[str, str], result: Mapping[str, str]) -> list[str]:
    """Return machine-readable reasons that block bulk approval."""
    problems: list[str] = []
    abstract_missing = not source.get("abstract", "").strip()
    summary_ja = result.get("summary_ja", "").strip()
    summary_en = result.get("summary_en", "").strip()
    if abstract_missing:
        if summary_ja != "Abstractなし" or summary_en != "No abstract available.":
            problems.append("abstract_missing_sentinel_invalid")
        if result.get("classification_basis") != "metadata_only":
            problems.append("classification_basis_invalid")
    else:
        ja_length = len(re.sub(r"\s+", "", summary_ja))
        en_words = len(re.findall(r"\b[\w'-]+\b", summary_en, flags=re.UNICODE))
        if not 120 <= ja_length <= 200:
            problems.append("summary_ja_length")
        if not 60 <= en_words <= 100:
            problems.append("summary_en_length")
        if result.get("classification_basis") != "abstract":
            problems.append("classification_basis_invalid")
    if result.get("type") not in TYPE_VALUES[:3]:
        problems.append("type_outside_vocabulary")
    if result.get("subtype") not in subtype_values():
        problems.append("subtype_outside_vocabulary")
    if result.get("subtype") == "Other":
        problems.append("subtype_other_needs_review")
    publication_types = " ".join(json_list(source.get("publication_types", ""))).casefold()
    if any(term in publication_types for term in ("review", "meta-analysis")) and result.get("type") != "Review":
        problems.append("publication_type_classification_conflict")
    return list(dict.fromkeys(problems))


def latest_master(master_dir: Path) -> Path | None:
    files = sorted(master_dir.glob("literature_master_*.tsv"))
    return files[-1] if files else None


def render_review(path: Path, rows: Sequence[Mapping[str, str]], stats: Mapping[str, Any]) -> None:
    table_rows = []
    for row in rows:
        abstract_state = "なし" if not row.get("abstract", "").strip() else "あり"
        table_rows.append(
            "<tr>" + "".join(
                f"<td>{html.escape(str(value))}</td>"
                for value in (
                    row.get("pmid", ""), row.get("publication_year", ""), row.get("title", ""),
                    abstract_state, row.get("summary_ja", ""), row.get("summary_en", ""),
                    row.get("type", ""), row.get("subtype", ""), row.get("jif_match_status", ""),
                    row.get("quality_status", ""), row.get("ai_warning", ""),
                )
            ) + "</tr>"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Step 1 review</title><style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#202124}} table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccd1d8;padding:6px;vertical-align:top;max-width:380px}} th{{position:sticky;top:0;background:#eef2f7}}
.summary{{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:18px}} .summary div{{border:1px solid #ccd1d8;border-radius:8px;padding:10px}}
</style></head><body><h1>Step 1 review</h1>
<div class="summary">{''.join(f'<div><strong>{html.escape(str(k))}</strong><br>{html.escape(str(v))}</div>' for k, v in stats.items())}</div>
<p>このHTMLは確認用です。承認は別のdecision TSVとして記録されます。</p>
<table><thead><tr><th>PMID</th><th>Year</th><th>Title</th><th>Abstract</th><th>Summary JA</th><th>Summary EN</th><th>Type</th><th>Subtype</th><th>JIF match</th><th>Quality</th><th>Warning</th></tr></thead>
<tbody>{''.join(table_rows)}</tbody></table></body></html>""", encoding="utf-8")


def step1(args: argparse.Namespace) -> None:
    """Original one-shot Step 1: mechanical cleaning, JIF match, and (optionally) Claude, in one run.

    Unchanged since 1.1.0. Kept for manual/ad-hoc use. See step1_ingest and
    step1_classify below for the automation-friendly split of this same
    logic into two independently triggerable halves.
    """
    raw_files = sorted(path for path in args.raw_dir.rglob("*.txt") if path.is_file())
    if not raw_files:
        raise FileNotFoundError(f"No .txt files found under {args.raw_dir}")
    matcher = JIFMatcher(args.jif_reference)
    master_by_pmid: dict[str, dict[str, str]] = {}
    master_path = args.master or latest_master(args.master_dir)
    if master_path and master_path.is_file():
        master_by_pmid = {row.get("pmid", ""): row for row in read_tsv(master_path)}

    unique: dict[str, dict[str, str]] = {}
    conflicts: set[str] = set()
    duplicate_same = 0
    input_manifest = []
    for raw_file in raw_files:
        input_manifest.append({"path": raw_file.as_posix(), "sha256": sha256(raw_file)})
        for row in cleaner.read_pubmed(raw_file):
            pmid = row["pmid"]
            if pmid in unique:
                if core_fingerprint(unique[pmid]) == core_fingerprint(row):
                    duplicate_same += 1
                else:
                    conflicts.add(pmid)
                continue
            unique[pmid] = row

    candidates: list[dict[str, str]] = []
    skipped_master = 0
    for pmid, source in unique.items():
        if pmid in master_by_pmid and core_fingerprint(master_by_pmid[pmid]) == core_fingerprint(source):
            skipped_master += 1
            continue
        row = dict(source)
        row.update(matcher.match(row))
        row.update(default_ai_fields(row))
        row["search_keywords"] = search_keywords(row)
        row["duplicate_status"] = "conflict" if pmid in conflicts else "unique"
        row["quality_status"] = (
            "duplicate_conflict" if pmid in conflicts
            else ("pending_claude" if args.claude else "claude_not_run")
        )
        row["review_status"] = "pending"
        row["added_at"] = ""
        candidates.append(row)

    claude_errors = 0
    claude_error_messages: list[str] = []
    if args.claude:
        for start in range(0, len(candidates), args.claude_batch_size):
            batch = candidates[start:start + args.claude_batch_size]
            try:
                enriched = call_claude(batch, args.claude_model)
                for row in batch:
                    result = enriched.get(row["pmid"])
                    if result:
                        row.update(result)
                        problems = validate_ai_result(row, result)
                        if problems:
                            warning = ";".join(filter(None, (row.get("ai_warning", ""), *problems)))
                            row["ai_warning"] = warning
                            row["quality_status"] = "claude_validation_error"
                        elif row.get("duplicate_status") != "conflict":
                            row["quality_status"] = "ok"
                    else:
                        row["quality_status"] = "claude_result_missing"
            except Exception as error:  # keep candidates reviewable and retryable
                claude_errors += 1
                message = f"{type(error).__name__}: {error}"
                if message not in claude_error_messages:
                    claude_error_messages.append(message)
                for row in batch:
                    row["quality_status"] = "claude_error"
                    row["ai_warning"] = f"claude_error:{type(error).__name__}"

    identifier = args.run_id or run_id()
    candidate_path = args.output_dir / identifier / f"candidate_{identifier}.tsv"
    anomaly_path = args.output_dir / identifier / f"anomalies_{identifier}.tsv"
    review_path = args.review_dir / identifier / f"review_{identifier}.html"
    write_tsv(candidate_path, candidates, CANDIDATE_HEADER)
    anomalies = [row for row in candidates if row.get("quality_status") != "ok"]
    write_tsv(anomaly_path, anomalies, CANDIDATE_HEADER)
    stats = {
        "raw files": len(raw_files), "unique PMID": len(unique), "candidates": len(candidates),
        "same duplicates skipped": duplicate_same, "existing master skipped": skipped_master,
        "conflicts": len(conflicts), "anomalies": len(anomalies), "Claude batch errors": claude_errors,
    }
    render_review(review_path, candidates, stats)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.log_dir / f"{identifier}_step1.json"
    log_path.write_text(json.dumps({
        "run_id": identifier, "program_version": __version__, "created_at": now_utc(),
        "inputs": input_manifest,
        "jif_references": [path.as_posix() for path in args.jif_reference],
        "master_compared": master_path.as_posix() if master_path else None,
        "candidate": candidate_path.as_posix(), "anomalies": anomaly_path.as_posix(),
        "review": review_path.as_posix(), "stats": stats,
        "claude_error_messages": claude_error_messages[:10],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"candidate": str(candidate_path), "review": str(review_path), "stats": stats}, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 1.2.0: run-state tracking and the automation-friendly split of Step 1.
#
# A "run" is identified by the same run_id used for candidate/review/log
# file names. Its live progress is tracked in one small, mutable JSON file:
#   data/intermediate/<run_id>/run_state.json
# with a "stage" field that moves forward as
#   awaiting_ai_start -> awaiting_review -> approved -> master_promoted
# This file lives under data/intermediate/, which DIRECTORY_MANIFEST.md
# classifies as regenerable working data, so overwriting it in place as a
# run progresses is expected and does not violate the "no overwrite" rules
# that apply to data/raw/ or data/manifests/.
# ---------------------------------------------------------------------------


def read_run_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_run_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def find_runs_by_stage(intermediate_dir: Path, stage: str) -> list[tuple[Path, dict[str, Any]]]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    if not intermediate_dir.is_dir():
        return matches
    for run_dir in sorted(path for path in intermediate_dir.iterdir() if path.is_dir()):
        state_path = run_dir / "run_state.json"
        if not state_path.is_file():
            continue
        state = read_run_state(state_path)
        if state.get("stage") == stage:
            matches.append((run_dir, state))
    return matches


def resolve_run(
    intermediate_dir: Path, from_run: str, latest: bool, required_stage: str
) -> tuple[Path, dict[str, Any]]:
    """Find the run_state.json for a run at required_stage.

    Pass from_run to select an exact run id. Otherwise, pass latest=True to
    pick the most recently created run at that stage when more than one
    qualifies (run ids are timestamp-based, so lexicographic order is
    chronological order).
    """
    if from_run:
        run_dir = intermediate_dir / from_run
        state_path = run_dir / "run_state.json"
        if not state_path.is_file():
            raise FileNotFoundError(f"No run_state.json found for run id {from_run!r} under {intermediate_dir}")
        state = read_run_state(state_path)
        if state.get("stage") != required_stage:
            raise ValueError(
                f"Run {from_run!r} is at stage {state.get('stage')!r}, expected {required_stage!r}."
            )
        return run_dir, state

    matches = find_runs_by_stage(intermediate_dir, required_stage)
    if not matches:
        raise FileNotFoundError(f"No run under {intermediate_dir} is at stage {required_stage!r}.")
    if len(matches) > 1 and not latest:
        names = ", ".join(run_dir.name for run_dir, _ in matches)
        raise ValueError(
            f"Multiple runs are at stage {required_stage!r}: {names}. "
            "Pass --from-run to choose one, or --latest to use the most recently created run."
        )
    return max(matches, key=lambda pair: pair[0].name)


def load_ingested_hashes(manifests_dir: Path) -> set[str]:
    """Union the sha256 values recorded in every raw_ingest_ledger_*.json file.

    Each step1-ingest run writes one new, never-overwritten ledger file, so
    checking "has this raw file already been ingested" means scanning all of
    them rather than mutating a single shared ledger.
    """
    hashes: set[str] = set()
    if not manifests_dir.is_dir():
        return hashes
    for ledger_path in sorted(manifests_dir.glob("raw_ingest_ledger_*.json")):
        try:
            payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for entry in payload.get("files", []):
            digest = entry.get("sha256")
            if digest:
                hashes.add(digest)
    return hashes


def write_ingest_ledger(path: Path, run_identifier: str, files: Sequence[Mapping[str, str]]) -> None:
    if path.exists():
        raise FileExistsError(f"{path} already exists; ledgers are append-only, one new file per run.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "run_id": run_identifier, "created_at": now_utc(), "files": list(files),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_candidate_rows(
    raw_files: Sequence[Path], matcher: JIFMatcher, master_by_pmid: Mapping[str, Mapping[str, str]]
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Shared mechanical Step 1 logic: dedupe raw rows, match JIF, seed AI defaults.

    Every non-conflicting, non-master-duplicate row is marked
    quality_status="pending_claude" so that step1_classify (run later, maybe
    much later) knows which rows are still waiting for AI classification.
    """
    unique: dict[str, dict[str, str]] = {}
    conflicts: set[str] = set()
    duplicate_same = 0
    for raw_file in raw_files:
        for row in cleaner.read_pubmed(raw_file):
            pmid = row["pmid"]
            if pmid in unique:
                if core_fingerprint(unique[pmid]) == core_fingerprint(row):
                    duplicate_same += 1
                else:
                    conflicts.add(pmid)
                continue
            unique[pmid] = row

    candidates: list[dict[str, str]] = []
    skipped_master = 0
    for pmid, source in unique.items():
        if pmid in master_by_pmid and core_fingerprint(master_by_pmid[pmid]) == core_fingerprint(source):
            skipped_master += 1
            continue
        row = dict(source)
        row.update(matcher.match(row))
        row.update(default_ai_fields(row))
        row["search_keywords"] = search_keywords(row)
        row["duplicate_status"] = "conflict" if pmid in conflicts else "unique"
        row["quality_status"] = "duplicate_conflict" if pmid in conflicts else "pending_claude"
        row["review_status"] = "pending"
        row["added_at"] = ""
        candidates.append(row)

    stats = {
        "unique_pmid": len(unique), "candidates": len(candidates),
        "same_duplicates_skipped": duplicate_same, "existing_master_skipped": skipped_master,
        "conflicts": len(conflicts),
    }
    return candidates, stats


def step1_ingest(args: argparse.Namespace) -> None:
    """Mechanical half of Step 1: clean + JIF-match new raw files only, no AI.

    Safe to trigger unattended (for example from a launchd file watcher):
    never calls Claude, and skips any raw file already recorded in a prior
    run's ledger so repeated triggers on the same directory are harmless.
    """
    raw_files = sorted(path for path in args.raw_dir.rglob("*.txt") if path.is_file())
    if not raw_files:
        raise FileNotFoundError(f"No .txt files found under {args.raw_dir}")

    already_ingested = load_ingested_hashes(args.manifests_dir)
    input_manifest: list[dict[str, str]] = []
    new_raw_files: list[Path] = []
    for raw_file in raw_files:
        digest = sha256(raw_file)
        if digest in already_ingested:
            continue
        input_manifest.append({"path": raw_file.as_posix(), "sha256": digest})
        new_raw_files.append(raw_file)

    if not new_raw_files:
        print(json.dumps({"status": "no_new_raw_files", "raw_files_scanned": len(raw_files)}, ensure_ascii=False))
        return

    matcher = JIFMatcher(args.jif_reference)
    master_path = args.master or latest_master(args.master_dir)
    master_by_pmid: dict[str, dict[str, str]] = {}
    if master_path and master_path.is_file():
        master_by_pmid = {row.get("pmid", ""): row for row in read_tsv(master_path)}

    candidates, stats = collect_candidate_rows(new_raw_files, matcher, master_by_pmid)
    stats["raw_files"] = len(new_raw_files)

    identifier = args.run_id or run_id()
    run_dir = args.intermediate_dir / identifier
    clean_path = run_dir / f"clean_jif_{identifier}.tsv"
    write_tsv(clean_path, candidates, CANDIDATE_HEADER)

    ledger_path = args.manifests_dir / f"raw_ingest_ledger_{identifier}.json"
    write_ingest_ledger(ledger_path, identifier, input_manifest)

    args.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.log_dir / f"{identifier}_step1_ingest.json"
    log_path.write_text(json.dumps({
        "run_id": identifier, "program_version": __version__, "created_at": now_utc(),
        "inputs": input_manifest,
        "jif_references": [path.as_posix() for path in args.jif_reference],
        "master_compared": master_path.as_posix() if master_path else None,
        "clean_jif": clean_path.as_posix(), "stats": stats,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    state = {
        "run_id": identifier, "program_version": __version__,
        "created_at": now_utc(), "updated_at": now_utc(),
        "stage": "awaiting_ai_start",
        "raw_inputs": input_manifest,
        "jif_references": [path.as_posix() for path in args.jif_reference],
        "master_compared": master_path.as_posix() if master_path else None,
        "clean_jif_path": clean_path.as_posix(),
        "stats": stats,
    }
    write_run_state(run_dir / "run_state.json", state)
    print(json.dumps({
        "run_id": identifier, "clean_jif": str(clean_path), "stage": "awaiting_ai_start", "stats": stats,
    }, ensure_ascii=False))


def step1_classify(args: argparse.Namespace) -> None:
    """AI half of Step 1: classify a run's clean_jif TSV and finalize review outputs.

    Reads the run selected by --from-run/--latest (must be at stage
    awaiting_ai_start), optionally calls Claude in batches exactly like the
    one-shot step1 command, then writes candidate/anomaly/review outputs and
    advances the run to stage awaiting_review.
    """
    run_dir, state = resolve_run(args.intermediate_dir, args.from_run, args.latest, "awaiting_ai_start")
    identifier = state["run_id"]
    clean_path = Path(state["clean_jif_path"])
    candidates = read_tsv(clean_path)

    claude_errors = 0
    claude_error_messages: list[str] = []
    if args.claude:
        total_batches = (len(candidates) + args.claude_batch_size - 1) // args.claude_batch_size
        progress_path = run_dir / "classify_progress.json"
        for batch_index, start in enumerate(range(0, len(candidates), args.claude_batch_size), start=1):
            batch = candidates[start:start + args.claude_batch_size]
            try:
                enriched = call_claude(batch, args.claude_model)
                for row in batch:
                    result = enriched.get(row["pmid"])
                    if result:
                        row.update(result)
                        problems = validate_ai_result(row, result)
                        if problems:
                            warning = ";".join(filter(None, (row.get("ai_warning", ""), *problems)))
                            row["ai_warning"] = warning
                            row["quality_status"] = "claude_validation_error"
                        elif row.get("duplicate_status") != "conflict":
                            row["quality_status"] = "ok"
                    else:
                        row["quality_status"] = "claude_result_missing"
            except Exception as error:  # keep candidates reviewable and retryable
                claude_errors += 1
                message = f"{type(error).__name__}: {error}"
                if message not in claude_error_messages:
                    claude_error_messages.append(message)
                for row in batch:
                    row["quality_status"] = "claude_error"
                    row["ai_warning"] = f"claude_error:{type(error).__name__}"
            print(f"[step1-classify] batch {batch_index}/{total_batches} done "
                  f"({len(batch)} papers, {claude_errors} batch errors so far)", flush=True)
            progress_path.write_text(json.dumps({
                "run_id": identifier, "batch": batch_index, "total_batches": total_batches,
                "papers_processed": min(start + args.claude_batch_size, len(candidates)),
                "papers_total": len(candidates), "claude_errors_so_far": claude_errors,
                "updated_at": now_utc(),
            }, ensure_ascii=False), encoding="utf-8")
    else:
        for row in candidates:
            if row.get("quality_status") == "pending_claude":
                row["quality_status"] = "claude_not_run"

    candidate_path = args.output_dir / identifier / f"candidate_{identifier}.tsv"
    anomaly_path = args.output_dir / identifier / f"anomalies_{identifier}.tsv"
    review_path = args.review_dir / identifier / f"review_{identifier}.html"
    write_tsv(candidate_path, candidates, CANDIDATE_HEADER)
    anomalies = [row for row in candidates if row.get("quality_status") != "ok"]
    write_tsv(anomaly_path, anomalies, CANDIDATE_HEADER)

    stats = dict(state.get("stats", {}))
    stats["anomalies"] = len(anomalies)
    stats["claude_batch_errors"] = claude_errors
    stats["claude_used"] = bool(args.claude)
    render_review(review_path, candidates, stats)

    args.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.log_dir / f"{identifier}_step1_classify.json"
    log_path.write_text(json.dumps({
        "run_id": identifier, "program_version": __version__, "created_at": now_utc(),
        "clean_jif": str(clean_path), "claude": bool(args.claude),
        "candidate": str(candidate_path), "anomalies": str(anomaly_path),
        "review": str(review_path), "stats": stats,
        "claude_error_messages": claude_error_messages[:10],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    state.update({
        "stage": "awaiting_review",
        "updated_at": now_utc(),
        "candidate_path": str(candidate_path),
        "anomaly_path": str(anomaly_path),
        "review_path": str(review_path),
        "stats": stats,
        "claude_used": bool(args.claude),
    })
    write_run_state(run_dir / "run_state.json", state)

    print(json.dumps({
        "run_id": identifier, "candidate": str(candidate_path), "review": str(review_path), "stats": stats,
    }, ensure_ascii=False))


def print_review_path(args: argparse.Namespace) -> None:
    """Print only the review HTML path for the run awaiting review (for `open "$(...)"`)."""
    _run_dir, state = resolve_run(args.intermediate_dir, args.from_run, True, "awaiting_review")
    review_path = state.get("review_path")
    if not review_path:
        raise FileNotFoundError("Resolved run has no review_path recorded yet.")
    print(review_path)


def retry_classify(args: argparse.Namespace) -> None:
    """Reset a run back to awaiting_ai_start so step1-classify can be retried.

    Use this after a step1-classify attempt failed for an infrastructure
    reason (e.g. the claude CLI was not on PATH or not logged in) rather
    than a data problem. Only rewrites run_state.json: raw files, the
    clean_jif TSV from step1-ingest, and any master rows already promoted
    are never touched. Refuses to retry a run that already promoted rows to
    master unless --force is given.
    """
    run_dir = args.intermediate_dir / args.run_id
    state_path = run_dir / "run_state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"No run_state.json found for run id {args.run_id!r} under {args.intermediate_dir}")
    state = read_run_state(state_path)
    if "clean_jif_path" not in state:
        raise ValueError(f"Run {args.run_id!r} has no clean_jif_path recorded; nothing to retry.")
    if state.get("stage") == "master_promoted" and state.get("master_added", 0) > 0 and not args.force:
        raise ValueError(
            f"Run {args.run_id!r} already promoted {state.get('master_added')} row(s) to master. "
            "Retrying would re-classify and could create a second, inconsistent master version. "
            "Pass --force if you are certain this is safe."
        )
    for key in ("candidate_path", "anomaly_path", "review_path", "decisions_path",
                "approved_count", "master_path", "private_jif_export",
                "master_added", "master_skipped", "master_conflicts"):
        state.pop(key, None)
    state["stage"] = "awaiting_ai_start"
    state["updated_at"] = now_utc()
    state["retry_count"] = state.get("retry_count", 0) + 1
    write_run_state(state_path, state)
    print(json.dumps({
        "run_id": args.run_id, "stage": "awaiting_ai_start", "retry_count": state["retry_count"],
    }, ensure_ascii=False))


def approve(args: argparse.Namespace) -> None:
    run_dir: Path | None = None
    state: dict[str, Any] | None = None
    if getattr(args, "from_run", "") or getattr(args, "latest", False):
        run_dir, state = resolve_run(args.intermediate_dir, args.from_run, args.latest, "awaiting_review")
        candidate_path = Path(state["candidate_path"])
        output_path = args.output or (run_dir / f"decisions_{state['run_id']}.tsv")
    else:
        if args.candidate is None:
            raise SystemExit("candidate TSV is required unless --from-run/--latest is used")
        if args.output is None:
            raise SystemExit("--output is required unless --from-run/--latest is used")
        candidate_path = args.candidate
        output_path = args.output

    rows = read_tsv(candidate_path)
    exceptions: dict[str, dict[str, str]] = {}
    if args.exceptions:
        exceptions = {row.get("pmid", ""): row for row in read_tsv(args.exceptions)}
    reviewed_at = now_utc()
    decisions = []
    for row in rows:
        pmid = row.get("pmid", "")
        exception = exceptions.get(pmid)
        if exception:
            decision = exception.get("decision", "needs_edit")
            note = exception.get("note", "exception")
        elif args.approve_all_valid and row.get("quality_status") == "ok":
            decision = "approved"
            note = "bulk approved after Step 1 review"
        else:
            decision = "needs_edit"
            note = "not eligible for bulk approval"
        decisions.append({
            "pmid": pmid, "decision": decision, "reviewer": args.reviewer,
            "reviewed_at": reviewed_at, "note": note,
        })
    write_tsv(output_path, decisions, DECISION_HEADER)
    approved_count = sum(d["decision"] == "approved" for d in decisions)
    print(f"Completed: {output_path} ({approved_count} approved)")

    if state is not None and run_dir is not None:
        state["stage"] = "approved"
        state["decisions_path"] = str(output_path)
        state["approved_count"] = approved_count
        state["updated_at"] = now_utc()
        write_run_state(run_dir / "run_state.json", state)


def jif_tier(value: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if number < 1:
        return "low"
    if number < 3:
        return "moderate"
    if number < 5:
        return "high"
    return "very-high"


def step2(args: argparse.Namespace) -> None:
    run_dir: Path | None = None
    state: dict[str, Any] | None = None
    if getattr(args, "from_run", "") or getattr(args, "latest", False):
        run_dir, state = resolve_run(args.intermediate_dir, args.from_run, args.latest, "approved")
        candidate_path = Path(state["candidate_path"])
        decisions_path = Path(state["decisions_path"])
        identifier = args.run_id or state["run_id"]
    else:
        if args.candidate is None or args.decisions is None:
            raise SystemExit("candidate and decisions TSVs are required unless --from-run/--latest is used")
        candidate_path = args.candidate
        decisions_path = args.decisions
        identifier = args.run_id or run_id()

    candidates = {row.get("pmid", ""): row for row in read_tsv(candidate_path)}
    decisions = {row.get("pmid", ""): row for row in read_tsv(decisions_path)}
    existing_files = sorted(args.master_dir.glob("literature_master_*.tsv"))
    existing_rows = read_tsv(existing_files[-1]) if existing_files else []
    merged = {row.get("pmid", ""): row for row in existing_rows}
    added = 0
    skipped = 0
    conflicts = []
    for pmid, decision in decisions.items():
        if decision.get("decision") != "approved" or pmid not in candidates:
            continue
        candidate = dict(candidates[pmid])
        candidate["review_status"] = "approved"
        candidate["reviewer"] = decision.get("reviewer", "")
        candidate["reviewed_at"] = decision.get("reviewed_at", "")
        candidate["added_at"] = candidate.get("added_at") or decision.get("reviewed_at", "")
        candidate["master_version"] = identifier
        if pmid in merged:
            if core_fingerprint(merged[pmid]) == core_fingerprint(candidate):
                skipped += 1
            else:
                conflicts.append(candidate)
            continue
        merged[pmid] = candidate
        added += 1

    args.master_dir.mkdir(parents=True, exist_ok=True)
    master_path = args.master_dir / f"literature_master_{identifier}.tsv"
    ordered = sorted(merged.values(), key=lambda row: (row.get("publication_year", ""), row.get("pmid", "")), reverse=True)
    write_tsv(master_path, ordered, MASTER_HEADER)
    conflict_path = args.master_dir / f"conflicts_{identifier}.tsv"
    write_tsv(conflict_path, conflicts, MASTER_HEADER)

    private_rows = []
    for row in ordered:
        private_rows.append({
            "pmid": row.get("pmid", ""), "issn": row.get("issn", ""), "eissn": row.get("eissn", ""),
            "journal_title": row.get("journal_title", "") or row.get("journal_abbrev", ""),
            "publication_year": row.get("publication_year", ""), "jif": row.get("jif", ""),
            "jif_data_year": row.get("jif_data_year", ""), "jcr_release_year": row.get("jcr_release_year", ""),
            "jif_source": row.get("jif_source", ""), "jif_match_status": row.get("jif_match_status", ""),
            "if_tier": jif_tier(row.get("jif", "")),
        })
    private_path = args.private_jif_dir / f"common_jif_{identifier}.tsv"
    write_tsv(private_path, private_rows, (
        "pmid", "issn", "eissn", "journal_title", "publication_year", "jif", "jif_data_year",
        "jcr_release_year", "jif_source", "jif_match_status", "if_tier"
    ))
    print(json.dumps({
        "master": str(master_path), "private_jif_export": str(private_path),
        "added": added, "skipped": skipped, "conflicts": len(conflicts),
    }, ensure_ascii=False))

    if state is not None and run_dir is not None:
        state["stage"] = "master_promoted"
        state["master_path"] = str(master_path)
        state["private_jif_export"] = str(private_path)
        state["master_added"] = added
        state["master_skipped"] = skipped
        state["master_conflicts"] = len(conflicts)
        state["updated_at"] = now_utc()
        write_run_state(run_dir / "run_state.json", state)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = root.add_subparsers(dest="command", required=True)

    first = commands.add_parser(
        "step1", help="Create review candidates from raw PubMed text files (ingest + Claude in one run)"
    )
    first.add_argument("--raw-dir", type=Path, default=Path("data/raw/pubmed_alerts"))
    first.add_argument("--jif-reference", type=Path, action="append", default=[],
                        help="Annual JIF TSV; repeat once for each JIF data year")
    first.add_argument("--master", type=Path)
    first.add_argument("--master-dir", type=Path, default=Path("data/master/literature"),
                        help="Use its latest version automatically when --master is omitted")
    first.add_argument("--claude", action="store_true")
    first.add_argument("--claude-model", default="")
    first.add_argument("--claude-batch-size", type=int, default=5)
    first.add_argument("--run-id", default="")
    first.add_argument("--output-dir", type=Path, default=Path("data/processed/literature_candidates"))
    first.add_argument("--review-dir", type=Path, default=Path("data/processed/review_reports"))
    first.add_argument("--log-dir", type=Path, default=Path("logs/runs"))
    first.set_defaults(function=step1)

    ingest = commands.add_parser(
        "step1-ingest",
        help="Mechanical half of Step 1: clean raw PubMed text and match JIF, without calling Claude",
    )
    ingest.add_argument("--raw-dir", type=Path, default=Path("data/raw/pubmed_alerts"))
    ingest.add_argument("--jif-reference", type=Path, action="append", default=[],
                         help="Annual JIF TSV; repeat once for each JIF data year")
    ingest.add_argument("--master", type=Path)
    ingest.add_argument("--master-dir", type=Path, default=Path("data/master/literature"))
    ingest.add_argument("--run-id", default="")
    ingest.add_argument("--intermediate-dir", type=Path, default=Path("data/intermediate"))
    ingest.add_argument("--manifests-dir", type=Path, default=Path("data/manifests"))
    ingest.add_argument("--log-dir", type=Path, default=Path("logs/runs"))
    ingest.set_defaults(function=step1_ingest)

    classify = commands.add_parser(
        "step1-classify",
        help="AI half of Step 1: classify a clean_jif TSV produced by step1-ingest and write review candidates",
    )
    classify.add_argument("--from-run", default="", help="Run id to resume")
    classify.add_argument("--latest", action="store_true", help="Use the most recent run awaiting AI classification")
    classify.add_argument("--intermediate-dir", type=Path, default=Path("data/intermediate"))
    classify.add_argument("--claude", action="store_true")
    classify.add_argument("--claude-model", default="")
    classify.add_argument("--claude-batch-size", type=int, default=5)
    classify.add_argument("--output-dir", type=Path, default=Path("data/processed/literature_candidates"))
    classify.add_argument("--review-dir", type=Path, default=Path("data/processed/review_reports"))
    classify.add_argument("--log-dir", type=Path, default=Path("logs/runs"))
    classify.set_defaults(function=step1_classify)

    review_path_cmd = commands.add_parser(
        "latest-review-path", help="Print the review HTML path for a run awaiting review"
    )
    review_path_cmd.add_argument("--from-run", default="")
    review_path_cmd.add_argument("--intermediate-dir", type=Path, default=Path("data/intermediate"))
    review_path_cmd.set_defaults(function=print_review_path)

    retry = commands.add_parser(
        "retry-classify",
        help="Reset a run back to awaiting_ai_start so step1-classify can be retried",
    )
    retry.add_argument("run_id", help="Run id to retry (the folder name under --intermediate-dir)")
    retry.add_argument("--intermediate-dir", type=Path, default=Path("data/intermediate"))
    retry.add_argument("--force", action="store_true",
                        help="Allow retrying a run that already promoted rows to master")
    retry.set_defaults(function=retry_classify)

    approval = commands.add_parser("approve", help="Write immutable review decisions")
    approval.add_argument("candidate", type=Path, nargs="?",
                           help="Candidate TSV. Omit when using --from-run or --latest.")
    approval.add_argument("--output", type=Path,
                           help="Decision TSV path. Auto-derived under the run folder when --from-run/--latest is used.")
    approval.add_argument("--reviewer", required=True)
    approval.add_argument("--approve-all-valid", action="store_true")
    approval.add_argument("--exceptions", type=Path)
    approval.add_argument("--from-run", default="")
    approval.add_argument("--latest", action="store_true")
    approval.add_argument("--intermediate-dir", type=Path, default=Path("data/intermediate"))
    approval.set_defaults(function=approve)

    second = commands.add_parser("step2", help="Merge approved candidates into a versioned master")
    second.add_argument("candidate", type=Path, nargs="?",
                         help="Candidate TSV. Omit when using --from-run or --latest.")
    second.add_argument("decisions", type=Path, nargs="?",
                         help="Decisions TSV. Omit when using --from-run or --latest.")
    second.add_argument("--run-id", default="",
                         help="Master version label; defaults to the resolved run id or a new timestamp")
    second.add_argument("--master-dir", type=Path, default=Path("data/master/literature"))
    second.add_argument("--private-jif-dir", type=Path, default=Path("data/processed/private_jif_export"))
    second.add_argument("--from-run", default="")
    second.add_argument("--latest", action="store_true")
    second.add_argument("--intermediate-dir", type=Path, default=Path("data/intermediate"))
    second.set_defaults(function=step2)
    return root


def main() -> None:
    args = parser().parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
