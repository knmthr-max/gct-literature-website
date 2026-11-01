// 区分(すべて/臨床/基礎)と研究デザインの絞り込みが、データの件数どおりに動くかを、実際のブラウザで確かめる。
//
//   npm run build:search && npm run check:filter
//
// 確認すること: 区分の件数 = データの件数、臨床で研究デザインを選ぶと件数が一致、複数選択はOR、区分を切り替えると選択が解除、
// URLに選択が入る(直接開いても再現)、検索語と組み合わせたとき、英語ページでも動く。
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const root = path.resolve(process.argv[2] || ".");
const list = JSON.parse(fs.readFileSync(path.join(root, "search/list.json"), "utf8"));
const BASIC = "基礎・トランスレーショナル";
const count = (fn) => list.filter(fn).length;
const designOf = (p) => (p.tags || [])[0] || "";
const total = list.length;
const nBasic = count((p) => designOf(p) === BASIC);
const nClinical = total - nBasic;
const nOf = (design) => count((p) => designOf(p) === design);

const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".css": "text/css", ".wasm": "application/wasm" };
const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end(); return; }
  res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" }).end(fs.readFileSync(file));
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
const num = (text) => Number((text.match(/^([\d,]+)/)?.[1] ?? "NaN").replace(/,/g, ""));

async function open(url) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await page.waitForSelector(".paper-card");
  await page.waitForFunction(() => !document.body.classList.contains("loading-full"), null, { timeout: 120000 }); // 全件の一覧が届くまで待つ
  return { page, errors };
}
const shown = async (page) => num(await page.locator("#result-count").innerText());
const waitShown = (page, n) => page.waitForFunction((x) => Number(document.querySelector("#result-count").innerText.match(/^([\d,]+)/)?.[1].replace(/,/g, "")) === x, n, { timeout: 20000 }).catch(() => {});
const segCount = async (page, label) => num((await page.locator(`#kubun-filters button:has-text("${label}")`).innerText()).replace(label, ""));

// 日本語ページ
{
  const { page, errors } = await open(`${base}/index.html`);
  check("既定: 件数 = 全件", await shown(page), total);
  check("区分の件数(すべて/臨床/基礎)", [await segCount(page, "すべて"), await segCount(page, "臨床"), await segCount(page, "基礎")], [total, nClinical, nBasic]);
  check("既定では研究デザインの段は出ない", await page.locator("#design-row").isHidden(), true);

  await page.click('#kubun-filters button:has-text("臨床")');
  await waitShown(page, nClinical);
  check("臨床: 件数", await shown(page), nClinical);
  check("臨床: 研究デザインの段が出る(8分類)", [await page.locator("#design-row").isVisible(), await page.locator("#design-filters button").count()], [true, 8]);

  await page.click('#design-filters button:has-text("RCT")');
  await waitShown(page, nOf("RCT"));
  check("臨床 + RCT: 件数", await shown(page), nOf("RCT"));
  check("URLに選択が入る", new URL(page.url()).search, "?kubun=clinical&design=RCT");

  await page.click('#design-filters button:has-text("観察研究")');
  await waitShown(page, nOf("RCT") + nOf("観察研究"));
  check("RCT + 観察研究(いずれか): 件数", await shown(page), nOf("RCT") + nOf("観察研究"));

  await page.click("#design-clear");
  await waitShown(page, nClinical);
  check("選択を解除: 臨床すべてに戻る", await shown(page), nClinical);

  await page.click('#design-filters button:has-text("総説")');
  await page.click('#kubun-filters button:has-text("基礎")');
  await waitShown(page, nBasic);
  check("基礎: 件数(研究デザインの選択は解除される)", await shown(page), nBasic);
  check("基礎: 研究デザインの段は出ない", await page.locator("#design-row").isHidden(), true);
  check("基礎: URL", new URL(page.url()).search, "?kubun=basic");

  await page.click('#kubun-filters button:has-text("すべて")');
  await waitShown(page, total);
  check("すべてに戻る: 件数とURL", [await shown(page), new URL(page.url()).search], [total, ""]);
  check("ページのエラーなし", errors, []);
  await page.close();
}

// URLを直接開く(共有された結果の再現)
{
  const { page } = await open(`${base}/index.html?kubun=clinical&design=${encodeURIComponent("症例報告・集積,総説")}`);
  const want = nOf("症例報告・集積") + nOf("総説");
  await waitShown(page, want);
  check("URLから再現: 件数", await shown(page), want);
  check("URLから再現: 選択されたチップ", await page.locator("#design-filters button.active").allInnerTexts().then((t) => t.map((x) => x.replace(/[\d,\s]+$/, "")).sort()), ["症例報告・集積", "総説"].sort());
  await page.close();
}

// 検索語との組み合わせ: 件数(チップ)は、検索語を反映する
{
  const { page } = await open(`${base}/index.html?kubun=clinical`);
  await page.fill("#search-box", "セミノーマ");
  await page.waitForFunction((all) => Number(document.querySelector("#result-count").innerText.match(/^([\d,]+)/)?.[1].replace(/,/g, "")) < all, nClinical, { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(500);
  const shownWithQuery = await shown(page);
  const chipSum = (await page.locator("#design-filters button").allInnerTexts()).map((t) => num(t.replace(/^\D+/, ""))).reduce((a, b) => a + b, 0);
  check("検索語あり: 臨床の件数 = 研究デザインのチップの合計", shownWithQuery, chipSum);
  await page.close();
}

// 英語ページ
{
  const { page, errors } = await open(`${base}/en/index.html`);
  check("英語: 区分の表示", await page.locator("#kubun-filters button").allInnerTexts().then((t) => t.map((x) => x.replace(/[\d,\s]+$/, ""))), ["All", "Clinical", "Basic"]);
  await page.click('#kubun-filters button:has-text("Clinical")');
  await waitShown(page, nClinical);
  check("英語: 臨床の件数", await shown(page), nClinical);
  check("英語: 研究デザインの表示", await page.locator("#design-filters button").allInnerTexts().then((t) => t.map((x) => x.replace(/[\d,\s]+$/, ""))),
    ["SR / MA", "RCT", "Non-randomized trial", "Observational study", "Case report / series", "Review", "Guideline / consensus", "Other"]);
  check("英語: ページのエラーなし", errors, []);
  await page.close();
}

await browser.close();
server.close();
console.log(failed ? `NG: ${failed}件` : "OK: 区分・研究デザインの絞り込みはすべて期待どおり");
process.exit(failed ? 1 : 0);
