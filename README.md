# GCT文献データベースサイト

GCT関連文献を収集・整理して公開するWebサイト。**部分公開しながらデータを段階的に拡充する**ことを前提に、ビルド不要・運用最小の構成にしています。

## アーキテクチャ

- **ビルドステップなしの静的サイト**: HTML + CSS + Vanilla JS のみ。フレームワーク・npm 依存なし
- **データソースは `data/` の JSON のみ**: サイトの表示内容はすべて `data/papers.json`(文献)と `data/site.json`(サイト情報)から動的に描画
- **ホスティングは GitHub Pages**: `main` への push で GitHub Actions が自動デプロイ

```
index.html          … 一覧ページ(検索・タグ絞り込み・並び替え)
assets/
  app.js            … JSON を読み込んで描画するロジック
  style.css         … スタイル
data/
  site.json         … サイトタイトル・説明・お知らせ
  papers.json       … 文献データ本体(ここに追記していく)
  README.md         … データ追加手順とフィールド仕様
.github/workflows/
  deploy.yml        … main への push で JSON 検証 → gh-pages ブランチへ公開(GitHub Pages)
  validate.yml      … main 以外のブランチ/PR で JSON 文法・重複ID・必須項目を検証
```

`gh-pages` ブランチはデプロイ用の自動生成ブランチです。直接編集しないでください(main への push で毎回上書きされます)。

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
