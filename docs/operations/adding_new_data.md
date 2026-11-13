# 新しい論文データを追加する流れ(2026-11 時点)

非公開リポジトリ `gct-literature-data` を `<data>`、公開リポジトリ(このリポジトリ)を `<site>` と書く。
**自動なのは「取り込み」(AI なし)と「状況レポートの更新」と「公開(デプロイ)」だけ。AI を使う処理は、ボタンにしておらず、Claude のセッションで、モデル・effort・対象・費用を示して許可を得てから実行する**(当面の運用。ボタン化には、Anthropic の API キーが要る)。

| # | 段階 | 内容 | 実行 |
|---|---|---|---|
| 1 | 置く | PubMed の検索結果を、Format: PubMed(MEDLINE 形式)の `.txt` で保存し、`<data>/data/raw/historical_bulk/` に、新しい名前でアップロードして main にコミットする(例: `GCT_literature_2026_20261109.txt`。過去のファイルは上書きしない) | あなた |
| 2 | 取り込み | Actions「0 取り込み(自動)」が、コミットで自動で動く。PMID で重複を除いて、DB に「未判定」で登録し、結果を実行画面に出す(新規の件数、発行年別、重複、AI判定待ちの合計) | **自動** |
| 3 | 状況レポート | `<data>/portal/STATUS.md` が、DB を更新するコミットのたびに、自動で更新される | **自動** |
| 4 | AI の判定・和訳 | `process_batch.py`(関連性の判定、日英の要約、題名と抄録の和訳。用語集に従う) | Claude のセッション(許可が要る) |
| 5 | 研究デザイン・属性・CNS | `classify_design.py` → `retag_categories.py`、`extract_attributes.py` / `extract_case_attributes.py` → `sync_site_attributes.py`、`screen_cns_gct.py`(手順: `attributes_and_screening.md`)。`needs_review` の人の確認は、`screen_by_criteria.py` と `apply_status_decisions.py` | Claude のセッション(許可が要る) |
| 6 | 公開前レビュー | Actions「3 公開前レビュー作成」(または `bulk_publish_decisions.py`) | あなた(ボタン) |
| 7 | 公開反映 | Actions「4 公開反映」が、このリポジトリへの PR を作る | あなた(ボタン) |
| 8 | 公開 | PR の `validate` が緑なのを確認して、マージ。`deploy.yml` が、検索データを作って公開する | マージはあなた。公開は**自動** |

## Claude のセッションに頼むときの言い方(例)
- 「2026年のデータを追加して。取り込みは済んでいる」→ 4・5 の対象件数と、費用の見積もりが示される。
- 許可は、段階ごとに出す(モデル・effort・対象件数・推定費用が、先に示される)。

## 4・5 のコマンド(手でも実行できる)
```bash
# 4. AI の判定・和訳(1回に --batch-size 件。実行のたびに、次のバッチへ進む。Claude Code の CLI が要る)
python3 scripts/process_batch.py --claude --db-dir <data>/data/master --batch-size 25
# 5. 公開してよい論文の、研究デザイン・属性・CNS(詳細: attributes_and_screening.md)
python3 scripts/classify_design.py --db-dir <data>/data/master --out <data>/data/processed/classification/design_ai.jsonl --claude
python3 scripts/screen_cns_gct.py screen --db-dir <data>/data/master --out <data>/data/processed/scope_screen/cns_gct.jsonl --claude
```
- どれも、使用量の上限に達すると止まり、同じコマンドで再開できる。
- 結果は、まず別ファイルに出して目視確認してから、DB・サイトに反映する。

## サイトにだけある文献を DB に取り込む(1回きりの整理)
データリポジトリを作る前に、サイトへ直接載せた文献(PMID で DB に見つからないもの)は、`scripts/import_site_only.py` で DB に行を足せる。サイトのデータは変えない。取り込んだ行は `source_file = 'site_only_import'`、`published_to_site = 1` で、出所が分かる(2026-11: 65件=掲載44・除外21)。
```bash
python3 scripts/import_site_only.py --db-dir <data>/data/master --papers data/papers [--apply]   # --apply なしはドライラン
```

## 自動化の範囲を広げるには
- AI の処理をボタン(Actions)にする場合は、Anthropic の API キーを GitHub の Secrets に登録し、API の従量課金で動かす(Claude の契約(Pro)では、Actions では動かせない)。件数・モデル・effort・費用の上限を、入力欄にして、許可の代わりにする形を提案している。
- 公開前レビュー・公開反映・PR のマージは、人の確認を残す。
