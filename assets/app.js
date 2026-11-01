(() => {
  "use strict";

  const LANG = document.body.dataset.lang === "en" ? "en" : "ja";
  const DATA_ROOT = document.body.dataset.root || "";

  // 公開タグは、研究デザインの9分類(1論文に1つ)。基礎・トランスレーショナル以外はすべて「臨床」として扱う
  // (docs/decisions/2026-10-12_study_design_taxonomy.md)。フィルタ処理は常に日本語の原値(paper.tags)に対して行い、
  // 表示だけを差し替える。臨床の分類は、エビデンスの強い順に並べる。
  const BASIC = "基礎・トランスレーショナル";
  const CLINICAL = ["SR・MA", "RCT", "非ランダム化試験", "観察研究", "症例報告・集積", "総説", "ガイドライン・コンセンサス", "その他"];
  const designOf = (p) => (p.tags || [])[0] || "";
  const groupOf = (p) => (designOf(p) === BASIC ? "basic" : "clinical");
  const TAG_LABELS_EN = {
    "SR・MA": "SR / MA",
    "RCT": "RCT",
    "非ランダム化試験": "Non-randomized trial",
    "観察研究": "Observational study",
    "症例報告・集積": "Case report / series",
    "総説": "Review",
    "ガイドライン・コンセンサス": "Guideline / consensus",
    "基礎・トランスレーショナル": "Basic / translational",
    "その他": "Other",
  };
  const KUBUN_LABELS = {
    ja: { all: "すべて", clinical: "臨床", basic: "基礎" },
    en: { all: "All", clinical: "Clinical", basic: "Basic" },
  };
  const DESIGN_TEXT = {
    ja: { hintNone: "分類を選ばなければ、臨床の論文すべてを表示します。", hintSome: "選んだ分類のいずれかに当てはまる臨床論文を表示しています。", clear: "選択を解除" },
    en: { hintNone: "With no design selected, all clinical papers are shown.", hintSome: "Showing clinical papers that match any selected design.", clear: "Clear selection" },
  };

  const JIF_LABELS = {
    ja: { low: "IF: 低(<1)", moderate: "IF: 中(1-3)", high: "IF: 高(3-5)", "very-high": "IF: 非常に高(5+)", unknown: "IF: 未確認" },
    en: { low: "IF: low (<1)", moderate: "IF: moderate (1-3)", high: "IF: high (3-5)", "very-high": "IF: very-high (5+)", unknown: "IF: not yet verified" },
  };

  // ソート・絞り込み用の階層順位。tier未設定(旧データ)もunknownと同じ扱いにする
  const JIF_RANK = { "very-high": 4, high: 3, moderate: 2, low: 1, unknown: 0 };
  const jifTierOf = (p) => p.jif_tier || "unknown";
  const jifRank = (p) => JIF_RANK[jifTierOf(p)] ?? 0;

  // 検索方式: 既定は、抄録まで検索できる新方式(Pagefind)。?search=legacy を付けると従来の方式(全件を読み込んで
  // ブラウザ内で部分一致)になる。新方式の検索データ(search/list.json)を読めなかったときも、従来の方式に戻る。
  // 設計: docs/decisions/2026-09-30_pagefind_search.md
  let SEARCH_MODE = new URLSearchParams(location.search).get("search") !== "legacy";
  const pageUrl = (path) => new URL(DATA_ROOT + path, document.baseURI).href;

  const state = {
    papers: [],
    query: "",
    loadingFull: false, // 全件の一覧(list.json)を読み込み中か
    kubun: "all", // all | clinical | basic
    designs: new Set(), // 臨床の中で選んだ研究デザイン(選ばなければ臨床すべて)
    attr: {}, // 属性の絞り込み。項目の短い名前 → 選んだ値の Set(項目の中はOR、項目どうしはAND)
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

  function tagLabel(tag) {
    return LANG === "en" ? (TAG_LABELS_EN[tag] || tag) : tag;
  }

  // 区分(すべて/臨床/基礎)と、臨床のときだけ出す研究デザインの選択。件数は、検索語とIFの絞り込みを反映する
  // (区分と研究デザインの選択は反映しない。選ぶとどれだけ出るかが分かるように)。
  function renderDesignFilters() {
    const counts = new Map();
    let nClinical = 0;
    let nBasic = 0;
    for (const p of state.papers) {
      if (!baseMatches(p)) continue;
      if (groupOf(p) === "basic") nBasic += 1;
      else nClinical += 1;
      const d = designOf(p);
      counts.set(d, (counts.get(d) || 0) + 1);
    }
    const fmt = (n) => n.toLocaleString(LANG === "en" ? "en-US" : "ja-JP");
    const seg = $("kubun-filters");
    seg.innerHTML = "";
    for (const [key, n] of [["all", nClinical + nBasic], ["clinical", nClinical], ["basic", nBasic]]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = key === state.kubun ? "active" : "";
      btn.setAttribute("aria-pressed", String(key === state.kubun));
      btn.innerHTML = `${escapeHtml(KUBUN_LABELS[LANG][key])}<span class="n">${fmt(n)}</span>`;
      btn.addEventListener("click", () => {
        if (state.kubun === key) return;
        state.kubun = key;
        state.designs.clear();
        state.attr = {};
        syncUrl();
        renderList();
      });
      seg.appendChild(btn);
    }
    const showDesigns = state.kubun === "clinical";
    $("design-row").hidden = !showDesigns;
    $("design-hint").hidden = !showDesigns;
    if (!showDesigns) return;
    const box = $("design-filters");
    box.innerHTML = "";
    for (const design of CLINICAL) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tag-filter" + (state.designs.has(design) ? " active" : "");
      btn.setAttribute("aria-pressed", String(state.designs.has(design)));
      btn.innerHTML = `${escapeHtml(tagLabel(design))}<span class="n">${fmt(counts.get(design) || 0)}</span>`;
      btn.addEventListener("click", () => {
        state.designs.has(design) ? state.designs.delete(design) : state.designs.add(design);
        syncUrl();
        renderList();
      });
      box.appendChild(btn);
    }
    const clear = $("design-clear");
    clear.hidden = state.designs.size === 0;
    clear.textContent = DESIGN_TEXT[LANG].clear;
    $("design-hint").textContent = state.designs.size ? DESIGN_TEXT[LANG].hintSome : DESIGN_TEXT[LANG].hintNone;
  }

  // 区分・研究デザイン・属性の選択をURLに入れる(?kubun=clinical&design=RCT,観察研究&f_si=testis)。結果を人に渡せる。他のURLの指定(?search=legacy)は残す。
  function syncUrl() {
    const params = new URLSearchParams(location.search);
    params.delete("kubun");
    params.delete("design");
    for (const key of [...params.keys()]) if (key.startsWith("f_")) params.delete(key);
    if (state.kubun !== "all") params.set("kubun", state.kubun);
    if (state.kubun === "clinical" && state.designs.size) params.set("design", [...state.designs].join(","));
    for (const f of activeFacets()) {
      const sel = state.attr[f.key];
      if (sel && sel.size) params.set(`f_${f.key}`, [...sel].join(","));
    }
    const query = params.toString();
    history.replaceState(null, "", location.pathname + (query ? `?${query}` : "") + location.hash);
  }

  function readUrlSelection() {
    const params = new URLSearchParams(location.search);
    const kubun = params.get("kubun");
    if (kubun === "clinical" || kubun === "basic") state.kubun = kubun;
    if (state.kubun === "clinical") {
      for (const d of (params.get("design") || "").split(",")) if (CLINICAL.includes(d)) state.designs.add(d);
      for (const f of activeFacets()) {
        const values = (params.get(`f_${f.key}`) || "").split(",").filter((v) => f.values[v]);
        if (values.length) state.attr[f.key] = new Set(values);
      }
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

  // ---- 属性の絞り込み(臨床のみ) ----
  // 項目と表示名は assets/attr-labels.js。論文の属性は paper.attrs(scripts/sync_site_attributes.py が入れる)
  let ATTR = null;
  const T = {
    ja: { title: "属性で絞り込み", reset: "すべて解除", open: "絞り込み", close: "結果を見る", specific: "に固有の項目",
      hint: "「不明」は選択肢に出しません。抄録に書かれていない論文は、その項目を選ぶと除かれます。", themes: "テーマ" },
    en: { title: "Filter by attributes", reset: "Clear all", open: "Filters", close: "Show results", specific: " specific",
      hint: "\"Unknown\" is not offered. Papers whose abstract does not state an attribute are excluded when you pick that attribute.", themes: "Themes" },
  }[LANG];
  const attrValues = (p, key) => {
    const v = p.attrs && p.attrs[key];
    return v === undefined ? [] : Array.isArray(v) ? v : [v];
  };
  const activeFacets = () => (ATTR && state.kubun === "clinical" ? [...ATTR.FACETS, ...ATTR.specificFacets(state.designs)] : []);
  const facetLabel = (f) => (LANG === "en" ? f.en : f.ja);
  const valueLabel = (f, v) => (f.values[v] ? f.values[v][LANG === "en" ? 1 : 0] : v);
  // 選択中の項目のうち、論文が満たさない項目の名前(skip の項目は見ない)
  const failedFacets = (p, facets) => facets.filter((f) => {
    const sel = state.attr[f.key];
    return sel && sel.size > 0 && !attrValues(p, f.key).some((v) => sel.has(v));
  });
  function attrMatches(p) {
    const facets = activeFacets();
    return facets.length === 0 || failedFacets(p, facets).length === 0;
  }
  function pruneAttrSelection() {
    const keys = new Set(activeFacets().map((f) => f.key));
    for (const key of Object.keys(state.attr)) if (!keys.has(key)) delete state.attr[key];
  }
  const selectedCount = () => Object.values(state.attr).reduce((n, set) => n + set.size, 0);

  function renderAttrPanel() {
    const panel = $("attr-panel");
    const facets = activeFacets();
    panel.hidden = facets.length === 0;
    $("attr-open-row").hidden = facets.length === 0;
    if (facets.length === 0) return;
    // 件数: ほかの条件(検索語・IF・区分・デザイン・他の項目の選択)を満たす論文のうち、その値を持つ数
    const counts = new Map(facets.map((f) => [f.key, new Map()]));
    const bump = (key, p) => { const m = counts.get(key); for (const v of attrValues(p, key)) m.set(v, (m.get(v) || 0) + 1); };
    for (const p of state.papers) {
      if (!(designMatches(p) && baseMatches(p))) continue;
      const failed = failedFacets(p, facets);
      if (failed.length === 0) for (const f of facets) bump(f.key, p);
      else if (failed.length === 1) bump(failed[0].key, p);
    }
    const fmt = (n) => n.toLocaleString(LANG === "en" ? "en-US" : "ja-JP");
    const build = (facet, alwaysOpen = false) => {
      const sel = state.attr[facet.key] || new Set();
      const d = document.createElement("details");
      d.className = "attr-facet";
      d.open = alwaysOpen || Boolean(facet.open) || sel.size > 0;
      d.dataset.facet = facet.id;
      d.innerHTML = `<summary>${escapeHtml(facetLabel(facet))}</summary><div class="attr-chips"></div>`;
      const chips = d.querySelector(".attr-chips");
      for (const value of Object.keys(facet.values)) {
        const n = counts.get(facet.key).get(value) || 0;
        if (n === 0 && !sel.has(value)) continue;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tag-filter" + (sel.has(value) ? " active" : "");
        btn.setAttribute("aria-pressed", String(sel.has(value)));
        btn.dataset.value = value;
        btn.innerHTML = `${escapeHtml(valueLabel(facet, value))}<span class="n">${fmt(n)}</span>`;
        btn.addEventListener("click", () => {
          const set = state.attr[facet.key] || (state.attr[facet.key] = new Set());
          set.has(value) ? set.delete(value) : set.add(value);
          syncUrl();
          renderList();
        });
        chips.appendChild(btn);
      }
      return d;
    };
    const keep = new Set([...panel.querySelectorAll("details[open]")].map((d) => d.dataset.facet));
    const common = $("attr-facets");
    const specific = $("attr-specific");
    common.innerHTML = "";
    specific.innerHTML = "";
    for (const f of ATTR.FACETS) common.appendChild(build(f));
    const spec = ATTR.specificFacets(state.designs);
    if (spec.length) {
      const title = document.createElement("p");
      title.className = "attr-specific-title";
      title.textContent = `${[...state.designs].map(tagLabel).join(" / ")}${T.specific}`;
      specific.appendChild(title);
      for (const f of spec) specific.appendChild(build(f, true));
    }
    for (const d of panel.querySelectorAll("details")) if (keep.has(d.dataset.facet)) d.open = true;
    // 選択中の条件(×で外せる)
    const active = $("attr-active");
    active.innerHTML = "";
    for (const f of facets) {
      for (const value of state.attr[f.key] || []) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tag-filter active";
        btn.textContent = `${facetLabel(f)}: ${valueLabel(f, value)} ×`;
        btn.addEventListener("click", () => {
          state.attr[f.key].delete(value);
          syncUrl();
          renderList();
        });
        active.appendChild(btn);
      }
    }
    $("attr-reset").hidden = selectedCount() === 0;
    $("attr-badge").textContent = selectedCount() ? `(${selectedCount()})` : "";
  }

  const haystacks = new WeakMap();

  // 区分・研究デザインの選択に合うか
  function designMatches(paper) {
    if (state.kubun === "all") return true;
    if (groupOf(paper) !== state.kubun) return false;
    return state.kubun !== "clinical" || state.designs.size === 0 || state.designs.has(designOf(paper));
  }

  function matches(paper) {
    return designMatches(paper) && baseMatches(paper) && attrMatches(paper);
  }

  // 検索語とIFの絞り込みに合うか
  function baseMatches(paper) {
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

  // カードに出す属性: 部位・組織型・性別・年齢区分・病期・IGCCCG・例数、臨床テーマ。結果の数値は出さない
  function attrTags(p) {
    if (!ATTR || !p.attrs || groupOf(p) !== "clinical") return "";
    const a = p.attrs;
    const label = (key, value) => {
      const f = ATTR.FACETS.find((x) => x.key === key);
      return f ? valueLabel(f, value) : value;
    };
    const parts = [];
    if (a.si) parts.push(label("si", a.si));
    for (const h of a.hi || []) parts.push(label("hi", h));
    if (a.sx) parts.push(label("sx", a.sx));
    if (a.ag) parts.push(label("ag", a.ag));
    if (a.sg && ATTR.STAGE_LABEL[a.sg]) parts.push(ATTR.STAGE_LABEL[a.sg][LANG === "en" ? 1 : 0]);
    if (a.ig && ATTR.IGCCCG_LABEL[a.ig]) parts.push(ATTR.IGCCCG_LABEL[a.ig][LANG === "en" ? 1 : 0]);
    if (a.n) parts.push(`n = ${a.n.toLocaleString(LANG === "en" ? "en-US" : "ja-JP")}`);
    const themes = (a.th || []).map((v) => label("th", v));
    if (!parts.length && !themes.length) return "";
    return `<div class="paper-attrs">${parts.map((x) => `<span class="paper-attr">${escapeHtml(x)}</span>`).join("")}</div>`
      + (themes.length ? `<p class="paper-themes">${escapeHtml(T.themes)}: ${escapeHtml(themes.join(" · "))}</p>` : "");
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
      .map((t) => `<span class="paper-tag${t === BASIC ? " paper-tag-basic" : ""}">${escapeHtml(KUBUN_LABELS[LANG][t === BASIC ? "basic" : "clinical"])} › ${escapeHtml(tagLabel(t))}</span>`)
      .join("");

    // 要約: 表示言語側を優先し、無ければ他言語、どちらも無ければ「準備中」を明示する
    // (要約が存在するのに表示していないと誤解されないようにするため、単純に非表示にはしない)
    const summary = LANG === "en" ? (p.summary_en || p.summary_ja) : (p.summary_ja || p.summary_en);
    const summaryPending = LANG === "en" ? "Summary: not yet available" : "要約: 準備中";
    // 要約・著者・DOI は、一覧の核とは別に(details)裏で読み込む。届くまでは「読み込み中」を出す
    const waiting = SEARCH_MODE && p._d !== true;
    const summaryHtml = waiting
      ? `<p class="paper-summary paper-summary-pending" data-part="summary">${LANG === "en" ? "Loading summary…" : "要約を読み込み中…"}</p>`
      : summary
        ? `<p class="paper-summary" data-part="summary">${escapeHtml(summary)}</p>`
        : `<p class="paper-summary paper-summary-pending" data-part="summary">${escapeHtml(summaryPending)}</p>`;

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
      <article class="paper-card" data-card-id="${escapeHtml(p.id)}">
        <h2>${escapeHtml(mainTitle)}</h2>
        ${subTitle}
        ${metaParts.length ? `<p class="paper-meta" data-part="meta">${escapeHtml(metaParts.join(" · "))}</p>` : ""}
        ${summaryHtml}
        ${abstractHtml}
        ${tags ? `<div class="paper-tags">${tags}</div>` : ""}
        ${attrTags(p)}
        ${links.length ? `<div class="paper-links" data-part="links">${links.join("")}</div>` : ""}
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
  async function substringIds(text) {
    await detailsPromise; // 要約・著者は details にあるので、全部届いてから探す
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
      const found = await lib.searchWord(pagefind, sub);
      if (found === null) return substringIds(sub.text); // 1文字の日本語
      return new Set(found.results.map((r) => idmap[r.id]).filter(Boolean));
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
    pruneAttrSelection();
    renderDesignFilters();
    renderAttrPanel();
    shown = sortPapers(state.papers.filter(matches));
    shownCount = Math.min(PAGE_SIZE, shown.length);
    $("paper-list").innerHTML = shown.slice(0, shownCount).map(paperCard).join("");
    $("empty-message").hidden = shown.length > 0;
    $("result-count").textContent = LANG === "en"
      ? `${shown.length} of ${state.papers.length} results`
      : `${shown.length}件 / 全${state.papers.length}件`;
    renderMoreButton();
  }

  // 全件が届く前の最初の表示: 先頭のカードだけを描く(絞り込み・件数の欄は触らない)
  function renderListOnly() {
    shown = state.papers;
    shownCount = Math.min(PAGE_SIZE, shown.length);
    $("paper-list").innerHTML = shown.slice(0, shownCount).map(paperCard).join("");
    $("empty-message").hidden = true;
    renderMoreButton();
    $("load-more").hidden = true;
  }

  function renderMore() {
    const next = Math.min(shownCount + PAGE_SIZE, shown.length);
    $("paper-list").insertAdjacentHTML("beforeend", shown.slice(shownCount, next).map(paperCard).join(""));
    shownCount = next;
    renderMoreButton();
  }

  // 新方式の画面部品(検索の説明・抄録の遅延読み込み)。検索データを読み込めてから有効にする
  function enableSearchUi() {
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

  async function loadLegacyPapers() {
    // 検索データが使えないときの従来方式: 年代別に分けた文献データを全部読んで連結する
    const index = await loadJson("data/papers/index.json");
    const parts = await Promise.all(index.shards.map((name) => loadJson("data/papers/" + name)));
    return parts.flat();
  }

  // 最初の表示を速くするため、新方式では次の順に読む(設計: docs/decisions/2026-11-01_split_list_data.md)
  //  1. search/head.json … 先頭の100件(要約・著者つき)。すぐにカードを出す
  //  2. search/list.json … 全件の核(題名・年・タグ・属性など)。届くと絞り込み・検索・並び替えが使える
  //  3. search/details/<n>.json … 要約・著者・DOI。裏で順に読み、届いたカードから埋める
  const visible = (p) => p.relevance_status !== "excluded";
  const byId = new Map();
  let detailsPromise = Promise.resolve();

  function refreshCard(p) {
    const old = document.querySelector(`[data-card-id="${CSS.escape(p.id)}"]`);
    if (!old) return;
    const fresh = document.createElement("template");
    fresh.innerHTML = paperCard(p);
    for (const part of ["meta", "summary", "links"]) {
      const next = fresh.content.querySelector(`[data-part="${part}"]`);
      const prev = old.querySelector(`[data-part="${part}"]`);
      if (next && prev) {
        prev.replaceWith(next);
      } else if (next) {
        // 核だけでは無かった部分(著者・DOIが無かったカード)が、届いて初めて出る
        if (part === "meta") (old.querySelector(".paper-title-sub") || old.querySelector("h2")).after(next);
        else old.appendChild(next);
      }
    }
  }

  function applyDetails(chunk) {
    for (const [id, detail] of Object.entries(chunk)) {
      const p = byId.get(id);
      if (!p) continue;
      Object.assign(p, detail);
      p._d = true;
      refreshCard(p);
    }
  }

  function loadDetails(head) {
    const chunks = Array.from({ length: head.detail_chunks }, (_, n) => n);
    // 先頭から順に(新しい論文のカードが先に埋まる)。2つずつ並べて読む
    detailsPromise = (async () => {
      const queue = [...chunks];
      const worker = async () => {
        for (let n = queue.shift(); n !== undefined; n = queue.shift()) {
          try {
            applyDetails(await loadJson(`search/details/${n}.json`));
          } catch (err) {
            console.error(err);
          }
        }
      };
      await Promise.all([worker(), worker()]);
    })();
    return detailsPromise;
  }

  function setLoadingFull(flag, shownCount, total) {
    state.loadingFull = flag;
    document.body.classList.toggle("loading-full", flag);
    $("sort-select").disabled = flag;
    if (flag) {
      $("result-count").textContent = LANG === "en"
        ? `Showing the latest ${shownCount}. Loading all ${total.toLocaleString("en-US")} papers…`
        : `新しい順に${shownCount}件を表示中。全${total.toLocaleString("ja-JP")}件を読み込み中…`;
    }
  }

  async function init() {
    $("search-box").addEventListener("input", (e) => {
      state.query = e.target.value.trim();
      if (state.loadingFull) return; // 全件が届いたら、入力済みの検索語で検索する
      if (SEARCH_MODE) scheduleSearch();
      else renderList();
    });
    $("load-more").addEventListener("click", renderMore);
    $("sort-select").addEventListener("change", (e) => {
      state.sort = e.target.value;
      renderList();
    });

    try {
      ATTR = await import(pageUrl("assets/attr-labels.js"));
      readUrlSelection();
      // 絞り込みのURLを直接開いたときは、先頭の100件では足りないので、全件を待つ
      const hasSelection = state.kubun !== "all" || selectedCount() > 0;
      const siteLoad = loadJson("data/site.json");
      let head = null;
      let listLoad = null;
      if (SEARCH_MODE) {
        listLoad = loadJson("search/list.json");
        if (!hasSelection) head = await loadJson("search/head.json").catch(() => null);
      }
      applySiteInfo(await siteLoad);
      if (SEARCH_MODE) enableSearchUi();
      if (head) {
        // 1. 先頭の100件をすぐに出す(全件が届くまで、絞り込み・並び替え・検索は使えない)
        state.papers = head.papers.map((p) => ({ ...p, _d: true }));
        setLoadingFull(true, state.papers.length, head.total);
        renderListOnly();
        $("result-count").textContent = LANG === "en"
          ? `Showing the latest ${state.papers.length}. Loading all ${head.total.toLocaleString("en-US")} papers…`
          : `新しい順に${state.papers.length}件を表示中。全${head.total.toLocaleString("ja-JP")}件を読み込み中…`;
      }
      let papers;
      try {
        papers = SEARCH_MODE ? await listLoad : await loadLegacyPapers();
      } catch (err) {
        if (!SEARCH_MODE) throw err;
        console.error(err);
        SEARCH_MODE = false; // 検索データが無い・読めない: 従来の方式で表示する
        $("search-hint").hidden = true;
        papers = await loadLegacyPapers();
      }
      // relevance_status: "excluded" の文献のみ一覧から除外する。未設定/"kept"/"needs_review"は
      // すべて表示する(人間が明示的に除外と判断するまでは隠さない方針)
      const all = Array.isArray(papers) ? papers : [];
      const headById = new Map((head ? head.papers : []).map((p) => [p.id, p]));
      state.papers = all.filter(visible).map((p) => (headById.has(p.id) ? { ...p, ...headById.get(p.id), _d: true } : p));
      for (const p of state.papers) byId.set(p.id, p);
      setLoadingFull(false, 0, 0);
      $("attr-reset").addEventListener("click", () => {
        state.attr = {};
        syncUrl();
        renderList();
      });
      $("attr-open").addEventListener("click", () => $("attr-panel").classList.add("open"));
      $("attr-close").addEventListener("click", () => $("attr-panel").classList.remove("open"));
      $("design-clear").addEventListener("click", () => {
        state.designs.clear();
        state.attr = {};
        syncUrl();
        renderList();
      });
      renderJifFilters();
      if (SEARCH_MODE && state.query) scheduleSearch();
      else renderList();
      if (SEARCH_MODE) {
        const meta = head || (await loadJson("search/head.json").catch(() => null));
        if (meta) loadDetails(meta);
      }
    } catch (err) {
      console.error(err);
      $("error-message").hidden = false;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
