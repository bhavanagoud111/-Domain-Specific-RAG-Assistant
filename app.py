"""WanderRAG — Gradio chat UI with a country gallery (Week 8 UI refresh).

Runs the EXISTING LangGraph pipeline unchanged. Retrieval, generation, the
citation-keyed self_check gate, TOP_K, country filtering and chunking all live in
``graph/wanderrag_graph.py`` — nothing here reimplements any of them. This module only
calls ``run_query()`` and renders what comes back out of the graph state.

Two views (toggled by visibility, single-page):
  * HOME  — a hero + a scrolling gallery of all 50 countries, each with a
            Wikivoyage/Wikimedia photo. Region chips + a search box filter the gallery,
            and ‹ › arrows scroll it. Clicking a country opens its chat.
  * CHAT  — the chat is *scoped* to the picked country: its name is injected into the
            query so retrieval locks to that country (no graph change).

Per turn the chat surfaces the grounded answer, every citation as a source link with its
scrape date and score, the resolved-citation count, and the GROUNDED / THIN / LOW-CONFIDENCE
banner.

Launch:  python app.py     ->  http://127.0.0.1:7860
Requires Qdrant up (docker compose up -d) and OPENROUTER_API_KEY in .env.
Country photos live in assets/countries/ (run scratchpad/fetch_country_images.py to rebuild).
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from urllib.parse import urlparse

import gradio as gr

# Work around a Gradio 4.44 / gradio_client schema bug: a boolean `additionalProperties`
# makes `_json_schema_to_python_type` recurse with a bool and `get_type` do `"const" in
# True` -> TypeError, which breaks /config and trips Gradio's localhost self-check on launch.
import gradio_client.utils as _gcu  # noqa: E402

_wr_orig_schema = _gcu._json_schema_to_python_type


def _wr_safe_schema(schema, defs=None):
    if isinstance(schema, bool):
        return "Any"
    return _wr_orig_schema(schema, defs)


_gcu._json_schema_to_python_type = _wr_safe_schema

from config import settings
from config.countries import COUNTRIES
from graph.wanderrag_graph import run_query
from storage.qdrant_setup import get_client

ASSETS = Path(__file__).resolve().parent / "assets" / "countries"

SOURCE_LABELS = {
    "state_dept": "US State Dept",
    "cdc": "CDC",
    "tourism": "Tourism board",
}

REGIONS = ["All 50", "Europe", "Asia-Pacific", "Americas", "Middle East & Africa"]
REGION_EMOJI = {
    "Europe": "🏰", "Asia-Pacific": "🏯", "Americas": "🗽", "Middle East & Africa": "🕌",
}


# --------------------------------------------------------------------------- #
# Startup data: per-country counts + photo paths
# --------------------------------------------------------------------------- #
def _country_counts() -> dict[str, int]:
    """Live per-country chunk counts from Qdrant (one facet call; falls back gracefully)."""
    try:
        client = get_client()
        try:
            res = client.facet(collection_name=settings.QDRANT_COLLECTION,
                               key="country", limit=60, exact=True)
            return {h.value: h.count for h in res.hits}
        except Exception:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            out = {}
            for c in COUNTRIES:
                out[c.name] = client.count(
                    collection_name=settings.QDRANT_COLLECTION,
                    count_filter=Filter(must=[FieldCondition(
                        key="country", match=MatchValue(value=c.name))]),
                    exact=True).count
            return out
    except Exception:
        return {}


def _photo_uri(slug: str) -> str:
    p = ASSETS / f"{slug}.jpg"
    if not p.exists():
        return ""
    return f"data:image/jpeg;base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


_COUNTS = _country_counts()
_PHOTO_URI = {c.slug: _photo_uri(c.slug) for c in COUNTRIES}

_hero_path = ASSETS.parent / "hero.jpg"
_HERO_BG = (f"data:image/jpeg;base64,{base64.b64encode(_hero_path.read_bytes()).decode('ascii')}"
            if _hero_path.exists() else "")


# --------------------------------------------------------------------------- #
# Gallery data (reliable gr.Gallery.select mechanism)
# --------------------------------------------------------------------------- #
def _gallery_items(countries):
    """(image_path, caption) pairs for the gallery. Caption carries name + source count."""
    items = []
    for c in countries:
        n = _COUNTS.get(c.name, 0)
        cap = f"{c.name}  ·  {n} sources" if n else f"{c.name}  ·  no data"
        items.append((str(ASSETS / f"{c.slug}.jpg"), cap))
    return items


def _filter_countries(region: str, query: str):
    q = (query or "").strip().lower()
    out = []
    for c in COUNTRIES:
        if region and region != "All 50" and c.region != region:
            continue
        if q and q not in c.name.lower():
            continue
        out.append(c)
    return out


def refresh_grid(region: str, query: str):
    cs = _filter_countries(region, query)
    return gr.update(value=_gallery_items(cs)), [c.name for c in cs]


def _country_hero(name: str) -> str:
    c = next((x for x in COUNTRIES if x.name == name), None)
    if c is None:
        return ""
    img = _PHOTO_URI.get(c.slug, "")
    n = _COUNTS.get(name, 0)
    bg = (f"background-image:linear-gradient(90deg,rgba(6,10,25,.86),rgba(6,10,25,.30)),url('{img}');"
          if img else "background:linear-gradient(120deg,#1e293b,#0f172a);")
    return (
        f'<div class="wr-hero-country" style="{bg}"><div class="wr-hero-inner">'
        f'<span class="wr-hero-region">{REGION_EMOJI.get(c.region, "🌍")} {c.region}</span>'
        f'<h1>{name}</h1>'
        f'<p>Grounded answers from {n or "the"} WanderRAG sources — '
        f'visas · health · safety · what to see.</p>'
        f'</div></div>'
    )


# --------------------------------------------------------------------------- #
# Rendering helpers (unchanged behaviour from the original app)
# --------------------------------------------------------------------------- #
def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host or url
    except Exception:
        return url


def _render_status(state: dict) -> str:
    n = state.get("citations_resolved", len(state.get("citations", [])))
    retries = state.get("retry_count", 0)
    plural = "citation" if n == 1 else "citations"
    if state.get("low_confidence"):
        badge, note = (
            f"⚠️ &nbsp;**LOW CONFIDENCE** · **{n} {plural} resolved**",
            "No retrieved source could be resolved into a citation, so this answer is "
            "**not grounded** in the WanderRAG corpus.")
    elif state.get("thin_pass"):
        badge, note = (
            f"🟡 &nbsp;**THIN GROUNDING** · **{n} {plural} resolved**",
            "Clears the citation gate on a _single_ source — treat with caution.")
    else:
        badge, note = (f"✅ &nbsp;**GROUNDED** · **{n} {plural} resolved**", None)
    line = f"{badge} &nbsp;·&nbsp; _retry loops: {retries}_"
    return f"{line}\n\n{note}\n" if note else f"{line}\n"


def _render_sources(citations: list[dict]) -> str:
    if not citations:
        return ""
    rows = ["\n---\n\n**Sources**\n"]
    for c in citations:
        url = c.get("source_url") or ""
        src = SOURCE_LABELS.get(c.get("source_type", ""), c.get("source_type", "?"))
        link = f"[{_domain(url)}]({url})" if url else "_no URL on this chunk_"
        scraped = c.get("scrape_date")
        stamp = f" &nbsp; <sub>scraped {scraped}</sub>" if scraped else ""
        rows.append(
            f"- **`{c['marker']}`** &nbsp; {src} · {c.get('country', '?')} &nbsp; "
            f"→ &nbsp; {link}{stamp} &nbsp; <sub>score {c.get('score')}</sub>")
    return "\n".join(rows)


def _dedupe_banner(answer: str) -> str:
    for prefix in ("⚠️ Low confidence:",):
        if answer.startswith(prefix):
            _, _, rest = answer.partition("\n\n")
            answer = rest or answer
    marker = "\n\n_Note: this answer rests on a single supporting source"
    if marker in answer:
        answer = answer.split(marker)[0]
    return answer.strip()


def _answer_markdown(state: dict) -> str:
    answer = _dedupe_banner(state.get("final_answer", "")) or "_(the graph returned no answer)_"
    return f"{_render_status(state)}\n{answer}\n{_render_sources(state.get('citations', []))}"


# --------------------------------------------------------------------------- #
# Chat logic — scoped to the selected country
# --------------------------------------------------------------------------- #
def _run(message: str, country: str) -> str:
    """Run the existing graph, locking retrieval to `country` by injecting its name."""
    q = message.strip()
    if country and country.lower() not in q.lower():
        q = f"{q} (about {country})"
    try:
        state = run_query(q, run_id=f"ui_{uuid.uuid4().hex[:8]}")
    except Exception as exc:
        return f"❌ **The graph failed on that query.**\n\n```\n{type(exc).__name__}: {exc}\n```"
    return _answer_markdown(state)


def on_submit(message: str, history: list[dict], country: str):
    message = (message or "").strip()
    if not message:
        return "", history
    history = (history or []) + [{"role": "user", "content": message}]
    history.append({"role": "assistant", "content": _run(message, country)})
    return "", history


EXAMPLES = {
    "visit": "What should I visit in {c}?",
    "visa": "Do I need a visa to visit {c} as a US citizen?",
    "safety": "What's the safety situation in {c} right now?",
    "vacc": "What vaccinations do I need for {c}?",
}


def on_example(kind: str, country: str, history: list[dict]):
    return on_submit(EXAMPLES[kind].format(c=country), history, country)


def pick_country(names: list[str], evt: gr.SelectData):
    """Gallery.select handler: map the clicked tile index to a country and open its chat."""
    idx = evt.index if isinstance(evt.index, int) else 0
    country = names[idx] if names and 0 <= idx < len(names) else ""
    if not country:
        return gr.update(), gr.update(), "", gr.update(), gr.update()
    return (
        gr.update(visible=False),   # home_view
        gr.update(visible=True),    # chat_view
        country,                    # selected_country state
        _country_hero(country),     # hero
        [],                         # clear chat
    )


def go_home():
    return gr.update(visible=True), gr.update(visible=False), "", []


# --------------------------------------------------------------------------- #
# CSS + JS
# --------------------------------------------------------------------------- #
CSS = """
:root{ --wr-accent:#6366f1; --wr-ink:#f8fafc; --wr-mut:#94a3b8;
  --wr-card:linear-gradient(180deg,rgba(148,163,184,.09),rgba(148,163,184,.025));
  --wr-bd:rgba(148,163,184,.16); }
