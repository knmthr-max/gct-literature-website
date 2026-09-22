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
