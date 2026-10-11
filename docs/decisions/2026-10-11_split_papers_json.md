# Decision: 公開データ `data/papers.json` を年代別のファイルに分割する

- Date: 2026-10-11
- Status: adopted

## きっかけ

公開データの一括公開(約1.9万件)で、`data/papers.json` が約80MB になった。GitHub のファイルは100MBが上限で、
50MBを超えると警告も出る。残りの余裕は約2万件分しかなく、`needs_review` の確認が済んだ分や、毎週の追加ですぐ届く。

## 決めたこと

- `data/papers.json` をやめ、`data/papers/` に年代ごとのファイルを置く。
  `papers_pre1980.json`、`papers_1980s.json` … `papers_2020s.json`(発行年で振り分け)と、その一覧 `index.json`。
- 読み書きは `scripts/papers_store.py` に集約する。ディレクトリを渡すと分割ファイルを、ファイルを渡すと従来どおり
  1つのJSONを扱う。`data/papers.json` を指定して `data/papers/` がある場合は、後者に読み替える(古い呼び出しの互換)。
- 保存時は、中身が変わったシャードだけを書き換える。新しい文献は発行年のシャードの末尾に追加されるので、差分は小さい。
- サイトの表示は変わらない。ブラウザは今までどおり `search/list.json`(ビルドで `data/papers/` から生成)を読む。
  検索データが使えない場合の予備として、`index.json` の順に全シャードを読んで連結する。

## 大きさ(2026-10-11 時点、19,322件)

| ファイル | 大きさ |
|---|---|
| papers_pre1980 | 2.3MB |
| papers_1980s | 10.7MB |
| papers_1990s | 15.1MB |
| papers_2000s | 16.9MB |
| papers_2010s | 17.5MB |
| papers_2020s | 17.9MB |

最大のシャードでも約18MB。2020年代のシャードが毎週増えるので、100MBに近づく前(目安: 50MB)に、
2020年代を年ごとに分ける(`shard_name` を変えるだけでよい)。

## 変更したもの

- 読み書きするスクリプト: publish_to_site / backfill_jif / match_jif / review_relevance / ingest_historical /
  import_medline / sync_site_translations / retag_categories / screen_cns_gct / check_terminology
  (いずれも `--papers` などの引数にディレクトリを渡せる。既定は `data/papers`)
- `scripts/build_site_search.mjs`、`assets/app.js`(予備の読み込み)、`.github/workflows/{deploy,validate}.yml`
- データリポジトリ側: `portal/open_website_pr.sh`、ワークフロー「2 JIF遡及」「4 公開反映」のパス

## 注意

- 順序: 全体の並びは、年代の古い順にシャードを連結したものになる(従来は公開した順)。画面の並びは年で並べ替えるため影響しない。
- 既知の問題(分割とは無関係): 検索の一致テスト(`npm run check:search`)が、約1.9万件の規模で失敗する。
  英語の語の一部(例: `seminoma` で `non-seminomatous` のみの論文)が、検索結果に出ない。分割の前後で結果は同じ。
