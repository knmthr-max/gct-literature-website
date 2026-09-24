# データの追加・更新方法

このディレクトリがサイトの**唯一のデータソース**です。ここの JSON を編集して push するだけでサイトに反映されます(ビルド作業は不要)。

## 文献を追加する(推奨: PubMedデータから自動取り込み)

1. PubMed で文献を選び、**Save → Format: PubMed** でエクスポートする(MEDLINE形式)。ファイルの拡張子は `.nbib` でも `.txt` でも構いません(PubMed形式の表示をコピーして .txt に貼り付けたものでもOK)。スクリプトは拡張子ではなく中身で判断します
2. そのファイルを `data/raw/` に置く(例: `data/raw/2026-09-07-import.nbib`)
3. 取り込みスクリプトを実行する:

```sh
python3 scripts/import_medline.py data/raw/2026-09-07-import.nbib
# 複数ファイルをまとめて取り込むこともできます
python3 scripts/import_medline.py data/raw/*.nbib data/raw/*.txt
```

タイトル・著者・掲載誌・年・PMID・DOI・抄録・タグ(下記の固定7分類のいずれか)が自動で `papers.json` に追記されます。PMIDで重複判定するので、同じファイルを二度実行しても二重登録にはなりません。取り込み後、`title_ja`(日本語タイトル)や `summary_ja`(日本語要約)、`abstract_ja`(日本語抄録)を手で書き足すと、サイトでは日本語が優先表示されます。

## 文献を手動で追加する

`papers.json` の配列にエントリを1件追記します。

```json
{
  "id": "2026-0001",
  "title": "英語原題(必須)",
  "title_ja": "日本語タイトル・訳(任意)",
  "authors": ["著者1", "著者2"],
  "journal": "掲載誌名",
  "year": 2026,
  "pmid": "12345678",
  "doi": "10.1000/example",
  "url": "",
  "tags": ["総説"],
  "summary_en": "English summary (optional)",
  "summary_ja": "日本語の要約(任意)",
  "abstract_ja": "日本語訳の抄録(任意)",
  "added_at": "2026-09-01"
}
```

### フィールド仕様

| フィールド | 必須 | 説明 |
|---|---|---|
| `id` | ✅ | サイト内で一意のID。形式は自由(例: `2026-0001`)。後から変えない |
| `title` | ✅ | 論文タイトル |
| `year` | ✅ | 発行年(数値) |
| `title_ja` | – | 日本語タイトル。あれば一覧で優先表示 |
| `authors` | – | 著者の配列 |
| `journal` | – | 掲載誌 |
| `pmid` | – | PubMed ID。あれば PubMed へのリンクを自動生成 |
| `doi` | – | DOI。あれば doi.org へのリンクを自動生成 |
| `url` | – | その他のリンク(PMID/DOI がない場合用) |
| `tags` | – | 絞り込み用タグ。**必ず次の7分類のうち1つのみ**を入れる: `症例報告` / `臨床研究` / `基礎研究` / `総説` / `ガイドライン` / `論説` / `レター`。PubMedの著者キーワードや細かい文献種別はここに入れない(タグクラウドが機能しなくなるため)。該当なしなら空配列 `[]` |
| `summary_en` | – | 英語の短い要約・コメント |
| `summary_ja` | – | 日本語の短い要約・コメント |
| `abstract` | – | 英語の全文抄録。サイトでは折りたたみ表示される |
| `abstract_ja` | – | 日本語訳の全文抄録。収載文献は基本的に英語が原文であるため、日本語ページでは訳文(「抄録」)と英語原文(「抄録原文(英語)」)を**両方**、別々の折りたたみで常に参照できる。訳が無い場合は「抄録(英語)」に原文のみ表示する |
| `jif_tier` | – | Journal Impact Factorの階層(`low`/`moderate`/`high`/`very-high`/`unknown`)。実数値は非公開リポジトリ(`gct-literature-data`)にのみ保持し、ここには入れない。`unknown` は「JCR参照データに該当誌・該当年のデータが無く判定できない」ことを明示する値で、フィールド自体を省略する(未整備で表示されないのか、判定不能なのか区別できない)よりも意図的にこちらを使う。`programs/literature_pipeline/README.md` の `scripts/match_jif.py` で自動生成する |
| `relevance_status` | – | GCT(胚細胞腫瘍)関連性レビューの結果。`kept`(掲載継続)/`excluded`(除外)/`needs_review`(要確認)のいずれか。**フィールド未設定は`kept`と同じ扱い**(サイトは`excluded`のときだけ非表示にする)。`scripts/review_relevance.py` で生成・反映する。採否は後からdecisions TSVを作り直してAI判定・人間の確認を経ればいつでも修正できる |
| `relevance_note` | – | `relevance_status` の判断理由(AIの判定理由、または人間が上書きした場合はそのメモ) |
| `relevance_reviewed_at` | – | 関連性レビューを反映した日時(ISO 8601) |
| `added_at` | – | 掲載日 (`YYYY-MM-DD`)。新着表示に使用 |

`summary_en`/`summary_ja` がどちらも空の場合、サイトには「要約: 準備中」(英語ページでは "Summary: not yet available")と表示され、要約が存在しないのではなく未整備であることが分かるようになっています。

`jif_tier` の境界値: low(<1) / moderate(1〜3未満) / high(3〜5未満) / very-high(5以上)。`gct-literature-data/programs/literature_pipeline/pipeline.py` の `jif_tier()` と同じ定義。

## GCT関連性レビュー(掲載文献の採否を後から修正する)

文献は今後も継続的に追加していく方針のため、掲載後に「実はGCTとあまり関連が無い」と分かった文献を
後から除外(またはいったん除外したものを復活)できるよう、`scripts/review_relevance.py` に二段階の
AIレビューフローを用意しています(詳細な使い方はスクリプト冒頭のdocstring参照):

1. `propose --claude` — `relevance_status` 未設定(＝未レビュー)の文献をClaude Code CLIでバッチ判定し、
   非公開リポジトリ側に一覧レビューHTMLと `decisions_<run_id>.tsv` を出力する(AIは提案のみ)
2. 人間が `decisions_<run_id>.tsv` の `decision` 列(`keep`/`exclude`/`needs_review`)を確認・修正する
3. `apply` — 承認済みdecisionsを `papers.json` の `relevance_status`/`relevance_note` に反映する

`relevance_status` が `excluded` の文献だけがサイトの一覧から除外されます。それ以外(未設定/`kept`/
`needs_review`)はすべて表示されるため、レビューが済むまで文献が勝手に消えることはありません。採否は
`decision` 列を書き換えて `apply` を再実行すればいつでも修正できます。新規追加分だけを対象にしたい
場合は `propose` をそのまま実行すれば(`--all` を付けない限り)未レビューの文献だけが対象になります。

## サイト情報を変える

`site.json` でサイトタイトル・説明文・お知らせ文言を変更できます。`title`/`description`/`notice` が英語版(`/en/`)、`title_ja`/`description_ja`/`notice_ja` が日本語版(`/`)です。片方しか埋まっていない場合はもう片方の言語のページでも代わりに表示されます(フォールバック)。

## 注意

- JSON の文法エラー(カンマ忘れ等)があるとサイトにデータが表示されなくなります。push 前にローカルで確認するか、`python3 -m json.tool data/papers.json` でチェックしてください(CI でも自動チェックされます)。
