# GCT website maintained programs

This directory is the only normal execution source for website updates.

| Processing | Version | Entry point |
|---|---:|---|
| PubMed MEDLINE extraction with MH/OT preservation | `3.0.0` | `pubmed_cleaner/pubmed_cleaner.py` |
| Review-gated Step 1 / Step 2 workflow | `1.1.0` | `literature_pipeline/pipeline.py` |
| JCR CSV to annual internal JIF Reference conversion | `1.0.0` | `literature_pipeline/jif_reference_cleaner.py` |
| Static TSV-backed public and SSO site build | `3.0.0` | `literature_site/build_site.py` |

See each program README and `../docs/operations/literature_update_workflow.md`.

## Tests

```bash
python3 -m unittest discover -s programs/tests -v
```

Tests use only fixtures and temporary directories. Claude Code is never called
by the test suite.

## Archive policy

`programs/archive/` is read-only. The pre-change maintained baselines are saved
as `pubmed_cleaner/v2.1.0-maintained-baseline/` and
`literature_site/2.0.0-maintained-baseline/`.
