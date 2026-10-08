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

## 未確認の範囲と、今後の判定のしかた(2026-10-08 追記)

### 1. 過去に not_relevant で除外した 2,734 件は、CNS-GCT かどうか**未確認**
- 今回の 684 件は、関連性の判定を通過した論文(kept / needs_review)から選んだもの。
  過去のバッチで AI が `not_relevant` とした論文(`ai_relevance='not_relevant'` かつ `excluded`、2,734 件)は調べていない。
  この中に CNS-GCT が含まれている可能性があるが、含まれる件数は不明。
- 判定できるようにしてある: `screen_cns_gct.py screen --scope not_relevant --out <別ファイル> --claude`
  (候補は同じキーワードで絞る)。`apply --scope not_relevant` は、除外のまま `relevance_note` に CNS の文言を付けるだけ
  (元の AI 判定や和訳は変えない)。実行は必要になったとき(専用サイトを作る段階など)でよい。
- 判定済みの印は `relevance_note`。印が付いた論文は、次回の候補から外れる。

### 2. これから判定する約 25,779 件: 判定プロンプトに別ラベル `cns_gct` を追加した
- 判定の選択肢は relevant / uncertain / not_relevant / **cns_gct**。脳・脊髄原発の胚細胞腫瘍が主題なら `cns_gct`。
- `cns_gct` の扱い: `relevance_status='excluded'`、`relevance_note='対象外: 脳・脊髄原発の胚細胞腫瘍(編集方針 2026-10)'`
  (684 件と同じ印)、`ai_relevance='cns_gct'`。題名の和訳と英語の要約は付く。日本語の要約と抄録の全文訳は付けない(出力を減らして費用を抑えるため。
  専用サイトを作る段階で `--refill-missing-translations` を拡張して補う)。
- これにより、CNS-GCT の集合は常に `relevance_note` が上の文言の行(または `ai_relevance='cns_gct'`)で取り出せる。
- 既存の 684 件の `ai_relevance` は変えていない(AI が relevant と判定した履歴を残すため)。集合の取り出しは `relevance_note` を使う。

## 注意点・限界
- 判定はAI(haiku)で、抜き取り確認のみ。専用サイトにする場合は、`uncertain` 82件を中心に人が確認する。
- キーワードで候補を絞っているため、語に当たらない CNS-GCT 論文は漏れている可能性がある。
- 公開済みだった12件は、サイト側では非表示にしただけで、`data/papers.json` のエントリは残している(`relevance_status: excluded`)。
