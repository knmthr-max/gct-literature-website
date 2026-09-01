(() => {
  "use strict";

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
    const res = await fetch(path, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res.json();
  }

  function applySiteInfo(site) {
    if (site.title_ja || site.title) {
      const t = site.title_ja || site.title;
      document.title = t;
      $("site-title").textContent = t;
      $("footer-title").textContent = t;
    }
    if (site.description) $("site-description").textContent = site.description;
    if (site.notice) {
      $("site-notice").textContent = site.notice;
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

  function renderTagFilters() {
    const box = $("tag-filters");
    box.innerHTML = "";
    for (const tag of collectTags(state.papers)) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tag-filter" + (state.activeTags.has(tag) ? " active" : "");
      btn.textContent = tag;
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
      paper.title, paper.title_ja, paper.journal, paper.summary,
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
    } else {
      s.sort((a, b) => (b.year || 0) - (a.year || 0));
    }
    return s;
  }

  function paperCard(p) {
    const links = [];
    if (p.pmid) links.push(`<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(p.pmid)}/" target="_blank" rel="noopener">PubMed</a>`);
    if (p.doi) links.push(`<a href="https://doi.org/${encodeURIComponent(p.doi)}" target="_blank" rel="noopener">DOI</a>`);
    if (p.url) links.push(`<a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">リンク</a>`);

    const mainTitle = p.title_ja || p.title || "(無題)";
    const subTitle = p.title_ja && p.title ? `<p class="paper-title-sub">${escapeHtml(p.title)}</p>` : "";
    const metaParts = [
      (p.authors || []).join(", "),
      p.journal,
      p.year ? `${p.year}年` : "",
    ].filter(Boolean);
    const tags = (p.tags || [])
      .map((t) => `<span class="paper-tag">${escapeHtml(t)}</span>`)
      .join("");

    return `
      <article class="paper-card">
        <h2>${escapeHtml(mainTitle)}</h2>
        ${subTitle}
        ${metaParts.length ? `<p class="paper-meta">${escapeHtml(metaParts.join(" · "))}</p>` : ""}
        ${p.summary ? `<p class="paper-summary">${escapeHtml(p.summary)}</p>` : ""}
        ${tags ? `<div class="paper-tags">${tags}</div>` : ""}
        ${links.length ? `<div class="paper-links">${links.join("")}</div>` : ""}
      </article>`;
  }

  function renderList() {
    const filtered = sortPapers(state.papers.filter(matches));
    $("paper-list").innerHTML = filtered.map(paperCard).join("");
    $("empty-message").hidden = filtered.length > 0;
    $("result-count").textContent = `${filtered.length}件 / 全${state.papers.length}件`;
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
