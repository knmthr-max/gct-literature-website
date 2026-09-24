#!/usr/bin/env python3
"""data/papers.json の各文献がGCT(胚細胞腫瘍)に本当に関連しているかをレビューする。

既存の programs/literature_pipeline/pipeline.py の step1/approve と同じ「AIは提案
のみ、採否は人間が承認してから反映」という二段階ゲートを踏襲する:

  1. propose  — 未レビューの文献をClaude Code CLIでバッチ判定し、
                 一覧レビューHTMLと decisions TSV(判定結果+暫定decision列)を書き出す
  2. (人間が decisions TSV の decision 列を確認・修正する)
  3. apply    — 承認済み decisions TSV を読み、data/papers.json に
                 relevance_status ("kept"/"excluded"/"needs_review") を書き戻す

文献は今後も継続的に追加されていく前提のため、propose はデフォルトで
relevance_status が未設定の(＝まだ一度もレビューしていない)文献だけを対象にする。
既にレビュー済みの文献を再判定したい場合だけ --all を指定する。

使い方:
    # 1) 未レビュー分をAI判定してレビュー一式を生成(非公開リポジトリ側に出力する)
    python3 scripts/review_relevance.py propose --claude \
      --review-dir /path/to/gct-literature-data/data/processed/relevance_review

    # 2) 出力された decisions_<run_id>.tsv の decision 列(keep/exclude/needs_review)を
    #    人間が確認・修正する

    # 3) 承認済みdecisionsをpapers.jsonへ反映
    python3 scripts/review_relevance.py apply \
      --decisions /path/to/gct-literature-data/data/processed/relevance_review/<run_id>/decisions_<run_id>.tsv

relevance_status が "excluded" の文献は、サイト側(assets/app.js)で一覧から除外される。
それ以外(未設定 / "kept" / "needs_review")は表示される — つまり判定が終わるまで
文献を勝手に隠さない、除外は常に人間の明示判断のみで発生する設計。
"""
import argparse
import csv
import html
import json
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPERS_PATH = ROOT / "data" / "papers.json"

RELEVANCE_VALUES = ("relevant", "uncertain", "not_relevant")
DEFAULT_DECISION = {"relevant": "keep", "uncertain": "needs_review", "not_relevant": "exclude"}
DECISION_HEADER = (
    "id", "pmid", "title", "journal", "year",
    "ai_relevance", "ai_reason", "decision", "reviewer", "reviewed_at", "note",
)

