# Literature website update workflow v1.1.0

## Before Step 1

1. Save new PubMed MEDLINE exports under `data/raw/pubmed_alerts/<year>/` with a
   unique acquisition-date filename. Never edit or overwrite raw inputs.
2. If licensed annual JIF data are available, save each unmodified JCR CSV in
   `data/reference/jif/raw/` and run `jif_reference_cleaner.py` according to
   `docs/data_dictionary/jif_reference_v1.md`.
3. Install Claude Code and log in with the approved Claude Pro account before
   using `--claude`. No API key is stored in this workspace. The integration
   uses the official non-interactive `claude -p --output-format json` interface;
   the task body is supplied through standard input.

Official references checked 2026-07-20:

- <https://docs.anthropic.com/en/docs/claude-code/getting-started>
- <https://docs.anthropic.com/en/docs/claude-code/cli-usage>

## Step 1 — prepare and review

```bash
python3 programs/literature_pipeline/pipeline.py step1 \
  --raw-dir data/raw/pubmed_alerts \
  --jif-reference data/reference/jif/jcr_jif_reference_2024_v2026.07.0.tsv \
  --jif-reference data/reference/jif/jcr_jif_reference_2025_v2026.07.0.tsv \
  --claude
```

The latest versioned master under `data/master/literature/` is selected
automatically; use `--master` only when a specific earlier version must be
compared. Repeat `--jif-reference` for each JIF data year to be matched. If no JIF reference exists yet, omit that argument. For
a no-cost structural dry run, omit `--claude`; every row will then have
`quality_status=claude_not_run` and cannot be bulk-approved.

Review the printed candidate path, anomaly TSV, and review HTML. Confirm input
count, unique PMID count, conflicts, missing Abstracts, JIF match statuses,
Claude warnings, bilingual summaries, and classifications.

Python independently checks the Japanese 120–200-character and English
60–100-word limits, the exact missing-Abstract messages, the controlled type
and subtype lists, `Other` classifications, and obvious PT/type conflicts.
Any violation is written to the anomaly TSV.

## Bulk approval checkpoint

```bash
python3 programs/literature_pipeline/pipeline.py approve CANDIDATE.tsv \
  --output DECISIONS.tsv \
  --reviewer "REVIEWER" \
  --approve-all-valid
```

Only `quality_status=ok` rows are bulk-approved. Supply an exception TSV with
`pmid`, `decision`, and `note` to reject or hold individual records.

## Step 2 — promote approved rows

```bash
python3 programs/literature_pipeline/pipeline.py step2 CANDIDATE.tsv DECISIONS.tsv
```

Step 2 creates a new versioned master, never overwrites an earlier master, and
holds same-PMID/different-content records in a conflict TSV. It also creates a
local-only exact-JIF export under `data/processed/private_jif_export/`.

## Website build and second checkpoint

```bash
python3 programs/literature_site/build_site.py MASTER.tsv --output-dir site/build
```

Review `site/build/deployment_manifest.tsv`, public year TSVs, search behavior,
language toggle, update date, PubMed links, and absence of exact JIF/Abstract.
The `sso-jif/` subtree is upload-blocked until official UMIN SSO `.htaccess`
directives for approved UMIN IDs replace the template.

Uploading through SFTP remains a deliberate manual action after review.
