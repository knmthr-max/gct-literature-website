# Annual JIF reference specification v1.0.0

The reference is a long-form TSV with one journal-year per row.

```text
journal_title journal_abbreviation issn eissn jif_data_year jcr_release_year
jif source reference_version retrieved_at license_note
```

Matching order is ISSN plus publication year, eISSN plus publication year, then
an unambiguous normalized journal title plus publication year. A different year
is never substituted into the canonical `jif` field.

Exact JIF values are stored in the internal master and local-only export. They
are excluded from the public website. The reference and exact-JIF export must
not be uploaded unless the applicable license and UMIN SSO access scope have
been confirmed.

## JCR CSV conversion

Keep unmodified JCR exports in `data/reference/jif/raw/`. Run
`programs/literature_pipeline/jif_reference_cleaner.py` with an immutable
reference version and a license note. The cleaner reads the JIF data year from
the JCR column name (for example, `2024 JIF`) and creates one TSV per year.

The reference TSV retains these JCR-derived fields only:

| Reference field | JCR CSV column | Purpose |
|---|---|---|
| `journal_title` | `Journal name` | Title fallback matching |
| `journal_abbreviation` | `JCR Abbreviation` | Abbreviation fallback matching |
| `issn` | `ISSN` | Primary journal identifier |
| `eissn` | `eISSN` | Secondary journal identifier |
| `jif` | `<year> JIF` | Internal exact JIF |

`Publisher`, `Category`, `Edition`, `Total Citations`, `JIF Quartile`, JCI,
and OA percentage are not required for this JIF matching reference. They
remain in the unmodified raw JCR CSV, rather than being copied to the derived
TSV. Category-level duplicates with an identical JIF are collapsed. A
conflicting JIF for the same identity is excluded and reported for review.