DOMAIN_NOTE = (
    "This website curates literature specifically about germ cell tumors (GCT): "
    "testicular, ovarian, and extragonadal germ cell tumors, teratoma (mature/immature), "
    "seminoma/dysgerminoma, yolk sac tumor, choriocarcinoma, embryonal carcinoma, mixed "
    "germ cell tumor, gonadoblastoma, and closely related tumor markers (AFP, hCG, LDH) "
    "and their management, in pediatric or adult patients. A paper about an unrelated "
    "tumor type, or one that only mentions GCT in passing (e.g. in a differential "
    "diagnosis list) without GCT being a subject of the paper, is not relevant."
)


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_id():
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def load_papers(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_papers(path, papers):
    path.write_text(json.dumps(papers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def claude_schema():
    return {
        "type": "object",
        "properties": {
            "papers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "relevance": {"type": "string", "enum": list(RELEVANCE_VALUES)},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "relevance", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["papers"],
        "additionalProperties": False,
    }


def claude_prompt(rows):
    payload = [
        {
            "id": r["id"],
            "title": r.get("title", ""),
            "title_ja": r.get("title_ja", ""),
            "journal": r.get("journal", ""),
            "year": r.get("year", ""),
            "abstract": r.get("abstract") or r.get("summary_en") or r.get("summary_ja") or "",
        }
        for r in rows
    ]
    return (
        DOMAIN_NOTE + " Judge whether each paper below is relevant to this site's scope. "
        "relevant: clearly about GCT. uncertain: borderline or not enough information to "
        "decide confidently. not_relevant: clearly not about GCT. Write `reason` in "
        "Japanese, one concise sentence citing what in the title/abstract drove the "
        "judgment. Return exactly one result per id, for every id supplied. Return only a "
        "JSON object that conforms exactly to this JSON Schema; do not use Markdown fences:\n"
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


def call_claude(rows, model=""):
    if shutil.which("claude") is None:
        raise RuntimeError("Claude Code executable was not found. Install/login before using --claude.")
    command = [
        "claude", "-p", "Complete the JSON relevance-review task supplied on standard input.",
        "--output-format", "json", "--max-turns", "3",
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
    result = {}
    for item in structured.get("papers", []):
        result[item["id"]] = {"relevance": item.get("relevance", ""), "reason": item.get("reason", "")}
    return result


def render_review_html(path, rows, stats):
    order = {"not_relevant": 0, "uncertain": 1, "": 1, "relevant": 2}
    ordered = sorted(rows, key=lambda r: order.get(r["ai_relevance"], 1))
    table_rows = []
    for row in ordered:
        table_rows.append(
            "<tr>" + "".join(
                f"<td>{html.escape(str(value))}</td>"
                for value in (
                    row["id"], row["pmid"], row["title"], row["journal"], row["year"],
                    row["ai_relevance"], row["ai_reason"], row["decision"],
                )
            ) + "</tr>"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>GCT関連性レビュー</title><style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#202124}} table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccd1d8;padding:6px;vertical-align:top;max-width:380px}} th{{position:sticky;top:0;background:#eef2f7}}
.summary{{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:18px}} .summary div{{border:1px solid #ccd1d8;border-radius:8px;padding:10px}}
</style></head><body><h1>GCT関連性レビュー</h1>
<div class="summary">{''.join(f'<div><strong>{html.escape(str(k))}</strong><br>{html.escape(str(v))}</div>' for k, v in stats.items())}</div>
<p>このHTMLは確認用です。採否は decisions TSV の decision 列(keep/exclude/needs_review)を編集し、
apply コマンドで反映してください。</p>
<table><thead><tr><th>id</th><th>PMID</th><th>Title</th><th>Journal</th><th>Year</th>
<th>AI relevance</th><th>AI reason</th><th>Default decision</th></tr></thead>
<tbody>{''.join(table_rows)}</tbody></table></body></html>""", encoding="utf-8")


def cmd_propose(args):
    papers = load_papers(args.papers)
    target = [p for p in papers if args.all or not p.get("relevance_status")]
    if not target:
        print("No papers need relevance review (already reviewed; pass --all to re-review everyone).")
        return

    results = {}
    claude_errors = 0
    if args.claude:
        for start in range(0, len(target), args.batch_size):
            batch = target[start:start + args.batch_size]
            try:
                results.update(call_claude(batch, args.model))
            except Exception as error:
                claude_errors += 1
                print(f"warning: Claude batch failed ({type(error).__name__}: {error})", file=sys.stderr)

    decision_rows = []
    for p in target:
        r = results.get(p["id"])
        if r is None:
            ai_relevance, ai_reason = "", ("claude_not_run" if not args.claude else "claude_error_or_missing")
        else:
            ai_relevance, ai_reason = r["relevance"], r["reason"]
        decision_rows.append({
            "id": p["id"], "pmid": p.get("pmid", ""), "title": p.get("title", ""),
            "journal": p.get("journal", ""), "year": p.get("year", ""),
            "ai_relevance": ai_relevance, "ai_reason": ai_reason,
            "decision": DEFAULT_DECISION.get(ai_relevance, "needs_review"),
            "reviewer": "", "reviewed_at": "", "note": "",
        })

    identifier = args.run_id or run_id()
    run_dir = args.review_dir / identifier
    review_path = run_dir / f"review_{identifier}.html"
    decisions_path = run_dir / f"decisions_{identifier}.tsv"

    run_dir.mkdir(parents=True, exist_ok=True)
    with decisions_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DECISION_HEADER, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(decision_rows)

    stats = {
        "papers reviewed": len(target),
        "not_relevant (AI)": sum(1 for r in decision_rows if r["ai_relevance"] == "not_relevant"),
        "uncertain (AI)": sum(1 for r in decision_rows if r["ai_relevance"] == "uncertain"),
        "relevant (AI)": sum(1 for r in decision_rows if r["ai_relevance"] == "relevant"),
        "Claude batch errors": claude_errors,
    }
    render_review_html(review_path, decision_rows, stats)

    print(json.dumps(stats, ensure_ascii=False))
    print(f"wrote: {review_path}")
    print(f"wrote: {decisions_path}")
    print("Edit the 'decision' column (keep/exclude/needs_review) as needed, then run:")
    print(f"  python3 scripts/review_relevance.py apply --decisions {decisions_path}")


def cmd_apply(args):
    papers = load_papers(args.papers)
    by_id = {p["id"]: p for p in papers}
    with args.decisions.open(encoding="utf-8", newline="") as f:
        decisions = list(csv.DictReader(f, delimiter="\t"))

    counts = {"kept": 0, "excluded": 0, "needs_review": 0, "unknown_id": 0}
    reviewed_at = now_utc()
    for row in decisions:
        paper = by_id.get(row.get("id", ""))
        if paper is None:
            counts["unknown_id"] += 1
            continue
        decision = (row.get("decision") or "").strip()
        if decision == "exclude":
            status = "excluded"
        elif decision == "keep":
            status = "kept"
        else:
            status = "needs_review"
        paper["relevance_status"] = status
        paper["relevance_note"] = (row.get("note") or "").strip() or row.get("ai_reason", "")
        paper["relevance_reviewed_at"] = (row.get("reviewed_at") or "").strip() or reviewed_at
        counts[status] += 1

    save_papers(args.papers, papers)
    print(json.dumps(counts, ensure_ascii=False))
    print(f"wrote: {args.papers}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    propose = commands.add_parser("propose", help="Judge un-reviewed papers with Claude and write a review HTML + decisions TSV")
    propose.add_argument("--review-dir", type=pathlib.Path, required=True,
                          help="Output folder for review HTML/decisions TSV (private data repo, not this repo)")
    propose.add_argument("--papers", type=pathlib.Path, default=PAPERS_PATH)
    propose.add_argument("--all", action="store_true", help="Re-review every paper, not just unreviewed ones")
    propose.add_argument("--claude", action="store_true", help="Actually call Claude Code; omit for a structural dry run")
    propose.add_argument("--model", default="")
    propose.add_argument("--batch-size", type=int, default=5)
    propose.add_argument("--run-id", default="")
    propose.set_defaults(function=cmd_propose)

    apply_cmd = commands.add_parser("apply", help="Write approved decisions back into papers.json as relevance_status")
    apply_cmd.add_argument("--decisions", type=pathlib.Path, required=True)
    apply_cmd.add_argument("--papers", type=pathlib.Path, default=PAPERS_PATH)
    apply_cmd.set_defaults(function=cmd_apply)

    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
