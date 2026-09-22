# TSV-backed literature site architecture v1.0.0

```text
PubMed raw txt
  -> Cleaner 3.0.0 (loss-aware PubMed TSV rows)
  -> exact publication-year JIF match (optional reference)
  -> Claude Code bilingual summaries and controlled classification
  -> candidate TSV + anomaly TSV + review HTML
  -> separate review decision TSV
  -> versioned internal master TSV
  -> year-partitioned public TSV + keyword search index
  -> UMIN SQUARE public site

local-only exact-JIF export
  -> not uploaded automatically
  -> future UMIN SSO portal data only after authorization
```

The public HTML shell does not embed the literature corpus. It initially loads
a compact keyword index, then fetches the relevant year TSV when rendering a
result. The approach supports approximately 50,000 records without requiring a
server-side database.

The SSO portal shell is fail-closed for exact JIF: an absent reference produces
`参照不可`; the normal build never places a common JIF TSV in its protected data
directory.
