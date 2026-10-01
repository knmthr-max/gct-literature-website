// 公開用の検索データを data/papers.json から生成する(デプロイ時に実行。生成物はコミットしない)。
//
//   node scripts/build_site_search.mjs [papers.json] [出力ディレクトリ]   (既定: data/papers.json と、リポジトリ直下)
//
// 出力:
//   search/list.json          軽い一覧(抄録・人向けメモを除く)
//   search/abstract/<id>.json 抄録(英/日)。カードを開いたときだけ読む
//   search/idmap.json         Pagefind の結果ID → 論文ID
//   pagefind/                 検索索引(日本語は2文字ずつの語で索引する)
// 設計: docs/decisions/2026-09-30_pagefind_search.md
import * as pagefind from "pagefind";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { indexText } from "../assets/search-lib.js";

const papersPath = process.argv[2] || "data/papers.json";
const outDir = process.argv[3] || ".";

const LIST_FIELDS = ["id", "pmid", "doi", "url", "title", "title_ja", "journal", "year", "authors", "tags",
  "jif_tier", "added_at", "summary_ja", "summary_en"];
const SAFE_ID = /^[A-Za-z0-9._-]+$/;
// 検索に使わない Pagefind の部品(UI・ハイライト)と、読まない結果詳細は公開しない
const UNUSED = [/^pagefind-.*ui\.(js|css)$/, /^pagefind-highlight\.js$/, /^fragment$/];

const papers = JSON.parse(fs.readFileSync(papersPath, "utf8")).filter((p) => p.relevance_status !== "excluded");

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

// 一覧と抄録
const list = papers.map((p) => ({
  ...Object.fromEntries(LIST_FIELDS.filter((key) => p[key] !== undefined).map((key) => [key, p[key]])),
  has_abstract: Boolean(p.abstract),
  has_abstract_ja: Boolean(p.abstract_ja),
}));
fs.writeFileSync(path.join(searchDir, "list.json"), JSON.stringify(list));
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
const listBytes = fs.statSync(path.join(searchDir, "list.json")).size;
console.log(`search data: ${papers.length} papers, list.json ${(listBytes / 1024).toFixed(0)}KB ` +
  `(${Math.round(listBytes / Math.max(papers.length, 1))}B/件), pagefind ${(bytes(pagefindDir) / 1024).toFixed(0)}KB, ` +
  `search/ ${(bytes(searchDir) / 1024).toFixed(0)}KB`);