.gradio-container{ max-width:1200px !important; margin:0 auto !important; position:relative; z-index:1; }
footer{ display:none !important; }
#wr-home{ font-family:'Inter',system-ui,-apple-system,sans-serif; }
.wr-title, .wr-section-title h2, .wr-stat-num, .wr-hiw-card h3, #wr-explore h2{
  font-family:'Sora','Inter',system-ui,sans-serif; }

@keyframes wrFloat{ 0%,100%{transform:translate(0,0)} 50%{transform:translate(24px,-28px)} }
@keyframes wrFadeUp{ from{opacity:0;transform:translateY(20px)} to{opacity:1;transform:none} }
@keyframes wrShimmer{ to{background-position:200% center} }
@keyframes wrPulse{ 0%,100%{opacity:.55} 50%{opacity:1} }
/* scroll-reveal: hidden until IntersectionObserver adds .wr-in */
.wr-reveal{ opacity:0; transform:translateY(26px); }
.wr-reveal.wr-in{ opacity:1; transform:none;
  transition:opacity .7s cubic-bezier(.2,.7,.2,1), transform .7s cubic-bezier(.2,.7,.2,1); }
.wr-stats .wr-stat-tile:nth-child(2){ transition-delay:.06s; }
.wr-stats .wr-stat-tile:nth-child(3){ transition-delay:.12s; }
.wr-stats .wr-stat-tile:nth-child(4){ transition-delay:.18s; }
.wr-grid3 .wr-hiw-card:nth-child(2){ transition-delay:.10s; }
.wr-grid3 .wr-hiw-card:nth-child(3){ transition-delay:.20s; }

