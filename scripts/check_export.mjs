// 検索結果のダウンロード(CSV / RIS)が、期待どおり動くかを、実際のブラウザで確かめる。
//
//   npm run build:search && npm run check:export
//
// 確認すること: チェックした文献だけのダウンロード(最大100件・絞り込みを変えても残る・並び順) / 1行目が検索式 / 列(PMID・DOI・収載誌・発行年・タイトル・抄録(原文)) / 上位100件まで・現在の並び順 /
// 抄録が原文と一致 / BOMつきUTF-8 / RIS の項目と終端 / 絞り込みと検索語が検索式に入る / 100件以下ではそのまま / 英語ページ / ご利用にあたっての注意書き。
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const root = path.resolve(process.argv[2] || ".");
const list = JSON.parse(fs.readFileSync(path.join(root, "search/list.json"), "utf8"));
const head = JSON.parse(fs.readFileSync(path.join(root, "search/head.json"), "utf8"));
const detail = {};
for (const name of fs.readdirSync(path.join(root, "search/details"))) Object.assign(detail, JSON.parse(fs.readFileSync(path.join(root, "search/details", name), "utf8")));
const abstractOf = (id) => { const f = path.join(root, "search/abstract", `${id}.json`); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")).abstract || "" : ""; };

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
async function open(url) {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await page.waitForSelector(".paper-card");
  await page.waitForFunction(() => !document.body.classList.contains("loading-full"), null, { timeout: 120000 });
  await page.waitForSelector("#export-row:not([hidden])");
  return { page, errors };
}
async function download(page, selector) {
  const [dl] = await Promise.all([page.waitForEvent("download", { timeout: 60000 }), page.click(selector)]);
  const file = await dl.path();
  return { name: dl.suggestedFilename(), text: fs.readFileSync(file, "utf8") };
}
// RFC 4180 の CSV を読む(引用符・カンマ・改行を含むセルに対応)
function parseCsv(text) {
  const rows = []; let row = []; let cell = ""; let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') quoted = false; else cell += c; }
    else if (c === '"') quoted = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n") { row.push(cell.replace(/\r$/, "")); rows.push(row); row = []; cell = ""; }
    else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

{
  const { page, errors } = await open(`${base}/index.html`);
  check("ご利用にあたっての注意書きが、サイト紹介の冒頭に出る", await page.locator("#site-usage li").count(), 3);
  check("100件を超えるとき: 上位100件のみの案内", (await page.locator("#export-status").innerText()).includes("上位100件"), true);
  const csv = await download(page, "#export-csv");
  check("CSV: ファイル名", /^gct-literature_\d{4}-\d{2}-\d{2}_100\.csv$/.test(csv.name), true);
  check("CSV: BOMつき", csv.text.charCodeAt(0), 0xFEFF);
  const rows = parseCsv(csv.text.slice(1)).filter((r) => r.length > 1 || r[0]);
  check("CSV: 1行目は検索式", rows[0][0].startsWith("検索式: キーワード: 指定なし"), true);
  check("CSV: 2行目は列名", rows[1], ["PMID", "DOI", "収載誌", "発行年", "タイトル", "抄録(原文)"]);
  check("CSV: データは100行", rows.length - 2, 100);
  const top = list.slice(0, 100); // 既定の並び(発行年の新しい順)の上位100件
  check("CSV: 並びは現在の並び順(先頭100件のPMID)", rows.slice(2).map((r) => r[0]), top.map((p) => p.pmid));
  const sample = rows[2 + 5]; const sp = top[5];
  check("CSV: DOI・収載誌・発行年・タイトルが一致", [sample[1], sample[2], sample[3], sample[4]], [detail[sp.id].doi ?? "", sp.journal ?? "", String(sp.year), sp.title.replace(/\s+/g, " ").trim()]);
  check("CSV: 抄録が原文と一致", rows.slice(2).every((r, i) => r[5] === abstractOf(top[i].id).replace(/\s+/g, " ").trim()), true);

  const ris = await download(page, "#export-ris");
  check("RIS: ファイル名", /\.ris$/.test(ris.name), true);
  const records = ris.text.split("ER  - \r\n").filter((x) => x.trim());
  check("RIS: 100件", records.length, 100);
  check("RIS: 各件に TY・TI・AB・AN・N1(検索式)がある", records.every((r) => /^TY  - JOUR/.test(r.trim()) && r.includes("\r\nTI  - ") && r.includes("\r\nN1  - 検索式: ")), true);
  check("RIS: PMID(AN)が先頭の順と一致", records.map((r) => r.match(/\r\nAN  - (\d+)/)?.[1]), top.map((p) => p.pmid));

  // 絞り込み + 検索語: 検索式に入り、並び順は変えた順
  await page.click('#kubun-filters button:has-text("臨床")');
  await page.waitForFunction(() => document.querySelector("#result-count").innerText.includes("/"), null, { timeout: 60000 });
  await page.selectOption("#sort-select", "year-asc");
  await page.waitForTimeout(500);
  const asc = await download(page, "#export-csv");
  const arows = parseCsv(asc.text.slice(1)).filter((r) => r.length > 1 || r[0]);
  const clinicalAsc = list.filter((p) => (p.tags?.[0] || "") !== "基礎・トランスレーショナル").sort((a, b) => (a.year || 0) - (b.year || 0)).slice(0, 100);
  check("絞り込み+並び替え: 検索式に区分と並び順が入る", arows[0][0].includes("区分: 臨床") && arows[0][0].includes("並び順: 発行年: 古い順"), true);
  check("絞り込み+並び替え: 上位100件は発行年の古い順(年の並びが一致)", arows.slice(2).map((r) => r[3]), clinicalAsc.map((p) => String(p.year)));
  check("ページのエラーなし", errors, []);
  await page.close();
}
{ // 100件以下: そのまま全件
  const some = list.filter((p) => p.attrs?.sc === "treatment" && p.attrs?.mt === "yes" && p.tags?.[0] === "SR・MA"); // データが増えても100件以下に収まるよう、定量的統合ありに絞る
  const { page } = await open(`${base}/index.html?kubun=clinical&design=${encodeURIComponent("SR・MA")}&f_sc=treatment&f_mt=yes`);
  check("100件以下: 案内は出ない", await page.locator("#export-status").innerText(), "");
  const csv = await download(page, "#export-csv");
  const rows = parseCsv(csv.text.slice(1)).filter((r) => r.length > 1 || r[0]);
  check("100件以下: 全件(該当件数)を出力", rows.length - 2, Math.min(some.length, 100));
  check("検索式に研究デザインと属性が入る", rows[0][0].includes("研究デザイン: SR・MA") && rows[0][0].includes("統合の対象: 治療"), true);
  await page.close();
}
{ // チェックした文献だけをダウンロード
  const { page, errors } = await open(`${base}/index.html`);
  const pick = [list[7], list[1], list[3]]; // チェックする順は、並び順と違ってよい
  for (const p of pick) await page.locator(`input[data-select-id="${p.id}"]`).check();
  check("選択: バーに件数が出る", (await page.locator("#selection-count").innerText()).includes("3件"), true);
  check("選択: 選んだカードに枠がつく", await page.locator(".paper-card.selected").count(), 3);
  const sel = await download(page, "#select-csv");
  const srows = parseCsv(sel.text.slice(1)).filter((r) => r.length > 1 || r[0]);
  check("選択CSV: 1行目は「選択した文献: 3」", srows[0][0].startsWith("検索式: 選択した文献: 3"), true);
  check("選択CSV: 3件だけ、現在の並び順", srows.slice(2).map((r) => r[0]), [list[1], list[3], list[7]].map((p) => p.pmid));
  check("選択CSV: ファイル名に件数", /_3\.csv$/.test(sel.name), true);
  const selRis = await download(page, "#select-ris");
  check("選択RIS: 3件", selRis.text.split("ER  - \r\n").filter((x) => x.trim()).length, 3);

  // 絞り込みを変えても、選択は残る
  await page.click('#kubun-filters button:has-text("基礎")');
  await page.waitForFunction(() => document.querySelector("#result-count").innerText.includes("/"), null, { timeout: 60000 });
  check("絞り込みを変えても、選択は残る", (await page.locator("#selection-count").innerText()).includes("3件"), true);
  await page.click("#select-clear");
  check("選択を解除: バーが消える", await page.locator("#selection-bar").isHidden(), true);

  // 上限(100件): 表示中の文献を選択 → さらに表示 → 選択、で100件に達し、残りは選べない
  await page.click('#kubun-filters button:has-text("すべて")');
  await page.waitForFunction(() => document.querySelector("#result-count").innerText.includes("/"), null, { timeout: 60000 });
  await page.click("#select-shown");
  check("表示中の文献を選択: 50件", (await page.locator("#selection-count").innerText()).includes("50件"), true);
  await page.click("#load-more");
  await page.click("#select-shown");
  await page.click("#load-more");
  await page.click("#select-shown");
  check("上限: 100件でとまる", (await page.locator("#selection-count").innerText()).includes("100件"), true);
  check("上限: 選んでいないチェックボックスは使えない", await page.locator('input[data-select-id]:not(:checked):not(:disabled)').count(), 0);
  const hundred = await download(page, "#select-csv");
  check("上限: 100件を出力", parseCsv(hundred.text.slice(1)).filter((r) => r.length > 1 || r[0]).length - 2, 100);
  await page.uncheck('input[data-select-id]:checked >> nth=0');
  check("1件外すと、選べる状態に戻る", await page.locator('input[data-select-id]:not(:checked):not(:disabled)').count() > 0, true);
  check("ページのエラーなし(選択)", errors, []);
  await page.close();
}
{ // 英語ページ: 選択
  const { page } = await open(`${base}/en/index.html`);
  await page.locator(`input[data-select-id="${list[0].id}"]`).check();
  check("英語ページ: バーの表示", (await page.locator("#selection-count").innerText()).startsWith("Selected: 1"), true);
  const csv = await download(page, "#select-csv");
  check("英語ページ: 選択CSVの1行目", parseCsv(csv.text.slice(1))[0][0].startsWith("Search: Selected papers: 1"), true);
  await page.close();
}
{ // 英語ページ
  const { page, errors } = await open(`${base}/en/index.html`);
  const csv = await download(page, "#export-csv");
  const rows = parseCsv(csv.text.slice(1)).filter((r) => r.length > 1 || r[0]);
  check("英語ページ: 1行目は Search: …", rows[0][0].startsWith("Search: Keyword: none"), true);
  check("英語ページ: 列名", rows[1], ["PMID", "DOI", "Journal", "Year", "Title", "Abstract (original)"]);
  check("英語ページ: 注意書き", await page.locator("#site-usage li").count(), 3);
  check("英語ページ: ページのエラーなし", errors, []);
  await page.close();
}
await browser.close();
server.close();
if (failed) { console.error(`\n${failed} 件が期待と違います`); process.exit(1); }
console.log("\n検索結果のダウンロードはすべて期待どおり");
