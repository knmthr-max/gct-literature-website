(() => {
  "use strict";

  const LANG = document.body.dataset.lang === "en" ? "en" : "ja";
  const DATA_ROOT = document.body.dataset.root || "";

  // 公開タグ(症例報告/臨床研究/基礎研究/総説/ガイドライン/論説/レター)の英語表示ラベル。
  // フィルタ処理は常にこの日本語の原値(paper.tags)に対して行い、表示だけを差し替える。
  const TAG_LABELS_EN = {
    "症例報告": "Case Report",
    "臨床研究": "Clinical Study",
    "基礎研究": "Basic Research",
    "総説": "Review",
    "ガイドライン": "Guideline",
    "論説": "Editorial",
    "レター": "Letter",
  };

  const JIF_LABELS = {
    ja: { low: "IF: 低(<1)", moderate: "IF: 中(1-3)", high: "IF: 高(3-5)", "very-high": "IF: 非常に高(5+)", unknown: "IF: 未確認" },
    en: { low: "IF: low (<1)", moderate: "IF: moderate (1-3)", high: "IF: high (3-5)", "very-high": "IF: very-high (5+)", unknown: "IF: not yet verified" },
  };

  // ソート・絞り込み用の階層順位。tier未設定(旧データ)もunknownと同じ扱いにする
  const JIF_RANK = { "very-high": 4, high: 3, moderate: 2, low: 1, unknown: 0 };
  const jifTierOf = (p) => p.jif_tier || "unknown";
  const jifRank = (p) => JIF_RANK[jifTierOf(p)] ?? 0;

  // 検索方式: ?search=pagefind のときだけ、抄録まで検索できる新方式(Pagefind)を使う。
  // 設計: docs/decisions/2026-09-30_pagefind_search.md
  const SEARCH_MODE = new URLSearchParams(location.search).get("search") === "pagefind";
  const pageUrl = (path) => new URL(DATA_ROOT + path, document.baseURI).href;

  const state = {
    papers: [],
    query: "",
    activeTags: new Set(),
    activeJifTiers: new Set(),
    sort: "year-desc",
  };

  const $ = (id) => document.getElementById(id);

  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));

  async function loadJson(path) {
    const res = await fetch(DATA_ROOT + path, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res.json();
  }

  function applySiteInfo(site) {
    const title = LANG === "en" ? (site.title || site.title_ja) : (site.title_ja || site.title);
    const description = LANG === "en" ? (site.description || site.description_ja) : (site.description_ja || site.description);
    const notice = LANG === "en" ? (site.notice || site.notice_ja) : (site.notice_ja || site.notice);
    if (title) {
      document.title = title;
      $("site-title").textContent = title;
      $("footer-title").textContent = title;
    }
    if (description) $("site-description").textContent = description;
    if (notice) {
      $("site-notice").textContent = notice;
      $("site-notice").hidden = false;
    }
    if (site.last_updated) $("last-updated").textContent = site.last_updated;
  }

  function collectTags(papers) {
    const counts = new Map();
    for (const p of papers) {
      for (const t of p.tags || []) {
        counts.set(t, (counts.get(t) || 0) + 1);
      }
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
  }

  function tagLabel(tag) {
    return LANG === "en" ? (TAG_LABELS_EN[tag] || tag) : tag;
  }

  function renderTagFilters() {
    const box = $("tag-filters");
    box.innerHTML = "";
    for (const tag of collectTags(state.papers)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tag-filter" + (state.activeTags.has(tag) ? " active" : "");
      btn.textContent = tagLabel(tag);
      btn.addEventListener("click", () => {
        state.activeTags.has(tag) ? state.activeTags.delete(tag) : state.activeTags.add(tag);
        renderTagFilters();
        renderList();
      });
      box.appendChild(btn);
    }
  }

  function collectJifTiers(papers) {
    const present = new Set(papers.map(jifTierOf));
    return Object.keys(JIF_RANK)
      .sort((a, b) => JIF_RANK[b] - JIF_RANK[a])
      .filter((tier) => present.has(tier));
  }

  function renderJifFilters() {
    const box = $("jif-filters");
    if (!box) return;
    box.innerHTML = "";
    for (const tier of collectJifTiers(state.papers)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tag-filter" + (state.activeJifTiers.has(tier) ? " active" : "");
      btn.textContent = (JIF_LABELS[LANG] || {})[tier] || tier;
      btn.addEventListener("click", () => {
        state.activeJifTiers.has(tier) ? state.activeJifTiers.delete(tier) : state.activeJifTiers.add(tier);
        renderJifFilters();
        renderList();
      });
      box.appendChild(btn);
    }
  }

  const haystacks = new WeakMap();

  function matches(paper) {
    if (state.activeTags.size > 0) {
      const tags = paper.tags || [];
      for (const t of state.activeTags) {
        if (!tags.includes(t)) return false;
      }
    }
    if (state.activeJifTiers.size > 0 && !state.activeJifTiers.has(jifTierOf(paper))) {
      return false;
    }
    if (SEARCH_MODE) return hitIds === null || hitIds.has(paper.id);
    if (!state.query) return true;
    const q = state.query.toLowerCase();
    // 検索対象の文字列は論文ごとに1度だけ作る(入力のたびに全件分を作り直さない)
    let haystack = haystacks.get(paper);
    if (haystack === undefined) {
      haystack = [
        paper.title, paper.title_ja, paper.journal,
        paper.summary_en, paper.summary_ja, paper.abstract, paper.abstract_ja,
        ...(paper.authors || []), ...(paper.tags || []),
        String(paper.year || ""), paper.pmid, paper.doi,
      ].filter(Boolean).join(" ").toLowerCase();
      haystacks.set(paper, haystack);
    }
    return haystack.includes(q);
  }

  function sortPapers(list) {
    const s = [...list];
    if (state.sort === "year-asc") {
      s.sort((a, b) => (a.year || 0) - (b.year || 0));
    } else if (state.sort === "added-desc") {
      s.sort((a, b) => String(b.added_at || "").localeCompare(String(a.added_at || "")));
    } else if (state.sort === "jif-desc") {
      s.sort((a, b) => jifRank(b) - jifRank(a));
    } else if (state.sort === "jif-asc") {
      s.sort((a, b) => jifRank(a) - jifRank(b));
    } else {
      s.sort((a, b) => (b.year || 0) - (a.year || 0));
    }
    return s;
  }

  function paperCard(p) {
    const links = [];
    if (p.pmid) links.push(`<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(p.pmid)}/" target="_blank" rel="noopener">PubMed</a>`);
    if (p.doi) links.push(`<a href="https://doi.org/${encodeURIComponent(p.doi)}" target="_blank" rel="noopener">DOI</a>`);
    if (p.url) links.push(`<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">${LANG === "en" ? "Link" : "リンク"}</a>`);

    const mainTitle = LANG === "en" ? (p.title || p.title_ja || "(untitled)") : (p.title_ja || p.title || "(無題)");
    const subTitle = LANG === "ja" && p.title_ja && p.title ? `<p class="paper-title-sub">${escapeHtml(p.title)}</p>` : "";
    const metaParts = [
      (p.authors || []).join(", "),
      p.journal,
      p.year ? (LANG === "en" ? `${p.year}` : `${p.year}年`) : "",
      (JIF_LABELS[LANG] || {})[p.jif_tier] || "",
    ].filter(Boolean);
    const tags = (p.tags || [])
      .map((t) => `<span class="paper-tag">${escapeHtml(tagLabel(t))}</span>`)
      .join("");

    // 要約: 表示言語側を優先し、無ければ他言語、どちらも無ければ「準備中」を明示する
    // (要約が存在するのに表示していないと誤解されないようにするため、単純に非表示にはしない)
    const summary = LANG === "en" ? (p.summary_en || p.summary_ja) : (p.summary_ja || p.summary_en);
    const summaryPending = LANG === "en" ? "Summary: not yet available" : "要約: 準備中";
    const summaryHtml = summary
      ? `<p class="paper-summary">${escapeHtml(summary)}</p>`
      : `<p class="paper-summary paper-summary-pending">${escapeHtml(summaryPending)}</p>`;

    // 抄録: 収載文献は基本的に英語が原文のため、日本語ページでも英語原文を常に参照できるようにする。
    // 日本語訳(abstract_ja)がある場合は「抄録」に訳文を表示しつつ、「抄録原文(英語)」で原文も別途提示する。
    // 訳がまだ無い場合は、これまでどおり「抄録(英語)」に原文だけを表示する
    let abstractHtml = "";
    if (SEARCH_MODE) {
      // 新方式の一覧には抄録の本文が無い。開いたときに search/abstract/<id>.json から読む
      const lazy = (field, label) =>
        `<details class="paper-abstract" data-abstract-id="${escapeHtml(p.id)}" data-abstract-field="${field}"><summary>${label}</summary><p></p></details>`;
      if (LANG === "en") {
        if (p.has_abstract) abstractHtml = lazy("abstract", "Abstract");
      } else if (p.has_abstract_ja) {
        abstractHtml = lazy("abstract_ja", "抄録") + (p.has_abstract ? lazy("abstract", "抄録原文(英語)") : "");
      } else if (p.has_abstract) {
        abstractHtml = lazy("abstract", "抄録(英語)");
      }
    } else if (LANG === "en") {
      if (p.abstract) {
        abstractHtml = `<details class="paper-abstract"><summary>Abstract</summary><p>${escapeHtml(p.abstract)}</p></details>`;
      }
    } else if (p.abstract_ja) {
      abstractHtml = `<details class="paper-abstract"><summary>抄録</summary><p>${escapeHtml(p.abstract_ja)}</p></details>`;
      if (p.abstract) {
        abstractHtml += `<details class="paper-abstract"><summary>抄録原文(英語)</summary><p>${escapeHtml(p.abstract)}</p></details>`;
      }
    } else if (p.abstract) {
      abstractHtml = `<details class="paper-abstract"><summary>抄録(英語)</summary><p>${escapeHtml(p.abstract)}</p></details>`;
    }

    return `
      <article class="paper-card">
        <h2>${escapeHtml(mainTitle)}</h2>
        ${subTitle}
        ${metaParts.length ? `<p class="paper-meta">${escapeHtml(metaParts.join(" · "))}</p>` : ""}
        ${summaryHtml}
        ${abstractHtml}
        ${tags ? `<div class="paper-tags">${tags}</div>` : ""}
        ${links.length ? `<div class="paper-links">${links.join("")}</div>` : ""}
      </article>`;
  }

  // ---- 新方式の検索(SEARCH_MODE) ----
  // Pagefind は「語 → 該当する論文ID」の引き当てにだけ使い、絞り込み・並び替え・ページ分けは一覧(list.json)で行う
  let hitIds = null; // null = 検索語なし
  let searchSeq = 0;
  let searchTimer = null;
  let enginePromise = null;
  const abstractCache = new Map();

  function loadEngine() {
    if (!enginePromise) {
      enginePromise = Promise.all([
        import(pageUrl("assets/search-lib.js")).then(async (lib) => ({ lib, pagefind: await lib.loadPagefind(pageUrl("pagefind/pagefind.js")) })),
        loadJson("search/idmap.json"),
      ]).then(([{ lib, pagefind }, idmap]) => ({ lib, pagefind, idmap }));
      enginePromise.catch(() => { enginePromise = null; });
    }
    return enginePromise;
  }

  // 一覧の範囲(タイトル・要約・著者・雑誌)での部分一致。1文字の日本語と、Pagefind を読めなかったときに使う
  function substringIds(text) {
    const needle = text.toLowerCase();
    return new Set(state.papers.filter((p) => [
      p.title, p.title_ja, p.journal, p.summary_en, p.summary_ja, ...(p.authors || []), ...(p.tags || []),
    ].filter(Boolean).join(" ").toLowerCase().includes(needle)).map((p) => p.id));
  }

  async function searchIds(query) {
    const allIds = state.papers.map((p) => p.id);
    let engine;
    try {
      engine = await loadEngine();
    } catch (err) {
      console.error(err);
      const lib = await import(pageUrl("assets/search-lib.js"));
      $("search-notice").hidden = false;
      return lib.evaluateQuery(query, async (sub) => substringIds(sub.text), allIds);
    }
    $("search-notice").hidden = true;
    const { lib, pagefind, idmap } = engine;
    const lookup = async (sub) => {
      const q = lib.pagefindQuery(sub);
      if (q === null) return substringIds(sub.text); // 1文字の日本語
      const { results } = await pagefind.search(q);
      return new Set(results.map((r) => idmap[r.id]).filter(Boolean));
    };
    return lib.evaluateQuery(query, lookup, allIds);
  }

  async function runSearch() {
    const seq = ++searchSeq;
    let ids = null;
    if (state.query) {
      try {
        ids = await searchIds(state.query);
      } catch (err) {
        console.error(err);
        ids = null;
      }
    }
    if (seq !== searchSeq) return; // 入力が進んだ後の古い結果は捨てる
    hitIds = ids;
    renderList();
  }

  function scheduleSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, state.query ? 150 : 0);
  }

  function loadAbstract(details) {
    const id = details.dataset.abstractId;
    const field = details.dataset.abstractField;
    const target = details.querySelector("p");
    if (!id || target.dataset.loaded) return;
    target.dataset.loaded = "1";
    target.textContent = LANG === "en" ? "Loading…" : "読み込み中…";
    if (!abstractCache.has(id)) abstractCache.set(id, loadJson(`search/abstract/${encodeURIComponent(id)}.json`));
    abstractCache.get(id).then((data) => {
      target.textContent = data[field] || "";
    }).catch((err) => {
      console.error(err);
      delete target.dataset.loaded;
      target.textContent = LANG === "en" ? "Could not load the abstract." : "抄録を読み込めませんでした。";
    });
  }

  // 一覧は PAGE_SIZE 件ずつ描画し、「もっと見る」で追加する(件数が増えても描画コストを一定に保つ)。
  // 絞り込み・並び替え・検索が変わると先頭から描き直し、「もっと見る」では続きだけを追記する
  // (追記なので、開いている抄録の状態は保たれる)
  const PAGE_SIZE = 50;
  let shown = [];
  let shownCount = 0;

  function renderMoreButton() {
    const remaining = shown.length - shownCount;
    const btn = $("load-more");
    btn.hidden = remaining <= 0;
    btn.textContent = LANG === "en"
      ? `Show more (${remaining} remaining)`
      : `もっと見る(残り${remaining}件)`;
  }

  function renderList() {
    shown = sortPapers(state.papers.filter(matches));
    shownCount = Math.min(PAGE_SIZE, shown.length);
    $("paper-list").innerHTML = shown.slice(0, shownCount).map(paperCard).join("");
    $("empty-message").hidden = shown.length > 0;
    $("result-count").textContent = LANG === "en"
      ? `${shown.length} of ${state.papers.length} results`
      : `${shown.length}件 / 全${state.papers.length}件`;
    renderMoreButton();
  }

  function renderMore() {
    const next = Math.min(shownCount + PAGE_SIZE, shown.length);
    $("paper-list").insertAdjacentHTML("beforeend", shown.slice(shownCount, next).map(paperCard).join(""));
    shownCount = next;
    renderMoreButton();
  }

  async function init() {
    $("search-box").addEventListener("input", (e) => {
      state.query = e.target.value.trim();
      if (SEARCH_MODE) scheduleSearch();
      else renderList();
    });
    if (SEARCH_MODE) {
      $("search-hint").hidden = false;
      $("search-box").placeholder = LANG === "en"
        ? "Search title, authors, summary, abstract…"
        : "タイトル・著者・要約・抄録で検索…";
      $("search-box").addEventListener("focus", () => loadEngine().catch(() => {}), { once: true });
      // toggle は伝播しないので、捕捉(capture)で受ける
      $("paper-list").addEventListener("toggle", (e) => {
        if (e.target.matches("details[data-abstract-id]") && e.target.open) loadAbstract(e.target);
      }, true);
    }
    $("load-more").addEventListener("click", renderMore);
    $("sort-select").addEventListener("change", (e) => {
      state.sort = e.target.value;
      renderList();
    });

    try {
      const [site, papers] = await Promise.all([
        loadJson("data/site.json"),
        loadJson(SEARCH_MODE ? "search/list.json" : "data/papers.json"),
      ]);
      applySiteInfo(site);
      // relevance_status: "excluded" の文献のみ一覧から除外する。未設定/"kept"/"needs_review"は
      // すべて表示する(人間が明示的に除外と判断するまでは隠さない方針)
      const all = Array.isArray(papers) ? papers : [];
      state.papers = all.filter((p) => p.relevance_status !== "excluded");
      renderTagFilters();
      renderJifFilters();
      renderList();
    } catch (err) {
      console.error(err);
      $("error-message").hidden = false;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