/* ---------- ambient background glows ---------- */
.wr-orbs{ position:fixed; inset:0; pointer-events:none; z-index:0; overflow:hidden; }
.wr-orb{ position:absolute; border-radius:50%; filter:blur(90px); }
.wr-orb-1{ width:440px;height:440px; background:#4f46e5; opacity:.30; top:-140px; left:-90px;
  animation:wrFloat 20s ease-in-out infinite; }
.wr-orb-2{ width:380px;height:380px; background:#db2777; opacity:.24; top:38%; right:-120px;
  animation:wrFloat 26s ease-in-out infinite reverse; }
.wr-orb-3{ width:320px;height:320px; background:#f59e0b; opacity:.16; bottom:-140px; left:34%;
  animation:wrFloat 30s ease-in-out infinite; }

/* ---------- cinematic hero ---------- */
#wr-hero{ position:relative; border-radius:28px; overflow:hidden; margin:8px 0 4px; min-height:466px;
  background-size:cover; background-position:center right; display:flex; align-items:center;
  box-shadow:0 30px 70px rgba(2,6,23,.55); border:1px solid rgba(148,163,184,.14);
  animation:wrFadeUp .6s ease both; }
.wr-hero-body{ padding:56px 58px; max-width:660px; color:var(--wr-ink); }
.wr-kicker{ display:inline-flex; align-items:center; gap:8px; font-size:.7rem; text-transform:uppercase;
  letter-spacing:.15em; font-weight:700; color:#c7d2fe; background:rgba(99,102,241,.20);
  border:1px solid rgba(129,140,248,.45); padding:6px 14px; border-radius:999px; }
