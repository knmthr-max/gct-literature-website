// 公開用の検索データを data/papers/(年代別の文献データ)から生成する(デプロイ時に実行。生成物はコミットしない)。
//
//   node scripts/build_site_search.mjs [papers(ディレクトリまたはJSON)] [出力ディレクトリ]   (既定: data/papers と、リポジトリ直下)
//
// 出力:
//   search/list.json          軽い一覧の「核」(題名・年・タグ・属性・雑誌など。要約・著者・DOI・抄録を除く)。発行年の新しい順
//   search/head.json          一覧の先頭(既定の並びの先頭 HEAD_SIZE 件)。要約・著者つきで、最初の表示に使う
//   search/details/<n>.json   要約・著者・DOI・URL(一覧と同じ順に DETAIL_CHUNK 件ずつ。画面が裏で読み込む)
//   search/abstract/<id>.json 抄録(英/日)。カードを開いたときだけ読む
//   search/idmap.json         Pagefind の結果ID → 論文ID
//   pagefind/                 検索索引(日本語は2文字ずつの語で索引する)
// 設計: docs/decisions/2026-09-30_pagefind_search.md
import * as pagefind from "pagefind";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { indexText } from "../assets/search-lib.js";

const papersPath = process.argv[2] || "data/papers";
const outDir = process.argv[3] || ".";

// 一覧の核(絞り込み・並び替え・カードの見出しに要る項目)。それ以外の表示項目は details に分ける(最初に読むデータを軽くするため)
const LIST_FIELDS = ["id", "pmid", "title", "title_ja", "journal", "year", "tags", "jif_tier", "added_at", "attrs"];
const DETAIL_FIELDS = ["authors", "doi", "url", "summary_ja", "summary_en"];
const HEAD_SIZE = 100;
const DETAIL_CHUNK = 2000;
const SAFE_ID = /^[A-Za-z0-9._-]+$/;
// 検索に使わない Pagefind の部品(UI・ハイライト)と、読まない結果詳細は公開しない
const UNUSED = [/^pagefind-.*ui\.(js|css)$/, /^pagefind-highlight\.js$/, /^fragment$/];

// 文献データは data/papers/ の年代別ファイル(index.json の順)。1つのJSONファイルを渡すこともできる
function readPapers(target) {
  if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
    const index = JSON.parse(fs.readFileSync(path.join(target, "index.json"), "utf8"));
    return index.shards.flatMap((name) => JSON.parse(fs.readFileSync(path.join(target, name), "utf8")));
  }
  return JSON.parse(fs.readFileSync(target, "utf8"));
}

const papers = readPapers(papersPath).filter((p) => p.relevance_status !== "excluded");

const seen = new Set();
for (const p of papers) {
  if (!SAFE_ID.test(String(p.id ?? ""))) throw new Error(`検索データに使えないid: ${JSON.stringify(p.id)}`);
  if (seen.has(p.id)) throw new Error(`idが重複しています: ${p.id}`);
  seen.add(p.id);
}

const searchDir = path.join(outDir, "search");
const pagefindDir = path.join(outDir, "pagefind");
fs.rmSync(searchDir, { recursive: true, force: true });
fs.rmSync(pagefindDir, { recursive: true, force: true });
fs.mkdirSync(path.join(searchDir, "abstract"), { recursive: true });

