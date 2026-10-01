// 検索の一致テスト: 実際のブラウザで索引を引き、素朴な全文一致(基準)と結果を比べる。
//
//   npm run build:search && npm run check:search
//
// 合格条件(設計 docs/decisions/2026-09-30_pagefind_search.md の 4.1):
//   - 取りこぼし 0(基準に含まれる論文が、検索結果に全部ある)
//   - 日本語だけの検索式では、余分な結果は基準の2%まで(Pagefind 側の挙動による。実データでは1件程度)。
//     英語を含む場合は、語幹処理による余分を許容する
//   - 画面の件数表示が、検索結果の件数と一致する
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";
import { normalise, parseQuery, evaluateQuery, subterms } from "../assets/search-lib.js";

const root = path.resolve(process.argv[2] || ".");
const list = JSON.parse(fs.readFileSync(path.join(root, "search/list.json"), "utf8"));
const abstracts = {};
for (const p of list) {
  const file = path.join(root, "search/abstract", `${p.id}.json`);
  abstracts[p.id] = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
}
const haystack = Object.fromEntries(list.map((p) => [p.id, normalise([
  p.title_ja, p.title, p.summary_ja, p.summary_en, abstracts[p.id].abstract_ja, abstracts[p.id].abstract,
  (p.authors || []).join(", "), p.journal, ...(p.tags || []),
].filter(Boolean).join("\n")).toLowerCase()]));
const allIds = list.map((p) => p.id);

// 基準: 日本語は部分一致、英語は語の先頭一致
const reference = async (sub) => {
  const test = sub.kind === "cjk"
    ? (text) => text.includes(sub.text)
    : (() => { const re = new RegExp(`(^|[^\\p{L}\\p{N}])${sub.text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "u"); return (text) => re.test(text); })();
  return new Set(allIds.filter((id) => test(haystack[id])));
};

// 検索式: 固定の代表例 + データから自動で取り出した頻出語
const golden = JSON.parse(fs.readFileSync(new URL("../tests/search/queries.json", import.meta.url), "utf8"));
const frequent = (() => {
  const seg = new Intl.Segmenter("ja", { granularity: "word" });
  const df = new Map();
  for (const p of list) {
    const words = new Set([...seg.segment(normalise(`${p.title_ja || ""} ${p.title || ""}`).toLowerCase())]
      .filter((s) => s.isWordLike && [...s.segment].length >= 2).map((s) => s.segment));
    for (const w of words) df.set(w, (df.get(w) || 0) + 1);
  }
  return [...df].filter(([, n]) => n >= 3).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).slice(0, 40).map(([w]) => w);
})();
const queries = [...new Set([...golden, ...frequent])];

const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".css": "text/css", ".wasm": "application/wasm" };
const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" }).end(fs.readFileSync(file));
});
await new Promise((resolve) => server.listen(0, resolve));
const base = `http://localhost:${server.address().port}`;

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(`${base}/index.html?search=pagefind`);
await page.waitForSelector(".paper-card");

// 画面と同じ手順(語ごとに Pagefind を引き、論文IDの集合で組み合わせる)をページ内で実行する
const engineResult = (query) => page.evaluate(async ({ q, allIds: all }) => {
  const lib = await import("/assets/search-lib.js");
  window.__engine ??= { pagefind: await lib.loadPagefind("/pagefind/pagefind.js"), idmap: await (await fetch("/search/idmap.json")).json() };
  const { pagefind, idmap } = window.__engine;
  const lookup = async (sub) => {
    const pq = lib.pagefindQuery(sub);
    if (pq === null) return new Set(); // 1文字の日本語は画面側が別の方法で探す(このテストの対象外)
    const { results } = await pagefind.search(pq);
    return new Set(results.map((r) => idmap[r.id]).filter(Boolean));
  };
  const ids = await lib.evaluateQuery(q, lookup, all);
  return ids && [...ids];
}, { q: query, allIds });

let failed = 0;
const rows = [];
for (const query of queries) {
  const want = await evaluateQuery(query, reference, allIds);
  const gotList = await engineResult(query);
  if (want === null || gotList === null) continue;
  const got = new Set(gotList);
  const missing = [...want].filter((id) => !got.has(id));
  const extra = [...got].filter((id) => !want.has(id));
  const { clauses, excludes } = parseQuery(query);
  const cjkOnly = [...clauses.flat(), ...excludes].every((t) => subterms(t).every((s) => s.kind === "cjk"));
  const ok = missing.length === 0 && (!cjkOnly || extra.length <= Math.ceil(want.size * 0.02));
  if (!ok) failed++;
  rows.push({ query, want: want.size, got: got.size, missing: missing.length, extra: extra.length, ok });
}

// 画面の件数表示が検索結果と一致するか(代表の検索式のみ)
for (const query of golden.slice(0, 5)) {
  await page.fill("#search-box", query);
  await page.waitForTimeout(700);
  const shown = await page.locator("#result-count").innerText();
  const want = await evaluateQuery(query, reference, allIds);
  const expected = `${want ? want.size : list.length}件`;
  const ok = shown.startsWith(expected);
  if (!ok) { failed++; console.error(`画面の件数が違います: 「${query}」 画面=${shown} 期待=${expected}`); }
}
await page.fill("#search-box", "");

await browser.close();
server.close();

console.table(rows);
if (errors.length) { console.error("ページのエラー:", errors); failed++; }
console.log(failed ? `NG: ${failed}件` : `OK: ${rows.length}件の検索式すべてで、取りこぼし0`);
process.exit(failed ? 1 : 0);
