
# PubMed 文献JSONフォーマット（簡易マニュアル）

本ドキュメントは、PubMed文献情報を構造化JSON形式で整理・出力する際のテンプレート仕様です。

---

## 🔧 出力構造

各文献情報は以下のようなJSON形式で表現されます。

```json
{
  "pmid": 40347127,
  "title": "Suprasellar Ectopic Pituitary Neuroendocrine Tumor Misdiagnosed as Pineal Parenchymal Tumor: A Case Report.",
  "first_author": "Woo SB",
  "journal": "Brain Tumor Res Treat",
  "if": 1.9,
  "pubdate": "2025-04-01",
  "type": "Clinical",
  "subtype": "Case Report",
  "summary": "A 39-year-old male presented with dizziness and headaches..."
}
```

---

## 🧩 各フィールドの説明

| フィールド名     | 型     | 説明                                                                 |
|------------------|--------|----------------------------------------------------------------------|
| `pmid`           | 整数   | PubMed ID（一意の識別子）                                            |
| `title`          | 文字列 | 論文タイトル                                                        |
| `first_author`   | 文字列 | 第一著者の姓とイニシャル                                            |
| `journal`        | 文字列 | 掲載雑誌名                                                          |
| `if`             | 数値   | インパクトファクター（事前定義または手動設定）                     |
| `pubdate`        | 日付文字列 | 出版日（形式: `YYYY-MM-DD`、印刷日優先、なければEpub日）         |
| `type`           | 文字列 | 文献種別（例：Clinical, Review, Basic）                            |
| `subtype`        | 文字列 | 文献サブタイプ（例：Case Report, Retrospective Study）            |
| `summary`        | 文字列 | AbstractをもとにGPTが自動生成した要約文                             |

---

## 📏 運用ルール

- 1回の出力につき **最大5件**（推奨）
- 長文データや多数件は分割処理
- `pubdate` は印刷日が優先、なければ Epub 日を使用（`YYYY-MM-DD`形式）
- `summary` は与えられたAbstractから自動で作成
- `if` 値は事前定義表または手動入力（自動取得は将来的に対応可）

---

## 🔁 再利用方法（ChatGPT新チャット時）

> 「以下の文献を、Canvas `Pubmed Json Format` に従って出力してください」  
または  
> 「pmid, title, first_author, journal, if, pubdate, type, subtype, summary を含む形式で出力してください」

---

## 📦 このテンプレートのバージョン
- 最終更新: 2025年5月
- 管理: ChatGPT + ユーザー定義Canvas `Pubmed Json Format`