// 一覧(核)・先頭・詳細。並びは発行年の新しい順(画面の既定の並びと同じ。同じ年は元の順)
const pick = (p, keys) => Object.fromEntries(keys.filter((key) => p[key] !== undefined).map((key) => [key, p[key]]));
const ordered = [...papers].sort((a, b) => (b.year || 0) - (a.year || 0));
const withAbstractFlags = (p, base) => ({ ...base, has_abstract: Boolean(p.abstract), has_abstract_ja: Boolean(p.abstract_ja) });
const list = ordered.map((p) => withAbstractFlags(p, pick(p, LIST_FIELDS)));
fs.writeFileSync(path.join(searchDir, "list.json"), JSON.stringify(list));
fs.mkdirSync(path.join(searchDir, "details"), { recursive: true });
const chunkCount = Math.ceil(ordered.length / DETAIL_CHUNK);
for (let n = 0; n < chunkCount; n += 1) {
  const chunk = Object.fromEntries(ordered.slice(n * DETAIL_CHUNK, (n + 1) * DETAIL_CHUNK).map((p) => [p.id, pick(p, DETAIL_FIELDS)]));
  fs.writeFileSync(path.join(searchDir, "details", `${n}.json`), JSON.stringify(chunk));
}
fs.writeFileSync(path.join(searchDir, "head.json"), JSON.stringify({
  total: ordered.length, detail_chunks: chunkCount, chunk_size: DETAIL_CHUNK,
  papers: ordered.slice(0, HEAD_SIZE).map((p) => withAbstractFlags(p, pick(p, [...LIST_FIELDS, ...DETAIL_FIELDS]))),
}));
for (const p of papers) {
  if (!p.abstract && !p.abstract_ja) continue;
  fs.writeFileSync(path.join(searchDir, "abstract", `${p.id}.json`),
    JSON.stringify({ abstract: p.abstract || "", abstract_ja: p.abstract_ja || "" }));
}

// 検索索引
const { index } = await pagefind.createIndex({ forceLanguage: "en" }); // 日本語は indexText で分割済み。空白で区切るだけ
for (const p of papers) {
  const content = indexText([p.title_ja, p.title, p.summary_ja, p.summary_en, p.abstract_ja, p.abstract,
    (p.authors || []).join(", "), p.journal, ...(p.tags || [])].filter(Boolean).join("\n"));
  const result = await index.addCustomRecord({ url: `/#${p.id}`, content, language: "en" });
  if (result.errors?.length) throw new Error(`索引に追加できません(${p.id}): ${result.errors.join("; ")}`);
}
const written = await index.writeFiles({ outputPath: pagefindDir });
await pagefind.close();
if (written.errors?.length) throw new Error(`索引を書き出せません: ${written.errors.join("; ")}`);

// 結果ID(結果ファイル名) → 論文ID。結果ファイルは gzip 済みのJSONで、url は "/#<論文ID>"
const idmap = {};
const fragmentDir = path.join(pagefindDir, "fragment");
for (const name of fs.readdirSync(fragmentDir)) {
  const body = zlib.gunzipSync(fs.readFileSync(path.join(fragmentDir, name))).toString().replace(/^pagefind_dcd/, "");
  idmap[name.replace(/\.pf_fragment$/, "")] = JSON.parse(body).url.slice(2);
}
if (Object.keys(idmap).length !== papers.length) {
  throw new Error(`結果IDの対応表が一致しません: ${Object.keys(idmap).length} / ${papers.length}`);
}
fs.writeFileSync(path.join(searchDir, "idmap.json"), JSON.stringify(idmap));

for (const name of fs.readdirSync(pagefindDir)) {
  if (UNUSED.some((pattern) => pattern.test(name))) fs.rmSync(path.join(pagefindDir, name), { recursive: true, force: true });
}

const bytes = (dir) => fs.readdirSync(dir, { recursive: true, withFileTypes: true })
  .filter((e) => e.isFile()).reduce((sum, e) => sum + fs.statSync(path.join(e.parentPath, e.name)).size, 0);
const gzSize = (file) => zlib.gzipSync(fs.readFileSync(file)).length;
const listBytes = fs.statSync(path.join(searchDir, "list.json")).size;
const headBytes = fs.statSync(path.join(searchDir, "head.json")).size;
const detailBytes = bytes(path.join(searchDir, "details"));
console.log(`search data: ${papers.length} papers, list.json ${(listBytes / 1024).toFixed(0)}KB ` +
  `(gzip ${(gzSize(path.join(searchDir, "list.json")) / 1024).toFixed(0)}KB, ${Math.round(listBytes / Math.max(papers.length, 1))}B/件), ` +
  `head.json ${(headBytes / 1024).toFixed(0)}KB (gzip ${(gzSize(path.join(searchDir, "head.json")) / 1024).toFixed(0)}KB), ` +
  `details ${(detailBytes / 1024).toFixed(0)}KB x ${chunkCount}, pagefind ${(bytes(pagefindDir) / 1024).toFixed(0)}KB, ` +
  `search/ ${(bytes(searchDir) / 1024).toFixed(0)}KB`);
