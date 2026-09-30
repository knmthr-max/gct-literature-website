# Decision: JCR の「N/A」(JIFなし)を参照データに記録する区別は実装しない(保留)

- Date: 2026-09-30
- Status: deferred(将来、方針を変えるかもしれない)

## きっかけ

`BMJ Case Rep`(ESCI収載誌)は、JCRの All Years CSV に 2025〜2022年のJIFがあり、2021年は `N/A`、
それ以前の年はCSVに載っていない。DBには2009〜2021年の論文が110件あり、これらは「未確認」のまま残る。
ESCI誌には2022年分より前のJIFが存在しないので、CSVを追加しても埋まらない。

## 現状の挙動

- `jif_reference_cleaner.py` は `N/A` などJIFの無い行を読み飛ばす(参照TSVには入らない)。
- そのため「JCRが『JIFなし』と明示した年」と「参照データにまだ入れていない年」を区別できず、
  どちらも `year_not_found`(その年のJIFが参照データに無い)になる。
- 「参照データに追加すると埋まる発行年」の集計に、ESCI誌の古い年のように追加しても埋まらない年が混ざる。
- JCRを追加すれば埋まる年が、この集計では見分けにくくなる(過大に見える)。

## 決めたこと

区別は**実装しない**。上の挙動のまま運用する。集計の「埋まる年」は、上限の目安として読む。

## 将来やるなら(メモ)

- cleaner で `N/A` の行を「jif が空の行」として参照TSVに残す。
  `JIFMatcher` は jif が空の行を既に `suppressed_or_unavailable`(JIF非開示/未付与)として扱えるので、
  照合側の変更は小さい。`suppressed_or_unavailable` は「不足の年」の集計に数えない扱いにする。
- 統合処理(`jif_reference_add.py` の `merge_rows`)と `fact_set` が、空JIFの行を扱えるようにする。
  「値の食い違い」の判定で、空JIFと数値が衝突しないようにする(数値を優先)。
- 既存データには、`N/A` の行が参照TSVに入っていない。反映するには、`raw/` のCSVを再変換する必要がある
  (`processed_raw.tsv` の台帳は、変換済みCSVを再処理しない設計なので、台帳の扱いを決める)。
- CSVに載っていない年(ESCI誌の5年より前など)は、この方法でも区別できない。
  区別するには、その雑誌の「最初にJIFが付いた年」より前かどうかの判定が別途要る。

関連: `scripts/backfill_jif.py`(`year_not_found` の集計)、`programs/literature_pipeline/pipeline.py`(`JIFMatcher.match`)、
`programs/literature_pipeline/jif_reference_cleaner.py`(`is_available_jif`)。
