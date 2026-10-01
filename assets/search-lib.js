// 検索式の解析と、Pagefind に渡す形への変換。ブラウザ(assets/app.js)とビルド(scripts/build_site_search.mjs)で
// 同じ実装を共有する。索引と検索語の変換が食い違うと検索できなくなるため、変換はここに1か所だけ置く。
// 設計: docs/decisions/2026-09-30_pagefind_search.md

const CJK_CHAR = "\\u3040-\\u30ff\\u3400-\\u9fff\\uf900-\\ufaff々ー";
const CJK_RUN = new RegExp(`[${CJK_CHAR}]+`, "g");
const SPLIT_RUNS = new RegExp(`[${CJK_CHAR}]+|[^${CJK_CHAR}]+`, "g");
const IS_CJK = new RegExp(`^[${CJK_CHAR}]+$`);
const WORD_CHAR = /[\p{L}\p{N}]/u;

// 全角英数・半角カナなどを正規化する(索引側と検索側で同じ変換を通す)
export const normalise = (text) => String(text ?? "").normalize("NFKC");

// 日本語(かな・カナ・漢字)の連続を、重なる2文字ずつと3文字ずつの語に分けて索引に入れる:
//   胚細胞腫瘍 → 胚細 細胞 胞腫 腫瘍 / 胚細胞 細胞腫 胞腫瘍
// 検索では、2文字の語は2文字語1つ、3文字以上の語は3文字語を全部含む(AND)ものを探す。
// 3文字語のANDは、実データでは部分一致とほぼ同じ結果になる(2文字語のANDだと、離れた位置の語が混ざって誤ヒットが出る)。
// Pagefind の引用符フレーズ検索は、長い文書で取りこぼすことがあるため使わない。
const ngrams = (run, n) =>
  run.length < n ? [] : Array.from({ length: run.length - n + 1 }, (_, i) => run.slice(i, i + n));

export const indexText = (text) =>
  normalise(text).replace(CJK_RUN, (run) =>
    ` ${run.length < 2 ? run : [...ngrams(run, 2), ...ngrams(run, 3)].join(" ")} `);

// 検索語(空白を含まない1語)を、日本語の連続と、それ以外に分ける。
//   BEP療法 → [{kind:"latin", text:"BEP"}, {kind:"cjk", text:"療法"}]
// 英数字を含まない断片(記号だけ)は捨てる。
export function subterms(token) {
  const parts = [];
  for (const piece of normalise(token).match(SPLIT_RUNS) ?? []) {
    if (IS_CJK.test(piece)) parts.push({ kind: "cjk", text: piece });
    else {
      const text = piece.replace(/^["'()]+|["'()]+$/g, "").trim().toLowerCase();
      if (WORD_CHAR.test(text)) parts.push({ kind: "latin", text });
    }
  }
  return parts;
}

// Pagefind に渡す検索語(空白区切り=すべてを含む)。日本語は、2文字なら2文字語、3文字以上なら3文字語の並び。
// 1文字だけの日本語は2文字語が作れないので null(呼び出し側が別の方法で探す)。
export function pagefindQuery(sub) {
  if (sub.kind === "latin") return sub.text;
  if (sub.text.length < 2) return null;
  return (sub.text.length === 2 ? [sub.text] : ngrams(sub.text, 3)).join(" ");
}

// 検索式を解析する。
//   空白(全角可)区切り = AND、OR または | = OR(ANDより強く結びつく)、語頭の - = 除外
//   例: "精巣 OR 卵巣 -腫瘍" → 全部: [[精巣, 卵巣]]、除外: [腫瘍]
export function parseQuery(query) {
  const tokens = normalise(query).replace(/\|/g, " | ").split(/\s+/).filter(Boolean);
  const clauses = [];
  const excludes = [];
  let joinNext = false;
  for (const token of tokens) {
    if (token === "OR" || token === "|") {
      joinNext = clauses.length > 0;
      continue;
    }
    if (token.length > 1 && token.startsWith("-")) {
      const term = token.slice(1);
      if (subterms(term).length) excludes.push(term);
      joinNext = false;
      continue;
    }
    if (!subterms(token).length) continue;
    if (joinNext) clauses[clauses.length - 1].push(token);
    else clauses.push([token]);
    joinNext = false;
  }
  return { clauses, excludes };
}

const intersect = (sets) => {
  const [first, ...rest] = sets;
  return new Set([...first].filter((id) => rest.every((set) => set.has(id))));
};

// 検索式を評価して、該当する論文IDの集合を返す(検索語が無ければ null)。
//   lookup(sub): 1つの断片(subterms の要素)に一致する論文IDの Set を返す(非同期可)
//   allIds: 除外だけの検索式のときの母集団
export async function evaluateQuery(query, lookup, allIds) {
  const { clauses, excludes } = parseQuery(query);
  if (!clauses.length && !excludes.length) return null;

  const tokenSet = async (token) => intersect(await Promise.all(subterms(token).map(lookup)));
  let result;
  if (clauses.length) {
    const clauseSets = await Promise.all(
      clauses.map(async (clause) => {
        const sets = await Promise.all(clause.map(tokenSet));
        return new Set(sets.flatMap((set) => [...set]));
      }),
    );
    result = intersect(clauseSets);
  } else {
    result = new Set(allIds);
  }
  for (const term of excludes) {
    for (const id of await tokenSet(term)) result.delete(id);
  }
  return result;
}

// Pagefind を読み込む(ブラウザ専用)。Pagefind は <html lang> で検索言語を決める。索引は日本語を2文字ずつの語に
// 分けた「英語(空白区切り)」の索引なので、日本語ページ(lang="ja")のまま読み込むと、検索語が日本語として
// 別に分割されて、索引と一致しなくなる。そこで、読み込みと初期化の間だけ lang を en にする。
export async function loadPagefind(url) {
  const root = document.documentElement;
  const original = root.getAttribute("lang");
  root.setAttribute("lang", "en");
  try {
    const pagefind = await import(url);
    await pagefind.init();
    return pagefind;
  } finally {
    if (original === null) root.removeAttribute("lang");
    else root.setAttribute("lang", original);
  }
}
