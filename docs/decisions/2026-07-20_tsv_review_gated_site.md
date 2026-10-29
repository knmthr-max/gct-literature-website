> **追記(2026-10-29):** この設計は本番で採用されず、TSV パイプライン一式(`programs/literature_pipeline/pipeline.py` と `programs/literature_site/` など)を削除した。現行の構成は `docs/architecture/current_architecture.md`。以下は当時の記録。

# Decision: review-gated TSV literature website

- Date: 2026-07-20
- Status: accepted

The maintained workflow uses PubMed raw text as immutable input, preserves all
MH and OT fields, produces a review candidate TSV, requires a separate human
decision file, and promotes only approved records into versioned master TSVs.

Claude Code through Claude Pro supplies bilingual Abstract-only summaries and
controlled type/subtype candidates. Python owns extraction, exact-year JIF
matching, validation, deduplication, and promotion.

The public site reads year-partitioned TSVs and a summary-free keyword search
index. Exact JIF remains internal. The UMIN SSO portal capability is prepared
but exact-JIF data are not uploaded automatically.
