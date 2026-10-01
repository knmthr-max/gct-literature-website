# サイト内検索(Pagefind)の運用

設計と根拠: `docs/decisions/2026-09-30_pagefind_search.md`

## 人の作業は変わらない

新しい文献の公開は、これまでどおり「3 公開前レビュー作成 → 4 公開反映 → 公開サイトのPRをマージ」です。
マージ後のデプロイ(`.github/workflows/deploy.yml`)が、検索データを自動で作って公開します。人が検索のために行う作業はありません。

## 仕組み(自動)

デプロイのたびに `node scripts/build_site_search.mjs` が `data/papers.json` から次を生成し、公開ブランチ(gh-pages)に出します。
リポジトリにはコミットしません(`.gitignore` 済み)。

| 生成物 | 内容 |
|---|---|
| `search/list.json` | 軽い一覧(抄録・人向けメモを除く) |
| `search/abstract/<id>.json` | 抄録(英/日)。カードを開いたときに読む |
| `search/idmap.json` | 検索結果ID → 論文ID |
| `pagefind/` | 検索索引 |

- 生成に失敗するとデプロイも失敗し、公開中のサイトは前の状態のままです(Actions のログで原因を確認できます)。
- PR の検証(`validate.yml`)も、同じ生成と検索の一致テストを実行します。失敗したPRはマージしないでください。

## 検索の使い方(サイト利用者向け)

| 書き方 | 意味 | 例 |
|---|---|---|
| 空白で区切る | AND | `胚細胞腫瘍 化学療法` |
| `OR` または `|` | OR | `精巣 OR 卵巣` |
| `-語` | 除外 | `腫瘍 -精巣` |

1文字だけの日本語は、タイトル・要約・著者・雑誌の範囲の部分一致になります(抄録は対象外)。

## 新方式の有効化(現在)

現在は、URL に `?search=pagefind` を付けたときだけ新方式です(例: `https://<サイト>/?search=pagefind`)。
付けなければ従来の検索(全件読み込み)です。実機での確認後に、既定を切り替えます。

## 手元で確認する

```bash
npm ci
npm run test:search          # 単体テスト(速い)
npm run build:search         # 検索データを生成(リポジトリ直下に search/ と pagefind/ ができる)
npx playwright install chromium   # 初回のみ
npm run check:search         # 実ブラウザでの一致テスト
python3 -m http.server 8000  # http://localhost:8000/?search=pagefind で表示を確認
```

## 件数が増えたとき

- 約1,000件を超えて `list.json` が重くなったら、年ごとの分割と、直近年を先に読む方式に進めます(設計書 6)。
- 生成のたびに、`list.json` の1件あたりの大きさと索引の大きさがログに出ます。
