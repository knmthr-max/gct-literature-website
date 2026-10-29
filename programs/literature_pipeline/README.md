# JIF reference tools and glossary parser

Contents (2026-10; the first-generation Step 1 / Step 2 TSV workflow that used to live here was removed, see git history):

| File | Role |
|---|---|
| `jif_reference_cleaner.py` (`1.2.1`) | Convert licensed JCR CSV exports into annual JIF reference TSVs (run by `scripts/jif_reference_add.py`) |
| `jif_matcher.py` | `JIFMatcher` and `jif_tier()`: exact-year matching of a journal to the reference, and the JIF tier (used by `scripts/backfill_jif.py`, `scripts/match_jif.py`, `scripts/jif_reference_add.py`) |
| `glossary.py` | Parser for the Japanese terminology glossary (used by `scripts/process_batch.py`, `scripts/check_terminology.py`, `scripts/portal_status.py`) |

## Annual JIF reference preparation

Keep each unmodified JCR CSV export in `data/reference/jif/raw/`. Convert one
or more CSV exports into one non-public, versioned TSV per JIF data year
(version `1.2.1`):

```bash
python3 programs/literature_pipeline/jif_reference_cleaner.py \
  data/reference/jif/raw
```

> The data repository does not run this cleaner directly. `scripts/jif_reference_add.py` runs it on
> the not-yet-processed CSVs in a scratch folder and merges the result with the existing TSVs into
> one `jcr_jif_reference_<year>_vmerged.tsv` per year, so repeated runs never multiply files. Rows
> that state the same JIF are one fact (`2` equals `2.0`); different values for the same
> journal-year are left out and listed in `jcr_jif_reference_conflicts_vmerged.tsv`.

`--reference-version`, `--jcr-release-year`, `--license-note`, and
`--output-dir` are all optional as of `1.2.1`: the reference version defaults
to today's date, the JCR release year is inferred from the Clarivate
copyright text embedded in the CSV, and output goes to a `jif-output`
subfolder next to the input by default. Pass any of these flags explicitly to
override the inferred value, e.g.:

```bash
python3 programs/literature_pipeline/jif_reference_cleaner.py \
  data/reference/jif/raw \
  --reference-version 2026.07.0 \
  --jcr-release-year 2026 \
  --output-dir data/reference/jif \
  --license-note "JCR institutional use only; do not upload or redistribute"
```

Two CSV layouts are supported: the standard JCR journal-list export (columns
such as `Journal name` and `2024 JIF`) and a single-journal `All Years`
history export. The program detects the JIF year automatically and removes
identical category-level journal duplicates. A journal identity with
conflicting JIF values is excluded from the reference and recorded in a
separate conflict TSV for review. A CSV in an unsupported layout is skipped
and reported rather than aborting the whole run when a folder is given (an
explicit `--input` file still raises an error). Existing output files are
never overwritten. The generated reference retains only the fields defined in
`docs/data_dictionary/jif_reference_v1.md`; the raw CSV remains the source
record and is not modified.

## 公開データへの反映(`scripts/match_jif.py`・`scripts/backfill_jif.py`)

照合は `jif_matcher.py`(`JIFMatcher`・`jif_tier()`)が行う。公開データ(`data/papers/`)だけを対象にする簡易版が
`scripts/match_jif.py`、非公開DBと公開データの両方に遡及するのが `scripts/backfill_jif.py`(非公開リポジトリの
GitHub Actions「2 JIF遡及」)。

```bash
python3 scripts/match_jif.py \
  --reference ../gct-literature-data/data/reference/jif/jcr_jif_reference_2025_v2026.09.24.tsv \
  --audit-output ../gct-literature-data/data/processed/jif_match_audit/2026-09-24.csv
```

複数の年次参照TSVがある場合は `--reference` を繰り返し指定する。公開データの
各エントリを `journal`(PubMed略称)+`year` で参照TSVに照合し(ISSNは
`papers.json` に保持していないため誌名フォールバックのみで照合される)、完全一致
(`jif_match_status == exact`)の場合のみ実測JIFから `jif_tier` を計算して書き戻す。
一致しない場合(誌名が参照に無い/対象年のデータが無い等)は `jif_tier` を
`"unknown"` にし、値を一切推測しない。実測JIFと不一致理由の詳細は非公開リポジトリ
側の監査用CSVにのみ出力され、公開リポジトリには一切含まれない。

JCRのカバー範囲(カテゴリ・年)を追加で取得した場合は、`jif_reference_cleaner.py`
で参照TSVを追加生成したうえで、この `match_jif.py` を再実行すれば
`"unknown"` だったエントリも含めて全件が再照合される。
