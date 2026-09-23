# GCT文献データベースサイト

GCT関連文献を収集・整理して公開するWebサイト。**部分公開しながらデータを段階的に拡充する**ことを前提に、ビルド不要・運用最小の構成にしています。

## アーキテクチャ

- **ビルドステップなしの静的サイト**: HTML + CSS + Vanilla JS のみ。フレームワーク・npm 依存なし
- **データソースは `data/` の JSON のみ**: サイトの表示内容はすべて `data/papers.json`(文献)と `data/site.json`(サイト情報)から動的に描画
- **ホスティングは GitHub Pages**: `main` への push で GitHub Actions が自動デプロイ

```
index.html          … 日本語ページ(メイン、検索・タグ絞り込み・並び替え)
en/index.html         … 英語専用ページ(同じ data/ を参照。日本語訳やタグの和名は表示しない)
assets/
  app.js            … JSON を読み込んで描画するロジック。<body data-lang> で日英を切り替える
  style.css         … スタイル(日英共通)
data/
  site.json         … サイトタイトル・説明・お知らせ
  papers.json       … 文献データ本体(ここに追記していく)
  raw/              … PubMedからエクスポートした生データ(.nbib)の保管場所
  README.md         … データ追加手順とフィールド仕様
scripts/
  import_medline.py … PubMedの .nbib ファイルを papers.json に自動取り込み
.github/workflows/
  deploy.yml        … main への push で JSON 検証 → gh-pages ブランチへ公開(GitHub Pages)
  validate.yml      … main 以外のブランチ/PR で JSON 文法・重複ID・必須項目を検証
```

`gh-pages` ブランチはデプロイ用の自動生成ブランチです。直接編集しないでください(main への push で毎回上書きされます)。

## 日英2ページ構成

日本語ユーザーをメインに想定しつつ、英語のみで読めるページ(`en/`)を別途用意しています。データは**共有**しており、`data/papers.json` / `data/site.json` を1箇所編集するだけで両ページに反映されます(翻訳データを2重管理する必要はありません)。

- `index.html`(`/`): `title_ja` を優先表示、原題を小さく併記。タグは日本語のまま(`症例報告`等)
- `en/index.html`(`/en/`): `title` (英語) のみ表示、`title_ja` は出さない。タグは `assets/app.js` 内の `TAG_LABELS_EN` で英語ラベルに変換して表示(データ自体は書き換えない)
- 言語判定は `<body data-lang="en">` 属性で行う。`en/index.html` は `data-root="../"` も併せて指定し、1階層上の `assets/`・`data/` を参照する
- `site.json` は `title`/`description`/`notice`(英語)と `title_ja`/`description_ja`/`notice_ja`(日本語)を両方持つ。機械翻訳ではなく、GCT領域の文脈を踏まえて人(Claude)が直接執筆する方針

## `programs/` — 本来のデータ処理パイプライン(移植済み)

`scripts/import_medline.py` はこのサイト単体で使える簡易版インポータですが、`programs/` 配下にはより本格的な、人によるレビューを挟む処理パイプラインが移植されています(元は別ワークスペースで運用されていたもの):

```
programs/
  README.md, VERSIONS.md    … プログラム一覧と版情報
  pubmed_cleaner/            … PubMed MEDLINE textをMH/OT保持TSVへ変換
  literature_pipeline/       … PubMed取り込み→JIF照合→Claude分類→人によるレビュー→マスター昇格
  literature_site/           … 承認済みマスターTSVから公開用TSV・検索indexを生成
  tests/                     … 上記プログラムの回帰テスト(`python3 -m unittest discover -s programs/tests`)
```

`literature_pipeline/pipeline.py` は `--claude` オプション付きでローカルの `claude` CLI を呼び出し、文献の分類・要約下書きを行い、`approve` ステップで人が承認したものだけを `data/master/literature/` に昇格させる設計です(現時点ではこのリポジトリの `data/papers.json` とは連携していません — 将来の統合候補)。

**非公開データとの接続に注意:** `jif_reference_cleaner.py` はJournal Impact Factor(JCR)のライセンスデータを扱うプログラムですが、そのデータ自体(`data/reference/jif/`)は著作権上**このリポジトリには含めていません**。ローカルで運用する場合は、ライセンスされた別データを別途用意してください。

設計の詳細・データ定義は [`docs/`](docs/) を参照。

## データフロー

```
文献を選定
  → data/papers.json にエントリを追記(手動 or スクリプト)
  → ブランチに push(validate.yml が JSON をチェック)
  → main にマージ
  → deploy.yml が自動で GitHub Pages に公開
```

反映に必要な作業は **JSON への追記と push だけ**です。詳細なフィールド仕様は [`data/README.md`](data/README.md) を参照。

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

- [ ] サンプルデータを実データに置き換え、部分公開開始
- [ ] 文献データの拡充(タグ体系を運用しながら整備)
- [ ] 件数が増えたら: タグ以外の絞り込み軸(年代・研究デザイン等)の追加
- [ ] 必要になったら: 文献ごとの個別ページ・カテゴリ解説ページの追加
- [ ] データ量が数千件を超えたら: `papers.json` の分割読み込みや静的生成への移行を検討

現状の構成は数百〜千件程度までは十分軽快に動作します。データ形式(JSON スキーマ)を先に固定してあるので、将来サイト側の実装を差し替えてもデータはそのまま流用できます。
