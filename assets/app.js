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

  // ソート用の階層順位。tier未設定(旧データ)もunknownと同じ扱いにする
  const JIF_RANK = { "very-high": 4, high: 3, moderate: 2, low: 1, unknown: 0 };
  const jifRank = (p) => JIF_RANK[p.jif_tier] ?? 0;

  const state = {
    papers: [],
    query: "",
    activeTags: new Set(),
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

  function matches(paper) {
    if (state.activeTags.size > 0) {
      const tags = paper.tags || [];
      for (const t of state.activeTags) {
        if (!tags.includes(t)) return false;
      }
    }
    if (!state.query) return true;
    const q = state.query.toLowerCase();
    const haystack = [
      paper.title, paper.title_ja, paper.journal,
      paper.summary_en, paper.summary_ja, paper.abstract, paper.abstract_ja,
      ...(paper.authors || []), ...(paper.tags || []),
      String(paper.year || ""), paper.pmid, paper.doi,
    ].filter(Boolean).join(" ").toLowerCase();
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
    if (LANG === "en") {
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

  function renderList() {
    const filtered = sortPapers(state.papers.filter(matches));
    $("paper-list").innerHTML = filtered.map(paperCard).join("");
    $("empty-message").hidden = filtered.length > 0;
    $("result-count").textContent = LANG === "en"
      ? `${filtered.length} of ${state.papers.length} results`
      : `${filtered.length}件 / 全${state.papers.length}件`;
  }

  async function init() {
    $("search-box").addEventListener("input", (e) => {
      state.query = e.target.value.trim();
      renderList();
    });
    $("sort-select").addEventListener("change", (e) => {
      state.sort = e.target.value;
      renderList();
    });

    try {
      const [site, papers] = await Promise.all([
        loadJson("data/site.json"),
        loadJson("data/papers.json"),
      ]);
      applySiteInfo(site);
      state.papers = Array.isArray(papers) ? papers : [];
      renderTagFilters();
      renderList();
    } catch (err) {
      console.error(err);
      $("error-message").hidden = false;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
