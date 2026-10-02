# 英和対訳用語集(移動しました)

和訳(`title_ja` / `summary_ja` / `abstract_ja`)で使う用語集は、データの一部として扱うため、**非公開のデータリポジトリ**へ移しました。

- 場所: `gct-literature-data/data/reference/terminology/terminology_ja.md`
- AI処理(`scripts/process_batch.py`、`programs/literature_pipeline/pipeline.py`)は、データリポジトリ側のこのファイルを指示文に埋め込みます
  (`--glossary` で場所を変更可。ファイルが無いとエラーで止まり、用語集なしでの実行は `--no-glossary` を明示したときだけです)。
- 運用は、そのファイルの冒頭の説明を参照してください。
