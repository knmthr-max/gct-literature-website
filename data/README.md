# データの追加・更新方法

このディレクトリがサイトの**唯一のデータソース**です。文献データは `data/papers/`(年代別の `papers_<年代>.json` と、その一覧 `index.json`)にあり、スクリプトは `scripts/papers_store.py` で読み書きします。サイト情報は `site.json`。検索データ(`search/`・`pagefind/`)は、デプロイ時に自動で生成され、リポジトリには含まれません。

全体の構成は `docs/architecture/current_architecture.md`、スクリプトの使い方は `docs/operations/attributes_and_screening.md` を参照してください。

## 論文が公開されるまでの流れ(現行)

大量の文献は、非公開リポジトリ `gct-literature-data` のSQLite(年代ごとに分割した `data/master/gct_literature_<年代>.db`)で処理し、公開してよいものだけをこのディレクトリに反映します。`data/papers/` を直接編集する必要はありません。

1. **取り込み**(AIなし): `scripts/ingest_historical.py` が、MEDLINE形式のテキスト(`gct-literature-data/data/raw/historical_bulk/`)を読み、PMIDで重複を除いてDBに登録します(`relevance_status` 未設定=未判定)。何度実行しても安全です。
2. **判定・和訳**(AI): `scripts/process_batch.py --claude` が、未判定の論文を発行年の新しい順に `--batch-size` 件だけ取り出し、GCTとの関連性の判定、日英の要約、題名と抄録の和訳を1回の呼び出しで作ります。実行のたびに次のバッチへ進むだけです。既定のモデルは Haiku 5.5、effort は low。和訳は用語集(`gct-literature-data/data/reference/terminology/terminology_ja.md`)に従います。
   - 判定は `relevance_status` に反映されます: relevant → `kept`、uncertain → `needs_review`、not_relevant と、脳・脊髄原発の胚細胞腫瘍(`cns_gct`)→ `excluded`。誤りは、DBの `relevance_status`/`relevance_note` を直接書き換えれば、いつでも直せます(除外も復元できます)。
   - タグ(研究デザイン)は、PubMed の文献種別から決定的に付けます。決まらないものは `scripts/classify_design.py`(AI)で判定します。
   - `--refill-missing-translations`(抜けた和訳の補完)、`--retranslate`(再和訳。`sync_site_translations.py` でサイトへ反映)、`--pmids`(指定した論文だけ)も使えます。
3. **公開前レビュー**: `kept` は「GCTに関連する」という意味にすぎず、AIが書いた和訳・要約をそのまま公開してよいかは別の判断です。次のいずれかで確認し、承認した分だけを公開します。
   - 少数ずつ確認する: `scripts/export_publish_review.py` が確認用のHTMLと `decisions_<run_id>.tsv`(`decision` 列は `approve` で初期化)を作ります。直したい行は `reject` か `needs_edit` にします。空欄とそれ以外の値は公開されません(fail-closed)。
   - 年の範囲ごとに一括で公開する: `scripts/bulk_publish_decisions.py` が、候補(`kept`・未公開・和訳が揃ったもの)を全件 `approve` にした decisions を作ります(方針: `needs_review` だけ人が確認する)。
4. **公開反映**: `scripts/publish_to_site.py --decisions <decisions.tsv> --db-dir ...` が、`approve` の行だけを `data/papers/` にエントリとして追加し(既存のPMIDは重複追加しない)、DB側に `published_to_site` などを記録します。実際の運用では、非公開リポジトリの GitHub Actions「3 公開前レビュー作成」「4 公開反映」(`gct-literature-data/portal/README.md`)が、この2つを実行し、このリポジトリへの **PR を作ります**。
5. **PR をマージ**すると、`deploy.yml` が検索データを生成して GitHub Pages に公開します。**本番に反映されるのは、PR をマージしたときだけ**です。マージ前に `validate.yml` が緑であることを確認してください。

公開後に直すもの(研究デザインのタグ、和訳の表記、属性、CNS 除外)は、`docs/operations/attributes_and_screening.md` の手順で、DBとこのディレクトリの両方を直します。

## 文献を追加するその他の方法

小規模・手動の用途で、上の流れを通さずに追加する方法もあります。この場合、AIの判定・和訳・公開前レビューを通らないため、`relevance_status`・和訳・属性は自分で用意してください。

### PubMed のファイルから直接取り込む
PubMed で **Save → Format: PubMed**(MEDLINE形式。拡張子は `.nbib` でも `.txt` でも可)でエクスポートし、`data/raw/` に置いて実行します。

```sh
python3 scripts/import_medline.py data/raw/2026-09-07-import.nbib
```

題名・著者・掲載誌・年・PMID・DOI・抄録・タグ(研究デザイン)が自動で追記されます。PMIDで重複を判定するので、同じファイルを二度実行しても二重登録になりません。手で書いた `title_ja` などは上書きされません。

### 手動で1件追加する
`data/papers/` の該当する年代のファイルの配列に、エントリを1件追記します(`papers_store.py` で読み書きすると、年代の振り分けが正しくなります)。

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

