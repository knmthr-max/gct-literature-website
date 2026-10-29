# Python Program Versions

Configured Python runtime: `3.13.14`. The programs use only the Python standard
library.

| Program | Version | Entry point | Purpose |
|---|---:|---|---|
| PubMed Cleaner | `3.0.0` | `pubmed_cleaner/pubmed_cleaner.py` | Parse MEDLINE text; used as a library by `scripts/ingest_historical.py`. |
| JIF Reference Cleaner | `1.2.1` | `literature_pipeline/jif_reference_cleaner.py` | Convert licensed JCR CSV exports into one deduplicated, non-overwriting internal TSV per JIF data year. |
| JIF Matcher | - | `literature_pipeline/jif_matcher.py` | Exact-year journal matching and JIF tier. |
| Glossary parser | - | `literature_pipeline/glossary.py` | Parse the terminology glossary. |

The scripts in `../scripts/` are not versioned here. The TSV pipeline
(Literature Pipeline 1.1.0, Literature Site Builder 3.0.0) was removed in 2026-10.
