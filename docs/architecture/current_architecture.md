# 現行のアーキテクチャ(2026-10)

## 2つのリポジトリ

| リポジトリ | 公開 | 役割 |
|---|---|---|
| `gct-literature-website` | Public | サイト本体(静的ファイル)、公開データ(`data/papers/`)、データ処理のスクリプト(`scripts/`)、検証(`programs/tests/`、`tests/`)、設計文書(`docs/`) |
| `gct-literature-data` | Private | 作業用のSQLite(全文献・AIの出力・判定・レビューの記録)、PubMedの原本、JIFの参照データ、用語集、AI抽出結果、実行ログ、GitHub Actions(データ作業ポータル) |

公開してよいもの(コード・公開データ)と、公開できないもの(JCRのJIF実数値・抄録の全文・作業用DB)は、リポジトリごと分けます。データの流れは**一方向**で、非公開側から公開側へ、公開してよい部分だけを反映します。

## データの流れ

```text
PubMed の MEDLINE テキスト(年別。data/raw/historical_bulk/)
  → ingest_historical.py        … PMID で重複を除いて SQLite に登録(AIなし)
  → process_batch.py            … AIが関連性を判定し、日英の要約・題名と抄録の和訳を作る(用語集に従う)
       relevance_status: kept / needs_review / excluded(CNS-GCT を含む)
  → classify_design.py ほか     … 研究デザイン(9分類)・属性(extract_attributes.py 他)・CNS 判定(screen_cns_gct.py)
  → export_publish_review.py / bulk_publish_decisions.py  … 公開前レビューの decisions TSV
  → publish_to_site.py          … approve の行だけ data/papers/ に追加 → このリポジトリへの PR
  → PR をマージ(人の操作)
  → deploy.yml                  … 検索データ(search/・pagefind/)を生成して gh-pages に公開
  → GitHub Pages
```

非公開リポジトリの GitHub Actions(`portal/README.md`)が、状況レポート、JIFの参照データ追加・遡及、公開前レビュー作成、公開反映を、ボタン操作で実行します。AIを呼ぶ処理は、Claude のセッションから `claude -p` 経由で実行します(実行前に、モデル・effort・対象・費用の許可を得る)。

## サイトの仕組み

- 画面: `index.html`(日本語)、`en/index.html`(英語)、`assets/app.js`・`assets/attr-labels.js`・`assets/search-lib.js`・`assets/style.css`。ブラウザは、最初に `search/list.json`(軽い一覧。抄録を除く)を1回読み込み、絞り込み・並び替えはブラウザ内で行います。
- 検索: Pagefind は「語 → 論文ID」の引き当てだけに使い、抄録は、カードを開いたときに `search/abstract/<id>.json` から読みます(`docs/decisions/2026-09-30_pagefind_search.md`、`docs/operations/site_search.md`)。
- 公開データ: `data/papers/papers_<年代>.json`(年代別、`index.json` が一覧。`docs/decisions/2026-10-11_split_papers_json.md`)。フィールドは `docs/data_dictionary/site_papers_v1.md`。
- 絞り込み: 区分(臨床/基礎)→ 研究デザイン(9分類)→ 属性(臨床のみ)。URLに選択が入ります(`docs/decisions/2026-10-12_study_design_taxonomy.md`、`2026-10-26_attribute_filters.md`)。

## 検証とデプロイ

- `validate.yml`(main 以外のブランチ・PR): JSON・重複ID、Python のテスト、検索データのビルドと全文一致の照合、区分・研究デザイン・属性の絞り込みを、ubuntu-24.04 で検証します。
- `deploy.yml`(main への push): 検証 → 検索データ生成 → gh-pages に公開。
- 本番に反映されるのは、PR をマージしたときだけです。

## 旧世代(TSV パイプライン)

`programs/` の TSV ベースのパイプライン(PubMed クリーナー → 候補TSV → マスターTSV → UMIN SQUARE 向けのTSVサイト)は、本番では使っていません(設計の記録: `tsv_site_architecture.md`)。一部だけが現役です(用語集のパーサー、JIFの照合、JCR CSV の変換)。詳細は `programs/README.md`。
