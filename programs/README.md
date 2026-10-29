# Python programs

Reusable modules used by the scripts in `../scripts/`, and the regression tests.

| Program | Version | Used by |
|---|---:|---|
| `pubmed_cleaner/pubmed_cleaner.py` | `3.0.0` | `../scripts/ingest_historical.py` (MEDLINE text parser; the TSV output mode is not used by the live workflow) |
| `literature_pipeline/jif_reference_cleaner.py` | `1.2.1` | `../scripts/jif_reference_add.py` (portal workflow 5) |
| `literature_pipeline/jif_matcher.py` | - | `../scripts/backfill_jif.py`, `../scripts/match_jif.py`, `../scripts/jif_reference_add.py` |
| `literature_pipeline/glossary.py` | - | `../scripts/process_batch.py`, `../scripts/check_terminology.py`, `../scripts/portal_status.py` |

The live website and the data workflow are described in `../data/README.md` and
`../docs/architecture/current_architecture.md`.

## Removed in 2026-10

The first-generation TSV pipeline (`literature_pipeline/pipeline.py` Step 1 /
Step 2, `literature_site/build_site.py` for UMIN SQUARE, `pubmed_cleaner/step7_legacy_raw_audit.py`,
and their documents) was never run in production and was deleted. It remains
in the git history (the last commit that contains it is the parent of the commit
that removed it). `JIFMatcher` and `jif_tier()` were moved to `jif_matcher.py`.

## Tests

```bash
python3 -m unittest discover -s programs/tests -v
```

The directory holds the regression tests of these programs and of the scripts
in `../scripts/` (for example `test_extract_attributes.py`,
`test_screen_cns_gct.py`, `test_retag_categories.py`, `test_papers_store.py`).
CI (`validate.yml`) runs them on every pull request. Tests use only fixtures and
temporary directories. Claude Code is never called by the test suite.

## Archive policy

The earlier archive of previous baselines is in the private data repository
(`gct-literature-data/programs/archive/`, read-only).
