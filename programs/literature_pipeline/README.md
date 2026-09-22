# Literature Update Pipeline

Version: `1.1.0`

## Annual JIF reference preparation

Keep each unmodified JCR CSV export in `data/reference/jif/raw/`. Convert one
or more CSV exports into one non-public, versioned TSV per JIF data year:

```bash
python3 programs/literature_pipeline/jif_reference_cleaner.py \
  --raw-dir data/reference/jif/raw \
  --reference-version 2026.07.0 \
  --jcr-release-year 2026 \
  --license-note "JCR institutional use only; do not upload or redistribute"
```

The program detects the JIF year from a column such as `2024 JIF`. It removes
identical category-level journal duplicates. A journal identity with
conflicting JIF values is excluded from the reference and recorded in a
separate conflict TSV for review. Existing output files are never overwritten.
The generated reference retains only the fields defined in
`docs/data_dictionary/jif_reference_v1.md`; the raw CSV remains the source
record and is not modified.

The pipeline implements the two human-gated update stages.

## Step 1

```bash
python3 programs/literature_pipeline/pipeline.py step1 \
  --raw-dir data/raw/pubmed_alerts \
  --jif-reference data/reference/jif/jcr_jif_reference_2024_v2026.07.0.tsv \
  --jif-reference data/reference/jif/jcr_jif_reference_2025_v2026.07.0.tsv \
  --claude
```

This parses every PubMed text file, deduplicates by PMID, loads each specified
annual Reference and performs exact-year JIF matching, optionally invokes Claude Code in five-record structured batches,
and writes a candidate TSV, anomaly TSV, review HTML, and run log.

When `--master` is omitted, the latest version under
`data/master/literature/` is compared automatically. Claude results are checked
again in Python for summary length, missing-Abstract sentinels, controlled
vocabulary, `Other`, and clear PubMed publication-type conflicts. Failed rows
remain anomalies and cannot be bulk-approved.

Omit `--jif-reference` until a licensed annual reference exists. Omit
`--claude` for a deterministic dry run that does not consume Claude usage.

## Approval

```bash
python3 programs/literature_pipeline/pipeline.py approve CANDIDATE.tsv \
  --output DECISIONS.tsv \
  --reviewer "Reviewer name" \
  --approve-all-valid
```

Rows with a non-`ok` quality status remain `needs_edit`. An optional exception
TSV can override individual PMIDs with `approved`, `rejected`, or `needs_edit`.

## Step 2

```bash
python3 programs/literature_pipeline/pipeline.py step2 CANDIDATE.tsv DECISIONS.tsv
```

Step 2 writes a new versioned master. It never overwrites an earlier master.
The exact-JIF export is local-only under `data/processed/private_jif_export/`
and is not copied into the website build automatically.
