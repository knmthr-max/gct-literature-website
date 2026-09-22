# Python Program Versions

Configured Python runtime: `3.13.14`. The programs use only the Python standard
library and are also regression-tested with the locally available Python
`3.9.6`.

## Maintained programs

| Program | Version | Entry point | Purpose |
|---|---:|---|---|
| PubMed Cleaner | `3.0.0` | `pubmed_cleaner/pubmed_cleaner.py` | Preserve expanded PubMed fields including all MH and OT values in TSV. |
| Literature Pipeline | `1.1.0` | `literature_pipeline/pipeline.py` | Multi-year JIF enrichment, Claude candidates, review decisions, and versioned master promotion. |
| JIF Reference Cleaner | `1.2.1` | `literature_pipeline/jif_reference_cleaner.py` | Convert licensed JCR CSV exports (journal-list or single-journal All Years layout) into one deduplicated, non-overwriting internal TSV per JIF data year. |
| Literature Site Builder | `3.0.0` | `literature_site/build_site.py` | Build public year TSVs, keyword index, bilingual UI, and SSO JIF portal shell. |

## Current baselines archived during the 3.0 transition

| Archive | Status |
|---|---|
| `archive/pubmed_cleaner/v2.1.0-maintained-baseline` | Previous validated 11-column cleaner. |
| `archive/literature_site/2.0.0-maintained-baseline` | Previous validated JSON-to-embedded-HTML builder. |

Earlier legacy, prototype, experimental, and broken versions remain unchanged
in their existing archive directories and are not execution entry points.
