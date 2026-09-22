# Literature Site Builder

Version: `3.0.0`

Builds a static UMIN SQUARE-compatible website from an approved, versioned
literature master TSV.

## Output

- `index.html`: public literature page with Japanese/English summary toggle.
- `data/literature_<year>.tsv`: year-partitioned public card data.
- `data/search_index.json`: compact cross-year search index containing title,
  author, journal, year, PubMed keywords, type, and subtype, but no summary.
- `data/manifest.tsv`: data files, counts, and the latest approved addition date.
- `sso-jif/`: UMIN SSO-ready collaborator portal shell. Exact JIF data is not
  included automatically and the page displays `参照不可` until authorized.
- `deployment_manifest.tsv`: records public/SSO scope and upload eligibility.

Public TSV files never contain Abstract or exact JIF values.

## Run

```bash
python3 programs/literature_site/build_site.py \
  data/master/literature/literature_master_<version>.tsv \
  --output-dir site/build
```

Do not upload `sso-jif/` until its `.htaccess.template` has been replaced with
official UMIN SSO directives for approved UMIN IDs.
