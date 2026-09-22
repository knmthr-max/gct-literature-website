#!/usr/bin/env python3
"""Build a static TSV-backed public site and an SSO-ready JIF portal shell."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

__version__ = "3.0.0"

PUBLIC_FIELDS = (
    "pmid", "publication_date", "publication_year", "title", "summary_ja", "summary_en",
    "first_author", "journal_abbrev", "journal_title", "type", "subtype",
    "mesh_terms", "author_keywords", "added_at",
)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as source:
        return [dict(row) for row in csv.DictReader(source, delimiter="\t")]


def write_tsv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(
            destination, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def json_values(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return [value] if value else []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def latest_update(rows: Sequence[Mapping[str, str]]) -> str:
    dates = [row.get("added_at", "")[:10] for row in rows if row.get("added_at", "")]
    return max(dates) if dates else "未登録"


def public_row(row: Mapping[str, str]) -> dict[str, str]:
    return {field: row.get(field, "") for field in PUBLIC_FIELDS}


STYLE = r"""
:root{color-scheme:light;--ink:#17202a;--muted:#5d6d7e;--line:#d6dde5;--accent:#1f5d8f;--soft:#edf5fb}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,"Noto Sans JP",sans-serif;color:var(--ink);margin:0;background:#f7f9fb}
header{background:linear-gradient(135deg,#143d59,#1f6f8b);color:white;padding:28px max(20px,calc((100% - 1160px)/2))}
header h1{margin:0 0 8px}.updated{opacity:.9}main{max-width:1160px;margin:auto;padding:22px}
.controls{display:grid;grid-template-columns:minmax(220px,1fr) repeat(3,auto);gap:10px;background:white;border:1px solid var(--line);padding:14px;border-radius:12px;position:sticky;top:0;z-index:2}
input,select,button{font:inherit;border:1px solid #aeb9c5;border-radius:7px;padding:9px 11px;background:white}button{cursor:pointer}.status{color:var(--muted);margin:14px 2px}
.card{background:white;border:1px solid var(--line);border-radius:12px;padding:17px;margin:12px 0;box-shadow:0 2px 8px #1232}.card h2{font-size:1.12rem;margin:0 0 8px}.meta{color:var(--muted)}.tags{display:flex;gap:6px;flex-wrap:wrap}.tag{background:var(--soft);border-radius:999px;padding:3px 9px;font-size:.84rem}
.summary{line-height:1.65}.jif-panel{background:#fff6da;border:1px solid #dec56b;border-radius:10px;padding:12px;margin-bottom:14px}.hidden{display:none!important}
@media(max-width:720px){.controls{grid-template-columns:1fr 1fr}.controls input{grid-column:1/-1}}
"""

APP = r"""
const state={index:[],manifest:[],rows:new Map(),lang:'ja',jif:new Map(),privateMode:false};
function parseTSV(text){const rows=[];let row=[],cell='',quoted=false;for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}else if(c==='\t'&&!quoted){row.push(cell);cell='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);cell='';if(row.some(v=>v!==''))rows.push(row);row=[];}else cell+=c;}if(cell||row.length){row.push(cell);rows.push(row);}if(!rows.length)return[];const head=rows.shift();return rows.map(r=>Object.fromEntries(head.map((h,i)=>[h,r[i]??''])));}
async function fetchTSV(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok)throw new Error(`${response.status} ${path}`);return parseTSV(await response.text());}
function searchText(item){return [item.t,item.a,item.j,item.y,item.k,item.c,item.s,item.p].join(' ').toLocaleLowerCase();}
async function loadChunk(file){if(state.rows.has(file))return state.rows.get(file);const rows=await fetchTSV(file);const map=new Map(rows.map(r=>[r.pmid,r]));state.rows.set(file,map);return map;}
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function summary(row){return state.lang==='ja'?(row.summary_ja||'要約なし'):(row.summary_en||'No summary available.');}
function jifBlock(pmid){if(!state.privateMode)return'';const j=state.jif.get(pmid);if(!j)return'<p><strong>JIF:</strong> 参照不可</p>';return `<p><strong>JIF:</strong> ${esc(j.jif||'参照不可')} <span class="tag">${esc(j.if_tier||'unknown')}</span> <small>${esc(j.jif_data_year||'')} ${esc(j.jif_source||'')}</small></p>`;}
function card(row){const journal=row.journal_title||row.journal_abbrev||'Unknown journal';return `<article class="card"><h2>${esc(row.title||'Untitled')}</h2><p class="meta">${esc(row.first_author)} · ${esc(journal)} · ${esc(row.publication_year)}</p><div class="tags"><span class="tag">${esc(row.type)}</span><span class="tag">${esc(row.subtype)}</span></div><p class="summary">${esc(summary(row))}</p>${jifBlock(row.pmid)}<p><a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(row.pmid)}/" target="_blank" rel="noopener">PMID: ${esc(row.pmid)}</a></p></article>`;}
async function render(items){const target=document.querySelector('#results');target.innerHTML='';for(const item of items.slice(0,100)){const chunk=await loadChunk(item.f);const row=chunk.get(item.p);if(row)target.insertAdjacentHTML('beforeend',card(row));}document.querySelector('#resultStatus').textContent=`${items.length.toLocaleString()}件（最大100件表示）`;}
function filtered(){const q=document.querySelector('#query').value.trim().toLocaleLowerCase();const year=document.querySelector('#year').value;const type=document.querySelector('#type').value;return state.index.filter(item=>(!q||searchText(item).includes(q))&&(!year||item.y===year)&&(!type||item.c===type));}
function update(){render(filtered());}
async function loadJif(){if(!state.privateMode)return;const status=document.querySelector('#jifStatus');try{const rows=await fetchTSV('data/common_jif.tsv');state.jif=new Map(rows.map(r=>[r.pmid,r]));status.textContent=`JIFデータ参照可能：${rows.length.toLocaleString()}件`;update();}catch{status.textContent='JIFデータ：参照不可（共通JIF TSVは未配置）';}}
function localJif(event){const file=event.target.files[0];if(!file)return;const reader=new FileReader();reader.onload=()=>{const rows=parseTSV(reader.result);state.jif=new Map(rows.map(r=>[r.pmid,r]));document.querySelector('#jifStatus').textContent=`ローカルJIFデータ：${rows.length.toLocaleString()}件（サーバーには送信されません）`;update();};reader.readAsText(file,'UTF-8');}
async function init(){state.privateMode=document.body.dataset.private==='true';state.manifest=await fetchTSV(state.privateMode?'../data/manifest.tsv':'data/manifest.tsv');const indexPath=state.privateMode?'../data/search_index.json':'data/search_index.json';state.index=await (await fetch(indexPath,{cache:'no-store'})).json();if(state.privateMode)state.index=state.index.map(item=>({...item,f:'../'+item.f}));const years=[...new Set(state.index.map(x=>x.y).filter(Boolean))].sort().reverse();document.querySelector('#year').innerHTML='<option value="">All years</option>'+years.map(y=>`<option>${esc(y)}</option>`).join('');document.querySelector('#updated').textContent=state.manifest[0]?.latest_update||'未登録';['query','year','type'].forEach(id=>document.querySelector('#'+id).addEventListener(id==='query'?'input':'change',update));document.querySelector('#language').addEventListener('click',()=>{state.lang=state.lang==='ja'?'en':'ja';document.querySelector('#language').textContent=state.lang==='ja'?'English':'日本語';update();});if(state.privateMode){document.querySelector('#localJif').addEventListener('change',localJif);await loadJif();}update();}
init().catch(error=>{document.querySelector('#resultStatus').textContent=`読み込みエラー: ${error.message}`;});
"""


def page(private: bool = False) -> str:
    prefix = "../" if private else ""
    private_panel = """
<section class="jif-panel"><strong id="jifStatus">JIFデータ：確認中</strong><br>
<label>ローカルJIF TSVを一時参照: <input id="localJif" type="file" accept=".tsv,text/tab-separated-values"></label>
<p><small>選択したファイルはブラウザ内だけで処理され、サーバーへ送信されません。</small></p></section>""" if private else ""
    title = "GCT Literature — Collaborator Portal" if private else "GCT Literature"
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><link rel="stylesheet" href="{prefix}assets/style.css"></head>
<body data-private="{'true' if private else 'false'}"><header><h1>{title}</h1><div class="updated">文献データ最終更新日: <span id="updated">読込中</span></div></header><main>{private_panel}
<section class="controls"><input id="query" type="search" placeholder="Title, author, journal, Keyword, PMID"><select id="year"></select><select id="type"><option value="">All types</option><option>Clinical</option><option>Basic</option><option>Review</option><option>Unclassified</option></select><button id="language" type="button">English</button></section>
<p id="resultStatus" class="status">読込中</p><section id="results"></section></main><script src="{prefix}assets/app.js"></script></body></html>"""


def build_site(master_path: Path, output_dir: Path) -> tuple[int, int]:
    rows = read_tsv(master_path)
    approved = [row for row in rows if row.get("review_status", "approved") == "approved"]
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    assets_dir = output_dir / "assets"
    sso_dir = output_dir / "sso-jif"
    (sso_dir / "data").mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    by_year: dict[str, list[dict[str, str]]] = {}
    for row in approved:
        year = row.get("publication_year", "unknown") or "unknown"
        by_year.setdefault(year, []).append(public_row(row))

    search_index = []
    manifest_rows = []
    updated = latest_update(approved)
    for year, year_rows in sorted(by_year.items(), reverse=True):
        filename = f"literature_{year}.tsv"
        write_tsv(data_dir / filename, year_rows, PUBLIC_FIELDS)
        manifest_rows.append({"latest_update": updated, "year": year, "file": filename, "count": len(year_rows)})
        for row in year_rows:
            keywords = json_values(row.get("mesh_terms", "")) + json_values(row.get("author_keywords", ""))
            search_index.append({
                "p": row.get("pmid", ""), "t": row.get("title", ""), "a": row.get("first_author", ""),
                "j": row.get("journal_title", "") or row.get("journal_abbrev", ""), "y": year,
                "k": " | ".join(dict.fromkeys(keywords)), "c": row.get("type", ""),
                "s": row.get("subtype", ""), "f": f"data/{filename}",
            })
    write_tsv(data_dir / "manifest.tsv", manifest_rows or [{"latest_update": updated, "year": "", "file": "", "count": 0}], ("latest_update", "year", "file", "count"))
    (data_dir / "search_index.json").write_text(json.dumps(search_index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (assets_dir / "style.css").write_text(STYLE.strip() + "\n", encoding="utf-8")
    (assets_dir / "app.js").write_text(APP.strip() + "\n", encoding="utf-8")
    (output_dir / "index.html").write_text(page(False), encoding="utf-8")
    (sso_dir / "index.html").write_text(page(True), encoding="utf-8")
    (sso_dir / ".htaccess.template").write_text(
        "# Generate the official UMIN SSO directives for approved UMIN IDs.\n"
        "# Do not upload this portal until the template is replaced by .htaccess.\n",
        encoding="utf-8",
    )
    (sso_dir / "data" / "JIF_NOT_UPLOADED.txt").write_text(
        "The common JIF TSV is intentionally absent. The portal displays 参照不可.\n",
        encoding="utf-8",
    )
    deployment_rows = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == "deployment_manifest.tsv":
            continue
        relative = path.relative_to(output_dir).as_posix()
        sso = relative.startswith("sso-jif/")
        deployment_rows.append({
            "local_path": relative,
            "target_scope": "umin_sso" if sso else "public",
            "upload_allowed": "no_until_sso_configured" if sso else "yes",
            "contains_exact_jif": "no",
        })
    write_tsv(output_dir / "deployment_manifest.tsv", deployment_rows, ("local_path", "target_scope", "upload_allowed", "contains_exact_jif"))
    return len(by_year), len(approved)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("master", type=Path, help="Approved versioned master TSV")
    result.add_argument("--output-dir", type=Path, default=Path("site/build"))
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return result


def main() -> None:
    args = parser().parse_args()
    year_count, article_count = build_site(args.master, args.output_dir)
    print(f"Completed: {args.output_dir} ({year_count} year files, {article_count} articles)")


if __name__ == "__main__":
    main()
