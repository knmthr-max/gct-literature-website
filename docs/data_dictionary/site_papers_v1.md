# 公開データ(data/papers/)のエントリ v1

公開サイトの文献データです。場所は `data/papers/`(年代別の `papers_<年代>.json`)で、読み書きは `scripts/papers_store.py` を使います。
フィールドの完全な表(必須・任意・値の意味)は `data/README.md` の「エントリのフィールド仕様」が正本です。ここでは、構造と、作る側・使う側の対応を示します。

## 年代別ファイル
- `index.json` が、年代別ファイルの名前を順に並べます(`{"shards": [...]}`)。
- 各 `papers_<年代>.json` は、エントリの配列です。1つのPMIDは、1つのファイルにだけ入ります。
- ブラウザは `data/papers/` を直接読みません。デプロイ時に `scripts/build_site_search.mjs` が、`search/list.json`(軽い一覧)と `search/abstract/<id>.json` を作ります。`relevance_status` が `excluded` の論文は、これらに含まれません。

## 主なフィールドと作る側

| フィールド | 作る側 |
|---|---|
| `id`, `title`, `authors`, `journal`, `year`, `pmid`, `doi`, `url`, `abstract` | `publish_to_site.py`(DBの行から) |
| `title_ja`, `summary_ja`, `summary_en`, `abstract_ja` | `process_batch.py` が作り、`publish_to_site.py` が写す。再和訳・用語置換は `sync_site_translations.py`、`replace_terms.py` |
| `tags`(研究デザイン、9分類のうち1つ) | `study_design.py` の規則と `classify_design.py`(AI)、直し方は `retag_categories.py`・`sync_site_tags.py` |
| `attrs`(属性) | `sync_site_attributes.py`(`extract_attributes.py`・`extract_case_attributes.py` の結果から) |
| `jif_tier` | `backfill_jif.py`(DBの照合から)、簡易版は `match_jif.py` |
| `relevance_status`, `relevance_note`, `relevance_reviewed_at` | `process_batch.py`、`screen_cns_gct.py`(CNS-GCT の除外)。`excluded` だけが一覧から外れる |
| `added_at` | `publish_to_site.py`(掲載日。新着の並び順に使う) |

## `attrs`
臨床論文の属性。短い名前で、値は英語の選択肢です(表示名は `assets/attr-labels.js`)。値が分からない項目は入れません。

| キー | 意味 | 値 |
|---|---|---|
| `th` | 臨床テーマ(複数) | surgery / chemotherapy / radiotherapy / surveillance / late_effects / fertility / diagnosis_imaging / epidemiology / pathology_molecular / prognosis / qol |
| `si` | 原発部位 | testis / ovary / mediastinum / retroperitoneum / sacrococcygeal / other_extragonadal / cns / multiple |
| `hi` | 組織型(複数) | seminoma_germinoma / nonseminomatous_gct / mature_teratoma / immature_teratoma / teratoma_with_malignant_transformation / yolk_sac_tumor / embryonal_carcinoma / choriocarcinoma / gestational_choriocarcinoma / mixed_gct / spermatocytic_tumor / gonadoblastoma / gct_nos |
| `sx` | 性別 | male / female / mixed |
| `ag` | 年齢区分 | infant(<2歳) / child(2〜12) / adolescent(13〜17) / adult(18〜64) / elderly(65〜) / mixed |
| `tr` | 治療(複数) | surgery / chemotherapy / radiotherapy / observation / high_dose_chemo_transplant |
| `sg`, `ig`, `n` | 病期(I〜IV)、IGCCCG(good / intermediate / poor)、例数。絞り込みには使わず、カードに表示する | |
| `ln`, `ep`, `ph` | RCT・非ランダム化試験: 治療ライン、主要評価項目の種類、相 | |
| `sc`, `mt` | SR・MA: 統合の対象、メタ解析の有無(yes / no) | |
| `st` | 観察研究: 研究の型 | |

抽出しないもの: 結果の数値(生存率・ハザード比・p値など)。「不明」「記載なし」「その他」は入れません。仕様と判断の経緯: `docs/decisions/2026-10-26_attribute_filters.md`。
