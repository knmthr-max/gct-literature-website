# GCT website maintained programs

This directory holds the first-generation, TSV-based pipeline (PubMed text ->
candidate TSV -> review -> versioned master TSV -> TSV site for UMIN SQUARE).

## Current status (2026-10)

**The live website is not built by this pipeline.** The published site is the
static GitHub Pages site in the repository root, fed by the SQLite working
database in `gct-literature-data` and the scripts in `../scripts/` (see
`../data/README.md` and `../docs/architecture/current_architecture.md`). The
TSV pipeline was never run in production: `data/master/literature/` in the data
repository is empty and `data/raw/pubmed_alerts/` holds no files.

The parts that the live workflow still uses:

| Used by | What |
|---|---|
| `../scripts/process_batch.py`, `../scripts/check_terminology.py`, `../scripts/extract_term_candidates.py` | `literature_pipeline/glossary.py` (terminology glossary parser) |
| `../scripts/backfill_jif.py`, `../scripts/match_jif.py` | `JIFMatcher` in `literature_pipeline/pipeline.py` |
| `../scripts/jif_reference_add.py` (portal workflow 5) | `literature_pipeline/jif_reference_cleaner.py` |
| `../scripts/review_relevance.py` | modelled on the `step1` / `approve` two-stage gate of `pipeline.py` |

The remaining programs are kept, tested and versioned, but are not the
publishing path. Do not use them for a website update without a new decision.

| Processing | Version | Entry point | Status |
|---|---:|---|---|
| PubMed MEDLINE extraction with MH/OT preservation | `3.0.0` | `pubmed_cleaner/pubmed_cleaner.py` | not used by the live workflow |
| Review-gated Step 1 / Step 2 workflow | `1.1.0` | `literature_pipeline/pipeline.py` | `JIFMatcher` is shared; the workflow itself is unused |
| JCR CSV to annual internal JIF Reference conversion | `1.2.1` | `literature_pipeline/jif_reference_cleaner.py` | used (via `jif_reference_add.py`) |
| Static TSV-backed public and SSO site build | `3.0.0` | `literature_site/build_site.py` | not used (the live site is the GitHub Pages site) |

See each program README. The TSV workflow is described in
`../docs/operations/literature_update_workflow.md` (marked as not the live workflow).

## Tests

```bash
python3 -m unittest discover -s programs/tests -v
```

The directory also holds the regression tests of the scripts in `../scripts/`
(for example `test_extract_attributes.py`, `test_screen_cns_gct.py`,
`test_retag_categories.py`, `test_papers_store.py`). CI (`validate.yml`) runs
them on every pull request. Tests use only fixtures and temporary directories.
Claude Code is never called by the test suite.

## Archive policy

`programs/archive/` is read-only. The pre-change maintained baselines are saved
as `pubmed_cleaner/v2.1.0-maintained-baseline/` and
`literature_site/2.0.0-maintained-baseline/`.
