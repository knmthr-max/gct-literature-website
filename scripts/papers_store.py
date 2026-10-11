"""公開サイトの文献データ(papers)の読み書き。年代別に分割したファイル群と、従来の単一ファイルの両方を扱う。

公開データは `data/papers/` に年代ごとのファイル(papers_pre1980.json, papers_1980s.json, ...)と、
その一覧 `index.json` で持つ。単一ファイルは約2万件で約80MBになり、GitHub の1ファイル上限(100MB)に
近づくため分割した(docs/decisions/2026-10-11_split_papers_json.md)。

    load(path)         path がディレクトリなら index.json の順に全シャードを連結して返す。ファイルなら従来どおり1つのJSON。
                       `data/papers.json` が無く `data/papers/` があれば、後者を読む(古い呼び出しの互換)
    save(path, papers) ディレクトリなら発行年でシャードに振り分けて書く(中身が変わったシャードだけ書き換える)。
                       ファイルなら1つのJSONとして書く
    resolve(path)      実際に読み書きする場所(ディレクトリかファイル)を返す
"""
import json
import pathlib

INDEX_NAME = "index.json"
# 並び順(古い順)。発行年が1979以前は pre1980、以降は10年ごと
SHARD_ORDER = ["pre1980", "1980s", "1990s", "2000s", "2010s", "2020s"]


def shard_name(year):
    try:
        year = int(year)
    except (TypeError, ValueError):
        return "pre1980"
    if year < 1980:
        return "pre1980"
    return f"{year // 10 * 10}s"


def shard_file(name):
    return f"papers_{name}.json"


def _order(name):
    return (SHARD_ORDER.index(name), name) if name in SHARD_ORDER else (len(SHARD_ORDER), name)


def resolve(path):
    path = pathlib.Path(path)
    if path.is_dir():
        return path
    if not path.exists() and path.suffix == ".json" and path.with_suffix("").is_dir():
        return path.with_suffix("")
    return path


def exists(path):
    path = resolve(path)
    return path.is_dir() or path.is_file()


def load(path):
    path = resolve(path)
    if path.is_dir():
        index = json.loads((path / INDEX_NAME).read_text(encoding="utf-8"))
        papers = []
        for name in index["shards"]:
            papers += json.loads((path / name).read_text(encoding="utf-8"))
        return papers
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(papers):
    return json.dumps(papers, ensure_ascii=False, indent=2) + "\n"


def save(path, papers):
    path = resolve(path)
    if not path.is_dir():
        path.write_text(_dump(papers), encoding="utf-8")
        return
    groups = {}
    for paper in papers:
        groups.setdefault(shard_name(paper.get("year")), []).append(paper)
    names = sorted(groups, key=_order)
    for name in names:
        target = path / shard_file(name)
        text = _dump(groups[name])
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8")
    for old in path.glob("papers_*.json"):  # 空になったシャードは消す
        if old.name not in {shard_file(n) for n in names}:
            old.unlink()
    index_text = json.dumps({"shards": [shard_file(n) for n in names]}, indent=2) + "\n"
    index = path / INDEX_NAME
    if not index.is_file() or index.read_text(encoding="utf-8") != index_text:
        index.write_text(index_text, encoding="utf-8")
