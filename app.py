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
from graph.wanderrag_graph import run_query, session_cost
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


def _corpus_total() -> str:
    try:
        return f"{get_client().count(collection_name=settings.QDRANT_COLLECTION, exact=True).count:,}"
    except Exception:
        return "—"


def _photo_uri(slug: str) -> str:
    p = ASSETS / f"{slug}.jpg"
    if not p.exists():
        return ""
    return f"data:image/jpeg;base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


_COUNTS = _country_counts()
_TOTAL = _corpus_total()
_PHOTO_URI = {c.slug: _photo_uri(c.slug) for c in COUNTRIES}


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
:root{ --wr-accent:#4f46e5; }
.gradio-container{ max-width:1180px !important; margin:0 auto !important; }
footer{ display:none !important; }

#wr-home-hero{ text-align:center; padding:16px 0 4px; }
#wr-home-hero h1{ font-size:2.8rem; margin:0; letter-spacing:-.03em; font-weight:800;
  background:linear-gradient(95deg,#4f46e5,#db2777 55%,#f59e0b);
  -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
#wr-home-hero p{ margin:8px auto 0; opacity:.72; font-size:1.02rem; max-width:640px; }
#wr-home-hero .wr-stat{ display:inline-block; margin-top:12px; font-size:.85rem;
  padding:5px 14px; border-radius:999px; background:rgba(79,70,229,.10);
  border:1px solid rgba(79,70,229,.28); color:var(--wr-accent); font-weight:600; }

/* filter bar */
#wr-filterbar{ gap:12px; align-items:center; margin:12px 2px 2px; }
#wr-regions .wrap{ gap:8px !important; }
#wr-regions input[type=radio]{ position:absolute !important; opacity:0 !important; width:0 !important; }
#wr-regions label{ border-radius:999px !important; border:1px solid var(--border-color-primary,#e2e8f0) !important;
  padding:6px 15px !important; font-weight:600 !important; font-size:.85rem !important; cursor:pointer; }
#wr-regions label:has(input:checked){
  background:var(--wr-accent) !important; color:#fff !important; border-color:var(--wr-accent) !important; }

/* gallery -> horizontal slider */
.wr-slider{ position:relative; }
#wr-gallery{ border:none !important; background:transparent !important; }
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

.wr-arrow{ position:absolute; top:46%; transform:translateY(-50%); z-index:20;
  width:46px; height:46px; border-radius:50%; border:1px solid var(--border-color-primary,#e2e8f0);
  background:var(--background-fill-primary,#fff); color:#0f172a; font-size:1.7rem; line-height:1;
  cursor:pointer; box-shadow:0 6px 18px rgba(2,6,23,.22); }
.wr-arrow:hover{ background:var(--wr-accent); color:#fff; border-color:var(--wr-accent); }
.wr-arrow-l{ left:-8px; } .wr-arrow-r{ right:-8px; }
#wr-credit{ text-align:center; font-size:.72rem; opacity:.5; margin-top:6px; }

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
    "<script>window.wrScroll=function(dir){"
    "var t=document.querySelector('#wr-gallery .grid-container');"
    "if(t)t.scrollBy({left:dir*Math.min(t.clientWidth*0.85,760),behavior:'smooth'});"
    "};</script>"
)


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
with gr.Blocks(title="WanderRAG", theme=gr.themes.Soft(primary_hue="indigo"),
               css=CSS, head=HEAD, fill_height=True) as demo:
    selected_country = gr.State("")
    visible_names = gr.State([c.name for c in COUNTRIES])

    # ---------------- HOME ----------------
    with gr.Column(visible=True) as home_view:
        gr.HTML(
            f"""
            <div id="wr-home-hero">
              <h1>🧭 WanderRAG</h1>
              <p>Grounded travel answers over US State Dept advisories, CDC health notices
                 and national tourism boards. Pick a country to start.</p>
              <div class="wr-stat">🌍 50 countries · 📄 {_TOTAL} grounded chunks</div>
            </div>
            """
        )
        with gr.Row(elem_id="wr-filterbar"):
            region_radio = gr.Radio(choices=REGIONS, value="All 50", show_label=False,
                                    elem_id="wr-regions", container=False, scale=3)
            search_box = gr.Textbox(placeholder="🔎 Search a country…", show_label=False,
                                    container=False, scale=1)
        with gr.Column(elem_classes="wr-slider"):
            gr.HTML('<button class="wr-arrow wr-arrow-l" onclick="wrScroll(-1)">‹</button>'
                    '<button class="wr-arrow wr-arrow-r" onclick="wrScroll(1)">›</button>')
            gallery = gr.Gallery(
                value=_gallery_items(COUNTRIES), elem_id="wr-gallery", columns=8,
                object_fit="cover", show_label=False, allow_preview=False,
                show_share_button=False, show_download_button=False, container=False)
        gr.HTML('<p id="wr-credit">Photos: Wikivoyage / Wikimedia Commons · '
                'Answers cite US State Dept · CDC · tourism boards.</p>')

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
        with gr.Accordion("Session cost (real OpenRouter usage)", open=False):
            cost_md = gr.Markdown("_click refresh_")
            gr.Button("Refresh", size="sm").click(
                lambda: f"```\n{session_cost()}\n```", outputs=cost_md)

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
