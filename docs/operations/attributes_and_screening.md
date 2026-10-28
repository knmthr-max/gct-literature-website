# 属性抽出・分類・用語の運用

非公開データを `<data>` = `gct-literature-data/data` と書く。AIを呼ぶコマンドは `--claude` を付けたときだけ実行される(付けないとドライラン)。
**AIの実行前に、モデル・effort・対象・推定費用を示して許可を得る**(README「AI処理の運用ルール」)。

## 研究デザインのタグを直す(誤りに気づいたとき)
1. `<data>/reference/classification/tag_overrides.tsv` に1行足す(`pmid<TAB>タグ<TAB>理由`)。
2. DBに反映: `python3 scripts/retag_categories.py --db-dir <data>/master --overrides <data>/reference/classification/tag_overrides.tsv --ai-results <data>/processed/classification/design_ai_final.jsonl --site-papers data/papers --backup <data>/processed/classification/retag_backup_<日付>.jsonl [--apply]`
   (`--ai-results` を付けないと、PubMedの文献種別だけで再計算され、多数が変わる。必ず付ける。dry-run で件数を確認する)
3. DBは変更済みでサイトだけ直すとき: `python3 scripts/sync_site_tags.py --db-dir <data>/master --papers data/papers [--apply]`
4. タグを直した論文は、デザイン固有の属性が古くなる。`sync_site_attributes.py` を再実行すると外れる。

## 属性の抽出とサイトへの反映
| 目的 | コマンド |
|---|---|
| RCT・非ランダム化試験・SR・MA・観察研究の属性と、臨床テーマ | `python3 scripts/extract_attributes.py extract --db-dir <data>/master --out-dir <data>/processed/attributes_v2 [--designs ...] [--limit-per-design N] --claude` (effort 既定 medium、再開可) |
| 臨床テーマだけ(症例報告・総説・その他・ガイドライン) | 同上で `--designs 症例報告・集積,総説,その他,ガイドライン・コンセンサス` |
| 症例報告の共通項目 | `python3 scripts/extract_case_attributes.py extract --db-dir <data>/master --out <data>/processed/case_attributes/<名前>.jsonl [--only-pmids <PMID一覧>] --claude` |
| 抽出結果の集計 | `python3 scripts/extract_attributes.py stats --out-dir <data>/processed/attributes_v2` |
| サイトの `attrs` に反映 | `python3 scripts/sync_site_attributes.py --papers data/papers --attributes <data>/processed/attributes_v2 --case <data>/processed/case_attributes/full.jsonl [やり直しのファイル ...] [--apply]` (`--case` は複数可。後ろが前を上書き) |

- 抽出ルール(選択肢・プロンプト)は `scripts/extract_attributes.py` と `scripts/extract_case_attributes.py`。選択肢は症例報告と共通(症例報告側は上位互換に拡張済み)。
- ルールを直したら、まず少数(各デザイン10件ほど)を再抽出し、**前回と変わった項目だけの一覧**を目視確認する。AIの出力には揺れがあり、無関係な項目まで変わることがある。全部を入れ替えず、変えたい項目だけ反映する(例: `case_attributes/rest_redo_selected.jsonl`)。
- 症例報告は最初の版(組織型に妊娠性絨毛癌・非セミノーマの選択肢が無い)で抽出したため、2026-10-29 に絨毛癌1,237件・非セミノーマ534件を再抽出し、残りは新しい選択肢に移った分だけを反映した(`chorio_redo.jsonl`・`nsgct_redo.jsonl`・`rest_redo.jsonl`・`rest_redo_selected.jsonl`)。
- 妊娠性絨毛癌をサイトの選択肢から外す方法は `docs/decisions/2026-10-26_attribute_filters.md`。

## 脳・脊髄原発の胚細胞腫瘍(CNS-GCT)のスクリーニング
- `python3 scripts/screen_cns_gct.py screen --db-dir <data>/master --out <data>/processed/scope_screen/cns_gct.jsonl [--only-pmids <PMID一覧>] --claude` (effort 既定 low、再開可)
- `python3 scripts/screen_cns_gct.py apply --db-dir <data>/master --out ... --backup <data>/processed/scope_screen/cns_gct_backup_<日付>.jsonl --site-papers data/papers [--apply]` — `cns_primary` だけを `excluded` にする(元の状態はバックアップ)。`mixed`・`uncertain` は触らず、掲載のまま。
- 新しく判定する論文には、判定ラベル `cns_gct` が付くため、通常は再実行不要。方針と記録: `docs/decisions/2026-10-08_cns_gct_excluded_but_retained.md`、`<data>/processed/scope_screen/README.md`。

## 和訳の用語
- 正本は `<data>/reference/terminology/terminology_ja.md`。標準の訳と「避ける訳」を登録する(英語の語が出る論文の翻訳指示に自動で入る)。
- 点検: `python3 scripts/check_terminology.py --db-dir <data>/master --out <data>/processed/terminology/check.tsv`
- 誤った表記の機械的な置換: `python3 scripts/replace_terms.py --db-dir <data>/master --papers data/papers --replace 旧=新 [--replace ...] --backup <data>/processed/terminology/replace_backup_<日付>.jsonl [--apply]` (DBの `ai_*_ja` とサイトの和訳・判定メモが対象。dry-run が既定)。置換したら、用語集の「避ける訳」にも登録する。

## 検証(PR を出す前)
- `python3 -m unittest discover -s programs/tests`
- `npm run build:search`(約3分)の後、`npm run check:search`(検索の取りこぼし0)、`npm run check:filter`(区分・研究デザイン)、`npm run check:attr`(属性)。`CHROMIUM_PATH` に Chromium のパスを渡すと、Playwright のブラウザを入れずに実行できる。
- CI(`validate.yml`)は同じ検証を ubuntu-24.04 で行う。**マージ前に緑であることを確認する**。
