# データ辞書

| 文書 | 対象 | 状態 |
|---|---|---|
| `site_papers_v1.md` | 公開データ `data/papers/` のエントリ(`tags`、`attrs` を含む) | 現行 |
| `sqlite_papers_db.md` | 非公開の作業用SQLite(`papers` テーブル) | 現行 |
| `jif_reference_v1.md` | JIF参照データ(年別のTSV。JCR の CSV から変換) | 現行(非公開リポジトリのポータルが使用) |
| `terminology_ja.md` | 英和用語集の場所(非公開リポジトリへ移動済み) | 現行(案内のみ) |
| `literature_tsv_v1.md` | 旧世代のTSVパイプライン(`programs/`)の候補・マスターTSV | 旧世代(本番では未使用) |
| `pubmed_json_format_guide.md` | 旧世代の週次JSON出力の形式(2025年の文献JSON) | 旧世代(本番では未使用) |

フィールドの値の定義の正本は、現行のものはコード(`scripts/study_design.py`、`scripts/extract_attributes.py`、`scripts/extract_case_attributes.py`、`scripts/gct_db.py`)とそれぞれの設計判断(`docs/decisions/`)です。