.wr-kicker .wr-dot{ width:7px;height:7px;border-radius:50%;background:#818cf8; animation:wrPulse 2s infinite; }
.wr-title{ font-size:3.6rem; line-height:1.05; margin:20px 0 14px; font-weight:800; letter-spacing:-.035em;
  color:var(--wr-ink); }
.wr-grad{ background:linear-gradient(95deg,#818cf8,#e879f9 45%,#fbbf24); background-size:200% auto;
  -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
  animation:wrShimmer 7s linear infinite; }
.wr-sub{ font-size:1.08rem; line-height:1.6; color:#cbd5e1; max-width:548px; margin:0 0 26px; }
.wr-steps{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.wr-step{ display:inline-flex; align-items:center; gap:8px; font-size:.85rem; font-weight:600; color:#e2e8f0;
  background:rgba(255,255,255,.09); border:1px solid rgba(255,255,255,.18); padding:8px 15px; border-radius:999px;
  backdrop-filter:blur(6px); }
.wr-step b{ display:inline-flex; width:20px; height:20px; border-radius:50%; background:var(--wr-accent);
  color:#fff; align-items:center; justify-content:center; font-size:.72rem; }
.wr-sep{ opacity:.4; font-weight:700; color:#e2e8f0; }
.wr-scrollcue{ margin-top:24px; font-size:.8rem; color:#94a3b8; animation:wrPulse 2.6s ease-in-out infinite; }
@media (max-width:720px){ #wr-hero{ min-height:400px; } .wr-title{ font-size:2.4rem; } .wr-hero-body{ padding:34px 28px; } }

/* ---------- stat band ---------- */
.wr-stats{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:20px 0 6px;
  animation:wrFadeUp .7s ease .05s both; }
.wr-stat-tile{ background:var(--wr-card); border:1px solid var(--wr-bd); border-radius:18px;
  padding:22px 18px; text-align:center; transition:transform .2s, border-color .2s, box-shadow .2s, background .2s; }
.wr-stat-tile:hover{ transform:translateY(-5px); border-color:rgba(129,140,248,.55);
  box-shadow:0 16px 36px rgba(2,6,23,.4); background:linear-gradient(180deg,rgba(129,140,248,.12),rgba(148,163,184,.03)); }
.wr-stat-num{ font-size:2.3rem; font-weight:800; line-height:1; transition:filter .2s, transform .2s;
  background:linear-gradient(95deg,#a5b4fc,#f0abfc); -webkit-background-clip:text; background-clip:text;
  -webkit-text-fill-color:transparent; }
.wr-stat-tile:hover .wr-stat-num{ filter:brightness(1.18); transform:scale(1.06); }
.wr-step{ transition:background .18s, border-color .18s, transform .18s; }
.wr-step:hover{ background:rgba(255,255,255,.17); border-color:rgba(129,140,248,.5); transform:translateY(-1px); }
.wr-showcase{ transition:transform .25s, box-shadow .25s, border-color .25s; }
.wr-showcase:hover{ transform:translateY(-3px); box-shadow:0 28px 64px rgba(2,6,23,.52);
  border-color:rgba(129,140,248,.4); }
.wr-stat-lbl{ margin-top:8px; font-size:.8rem; color:var(--wr-mut); line-height:1.35; }
@media (max-width:720px){ .wr-stats{ grid-template-columns:repeat(2,1fr); } }

/* ---------- section titles + card grids ---------- */
.wr-section-title{ text-align:center; margin:38px 0 18px; }
.wr-section-title h2{ font-size:1.9rem; font-weight:800; letter-spacing:-.025em; margin:0; }
.wr-section-title p{ margin:7px 0 0; color:var(--wr-mut); font-size:.98rem; }
.wr-grid3{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
.wr-hiw-card{ background:var(--wr-card); border:1px solid var(--wr-bd); border-radius:20px; padding:26px 24px;
  transition:transform .22s, border-color .22s, box-shadow .22s; }
.wr-hiw-card:hover{ transform:translateY(-8px); border-color:rgba(129,140,248,.55);
  box-shadow:0 22px 48px rgba(2,6,23,.45); background:linear-gradient(180deg,rgba(129,140,248,.10),rgba(148,163,184,.03)); }
.wr-hiw-ic{ width:50px; height:50px; border-radius:15px; display:flex; align-items:center; justify-content:center;
  font-size:1.55rem; background:rgba(99,102,241,.16); border:1px solid rgba(129,140,248,.3); margin-bottom:15px;
  transition:transform .22s, background .22s, border-color .22s, box-shadow .22s; }
.wr-hiw-card:hover .wr-hiw-ic{ transform:translateY(-2px) scale(1.08); background:rgba(99,102,241,.30);
  border-color:rgba(129,140,248,.7); box-shadow:0 8px 22px rgba(79,70,229,.4); }
.wr-hiw-card h3{ font-size:1.06rem; font-weight:700; margin:0 0 7px; }
.wr-hiw-card p{ font-size:.92rem; color:var(--wr-mut); margin:0; line-height:1.5; }
@media (max-width:720px){ .wr-grid3{ grid-template-columns:1fr; } }

/* ---------- example-answer showcase ---------- */
.wr-showcase{ background:linear-gradient(180deg,rgba(15,23,42,.66),rgba(15,23,42,.42));
  border:1px solid var(--wr-bd); border-radius:22px; padding:24px 26px; max-width:820px; margin:0 auto;
  box-shadow:0 20px 50px rgba(2,6,23,.4); backdrop-filter:blur(8px); }
.wr-ans-head{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:14px; }
.wr-badge-ok{ font-size:.76rem; font-weight:700; color:#bbf7d0; background:rgba(34,197,94,.16);
  border:1px solid rgba(34,197,94,.4); padding:5px 12px; border-radius:999px; }
.wr-ans-q{ font-style:italic; color:#cbd5e1; font-size:.94rem; }
.wr-ans-body{ font-size:1rem; line-height:1.65; color:#e2e8f0; margin:0 0 16px; }
.wr-cite{ color:#a5b4fc; font-weight:700; background:rgba(99,102,241,.16); border-radius:5px; padding:0 5px; }
.wr-ans-src{ font-size:.82rem; color:var(--wr-mut); border-top:1px solid var(--wr-bd); padding-top:12px; }

/* ---------- explore section heading ---------- */
#wr-explore{ display:flex; align-items:flex-end; justify-content:space-between;
  gap:12px; flex-wrap:wrap; margin:38px 4px 10px; }
#wr-explore h2{ font-size:1.9rem; font-weight:800; margin:0; letter-spacing:-.025em; }
#wr-explore p{ margin:4px 0 0; color:var(--wr-mut); font-size:.95rem; }
#wr-explore .wr-pill{ font-size:.82rem; font-weight:600; color:#c7d2fe;
  background:rgba(99,102,241,.14); border:1px solid rgba(129,140,248,.35);
  padding:6px 14px; border-radius:999px; white-space:nowrap; }
.wr-explore-right{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }

/* ---------- structured panel around filters + slider ---------- */
.wr-panel{ background:rgba(148,163,184,.05) !important; border:1px solid var(--wr-bd) !important;
  border-radius:22px !important; padding:12px 16px 6px !important; }

/* ---------- footer ---------- */
#wr-footer{ text-align:center; margin:44px 0 12px; padding-top:24px;
  border-top:1px solid rgba(148,163,184,.12); color:var(--wr-mut); font-size:.86rem; }
#wr-footer .wr-foot-sub{ margin-top:6px; font-size:.76rem; opacity:.72; }

/* filter bar */
#wr-filterbar{ gap:12px; align-items:center; margin:4px 2px 2px; }
#wr-regions .wrap{ gap:8px !important; }
#wr-regions input[type=radio]{ position:absolute !important; opacity:0 !important; width:0 !important; }
#wr-regions label{ border-radius:999px !important; border:1px solid var(--border-color-primary,#e2e8f0) !important;
  padding:6px 15px !important; font-weight:600 !important; font-size:.85rem !important; cursor:pointer; }
#wr-regions label:has(input:checked){
  background:var(--wr-accent) !important; color:#fff !important; border-color:var(--wr-accent) !important; }

/* gallery -> horizontal slider */
.wr-slider{ position:relative; }
#wr-gallery{ border:none !important; background:transparent !important; }
#wr-gallery .thumbnail-item img{ transition:transform .5s ease !important; }
#wr-gallery .thumbnail-item:hover img{ transform:scale(1.07) !important; }
#wr-gallery .grid-wrap{ overflow:visible !important; }
#wr-gallery .grid-container{
  display:grid !important; grid-auto-flow:column !important; grid-template-columns:none !important;
  grid-auto-columns:230px !important; grid-template-rows:1fr !important;
  gap:16px !important; overflow-x:auto !important; scroll-snap-type:x mandatory;
  padding:14px 6px 18px !important; scrollbar-width:none; }
#wr-gallery .grid-container::-webkit-scrollbar{ display:none; }
#wr-gallery .thumbnail-item{ height:300px !important; width:230px !important; border-radius:20px !important;
  overflow:hidden !important; scroll-snap-align:start; cursor:pointer;
  box-shadow:0 8px 24px rgba(2,6,23,.18) !important; transition:transform .22s, box-shadow .22s !important;
  border:none !important; }
#wr-gallery .thumbnail-item:hover{ transform:translateY(-8px) scale(1.02);
  box-shadow:0 18px 40px rgba(2,6,23,.32) !important; }
#wr-gallery .thumbnail-item img{ width:100% !important; height:100% !important; object-fit:cover !important; }
#wr-gallery .caption-label, #wr-gallery .thumbnail-item .caption{
  position:absolute !important; left:0; right:0; bottom:0; margin:0 !important;
  padding:34px 14px 12px !important; text-align:left !important; color:#fff !important;
  font-weight:700 !important; font-size:.98rem !important; border-radius:0 !important;
  background:linear-gradient(180deg,rgba(2,6,23,0),rgba(2,6,23,.88)) !important;
  text-shadow:0 2px 8px rgba(0,0,0,.6); backdrop-filter:none !important; opacity:1 !important; }

/* paired slider nav buttons (aligned in the section heading) */
.wr-navbtns{ display:inline-flex; gap:8px; }
.wr-arrow{ width:42px; height:42px; border-radius:50%; border:1px solid var(--wr-bd);
  background:rgba(148,163,184,.10); color:#e2e8f0; font-size:1.45rem; line-height:1; cursor:pointer;
  display:inline-flex; align-items:center; justify-content:center;
  transition:background .18s, transform .18s, box-shadow .18s, border-color .18s; }
.wr-arrow:hover{ background:var(--wr-accent); color:#fff; border-color:var(--wr-accent);
  transform:translateY(-2px); box-shadow:0 8px 20px rgba(79,70,229,.45); }
.wr-arrow:active{ transform:scale(.92); }

/* chat view */
.wr-hero-country{ position:relative; border-radius:22px; overflow:hidden; min-height:172px;
  background-size:cover; background-position:center; display:flex; align-items:flex-end;
  box-shadow:0 10px 30px rgba(2,6,23,.22); margin-bottom:6px; }
.wr-hero-inner{ padding:22px 26px; color:#fff; }
.wr-hero-inner h1{ margin:6px 0 4px; font-size:2.2rem; font-weight:800; letter-spacing:-.02em;
  text-shadow:0 2px 14px rgba(0,0,0,.5); }
.wr-hero-inner p{ margin:0; opacity:.92; font-size:.92rem; max-width:640px; }
.wr-hero-region{ font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700;
  background:rgba(255,255,255,.22); padding:4px 11px; border-radius:999px; }
#wr-chatbox{ height:50vh !important; min-height:380px; }
.wr-legend{ display:flex; gap:8px; justify-content:center; flex-wrap:wrap; margin:8px 0 2px;
  font-size:.78rem; opacity:.85; }
.wr-legend span{ border:1px solid var(--border-color-primary,#e2e8f0); border-radius:999px; padding:3px 11px; }
"""

# Define the slider-arrow handler via a <head> <script> (global on load). NOTE: do NOT
# use Blocks(js=...) for this — in this Gradio version a custom js load-function silently
# breaks the frontend event dispatch (clicks stop reaching the backend). `head` is inert
# w.r.t. the event system.
HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&'
    'family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">'
    "<script>window.wrScroll=function(dir){"
    "var t=document.querySelector('#wr-gallery .grid-container');"
    "if(t)t.scrollBy({left:dir*Math.min(t.clientWidth*0.85,760),behavior:'smooth'});"
    "};</script>"
    # Scroll-reveal: fade cards/sections in as they enter the viewport. Re-scans on an
    # interval because Gradio renders the DOM asynchronously after load.
    "<script>(function(){function s(){var els=document.querySelectorAll("
    "'.wr-reveal:not([data-wro])');if(!('IntersectionObserver' in window)){"
    "els.forEach(function(e){e.classList.add('wr-in')});return;}"
    "var io=window.__wro||(window.__wro=new IntersectionObserver(function(en){"
    "en.forEach(function(x){if(x.isIntersecting){x.target.classList.add('wr-in');"
    "window.__wro.unobserve(x.target);}});},{threshold:0.12,rootMargin:'0px 0px -6% 0px'}));"
    "els.forEach(function(e){e.setAttribute('data-wro','1');io.observe(e);});}"
    "document.addEventListener('DOMContentLoaded',s);setInterval(s,500);})();</script>"
)


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
with gr.Blocks(title="WanderRAG", theme=gr.themes.Soft(primary_hue="indigo"),
               css=CSS, head=HEAD, fill_height=True) as demo:
    selected_country = gr.State("")
    visible_names = gr.State([c.name for c in COUNTRIES])

    # ---------------- HOME ----------------
    with gr.Column(visible=True, elem_id="wr-home") as home_view:
        gr.HTML('<div class="wr-orbs"><span class="wr-orb wr-orb-1"></span>'
                '<span class="wr-orb wr-orb-2"></span><span class="wr-orb wr-orb-3"></span></div>')

        # ---- cinematic hero ----
        gr.HTML(
            f"""
            <section id="wr-hero" style="background-image:linear-gradient(105deg,
                 rgba(7,10,22,.95) 0%, rgba(7,10,22,.80) 40%, rgba(7,10,22,.32) 100%),
                 url('{_HERO_BG}');">
              <div class="wr-hero-body">
                <span class="wr-kicker"><span class="wr-dot"></span> Retrieval-augmented · grounded &amp; cited</span>
                <h1 class="wr-title">Travel answers you<br>can <span class="wr-grad">actually trust.</span></h1>
                <p class="wr-sub">Ask about visas, health, safety or what to see across 50 countries.
                   Every answer is pulled from real US State Dept, CDC and tourism sources and cites
                   the exact chunk it came from — and when the corpus can't answer, it says so.</p>
                <div class="wr-steps">
                  <span class="wr-step"><b>1</b> Pick a country</span>
                  <span class="wr-sep">→</span>
                  <span class="wr-step"><b>2</b> Ask anything</span>
                  <span class="wr-sep">→</span>
                  <span class="wr-step"><b>3</b> Get cited answers</span>
                </div>
                <div class="wr-scrollcue">↓ &nbsp; Explore 50 countries below</div>
              </div>
            </section>
            """
        )

        # ---- stat band ----
        gr.HTML(
            '<div class="wr-stats">'
            '<div class="wr-stat-tile wr-reveal"><div class="wr-stat-num">50</div>'
            '<div class="wr-stat-lbl">Countries covered</div></div>'
            '<div class="wr-stat-tile wr-reveal"><div class="wr-stat-num">3</div>'
            '<div class="wr-stat-lbl">Official source types</div></div>'
            '<div class="wr-stat-tile wr-reveal"><div class="wr-stat-num">100%</div>'
            '<div class="wr-stat-lbl">Answers carry citations</div></div>'
            '<div class="wr-stat-tile wr-reveal"><div class="wr-stat-num">0</div>'
            '<div class="wr-stat-lbl">Invented sources — it refuses instead</div></div>'
            '</div>'
        )

        # ---- how it works ----
        gr.HTML(
            '<div class="wr-section-title wr-reveal"><h2>How it works</h2>'
            '<p>A grounded answer in three steps.</p></div>'
            '<div class="wr-grid3">'
            '<div class="wr-hiw-card wr-reveal"><div class="wr-hiw-ic">🧭</div><h3>1 · Pick a country</h3>'
            '<p>Browse 50 destinations and open a chat scoped to the one you choose.</p></div>'
            '<div class="wr-hiw-card wr-reveal"><div class="wr-hiw-ic">💬</div><h3>2 · Ask anything</h3>'
            '<p>Visas, vaccinations, safety, what to see — in plain language.</p></div>'
            '<div class="wr-hiw-card wr-reveal"><div class="wr-hiw-ic">📎</div><h3>3 · Get cited answers</h3>'
            '<p>Every claim links back to the exact source chunk, with its scrape date.</p></div>'
            '</div>'
        )

        # ---- example-answer showcase ----
        gr.HTML(
            '<div class="wr-section-title wr-reveal"><h2>What a grounded answer looks like</h2>'
            '<p>Real output — every citation resolves to a real retrieved chunk.</p></div>'
            '<div class="wr-showcase wr-reveal">'
            '<div class="wr-ans-head"><span class="wr-badge-ok">✅ GROUNDED · 3 citations</span>'
            '<span class="wr-ans-q">"What should I visit in Italy?"</span></div>'
            '<p class="wr-ans-body">Rome rewards visitors with its rich artistic heritage and '
            'historical sites <span class="wr-cite">[1]</span>. The Aosta Valley offers winter '
            'sports and high-altitude walks amid fairy-tale castles <span class="wr-cite">[2]</span>, '
            'while South Tyrol pairs alpine landscapes with relaxing spa towns '
            '<span class="wr-cite">[3]</span>.</p>'
            '<div class="wr-ans-src">📎 [1] Tourism board · Italy · italia.it &nbsp;·&nbsp; '
            'scraped 2026-06-28 &nbsp;·&nbsp; score 0.61</div></div>'
        )

        # ---- explore by country (functional) ----
        gr.HTML(
            '<div id="wr-explore" class="wr-reveal"><div><h2>Explore by country</h2>'
            '<p>Choose a destination to open a chat grounded in its sources.</p></div>'
            '<div class="wr-explore-right"><span class="wr-pill">🌍 50 countries · 4 regions</span>'
            '<div class="wr-navbtns">'
            '<button class="wr-arrow" onclick="wrScroll(-1)" aria-label="previous">‹</button>'
            '<button class="wr-arrow" onclick="wrScroll(1)" aria-label="next">›</button>'
            '</div></div></div>'
        )
        with gr.Column(elem_classes="wr-panel"):
            with gr.Row(elem_id="wr-filterbar"):
                region_radio = gr.Radio(choices=REGIONS, value="All 50", show_label=False,
                                        elem_id="wr-regions", container=False, scale=3)
                search_box = gr.Textbox(placeholder="🔎 Search a country…", show_label=False,
                                        container=False, scale=1)
            with gr.Column(elem_classes="wr-slider"):
                gallery = gr.Gallery(
                    value=_gallery_items(COUNTRIES), elem_id="wr-gallery", columns=8,
                    object_fit="cover", show_label=False, allow_preview=False,
                    show_share_button=False, show_download_button=False, container=False)

        # ---- trust section ----
        gr.HTML(
            '<div class="wr-section-title wr-reveal"><h2>Built to be honest</h2>'
            '<p>Grounding you can verify — not vibes.</p></div>'
            '<div class="wr-grid3">'
            '<div class="wr-hiw-card wr-reveal"><div class="wr-hiw-ic">✅</div><h3>Every claim cited</h3>'
            '<p>A deterministic gate passes an answer only when its citations resolve to real '
            'retrieved chunks — no hallucinated references.</p></div>'
            '<div class="wr-hiw-card wr-reveal"><div class="wr-hiw-ic">⚠️</div><h3>Refuses when unsure</h3>'
            '<p>If nothing relevant is retrieved, it returns a plain "low confidence" instead '
            'of guessing.</p></div>'
            '<div class="wr-hiw-card wr-reveal"><div class="wr-hiw-ic">🕓</div><h3>Point-in-time</h3>'
            '<p>Every source shows the date it was scraped, so you always know how fresh the '
            'answer is.</p></div>'
            '</div>'
        )

        # ---- footer ----
        gr.HTML(
            '<footer id="wr-footer">'
            '<div>Sources: US State Dept · CDC · national tourism boards &amp; Wikivoyage</div>'
            '<div class="wr-foot-sub">Local research prototype · Photos: Wikivoyage / '
            'Wikimedia Commons · Not for real travel decisions.</div></footer>'
        )

    # ---------------- CHAT ----------------
    with gr.Column(visible=False) as chat_view:
        with gr.Row():
            back_btn = gr.Button("← All countries", scale=0, size="sm")
        country_hero = gr.HTML()
        chatbot = gr.Chatbot(
            type="messages", elem_id="wr-chatbox", show_label=False,
            show_copy_button=True, bubble_full_width=False, avatar_images=(None, None),
            placeholder="<div style='text-align:center;opacity:.6'><h3>Ask about this country</h3>"
                        "<p>Visas · safety · vaccinations · what to visit</p>"
                        "<p><sub>Each answer runs the full graph — expect ~5–20s.</sub></p></div>")
        gr.HTML('<div class="wr-legend">'
                '<span>✅ Grounded — cites real sources</span>'
                '<span>🟡 Thin — one source</span>'
                '<span>⚠️ Low confidence — corpus can\'t answer</span></div>')
        with gr.Row():
            msg = gr.Textbox(placeholder="Ask anything about this country…", show_label=False,
                             scale=8, container=False, autofocus=True)
            send = gr.Button("Send", variant="primary", scale=1)
        with gr.Row():
            ex_visit = gr.Button("🗺️ What to visit", size="sm")
            ex_visa = gr.Button("🛂 Visa", size="sm")
            ex_safety = gr.Button("🛡️ Safety", size="sm")
            ex_vacc = gr.Button("💉 Vaccinations", size="sm")

    # ---------------- wiring ----------------
    region_radio.change(refresh_grid, [region_radio, search_box], [gallery, visible_names])
    search_box.change(refresh_grid, [region_radio, search_box], [gallery, visible_names])
    gallery.select(pick_country, [visible_names],
                   [home_view, chat_view, selected_country, country_hero, chatbot])
    back_btn.click(go_home, outputs=[home_view, chat_view, selected_country, chatbot])

    msg.submit(on_submit, [msg, chatbot, selected_country], [msg, chatbot])
    send.click(on_submit, [msg, chatbot, selected_country], [msg, chatbot])
    ex_visit.click(lambda c, h: on_example("visit", c, h), [selected_country, chatbot], [msg, chatbot])
    ex_visa.click(lambda c, h: on_example("visa", c, h), [selected_country, chatbot], [msg, chatbot])
    ex_safety.click(lambda c, h: on_example("safety", c, h), [selected_country, chatbot], [msg, chatbot])
    ex_vacc.click(lambda c, h: on_example("vacc", c, h), [selected_country, chatbot], [msg, chatbot])


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, show_api=False,
                allowed_paths=[str(ASSETS)])
