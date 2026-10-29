# 作業用SQLite(papers テーブル)v1

場所: 非公開リポジトリ `gct-literature-data/data/master/gct_literature_<年代>.db`。発行年で `pre1980` / `1980s` / `1990s` / `2000s` / `2010s` / `2020s` に分割(1ファイルを100MB未満に保つため)。
スキーマと分割の定義は `scripts/gct_db.py`(`SCHEMA`、`SHARDS`)。1つのPMIDは、1つのファイルにだけ入ります。
実測のJIFは持ちません(`jif_tier` のみ)。

| 区分 | 列 | 内容 |
|---|---|---|
| 取り込み(`ingest_historical.py`) | `pmid`(主キー), `publication_year`, `title`, `abstract`, `authors`, `first_author`, `journal_abbrev`, `journal_title`, `issn`, `eissn`, `doi`, `publication_types`, `mesh_terms`, `author_keywords`, `source_file`, `ingested_at` | PubMed の項目。繰り返す項目は JSON の配列(文字列) |
| AIの出力(`process_batch.py`) | `ai_relevance`, `ai_relevance_reason`, `ai_tags`, `ai_summary_en`, `ai_summary_ja`, `ai_abstract_ja`, `ai_title_ja`, `ai_processed_at`, `batch_id` | `ai_relevance`: relevant / uncertain / not_relevant / cns_gct。`ai_tags` は研究デザイン(JSON 配列で1つ)。抄録が無い論文には、決まった文言が入る |
| 関連性の状態 | `relevance_status`, `relevance_note`, `relevance_reviewed_at` | `NULL`(未判定)/ `kept` / `needs_review` / `excluded`。脳・脊髄原発のGCTの除外は、`relevance_note` の決まった文言(`process_batch.CNS_NOTE`)で見分ける |
| 公開前レビュー(`export_publish_review.py`・`publish_to_site.py`) | `human_review_status`, `human_review_note`, `human_reviewed_at` | approved / rejected / needs_edit。`relevance_status`(範囲に入るか)とは別の関門(AIが書いた内容を、そのまま公開してよいか) |
| JIF(`backfill_jif.py`) | `jif_tier`, `jif_match_status`, `jif_reference_version`, `jif_matched_at` | tier と、照合の根拠 |
| 公開 | `published_to_site`(0/1), `published_at`, `added_at` | 公開済みかどうかと日時 |

運用の注意:
- 値の修正は、`sqlite3` の `UPDATE` で直接できます。元に戻せるよう、変更前の値はバックアップ(`data/processed/*/..._backup_*.jsonl`)に残します。
- 列は後から足すことがあります(`gct_db.connect()` が、足りない列を開いたときに追加します)。
- データは削除しません(除外は `relevance_status='excluded'` で表します)。
