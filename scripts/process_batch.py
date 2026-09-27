#!/usr/bin/env python3
"""Process one user-controlled batch of pending historical-backlog papers.

Each invocation is the "Go" signal: it pulls the next --batch-size rows with
relevance_status IS NULL, newest publication year first, and stops. Nothing
else runs until this is invoked again, so token spend is entirely under the
caller's control.

For that one batch, a single Claude Code call judges GCT relevance and
writes a bilingual summary (combining what would otherwise be two separate
AI passes, since this scale makes a strict propose/apply gate impractical).
Category tags are NOT asked of the AI: they are computed deterministically
from the MEDLINE publication-type field via the same classify() used by
scripts/import_medline.py, for zero extra cost and consistency with the
already-published 65 entries.

The AI verdict directly sets relevance_status (relevant -> kept, uncertain
-> needs_review, not_relevant -> excluded) rather than going through a
separate decisions-file approval step -- at backlog scale, reviewing every
batch by hand isn't practical. This stays reversible: any row's
relevance_status/relevance_note can be corrected later with a direct
sqlite3 UPDATE, same as any other field. A short digest of the batch's
not_relevant/uncertain calls is printed after each run so it can be skimmed.

Usage:
    python3 scripts/process_batch.py --claude \
      --db-dir /path/to/gct-literature-data/data/master \
      --batch-size 25

The backlog is sharded into one SQLite file per era (see gct_db.py's
SHARDS); this walks shards newest-first and pulls pending rows from each in
turn until --batch-size is reached, so "newest first" holds across shard
boundaries too.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from import_medline import classify  # noqa: E402
from gct_db import connect, json_load, existing_shard_paths  # noqa: E402

RELEVANCE_VALUES = ("relevant", "uncertain", "not_relevant")
DEFAULT_STATUS = {"relevant": "kept", "uncertain": "needs_review", "not_relevant": "excluded"}

DOMAIN_NOTE = (
    "This website curates literature specifically about germ cell tumors (GCT): "
    "testicular, ovarian, and extragonadal germ cell tumors, teratoma (mature/immature), "
    "seminoma/dysgerminoma, yolk sac tumor, choriocarcinoma, embryonal carcinoma, mixed "
    "germ cell tumor, gonadoblastoma, and closely related tumor markers (AFP, hCG, LDH) "
    "and their management, in pediatric or adult patients. Gestational trophoblastic "
    "disease (hydatidiform mole, invasive mole, gestational choriocarcinoma, placental "
    "site trophoblastic tumor, placental site nodule, and related placental-site lesions) "
    "is ALSO treated as relevant/related content on this site -- even though it is "
    "genetically placental in origin, not a true germ-cell-derived tumor -- as long as "
    "that disease is the actual subject of the paper (this is an established editorial "
    "policy for this site, not a judgment call to re-derive). Judge it not_relevant only "
    "when it is a mere incidental mention. A paper about an unrelated tumor type, an "
    "animal/plant/veterinary study using 'teratoma' in a non-oncologic sense, or one that "
    "only mentions GCT (or the gestational trophoblastic disease spectrum above) in "
    "passing (e.g. in a differential diagnosis list, or as an unrelated tool/cell-line "
    "control) without it being a subject of the paper, is not relevant."
)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def claude_schema():
    return {
        "type": "object",
        "properties": {
            "papers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pmid": {"type": "string"},
                        "relevance": {"type": "string", "enum": list(RELEVANCE_VALUES)},
                        "relevance_reason": {"type": "string"},
                        "summary_en": {"type": "string"},
                        "summary_ja": {"type": "string"},
                    },
                    "required": ["pmid", "relevance", "relevance_reason", "summary_en", "summary_ja"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["papers"],
        "additionalProperties": False,
    }


def claude_prompt(rows):
    payload = []
    for row in rows:
        payload.append({
            "pmid": row["pmid"],
            "title": row["title"] or "",
            "journal": row["journal_abbrev"] or row["journal_title"] or "",
            "year": row["publication_year"],
            "abstract": row["abstract"] or "",
        })
    return (
        DOMAIN_NOTE + " For each paper below, judge relevance (relevant/uncertain/not_relevant) "
        "with a one-sentence Japanese reason, and write a short bilingual summary: summary_en "
        "60-100 words, summary_ja 120-200 Japanese characters. If the abstract is empty, base "
        "the summary on the title alone and keep it brief rather than inventing details. Return "
        "exactly one result per pmid, for every pmid supplied. Return only a JSON object that "
        "conforms exactly to this JSON Schema; do not use Markdown fences:\n"
        + json.dumps(claude_schema(), ensure_ascii=False, separators=(",", ":"))
        + "\n\nINPUT PAPERS:\n" + json.dumps(payload, ensure_ascii=False)
    )


def parse_claude_payload(response):
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


def call_claude(rows, model="", max_retries=2):
    if shutil.which("claude") is None:
        raise RuntimeError("Claude Code executable was not found. Install/login before using --claude.")
    command = [
        "claude", "-p", "Complete the JSON relevance-and-summary task supplied on standard input.",
        "--output-format", "json", "--max-turns", "5",
    ]
    if model:
        command.extend(["--model", model])
    prompt = claude_prompt(rows)

    last_error = None
    for attempt in range(1, max_retries + 2):
        completed = subprocess.run(command, input=prompt, capture_output=True, text=True, check=False)
        if completed.returncode:
            last_error = RuntimeError(f"Claude Code failed ({completed.returncode}): {completed.stderr.strip()}")
            print(f"warning: call_claude attempt {attempt} failed to run: {last_error}", file=sys.stderr)
            continue
        try:
            response = json.loads(completed.stdout)
            structured = parse_claude_payload(response)
        except (json.JSONDecodeError, ValueError) as error:
            # Occasionally the model exhausts --max-turns mid tool-use without ever emitting a
            # final text response (subtype often "error_max_turns"); retrying is usually enough.
            subtype = None
            try:
                subtype = json.loads(completed.stdout).get("subtype")
            except Exception:
                pass
            last_error = error
            print(
                f"warning: call_claude attempt {attempt} could not parse a response "
                f"(subtype={subtype}): {error}", file=sys.stderr,
            )
            continue
        result = {}
        for item in structured.get("papers", []):
            result[item["pmid"]] = item
        return result, response.get("total_cost_usd", 0.0)

    raise RuntimeError(f"call_claude failed after {max_retries + 1} attempts: {last_error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-dir", type=pathlib.Path, required=True)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--claude", action="store_true", help="Actually call Claude; omit for a structural dry run")
    parser.add_argument(
        "--model", default="claude-haiku-4-5",
        help="Model for the Claude Code call. Default claude-haiku-4-5: benchmarked against "
             "sonnet on 10 real backlog papers (see commit history), identical classifications "
             "except one genuinely borderline case where even sonnet disagreed with itself "
             "across runs, at roughly half the average cost. Pass --model sonnet to escalate a "
             "specific batch if a digest ever looks off.",
    )
    parser.add_argument(
        "--cost-log", type=pathlib.Path,
        help="Append {batch_id, papers, model, cost_usd} as a JSON line here after each run, "
             "and print the cumulative total across every line in the file. Lets a caller (or a "
             "human) track spend across many invocations without re-deriving it each time.",
    )
    args = parser.parse_args()

    shard_paths = existing_shard_paths(args.db_dir)
    if not shard_paths:
        print("No shard database files found under --db-dir. Nothing to do.")
        return
    shard_conns = {path: connect(path) for path in shard_paths}  # newest era first

    rows = []
    row_conn = {}  # pmid -> connection, for writing results back to the right shard
    for conn in shard_conns.values():
        if len(rows) >= args.batch_size:
            break
        remaining = args.batch_size - len(rows)
        for row in conn.execute(
            """SELECT * FROM papers WHERE relevance_status IS NULL
               ORDER BY publication_year DESC, pmid DESC LIMIT ?""",
            (remaining,),
        ).fetchall():
            rows.append(row)
            row_conn[row["pmid"]] = conn

    if not rows:
        print("No pending papers (relevance_status IS NULL) in any shard. Nothing to do.")
        return

    batch_id = now_utc()
    ai_results = {}
    cost_usd = 0.0
    if args.claude:
        ai_results, cost_usd = call_claude(rows, args.model)

    counts = {"relevant": 0, "uncertain": 0, "not_relevant": 0, "claude_not_run": 0}
    digest = []
    for row in rows:
        pmid = row["pmid"]
        tags = classify(json_load(row["publication_types"]))
        result = ai_results.get(pmid)
        if result is None:
            relevance = ""
            reason = "" if not args.claude else "claude_result_missing"
            summary_en = summary_ja = ""
            counts["claude_not_run"] += 1
        else:
            relevance = result.get("relevance", "")
            reason = result.get("relevance_reason", "")
            summary_en = result.get("summary_en", "")
            summary_ja = result.get("summary_ja", "")
            counts[relevance] = counts.get(relevance, 0) + 1

        status = DEFAULT_STATUS.get(relevance)  # None (still pending) if claude wasn't run
        row_conn[pmid].execute(
            """UPDATE papers SET
                 ai_relevance = ?, ai_relevance_reason = ?, ai_tags = ?,
                 ai_summary_en = ?, ai_summary_ja = ?, ai_processed_at = ?, batch_id = ?,
                 relevance_status = COALESCE(?, relevance_status),
                 relevance_reviewed_at = CASE WHEN ? IS NOT NULL THEN ? ELSE relevance_reviewed_at END
               WHERE pmid = ?""",
            (relevance, reason, json.dumps([tags] if tags else [], ensure_ascii=False),
             summary_en, summary_ja, now_utc(), batch_id,
             status, status, now_utc(), pmid),
        )
        if relevance in ("uncertain", "not_relevant"):
            digest.append((pmid, row["publication_year"], row["title"], relevance, reason))

    for conn in shard_conns.values():
        conn.commit()

    still_pending = sum(
        conn.execute("SELECT COUNT(*) FROM papers WHERE relevance_status IS NULL").fetchone()[0]
        for conn in shard_conns.values()
    )
    print(json.dumps({
        "batch_id": batch_id, "batch_size": len(rows), "claude_used": args.claude, **counts,
        "still_pending": still_pending, "cost_usd": cost_usd,
    }, ensure_ascii=False, indent=2))

    if args.cost_log and args.claude:
        with args.cost_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "batch_id": batch_id, "papers": len(rows), "model": args.model, "cost_usd": cost_usd,
            }, ensure_ascii=False) + "\n")
        cumulative = sum(
            json.loads(line)["cost_usd"] for line in args.cost_log.read_text(encoding="utf-8").splitlines() if line.strip()
        )
        print(f"cumulative_cost_usd (from {args.cost_log.name}): {cumulative:.4f}")

    if digest:
        print("\n--- uncertain / not_relevant this batch (skim and correct if needed) ---")
        for pmid, year, title, relevance, reason in digest:
            print(f"[{relevance:12s}] ({year}) {title[:80]}\n              -> {reason}")


if __name__ == "__main__":
    main()
