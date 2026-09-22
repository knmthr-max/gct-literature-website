# Literature TSV data dictionary v1.0.0

## Repeated PubMed fields

`publication_types`, `mesh_terms`, `author_keywords`, and `search_keywords` are
JSON arrays stored inside TSV cells. This preserves every MEDLINE PT, MH, and OT
value while retaining one row per PMID.

## Candidate and internal master fields

| Field | Meaning |
|---|---|
| `pmid` | Unique PubMed identifier and merge key. |
| `publication_date` | PubMed DP value; preferred for publication year. |
| `epub_date` | PubMed DEP value; fallback when DP has no year. |
| `publication_year` | Year used for exact-year JIF matching. |
| `title`, `abstract` | PubMed TI and AB. Abstract is internal only. |
| `first_author` | First AU value. |
| `journal_abbrev`, `journal_title` | PubMed TA and JT. |
| `issn`, `eissn` | Print/linking and electronic identifiers parsed from IS. |
| `doi` | DOI parsed from AID/LID. |
| `mesh_terms` | All MH values, unchanged except whitespace normalization. |
| `author_keywords` | All OT values, unchanged except whitespace normalization. |
| `search_keywords` | Case-insensitive union of MH and OT for search. |
| `jif` | Exact JIF for `publication_year`; never nearest-year-filled. |
| `jif_data_year` | JIF data year matched to publication year. |
| `jcr_release_year` | JCR release year, usually the following calendar year. |
| `jif_match_status` | `exact`, `reference_not_loaded`, `journal_not_found`, `year_not_found`, `ambiguous_match`, `suppressed_or_unavailable`, or `publication_year_missing`. |
| `summary_ja` | Abstract-only Japanese summary, normally 120–200 characters. |
| `summary_en` | Abstract-only English summary, normally 60–100 words. |
| `type` | Controlled: `Clinical`, `Basic`, `Review`, or pre-review `Unclassified`. |
| `subtype` | Controlled vocabulary in `subtype_vocabulary.json`. |
| `classification_basis` | `abstract` or `metadata_only`. |
| `quality_status` | Only `ok` rows are eligible for bulk approval. |
| `review_status` | `pending`, `approved`, `rejected`, or `needs_edit`. |
| `added_at` | Approval/addition timestamp; source of website update date. |

When Abstract is absent, `summary_ja` is `Abstractなし`, `summary_en` is
`No abstract available.`, and classification is marked `metadata_only`.

## Public TSV

Public year TSVs exclude Abstract, exact JIF, JIF year, source, reviewer, and
other internal provenance. They retain bilingual summaries, PubMed keywords,
classification, and approved addition date.

## Search index

The auxiliary JSON index contains PMID, title, first author, journal, year,
MH/OT keywords, type, subtype, and the year TSV filename. It contains neither
summary text nor JIF.
