import test from "node:test";
import assert from "node:assert/strict";
import { indexText, parseQuery, subterms, pagefindQuery, evaluateQuery, searchWord } from "../../assets/search-lib.js";

test("indexText: 日本語は重なる2文字ずつと3文字ずつに分け、英数字はそのまま", () => {
  assert.deepEqual(indexText("胚細胞腫瘍").trim().split(/\s+/),
    ["胚細", "細胞", "胞腫", "腫瘍", "胚細胞", "細胞腫", "胞腫瘍"]);
  assert.deepEqual(indexText("精巣").trim().split(/\s+/), ["精巣"]);
  assert.deepEqual(indexText("BEP療法 cisplatin").trim().split(/\s+/), ["BEP", "療法", "cisplatin"]);
  assert.deepEqual(indexText("ＢＥＰ").trim().split(/\s+/), ["BEP"]); // 全角英数は正規化
});

test("subterms: 日本語と英字の境目で分け、記号だけの断片は捨てる", () => {
  assert.deepEqual(subterms("BEP療法"), [{ kind: "latin", text: "bep" }, { kind: "cjk", text: "療法" }]);
  assert.deepEqual(subterms("(精巣)"), [{ kind: "cjk", text: "精巣" }]);
  assert.deepEqual(subterms("---"), []);
});

test("pagefindQuery: 日本語は2文字なら2文字語、3文字以上は3文字語の並び(AND)、1文字は null", () => {
  assert.equal(pagefindQuery({ kind: "cjk", text: "精巣腫瘍" }), "精巣腫 巣腫瘍");
  assert.equal(pagefindQuery({ kind: "cjk", text: "胚細胞腫瘍" }), "胚細胞 細胞腫 胞腫瘍");
  assert.equal(pagefindQuery({ kind: "cjk", text: "精巣" }), "精巣");
  assert.equal(pagefindQuery({ kind: "cjk", text: "腫" }), null);
  assert.equal(pagefindQuery({ kind: "latin", text: "cisplatin" }), "cisplatin");
});

test("parseQuery: 空白=AND、OR / | = OR(ANDより強い)、語頭の - = 除外", () => {
  assert.deepEqual(parseQuery("胚細胞腫瘍 化学療法"), { clauses: [["胚細胞腫瘍"], ["化学療法"]], excludes: [] });
  assert.deepEqual(parseQuery("精巣 OR 卵巣"), { clauses: [["精巣", "卵巣"]], excludes: [] });
  assert.deepEqual(parseQuery("精巣|卵巣"), { clauses: [["精巣", "卵巣"]], excludes: [] });
  assert.deepEqual(parseQuery("腫瘍 -精巣"), { clauses: [["腫瘍"]], excludes: ["精巣"] });
  assert.deepEqual(parseQuery("化学療法 精巣 OR 卵巣"), { clauses: [["化学療法"], ["精巣", "卵巣"]], excludes: [] });
  assert.deepEqual(parseQuery("精巣　化学療法"), { clauses: [["精巣"], ["化学療法"]], excludes: [] }); // 全角空白
  assert.deepEqual(parseQuery("OR 精巣 OR"), { clauses: [["精巣"]], excludes: [] }); // 端の OR は無視
  assert.deepEqual(parseQuery("non-seminomatous"), { clauses: [["non-seminomatous"]], excludes: [] }); // 語中の - は除外にしない
  assert.deepEqual(parseQuery("  "), { clauses: [], excludes: [] });
});

// 論文IDと本文だけの小さな「索引」で、集合演算の結果を確認する
const DOCS = {
  a: "精巣腫瘍に対するシスプラチン cisplatin",
  b: "卵巣奇形腫の症例",
  c: "精巣セミノーマと化学療法",
  d: "胚細胞腫瘍の化学療法 BEP療法",
};
const lookup = async (sub) =>
  new Set(Object.entries(DOCS).filter(([, text]) => text.toLowerCase().includes(sub.text)).map(([id]) => id));
const ALL = Object.keys(DOCS);
const run = async (query) => [...(await evaluateQuery(query, lookup, ALL))].sort();

test("evaluateQuery: AND / OR / NOT と、日本語+英字の混在", async () => {
  assert.deepEqual(await run("精巣 化学療法"), ["c"]);
  assert.deepEqual(await run("精巣 OR 卵巣"), ["a", "b", "c"]);
  assert.deepEqual(await run("精巣 OR 卵巣 化学療法"), ["c"]);
  assert.deepEqual(await run("腫瘍 -精巣"), ["d"]);
  assert.deepEqual(await run("-精巣"), ["b", "d"]); // 除外だけの検索式は全件から引く
  assert.deepEqual(await run("BEP療法"), ["d"]);
  assert.deepEqual(await run("精巣腫瘍 cisplatin"), ["a"]);
  assert.equal(await evaluateQuery("   ", lookup, ALL), null);
  assert.deepEqual(await run("存在しない語"), []);
});

test("indexText: 記号が付いた英語の語は、そのままの形と、記号で区切った部分の両方を索引に入れる", () => {
  const words = indexText("•patients non-seminomatous (GCT) cell/tissue plain").trim().split(/\s+/);
  for (const word of ["•patients", "patients", "non-seminomatous", "non", "seminomatous", "(GCT)", "GCT", "cell/tissue", "cell", "tissue", "plain"]) {
    assert.ok(words.includes(word), word);
  }
  assert.deepEqual(indexText("plain words").trim().split(/\s+/), ["plain", "words"]); // 記号の無い語は増やさない
});

test("searchWord: 3文字以上の英語の語は、前方一致の範囲の索引を先読みしてから1度だけ検索する", async () => {
  const preloaded = [];
  const pagefind = { preload: async (word) => { preloaded.push(word); }, search: async (query) => ({ query, results: [] }) };
  const result = await searchWord(pagefind, { kind: "latin", text: "seminoma" });
  assert.equal(result.query, "seminoma");
  assert.equal(preloaded.length, 36);
  assert.ok(preloaded.includes("seminomaa") && preloaded.includes("seminoma9"));
  await searchWord(pagefind, { kind: "latin", text: "seminoma" });
  assert.equal(preloaded.length, 36); // 同じ語は2回目は先読みしない
  await searchWord(pagefind, { kind: "latin", text: "in" });
  await searchWord(pagefind, { kind: "cjk", text: "精巣" });
  assert.equal(preloaded.length, 36); // 2文字以下の英語と、日本語は先読みしない
  assert.equal(await searchWord(pagefind, { kind: "cjk", text: "腫" }), null); // 1文字の日本語は呼び出し側が探す
});