## エントリのフィールド仕様

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
| `tags` | – | 研究デザイン。**必ず次の9分類のうち1つのみ**を入れる: `SR・MA` / `RCT` / `非ランダム化試験` / `観察研究` / `症例報告・集積` / `総説` / `ガイドライン・コンセンサス` / `基礎・トランスレーショナル` / `その他`(`基礎・トランスレーショナル` 以外は「臨床」)。PubMedの著者キーワードや細かい文献種別はここに入れない。分類の決め方は `docs/decisions/2026-10-12_study_design_taxonomy.md`。該当なしなら空配列 `[]` |
| `attrs` | – | AIが抄録から抽出した属性(臨床論文のみ)。`th` 臨床テーマ[]、`si` 原発部位、`hi` 組織型[]、`sx` 性別、`ag` 年齢区分、`tr` 治療[]、`sg` 病期、`ig` IGCCCG、`n` 例数。デザイン別に `ln` 治療ライン・`ep` 主要評価項目の種類・`ph` 相(RCT・非ランダム化試験)、`sc` 統合の対象・`mt` メタ解析の有無(SR・MA)、`st` 研究の型(観察研究)。値が分からない項目は入れない。結果の数値は持たない。`scripts/sync_site_attributes.py` が書く。仕様: `docs/decisions/2026-10-26_attribute_filters.md` |
| `summary_en` | – | 英語の短い要約・コメント |
| `summary_ja` | – | 日本語の短い要約・コメント |
| `abstract` | – | 英語の全文抄録。サイトでは折りたたみ表示される |
| `abstract_ja` | – | 日本語訳の全文抄録。収載文献は基本的に英語が原文であるため、日本語ページでは訳文(「抄録」)と英語原文(「抄録原文(英語)」)を**両方**、別々の折りたたみで常に参照できる。訳が無い場合は「抄録(英語)」に原文のみ表示する |
| `jif_tier` | – | Journal Impact Factorの階層(`low`/`moderate`/`high`/`very-high`/`unknown`)。実数値は非公開リポジトリ(`gct-literature-data`)にのみ保持し、ここには入れない。`unknown` は「JCR参照データに該当誌・該当年のデータが無く判定できない」ことを明示する値で、フィールド自体を省略する(未整備で表示されないのか、判定不能なのか区別できない)よりも意図的にこちらを使う。`programs/literature_pipeline/README.md` の `scripts/match_jif.py` で自動生成する |
| `relevance_status` | – | GCT(胚細胞腫瘍)関連性レビューの結果。`kept`(掲載継続)/`excluded`(除外。脳・脊髄原発のGCTを含む)/`needs_review`(要確認)のいずれか。**フィールド未設定は`kept`と同じ扱い**(サイトは`excluded`のときだけ非表示にする)。`scripts/process_batch.py` の判定が反映される(直接の書き換えもできる)。採否は後からいつでも修正できる |
| `relevance_note` | – | `relevance_status` の判断理由(AIの判定理由、または人間が上書きした場合はそのメモ) |
| `relevance_reviewed_at` | – | 関連性レビューを反映した日時(ISO 8601) |
| `added_at` | – | 掲載日 (`YYYY-MM-DD`)。新着表示に使用 |

`summary_en`/`summary_ja` がどちらも空の場合、サイトには「要約: 準備中」(英語ページでは "Summary: not yet available")と表示され、要約が存在しないのではなく未整備であることが分かるようになっています。

`jif_tier` の境界値: low(<1) / moderate(1〜3未満) / high(3〜5未満) / very-high(5以上)。`programs/literature_pipeline/jif_matcher.py` の `jif_tier()` と同じ定義。

## JIF(インパクトファクター)の tier

公開データには、実数値ではなく tier(`low`/`moderate`/`high`/`very-high`/`unknown`)だけを持たせます。実数値とJCRの参照データは、非公開リポジトリにだけ置きます。参照データの追加と、過去の論文への遡及は、非公開リポジトリの GitHub Actions「5 JIF参照データ追加」「2 JIF遡及」で行います(`scripts/jif_reference_add.py`、`scripts/backfill_jif.py`)。`scripts/match_jif.py` は、`data/papers/` だけを対象にした簡易版です。1996年以前の論文は、JIFのデータが存在しないため、保留(pending)として扱います。

## 以前の関連性レビュー(`review_relevance.py`)

最初に公開した65件のために作った、`data/papers/` の `relevance_status` を後から直す二段階の流れ(`propose --claude` → 人が decisions TSV を確認 → `apply`)です。現在の大量処理では使いません(関連性の判定は `process_batch.py` が行い、`needs_review` だけを人が確認します)。`relevance_status` が `excluded` の論文だけが一覧から除外され、それ以外(未設定・`kept`・`needs_review`)はすべて表示される、という表示のルールは、現在も同じです。

## サイト情報を変える

`site.json` でサイトタイトル・説明文・お知らせ文言を変更できます。`title`/`description`/`notice` が英語版(`/en/`)、`title_ja`/`description_ja`/`notice_ja` が日本語版(`/`)です。片方しか埋まっていない場合はもう片方の言語のページでも代わりに表示されます(フォールバック)。

## 注意

- JSON の文法エラー(カンマ忘れ等)があるとサイトにデータが表示されなくなります。PR を出す前に、`python3 -m unittest discover -s programs/tests` を実行してください。CI(`validate.yml`)でも、JSON の文法・重複ID・必須項目・検索と絞り込みの動作が自動で検証されます。
