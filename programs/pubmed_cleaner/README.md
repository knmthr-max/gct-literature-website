# PubMed Cleaner

Version: `3.0.0`

Converts one PubMed MEDLINE text export into a UTF-8 TSV without dropping
repeated search metadata.

## Input and output

Input is an immutable `.txt` export. Output contains one row per PMID and these
fields:

```text
pmid publication_date epub_date publication_year title abstract first_author
publication_types journal_abbrev journal_title issn eissn doi mesh_terms
author_keywords source_file
```

`publication_types`, `mesh_terms`, and `author_keywords` are JSON arrays inside
TSV cells. Every PT, MH, and OT occurrence is retained in input order. The raw
file is never modified.

## Run

```bash
python3 programs/pubmed_cleaner/pubmed_cleaner.py \
  data/raw/pubmed_alerts/2026/20260621input_pubmed.txt \
  --output data/processed/cleaned_pubmed/20260621cleaned_pubmed_v3.tsv
```

The two-stage operational workflow normally calls this parser through
`programs/literature_pipeline/pipeline.py`.
