"""英和対訳用語集(Markdownの表)の解析と、プロンプト用の絞り込み。

用語集 `terminology_ja.md`(データリポジトリ)は人が表を編集する。この模塊は次の3つを提供する。

  parse(text)               表を読み、用語の一覧にする
  select(entries, texts)    指定した原文(タイトル・抄録など)に出てくる用語だけを返す
  render_note(entries)      AIへの指示文に入れる、その回の用語(英語 => 日本語)

表の書き方(英語 | 日本語):
  - 英語の欄: ` / ` で別表記を並べる。括弧内の大文字は略語(例: `Germ cell tumor (GCT)`)。
  - 日本語の欄: 括弧内は、許容する別の訳(例: `ディスジャーミノーマ(未分化胚細胞腫)`)。
    `(原語のまま)` と書いた語は、訳さず英語のまま残す。
  - 見出し行が `| 英語 | 避ける訳 |` の表は、使ってはいけない訳(誤字・不統一)の一覧。`、` で区切る。
"""
import re

AVOID_HEADER = "避ける"
KEEP_ENGLISH_MARK = "原語のまま"


def _norm(text):
    """Lowercase, hyphens as spaces, British 'tumour' as 'tumor': the form terms are matched in."""
    text = (text or "").lower().replace("-", " ").replace("‐", " ")
    return re.sub(r"\s+", " ", text.replace("tumour", "tumor"))


def _acronyms(english):
    return [m for m in re.findall(r"\(([^)]*)\)", english)
            if re.fullmatch(r"[A-Za-z0-9/\-]{2,10}", m) and re.search(r"[A-Z]", m)]


def _names(english):
    names = []
    for part in re.split(r"\s+/\s+", english):
        name = _norm(re.sub(r"\([^)]*\)", "", part)).strip()
        if name:
            names.append(name)
    return names


def _entry(english, japanese):
    keep = KEEP_ENGLISH_MARK in japanese
    main = re.split(r"[（(]", japanese)[0].strip()
    alts = [a.strip() for a in re.findall(r"[（(]([^）)]*)[）)]", japanese) if len(a.strip()) >= 2]
    return {"english": english, "names": _names(english), "acronyms": _acronyms(english), "japanese": japanese,
            "main": "" if keep else main, "alts": [] if keep else alts, "keep_english": keep, "avoid": []}


def parse(text):
    """The entries of every terms table, with the avoid-lists attached."""
    entries, avoids, mode = [], [], None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("-: "):
            continue
        if cells[0] == "英語":
            mode = "avoid" if cells[1].startswith(AVOID_HEADER) else "terms"
            continue
        if mode == "terms":
            entries.append(_entry(cells[0], cells[1]))
        elif mode == "avoid":
            avoids.append((_names(cells[0]), [a.strip() for a in re.split(r"[、,]", cells[1]) if a.strip()]))
    for names, bad in avoids:
        for entry in entries:
            if set(names) & set(entry["names"]):
                entry["avoid"].extend(a for a in bad if a not in entry["avoid"])
    return entries


def _end(name):
    """Word-start matching lets plurals match ('teratoma' in 'teratomas'); a name ending in a numeral
    ('stage i') must end on a word boundary, or it would also match 'stage ii' and 'stage iii'."""
    return r"(?![a-z0-9])" if re.search(r"(?:^|\s)(?:[ivx]+|\d+)$", name) else ""


def terms_in(entries, texts):
    """The entries whose English term appears in any of the texts (word-start match, so plurals match)."""
    joined = " ".join(t for t in texts if t)
    normalised = _norm(joined)
    found = []
    for entry in entries:
        if any(re.search(r"(?<![a-z0-9])" + re.escape(name) + _end(name), normalised) for name in entry["names"]) or \
                any(re.search(r"(?<![A-Za-z0-9])" + re.escape(acr) + r"(?![A-Za-z0-9])", joined) for acr in entry["acronyms"]):
            found.append(entry)
    return found


def render_note(entries):
    """Prompt text for the entries found in this batch ('' when there are none)."""
    if not entries:
        return ""
    lines = []
    for entry in entries:
        english = re.sub(r"\s+", " ", entry["english"])
        target = "(keep in English, as written)" if entry["keep_english"] else entry["japanese"]
        avoid = f"   [do not use: {', '.join(entry['avoid'])}]" if entry["avoid"] else ""
        lines.append(f"- {english} => {target}{avoid}")
    return (
        "\n\nControlled Japanese terminology for terms found in these papers: whenever one of these English terms "
        "appears, use exactly the Japanese rendering given here -- the same English term must always get the same "
        "wording across every paper (an entry marked 'keep in English' stays untranslated; never use a rendering "
        "listed after 'do not use'). Terms not listed here: translate naturally.\n" + "\n".join(lines)
    )


def check_pair(entries, english, japanese):
    """Compare one English text with its Japanese translation.

    Returns [(entry, status, avoided)] for every glossary term in the English text that the Japanese gets wrong:
    status 'avoid' if a rendering the glossary says not to use is in the Japanese (even next to the standard one:
    that is the inconsistency), otherwise 'check' when the standard rendering is missing altogether
    (paraphrase, abbreviation, or a rendering the glossary does not know).
    """
    problems = []
    ja = japanese or ""
    ja_norm = _norm(ja)
    for entry in terms_in(entries, [english]):
        if entry["keep_english"]:
            ok = any(name in ja_norm for name in entry["names"]) or any(acr in ja for acr in entry["acronyms"])
        else:
            ok = any(form and form in ja for form in [entry["main"], *entry["alts"], *entry["acronyms"]])
        avoided = [a for a in entry["avoid"] if a in ja]
        if avoided:
            problems.append((entry, "avoid", avoided))
        elif not ok:
            problems.append((entry, "check", []))
    return problems
