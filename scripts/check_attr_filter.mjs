// 属性の絞り込み(部位・組織型・臨床テーマなど)が、データの件数どおりに動くかを、実際のブラウザで確かめる。
//
//   npm run build:search && npm run check:attr
//
// 確認すること: 臨床のときだけ絞り込みの欄が出る、1項目の選択の件数 = データの件数、項目をまたぐとAND(同じ項目の中はOR)、
// 研究デザインを選ぶと固有の項目が出る、URLに入り直接開いても再現、「すべて解除」、カードに属性が出る、英語ページでも動く。
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const root = path.resolve(process.argv[2] || ".");
const list = JSON.parse(fs.readFileSync(path.join(root, "search/list.json"), "utf8"));
const BASIC = "基礎・トランスレーショナル";
const designOf = (p) => (p.tags || [])[0] || "";
const clinical = list.filter((p) => designOf(p) !== BASIC);
const has = (p, key, v) => { const x = p.attrs?.[key]; return Array.isArray(x) ? x.includes(v) : x === v; };
const n = (arr) => arr.length;

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
const waitShown = (page, x) => page.waitForFunction((v) => Number(document.querySelector("#result-count").innerText.match(/^([\d,]+)/)?.[1].replace(/,/g, "")) === v, x, { timeout: 20000 }).catch(() => {});
const chip = (page, facet, value) => page.locator(`#attr-panel details[data-facet="${facet}"] button[data-value="${value}"]`);
const openFacet = (page, facet) => page.evaluate((f) => { document.querySelector(`#attr-panel details[data-facet="${f}"]`).open = true; }, facet);

{
  const { page, errors } = await open(`${base}/index.html`);
  check("既定(すべて)では絞り込みの欄は出ない", await page.locator("#attr-panel").isHidden(), true);
  await page.click('#kubun-filters button:has-text("臨床")');
  await waitShown(page, n(clinical));
  check("臨床: 絞り込みの欄が出る", await page.locator("#attr-panel").isVisible(), true);

  await chip(page, "site", "testis").click();
  const testis = clinical.filter((p) => has(p, "si", "testis"));
  await waitShown(page, n(testis));
  check("部位=精巣: 件数", await shown(page), n(testis));
  check("部位=精巣: URL", new URL(page.url()).searchParams.get("f_si"), "testis");

  await chip(page, "site", "ovary").click();
  const either = clinical.filter((p) => has(p, "si", "testis") || has(p, "si", "ovary"));
  await waitShown(page, n(either));
  check("部位=精巣 または 卵巣(同じ項目の中はOR): 件数", await shown(page), n(either));

  await openFacet(page, "theme");
  await chip(page, "theme", "surgery").click();
  const both = either.filter((p) => has(p, "th", "surgery"));
  await waitShown(page, n(both));
  check("さらに 臨床テーマ=手術(項目をまたぐとAND): 件数", await shown(page), n(both));

  const url = page.url();
  const reopened = await open(url);
  check("URLから再現: 件数", await shown(reopened.page), n(both));
  check("URLから再現: 選択中の条件の数", await reopened.page.locator("#attr-active button").count(), 3);
  check("URLから再現: ページのエラーなし", reopened.errors, []);
  await reopened.page.close();

  await page.click("#attr-reset");
  await waitShown(page, n(clinical));
  check("すべて解除: 件数とURL", [await shown(page), new URL(page.url()).searchParams.has("f_si")], [n(clinical), false]);

  check("固有の項目は、研究デザインを選ぶまで出ない", await page.locator("#attr-specific details").count(), 0);
  await page.click('#design-filters button:has-text("RCT")');
  const rct = clinical.filter((p) => designOf(p) === "RCT");
  await waitShown(page, n(rct));
  check("RCT: 固有の項目(治療ライン・主要評価項目・相)", await page.locator("#attr-specific details").count(), 3);
  const firstLine = rct.filter((p) => has(p, "ln", "first_line"));
  await chip(page, "line", "first_line").click();
  await waitShown(page, n(firstLine));
  check("RCT + 治療ライン=初回: 件数", await shown(page), n(firstLine));
  await page.click('#design-filters button:has-text("RCT")');
  await waitShown(page, n(clinical));
  check("デザインの選択を外すと、固有の項目の選択も外れる", [await shown(page), await page.locator("#attr-specific details").count()], [n(clinical), 0]);

  await page.click('#kubun-filters button:has-text("基礎")');
  check("基礎: 絞り込みの欄は出ない", await page.locator("#attr-panel").isHidden(), true);
  check("ページのエラーなし", errors, []);
  await page.close();
}
{
  const withAttrs = clinical.find((p) => p.attrs?.si && p.attrs?.th?.length && designOf(p) === "症例報告・集積");
  const { page, errors } = await open(`${base}/index.html?kubun=clinical&design=${encodeURIComponent("症例報告・集積")}`);
  check("カードに属性が出る", (await page.locator(".paper-card .paper-attr").count()) > 0, true);
  check("カードに臨床テーマが出る", (await page.locator(".paper-card .paper-themes").count()) > 0, true);
  check("(データ確認)症例報告に属性がある", Boolean(withAttrs), true);
  check("ページのエラーなし(症例報告)", errors, []);
  await page.close();
}
{
  const { page, errors } = await open(`${base}/en/index.html?kubun=clinical`);
  await waitShown(page, n(clinical));
  await chip(page, "site", "testis").click();
  const testis = clinical.filter((p) => has(p, "si", "testis"));
  await waitShown(page, n(testis));
  check("英語: 部位=Testis の件数", await shown(page), n(testis));
  check("英語: 項目名", await page.locator('#attr-panel details[data-facet="site"] summary').innerText(), "Primary site");
  check("英語: ページのエラーなし", errors, []);
  await page.close();
}
await browser.close();
server.close();
if (failed) { console.error(`\n${failed} 件が期待と違います`); process.exit(1); }
console.log("\n属性の絞り込みはすべて期待どおり");
