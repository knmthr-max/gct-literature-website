# GCT文献データベースサイト

GCT関連文献を収集・整理して公開するWebサイト。**部分公開しながらデータを段階的に拡充する**ことを前提に、ビルド不要・運用最小の構成にしています。

## アーキテクチャ

- **静的サイト**: HTML + CSS + Vanilla JS のみ。フレームワークは使わない。検索データ(`search/`・`pagefind/`)だけは、デプロイ時に `scripts/build_site_search.mjs` が生成する(リポジトリにはコミットしない。Node と Pagefind はビルドと検証にだけ使い、ブラウザには読み込まない)
- **データソースは `data/` の JSON のみ**: サイトの表示内容はすべて `data/papers/`(文献。年代別の `papers_*.json`)と `data/site.json`(サイト情報)から動的に描画
- **ホスティングは GitHub Pages**: `main` への push で GitHub Actions が自動デプロイ

```
index.html          … 日本語ページ(メイン、全文検索・区分/研究デザイン/属性の絞り込み・並び替え)
en/index.html         … 英語専用ページ(同じ data/ を参照。日本語訳やタグの和名は表示しない)
assets/
  app.js            … 一覧・検索・絞り込みの描画ロジック。<body data-lang> で日英を切り替える
  attr-labels.js    … 属性の絞り込み項目と表示名(日英)
  search-lib.js     … 検索式の解釈と Pagefind の呼び出し
  style.css         … スタイル(日英共通)
data/
  site.json         … サイトタイトル・説明・お知らせ
  papers/           … 文献データ本体(年代別の papers_*.json と index.json。scripts/papers_store.py で読み書き)
  raw/              … PubMedからエクスポートした生データ(.nbib)の保管場所
  README.md         … データ追加手順とフィールド仕様
scripts/            … データ処理・検証のスクリプト(一覧と使い方は docs/operations/attributes_and_screening.md)
  build_site_search.mjs … 検索データ(search/・pagefind/)の生成
  check_*.mjs       … 実ブラウザでの検索・絞り込みの検証
.github/workflows/
  deploy.yml        … main への push で JSON 検証 → gh-pages ブランチへ公開(GitHub Pages)
  validate.yml      … main 以外のブランチ/PR で JSON・重複ID・Python テスト・検索の一致・絞り込みを検証(ubuntu-24.04 固定)
```

`gh-pages` ブランチはデプロイ用の自動生成ブランチです。直接編集しないでください(main への push で毎回上書きされます)。

## 日英2ページ構成

日本語ユーザーをメインに想定しつつ、英語のみで読めるページ(`en/`)を別途用意しています。データは**共有**しており、`data/papers/` / `data/site.json` を1箇所編集するだけで両ページに反映されます(翻訳データを2重管理する必要はありません)。

- `index.html`(`/`): `title_ja` を優先表示、原題を小さく併記。タグ(研究デザイン)は日本語のまま(`症例報告・集積`等)
- `en/index.html`(`/en/`): `title` (英語) のみ表示、`title_ja` は出さない。タグは `assets/app.js` 内の `TAG_LABELS_EN` で英語ラベルに変換して表示(データ自体は書き換えない)
- 言語判定は `<body data-lang="en">` 属性で行う。`en/index.html` は `data-root="../"` も併せて指定し、1階層上の `assets/`・`data/` を参照する
- `site.json` は `title`/`description`/`notice`(英語)と `title_ja`/`description_ja`/`notice_ja`(日本語)を両方持つ。機械翻訳ではなく、GCT領域の文脈を踏まえて人(Claude)が直接執筆する方針

## `programs/` — 共有モジュールとテスト

`scripts/` のデータ処理が使う共有モジュールと、回帰テストを置いています(`python3 -m unittest discover -s programs/tests`)。

```
programs/
  README.md, VERSIONS.md    … 一覧と版情報
  pubmed_cleaner/            … MEDLINE テキストのパーサー(scripts/ingest_historical.py が使う)
  literature_pipeline/       … JIF の参照データ変換(jif_reference_cleaner.py)・照合(jif_matcher.py)、用語集のパーサー(glossary.py)
  tests/                     … 上記と scripts/ の回帰テスト
```

最初に作った TSV ベースのパイプライン(候補TSV → マスターTSV → UMIN SQUARE 向けTSVサイト)は、本番で使わなかったため **2026-10 に削除しました**(git の履歴に残っています。`programs/README.md`)。現行の流れは、下の「データフロー」と `docs/architecture/current_architecture.md` です。

**非公開データとの接続に注意:** JCR のJournal Impact Factor のライセンスデータ(`data/reference/jif/`)は、著作権上**このリポジトリには含めていません**。参照データの追加と遡及は、非公開リポジトリの GitHub Actions で行います。

設計の詳細・データ定義は [`docs/`](docs/) を参照。

## データフロー

