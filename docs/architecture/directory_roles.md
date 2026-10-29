# ディレクトリの役割(2026-10)

2つのリポジトリのフォルダごとの役割です。全体の構成とデータの流れは `current_architecture.md`。
「編集」の欄: **手** = 人が編集してよい、**生成** = スクリプトが書く(手で直さない)、**原本** = 上書き・削除しない。

## `gct-literature-website`(Public)

| パス | 内容 | 編集 |
|---|---|---|
| `index.html`, `en/index.html` | 日本語ページ・英語ページ | 手 |
| `assets/` | `app.js`(一覧・検索・絞り込み)、`attr-labels.js`(属性の項目と表示名)、`search-lib.js`(検索式)、`style.css` | 手 |
| `data/papers/` | 公開する文献データ(年代別 `papers_<年代>.json` と `index.json`)。**公開データの正本** | 生成(`publish_to_site.py` など。直す手順は `docs/operations/attributes_and_screening.md`) |
| `data/site.json` | サイトのタイトル・説明・お知らせ(日英) | 手 |
| `data/raw/` | PubMed のエクスポート(`import_medline.py` の入力) | 原本 |
| `scripts/` | データ処理・検証のスクリプト(Python と Node) | 手 |
| `programs/` | スクリプトが使う共有モジュール(MEDLINE のパーサー、JIF の変換・照合、用語集のパーサー)と、回帰テスト | 手 |
| `tests/search/` | 検索式の単体テスト(Node) | 手 |
| `docs/` | `architecture/`(構成)、`data_dictionary/`(データの定義)、`decisions/`(設計判断と理由)、`operations/`(手順) | 手 |
| `.github/workflows/` | `validate.yml`(PR の検証)、`deploy.yml`(main へのマージで公開) | 手 |
| `package.json`, `package-lock.json` | 検索データの生成と検証(Pagefind・Playwright) | 手 |
| `search/`, `pagefind/` | 検索データ。デプロイ時とローカルのビルドで作る。**コミットしない**(`.gitignore`) | 生成 |
| `gh-pages`(ブランチ) | デプロイ用の自動生成。直接編集しない | 生成 |

## `gct-literature-data`(Private)

公開できないもの(JCR のJIF実数値、抄録の全文、作業用DB)と、AIの出力・レビューの記録を置きます。**Private のまま維持します。**

### `data/`

| パス | 内容 | 編集 |
|---|---|---|
| `data/master/gct_literature_<年代>.db` | 作業用SQLite(全文献・AIの出力・判定・レビューの記録)。年代ごとに6ファイル。列は `docs/data_dictionary/sqlite_papers_db.md` | 生成(直接の修正は `sqlite3` で行い、変更前の値をバックアップに残す。データは削除しない) |
| `data/master/*_cost_log.jsonl` | AI処理ごとの費用・モデル・用語集の版の記録 | 生成(追記のみ) |
| `data/raw/historical_bulk/` | PubMed の年別 MEDLINE テキスト(1929〜2026)。`ingest_historical.py` の入力 | 原本 |
| `data/raw/pubmed_alerts/` | 定期アラートの取得分(現在は空) | 原本 |
| `data/reference/jif/` | JCR 由来の年別JIF参照データ(`jcr_jif_reference_<年>_vmerged.tsv`)。`raw/` に未改変の CSV、`processed_raw.tsv` に変換の台帳。**ライセンス上、公開しない** | `raw/` は原本、他は生成(`jif_reference_add.py`) |
| `data/reference/terminology/` | `terminology_ja.md`(英和用語集。標準の訳と「避ける訳」)。**唯一の正本** | 手 |
| `data/reference/classification/` | `tag_overrides.tsv`(研究デザインのタグを個別に直す上書き表) | 手(誤りに気づいたら1行足す) |
| `data/processed/classification/` | 研究デザインのAI判定(`design_ai_*.jsonl`)とタグ修正のバックアップ | 生成 |
| `data/processed/attributes/`, `attributes_v2/` | RCT・観察研究などの属性と臨床テーマのAI抽出結果(`attributes/` は初回パイロット) | 生成 |
| `data/processed/case_attributes/` | 症例報告の属性のAI抽出結果(全件・やり直し・反映用) | 生成 |
| `data/processed/scope_screen/` | 脳・脊髄原発の胚細胞腫瘍(CNS-GCT)のAI判定と除外のバックアップ。**消さない**(README あり) | 生成 |
| `data/processed/terminology/` | 用語の点検結果と、置換・再和訳のバックアップ | 生成 |
| `data/processed/publish_review/` | 公開前レビューの確認用ファイルと decisions TSV(run ごと) | 生成(decisions は人が確認・修正) |
| `data/processed/relevance_review/` | 関連性レビューの記録(最初の65件の時代のもの) | 生成 |
| `data/processed/jif_backfill/`, `jif_match_audit/` | JIF の遡及・照合の監査 CSV(**実測のJIFを含む。外に出さない**) | 生成 |
| `data/processed/literature_json/` | 2025年の週次AI出力(過去の作業環境からの移行分) | 原本に準じる |
| `data/processed/cleaned_pubmed/`, `literature_candidates/`, `review_reports/`, `private_jif_export/`, `data/intermediate/`, `data/manifests/` | 旧世代の TSV 経路の名残。**いずれも空で、使っていない**(削除は別途確認) | - |

### その他

| パス | 内容 | 編集 |
|---|---|---|
| `.github/workflows/portal-*.yml` | データ作業ポータル(状況レポート、JIFの参照データ追加・遡及、公開前レビュー作成、公開反映) | 手 |
| `portal/` | ポータルの説明(`README.md`)、状況レポート(`STATUS.md`。生成)、トークン確認・コミット・PR 作成の補助スクリプト | 手 / 生成 |
| `logs/` | 実行ログ・更新履歴の置き場(現在は空) | 生成 |
| `programs/archive/` | 旧版コードの保管(参照専用。実行しない・変更しない) | 原本 |

## 守るルール(両方のリポジトリ共通)
1. `data/raw/`、`data/reference/jif/raw/` は**上書き禁止**。再取得は新しいファイルとして追加する。
2. 作業用DBは、データを**削除しない**。除外は `relevance_status='excluded'` で表し、元の値はバックアップに残す。
3. AIの実行結果は、まず別ファイルに出し、目視確認の後に DB・サイトへ反映する。
4. APIキー・認証情報は、どのファイルにも書かない。
5. 非公開リポジトリの内容を公開側へコピーするときは、JIFの実数値・抄録の全文・個人情報を含まないことを確認する。
