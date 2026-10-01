// Spike (not wired into the site): build a Pagefind index from data/papers.json with Japanese
// indexed as overlapping 2-character tokens, so a query converted the same way behaves like a
// substring search. See ../2026-09-30_pagefind_search.md.
//
//   npm install pagefind
//   node build_index.mjs ../../../data/papers.json ./out en
//
// Query side (browser): split the query into terms; search each term separately (a Japanese term as a quoted
// phrase of bigrams, e.g.  pf.search('"胚細 細胞 胞腫 腫瘍"')), map result ids with idmap.json, then combine the
// id sets: AND = intersection, OR = union, NOT = difference.
import * as pagefind from "pagefind";
import fs from "fs";

const [, , papersPath, outDir, lang = "en"] = process.argv;
const papers = JSON.parse(fs.readFileSync(papersPath, "utf8")).filter((p) => p.relevance_status !== "excluded");
const RANK = { "very-high": 4, high: 3, moderate: 2, low: 1, unknown: 0 };

const CJK = /[぀-ヿ㐀-鿿豈-﫿々ー]+/g;
export const bigrams = (text) =>
  text.replace(CJK, (run) =>
    run.length < 2
      ? " " + run + " "
      : " " + Array.from({ length: run.length - 1 }, (_, i) => run.slice(i, i + 2)).join(" ") + " ");

// forceLanguage "en": whitespace tokenising (the Japanese is already split by `bigrams`)
const { index } = await pagefind.createIndex({ forceLanguage: lang });
for (const p of papers) {
  const content = bigrams(
    [p.title_ja, p.title, p.summary_ja, p.summary_en, p.abstract_ja, p.abstract, (p.authors || []).join(", "), p.journal]
      .filter(Boolean)
      .join("\n"),
  );
  const r = await index.addCustomRecord({
    url: `/#${p.id}`,
    content,
    language: lang,
    meta: { id: p.id, title: p.title_ja || p.title || "", year: String(p.year || ""), jif_tier: p.jif_tier || "unknown" },
    filters: { tag: p.tags || [], jif: [p.jif_tier || "unknown"], year: [String(p.year || "")] },
    sort: { year: String(p.year || 0).padStart(4, "0"), jif: String(RANK[p.jif_tier || "unknown"]), added: String(p.added_at || "") },
  });
  if (r.errors?.length) console.error(r.errors);
}
const w = await index.writeFiles({ outputPath: outDir });
console.log("records", papers.length, w.errors?.length ? w.errors : "ok");

// result id (fragment file name) -> paper id, so a search can return paper ids without fetching any fragment
import zlib from "zlib";
const idmap = {};
for (const f of fs.readdirSync(`${outDir}/fragment`)) {
  const json = zlib.gunzipSync(fs.readFileSync(`${outDir}/fragment/${f}`)).toString().replace(/^pagefind_dcd/, "");
  idmap[f.replace(".pf_fragment", "")] = JSON.parse(json).url.slice(2); // url is "/#<paper id>"
}
fs.writeFileSync(`${outDir}/idmap.json`, JSON.stringify(idmap));
await pagefind.close();