```
文献の収集・AI判定・和訳(非公開リポジトリ gct-literature-data のSQLite。スクリプトはこのリポジトリの scripts/)
  → 公開してよい論文を data/papers/ に反映するブランチを作る(portal の workflow または scripts/)
  → 人が内容を確認して PR をマージ(validate.yml の結果が緑であることを確認してから)
  → deploy.yml が検索データを生成して GitHub Pages に公開
```

サイトの表示内容を変える作業は、**PR のマージだけ**が人の操作です(AIの実行は、モデル・effort・対象・費用を示して許可を得てから行う)。詳細なフィールド仕様は [`data/README.md`](data/README.md) を参照。

## 現行の仕様(2026-10 時点)

詳細は各 `docs/decisions/` の文書。

- **対象範囲**: 胚細胞腫瘍(GCT)に関する文献。**脳・脊髄に原発する胚細胞腫瘍(CNS-GCT)は対象外**(データは削除せず非公開データ側に残す。`2026-10-08_cns_gct_excluded_but_retained.md`)。判定が「混合」「不確か」のものは、人の確認なしで掲載する。
- **研究デザインのタグ**(1論文に1つ、9分類): SR・MA / RCT / 非ランダム化試験 / 観察研究 / 症例報告・集積 / 総説 / ガイドライン・コンセンサス / 基礎・トランスレーショナル / その他。基礎以外はすべて「臨床」として扱う。分類は PubMed の文献種別を優先し、決められないものだけAIが判定する。個別の誤りは上書き表(`gct-literature-data/data/reference/classification/tag_overrides.tsv`)で直す(`2026-10-12_study_design_taxonomy.md`)。
- **全文検索**: Pagefind(題名・要約・抄録・著者・雑誌)。AND は空白、OR は「OR」、除外は「-語」(`2026-09-30_pagefind_search.md`、`docs/operations/site_search.md`)。
- **データの分割**: 公開データは年代別の `data/papers/papers_<年代>.json`。読み書きは `scripts/papers_store.py`(`2026-10-11_split_papers_json.md`)。
- **属性の絞り込み**(臨床のみ): AIが抄録から抽出した属性(臨床テーマ・原発部位・組織型・性別・年齢区分・治療。研究デザインを選ぶと、そのデザイン固有の項目)で絞り込む。病期・IGCCCG・例数はカード表示のみ。結果の数値は扱わない。「不明」は選択肢に出さない。妊娠性絨毛癌は組織型の独立した選択肢(`2026-10-26_attribute_filters.md`)。
- **和訳の用語**: 用語集(`gct-literature-data/data/reference/terminology/terminology_ja.md`)が正本。誤った表記は `scripts/replace_terms.py` で機械的に置換し、「避ける訳」に登録する。

## AI処理の運用ルール

- モデルの既定は Haiku 5.5(`claude-haiku-5-5`)。関連性判定・和訳・分類は effort `low`、属性抽出と研究デザイン分類は `medium`(いずれも少数の目視確認の上で採用)。
- **実行の前に、モデル・effort・対象・推定費用を示して許可を得る**。実行結果は、まず別ファイルに出し、目視確認(o/x)の後に DB・サイトへ反映する。AIの出力には揺れがあるため、前回との差分(変わった項目だけ)を確認する。
- 使用量の上限に達したら止める(同じコマンドで再開できる。回復を待つかは指示を受ける)。
- 長時間の実行は、実行中の作業セッションを閉じない(閉じると実行が止まる)。

## 公開のしくみ

`main` への push で deploy.yml が動き、サイト一式を `gh-pages` ブランチに書き出します。GitHub Pages は `gh-pages` ブランチを配信します(URL: `https://<ユーザー名>.github.io/gct-literature-website/`)。リポジトリは Public である必要があります。

独自ドメインを使う場合は Settings → Pages でカスタムドメインを追加してください。

## ローカルでの確認

`fetch` を使うため `file://` では動きません。簡易サーバーで確認します:

```sh
python3 -m http.server 8000
# → http://localhost:8000 を開く
```

## 拡充ロードマップ(想定)

- [x] 実データでの部分公開(年代別に段階的に拡充)
- [x] 研究デザイン9分類と、基礎/臨床の二段階の絞り込み
- [x] 全文検索(Pagefind)と、データの年代別分割
- [x] 臨床論文の属性による絞り込み
- [x] 初回の読み込みの高速化(一覧を先頭20件・核・詳細に分割。`docs/decisions/2026-11-01_split_list_data.md`)
- [ ] 公開後の実測: 実機のスマホでの初回表示
- [ ] 公開前レビューが済んでいない論文(needs_review 約2,400件)の判断
- [ ] 必要になったら: 文献ごとの個別ページ・カテゴリ解説ページの追加

現状の構成(約2万件を公開)は、先頭20件をすぐに出し、全件の一覧の核(約2MB gzip)を読んでから、絞り込み・検索を使えるようにする方式です。データ形式(JSON スキーマ)を先に固定してあるので、将来サイト側の実装を差し替えてもデータはそのまま流用できます。
