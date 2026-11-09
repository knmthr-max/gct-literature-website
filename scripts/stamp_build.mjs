// デプロイ時に、画面(HTML)へ「ビルドの識別子」を入れる(作業用のコピーだけを書き換える。コミットしない)。
//
//   node scripts/stamp_build.mjs [サイトのルート(既定: .)]
//
// 1. <script src=".../app.js"> と <link href=".../style.css"> に ?v=<識別子> を付ける
//    (ブラウザが古い app.js を使い続けて、新しいデータ形式と食い違うのを防ぐ)
// 2. <meta name="build-id" content="<識別子>"> を入れる。画面は、search/head.json の build と比べ、
//    食い違えば「サイトが更新されました。再読み込みしてください」と出す(assets/app.js)
// 識別子は、scripts/build_site_search.mjs が search/build.json に書いたもの。
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
console.log(`stamped build ${id}`);
