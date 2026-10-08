# Decision: 脳・脊髄原発の胚細胞腫瘍(CNS-GCT)は公開対象外にするが、データは削除せず残す

- Date: 2026-10-08
- Status: adopted(データ保持)/ idea(CNS-GCT 専用サイト。未着手)

## 決めたこと

- 編集方針として、脳・脊髄に原発する胚細胞腫瘍は**このサイトの対象外**にする(2026-10)。
- ただし、判定済みのデータは**削除しない**。DBの行は `relevance_status = 'excluded'` で残し、
  除外した理由・判定結果・除外前の状態も残す。
- 反転させれば「CNS-GCT の文献データベース」としてそのまま使える。将来、専用サイトを作る価値がある。

## どこに何が残っているか(データリポジトリ `gct-literature-data`)

| 場所 | 内容 |
|---|---|
| `data/master/*.db` の `papers` | 684件が `relevance_status='excluded'`、`relevance_note='対象外: 脳・脊髄原発の胚細胞腫瘍(編集方針 2026-10)'`。題名・抄録・MeSH・和訳(題名・要約・抄録訳のうち既にあるもの)は消していない |
| `data/processed/scope_screen/cns_gct.jsonl` | AI判定の全結果(pmid / verdict / 英語1文の理由)。1,330件。`cns_primary` 684、`not_cns_primary` 535、`mixed` 29、`uncertain` 82 |
| `data/processed/scope_screen/cns_gct_backup_2026-10-06.jsonl` | 除外前の `relevance_status` / `relevance_note`(元に戻せる) |
| `data/processed/scope_screen/cns_gct_review_mixed_uncertain.tsv` | 人が確認する `mixed` / `uncertain` の一覧 |

CNS-GCT の集合を取り出すには、`relevance_note` が上の文言の行、または `cns_gct.jsonl` の `verdict = cns_primary`。

## 将来の利用価値(メモ)

1. **CNS-GCT 専用サイト**: 既存のサイトの仕組み(静的サイト、Pagefind検索、タグ、JIF評価、和訳)をそのまま流用できる。
   `relevance_status` の条件を反転して `data/papers.json` を作るだけで、別サイトの基になる。
   頭蓋内ジャーミノーマ(日本で頻度が高い)の治療・予後の文献は、需要があると考えられる。
2. **除外した論文の再評価**: 方針が変わった場合は、バックアップを使って元の状態(kept / needs_review)に戻せる。
3. **`mixed` 29件**(例: 頭蓋内と精巣に同時発生した胚細胞腫瘍): 両方のサイトの対象になりうる。
   現在は本サイト側に残している。専用サイトを作る場合は両方に載せる扱いを検討する。
4. **本サイトとの相互リンク**: 専用サイトを作る場合、本サイトからの案内リンク(「脳・脊髄原発は別サイトへ」)を置ける。
5. **症例報告の属性抽出**(`extract_case_attributes.py`)は、CNS-GCT の症例にも使える(部位の選択肢に「頭蓋内/脊髄内」などを足す)。

## 注意点・限界(専用サイトにするときの前提)

- 今ある684件は、**関連性の判定を通過した論文**(kept / needs_review)から選んだもの。
  過去に `not_relevant` で除外済みの論文(約2,700件)は、CNS-GCT かどうかを調べていないので、含まれていない。
- 今後判定する約25,779件のうち CNS-GCT は、新しい判定プロンプトにより `not_relevant` / `excluded` になる。
  この場合は**和訳・要約が付かない**(`not_relevant` は抄録訳を作らない方針)。
  また `relevance_note` に上の文言は入らず、`ai_relevance_reason` に理由が入るだけなので、
  後から CNS-GCT だけを集めにくい。専用サイトを作る段階で、
  (a) 判定プロンプトで CNS-GCT を別のラベルにして残す、または
  (b) その時点で `screen_cns_gct.py` を `not_relevant` にも広げて実行する、のどちらかが必要。
- 判定はAI(haiku)で、抜き取り確認のみ。専用サイトにする場合は、`uncertain` 82件を中心に人が確認する。
- キーワードで候補を絞っているため、語に当たらない CNS-GCT 論文は漏れている可能性がある。
- 公開済みだった12件は、サイト側では非表示にしただけで、`data/papers.json` のエントリは残している(`relevance_status: excluded`)。
