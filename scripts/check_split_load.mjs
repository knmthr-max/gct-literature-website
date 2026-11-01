// 最初の表示を速くするための分割読み込み(先頭100件 → 全件の核 → 要約などの詳細)が、期待どおり動くかを、実際のブラウザで確かめる。
//
//   npm run build:search && npm run check:split
//
// 確認すること: list.json に要約・著者が入っていない / 先頭の100件はすぐ出る / 全件が届くまで絞り込みは隠れる /
// 全件が届くと件数が出る / 詳細が届くと「読み込み中」が消えて要約と著者が出る / 絞り込みのURLを直接開いても動く /
// 詳細が全部読めなくても、一覧は使える。
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const root = path.resolve(process.argv[2] || ".");
const list = JSON.parse(fs.readFileSync(path.join(root, "search/list.json"), "utf8"));
const head = JSON.parse(fs.readFileSync(path.join(root, "search/head.json"), "utf8"));
const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".css": "text/css", ".wasm": "application/wasm" };
let delayList = 0;
let failDetails = false;
const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  const file = path.join(root, decodeURIComponent(url.pathname).replace(/\/$/, "/index.html"));
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end(); return; }
  const send = () => res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" }).end(fs.readFileSync(file));
  if (failDetails && url.pathname.includes("/search/details/")) { res.writeHead(503).end(); return; }
  if (delayList && url.pathname.endsWith("/search/list.json")) setTimeout(send, delayList); else send();
});
await new Promise((resolve) => server.listen(0, resolve));
const base = `http://localhost:${server.address().port}`;
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});

let failed = 0;
const check = (name, actual, expected) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) { failed++; console.error(`NG: ${name}\n  実際: ${JSON.stringify(actual)}\n  期待: ${JSON.stringify(expected)}`); }
  else console.log(`OK: ${name}`);
};
const fullyLoaded = (page) => page.waitForFunction(() => !document.body.classList.contains("loading-full"), null, { timeout: 120000 });

check("list.json に要約・著者・DOI を含まない", list.some((p) => "summary_ja" in p || "summary_en" in p || "authors" in p || "doi" in p), false);
check("head.json: 先頭は100件で、要約つき", [head.papers.length, head.papers.every((p) => "title" in p)], [100, true]);
check("head.json の先頭 = list.json の先頭(同じ並び)", head.papers.map((p) => p.id), list.slice(0, 100).map((p) => p.id));
check("詳細の分割数が、全件を覆う", head.detail_chunks * head.chunk_size >= head.total, true);

// 全件の一覧を遅らせて、先頭の100件だけの状態を見る
delayList = 4000;
{
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/index.html`);
  await page.waitForSelector(".paper-card");
  check("全件が届く前: 先頭の100件のうち50件を描く", await page.locator(".paper-card").count(), 50);
  check("全件が届く前: 先頭のカードに要約がある", (await page.locator(".paper-card .paper-summary").first().innerText()).includes("読み込み中"), false);
  check("全件が届く前: 絞り込みの欄は見えない", await page.locator(".design-panel").isHidden(), true);
  check("全件が届く前: 件数の表示は「読み込み中」", (await page.locator("#result-count").innerText()).includes("読み込み中"), true);
  await page.fill("#search-box", "testis");
  await fullyLoaded(page);
  await page.waitForFunction(() => /^\d/.test(document.querySelector("#result-count").innerText), null, { timeout: 60000 });
  check("全件が届いた後: 入力済みの検索語で検索されている", (await page.locator("#result-count").innerText()).includes(`/ 全${list.length}件`), true);
  check("全件が届いた後: 絞り込みの欄が見える", await page.locator(".design-panel").isVisible(), true);
  check("ページのエラーなし", errors, []);
  await page.close();
}

// 詳細が届くと、「読み込み中」が消えて要約・著者が出る(核だけのカードで確かめる)
delayList = 0;
{
  const page = await browser.newPage();
  await page.goto(`${base}/index.html?kubun=clinical&design=${encodeURIComponent("症例報告・集積")}&sort=x`);
  await page.waitForSelector(".paper-card");
  await fullyLoaded(page);
  await page.waitForFunction(() => !document.querySelector(".paper-summary-pending")?.textContent.includes("読み込み中"), null, { timeout: 60000 });
  const withAuthors = await page.locator(".paper-card .paper-meta").first().innerText();
  const firstId = list.find((p) => p.tags?.[0] === "症例報告・集積").id;
  const detail = JSON.parse(fs.readFileSync(path.join(root, "search/details", `${Math.floor(list.findIndex((p) => p.id === firstId) / head.chunk_size)}.json`), "utf8"))[firstId];
  check("詳細が届く: 先頭のカードの著者が出る", withAuthors.includes((detail.authors || [""])[0]), true);
  check("絞り込みのURLを直接開く: 件数 = データの件数", await page.locator("#result-count").innerText().then((t) => Number(t.match(/^([\d,]+)/)[1].replace(/,/g, ""))), list.filter((p) => p.tags?.[0] === "症例報告・集積").length);
  await page.close();
}

// 詳細を読めなくても、一覧(核)は使える
failDetails = true;
{
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/index.html`);
  await page.waitForSelector(".paper-card");
  await fullyLoaded(page);
  await page.waitForTimeout(1500);
  check("詳細を読めない: 一覧と件数は出る", await page.locator("#result-count").innerText().then((t) => t.startsWith(`${list.length}件`)), true);
  check("詳細を読めない: ページのエラーなし", errors, []);
  await page.close();
}

// 英語ページ
failDetails = false;
{
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/en/index.html`);
  await page.waitForSelector(".paper-card");
  await fullyLoaded(page);
  await page.waitForFunction(() => ![...document.querySelectorAll(".paper-card:nth-child(-n+5) .paper-summary-pending")].some((e) => e.textContent.includes("Loading")), null, { timeout: 60000 });
  check("英語ページ: 件数", await page.locator("#result-count").innerText().then((t) => t.startsWith(`${list.length} of`)), true);
  check("英語ページ: ページのエラーなし", errors, []);
  await page.close();
}
await browser.close();
server.close();
if (failed) { console.error(`\n${failed} 件が期待と違います`); process.exit(1); }
console.log("\n分割読み込みはすべて期待どおり");
