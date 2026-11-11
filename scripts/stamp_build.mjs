// デプロイ時に、画面(HTML)へ「ビルドの識別子」を入れる(作業用のコピーだけを書き換える。コミットしない)。
//
//   node scripts/stamp_build.mjs [サイトのルート(既定: .)]
//
// 1. <script src=".../app.js"> と <link href=".../style.css"> に ?v=<識別子> を付ける
//    (ブラウザが古い app.js を使い続けて、新しいデータ形式と食い違うのを防ぐ)
// 2. <meta name="build-id" content="<識別子>"> を入れる。画面は、search/head.json の build と比べ、
//    食い違えば「サイトが更新されました。再読み込みしてください」と出す(assets/app.js)
// 識別子は、scripts/build_site_search.mjs が search/build.json に書いたもの。
// 3. data/site.json の last_updated(画面の「最終更新」)を、掲載中の文献の added_at の最新日にそろえる
//    (手で書き換えると更新が漏れるため)。掲載中 = relevance_status が excluded でない文献。
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.argv[2] || ".");
const id = JSON.parse(fs.readFileSync(path.join(root, "search/build.json"), "utf8")).id;
for (const page of ["index.html", "en/index.html"]) {
  const file = path.join(root, page);
  let html = fs.readFileSync(file, "utf8");
  html = html.replace(/(src="[^"]*assets\/app\.js)(\?v=[^"]*)?"/, `$1?v=${id}"`)
    .replace(/(href="[^"]*assets\/style\.css)(\?v=[^"]*)?"/, `$1?v=${id}"`);
  html = html.replace(/<meta name="build-id"[^>]*>\s*/, "");
  html = html.replace("</head>", `  <meta name="build-id" content="${id}">\n</head>`);
  fs.writeFileSync(file, html);
}

let latest = "";
for (const name of fs.readdirSync(path.join(root, "data/papers"))) {
  if (!name.endsWith(".json") || name === "index.json") continue;
  for (const e of JSON.parse(fs.readFileSync(path.join(root, "data/papers", name), "utf8"))) {
    if (e.relevance_status !== "excluded" && /^\d{4}-\d{2}-\d{2}$/.test(e.added_at || "") && e.added_at > latest) latest = e.added_at;
  }
}
if (latest) {
  const siteFile = path.join(root, "data/site.json");
  const site = JSON.parse(fs.readFileSync(siteFile, "utf8"));
  site.last_updated = latest;
  fs.writeFileSync(siteFile, JSON.stringify(site, null, 2) + "\n");
}
console.log(`stamped build ${id}, last_updated ${latest || "(unchanged)"}`);
