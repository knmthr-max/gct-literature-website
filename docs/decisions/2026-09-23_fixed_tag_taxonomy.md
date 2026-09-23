# Decision: fixed 7-category tag taxonomy for the public site

- Date: 2026-09-23
- Status: accepted

`data/papers.json`'s `tags` field is limited to exactly one value from a fixed
set: 症例報告 / 臨床研究 / 基礎研究 / 総説 / ガイドライン / 論説 / レター (or
empty when none apply). This matches the original plan's scope
(`literature_pipeline`'s `type`/`subtype` taxonomy was always meant to
classify at this granularity, not to surface every PubMed author keyword).

## What happened

An early import (`scripts/import_medline.py`) mixed PubMed's own official
publication-type tags with author-supplied free-text keywords (`OT`). A later
import of pre-classified historical JSON also appended the raw English
`type`/`subtype` strings alongside a Japanese PT-derived tag. By 65 entries
this produced 310 distinct tags, 89% of which appeared on only one paper —
the tag cloud stopped being usable as a filter.

## Rule

Both import paths (`scripts/import_medline.py`'s `classify()`, and any
future importer for `literature_json`-style pre-classified files) must derive
the single category tag from a fixed priority order over PubMed's official
`PT` article types (症例報告 before 総説 before ガイドライン before 論説
before レター before 臨床研究), never from free-text keywords or an
AI-generated subtype string. Author keywords and granular AI subtypes are
not written to `papers.json` at all — they are dropped after being folded
into the retained `abstract`/`summary` text, which the site's search already
covers, so search behavior does not regress.

`基礎研究` cannot be derived from PubMed's `PT` field alone (it does not
distinguish clinical from basic research) — only an AI classification step
(`literature_pipeline`'s `type` field) can set it. Manual `.nbib` imports via
`scripts/import_medline.py` will leave it out when it can't be determined
rather than guess.
