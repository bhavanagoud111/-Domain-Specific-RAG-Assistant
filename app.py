"""WanderRAG — minimal Gradio chat UI (Week 5).

Runs the EXISTING LangGraph pipeline unchanged. Retrieval, generation, the
citation-keyed self_check gate, TOP_K, country filtering and chunking all live in
``graph/wanderrag_graph.py`` — nothing here reimplements any of them. This module only
calls ``run_query()`` and renders what comes back out of the graph state.

What it surfaces, per turn:
  * the grounded answer
  * every citation as a source link (URL + source_type + country + score)
  * the resolved-citation count  (``state["citations_resolved"]``)
  * the LOW-CONFIDENCE flag when it fires (``state["low_confidence"]``, i.e. 0 citations)
  * the THIN-PASS flag when it fires (``state["thin_pass"]``, i.e. passed on exactly 1)

Launch:  python app.py     ->  http://127.0.0.1:7860

Requires Qdrant to be up (docker compose up -d) and OPENROUTER_API_KEY in .env.
No streaming, no auth, no deployment.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

import gradio as gr

from graph.wanderrag_graph import run_query, session_cost

SOURCE_LABELS = {
    "state_dept": "US State Dept",
    "cdc": "CDC",
    "tourism": "Tourism board",
}


def _domain(url: str) -> str:
    """Short, readable link text instead of a 120-char URL."""
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host or url
    except Exception:
        return url


def _render_status(state: dict) -> str:
    """Confidence banner: citation count + low-confidence / thin-pass flags."""
    n = state.get("citations_resolved", len(state.get("citations", [])))
    retries = state.get("retry_count", 0)
    plural = "citation" if n == 1 else "citations"

    if state.get("low_confidence"):
        badge, note = (
            f"⚠️ &nbsp;**LOW CONFIDENCE** · **{n} {plural} resolved**",
            "No retrieved source could be resolved into a citation, so this answer is "
            "**not grounded** in the WanderRAG corpus.",
        )
    elif state.get("thin_pass"):
        badge, note = (
            f"🟡 &nbsp;**THIN GROUNDING** · **{n} {plural} resolved**",
            "Clears the citation gate on a _single_ source — treat with caution.",
        )
    else:
        badge, note = (
            f"✅ &nbsp;**GROUNDED** · **{n} {plural} resolved**",
            None,
        )

    line = f"{badge} &nbsp;·&nbsp; _retry loops: {retries}_"
    return f"{line}\n\n{note}\n" if note else f"{line}\n"


def _render_sources(citations: list[dict]) -> str:
    """One line per citation: marker, source, country, score, link."""
    if not citations:
        return ""
    rows = ["\n---\n\n**Sources**\n"]
    for c in citations:
        url = c.get("source_url") or ""
        src = SOURCE_LABELS.get(c.get("source_type", ""), c.get("source_type", "?"))
        link = f"[{_domain(url)}]({url})" if url else "_no URL on this chunk_"
        rows.append(
            f"- **`{c['marker']}`** &nbsp; {src} · {c.get('country', '?')} &nbsp; "
            f"→ &nbsp; {link} &nbsp; <sub>score {c.get('score')}</sub>"
        )
    return "\n".join(rows)


def _dedupe_banner(answer: str) -> str:
    """Drop the graph's own low-conf / thin notices — the status banner already says it.

    Presentation only: the graph's answer text is left exactly as-is in graph state and in
    the CLI; this just avoids printing the same warning twice in the chat bubble.
    """
    for prefix in ("⚠️ Low confidence:",):
        if answer.startswith(prefix):
            _, _, rest = answer.partition("\n\n")
            answer = rest or answer
    marker = "\n\n_Note: this answer rests on a single supporting source"
    if marker in answer:
        answer = answer.split(marker)[0]
    return answer.strip()


def respond(message: str, history: list[dict]) -> str:
    """One turn: run the existing graph, render status + answer + sources."""
    message = (message or "").strip()
    if not message:
        return "Ask me about visas, safety, vaccinations, or what to see in a country."

    try:
        state = run_query(message, run_id=f"ui_{uuid.uuid4().hex[:8]}")
    except Exception as exc:  # surface failures in the UI rather than dying silently
        return f"❌ **The graph failed on that query.**\n\n```\n{type(exc).__name__}: {exc}\n```"

    answer = _dedupe_banner(state.get("final_answer", "")) or "_(the graph returned no answer)_"
    return (
        f"{_render_status(state)}\n"
        f"{answer}\n"
        f"{_render_sources(state.get('citations', []))}"
    )


CSS = """
.gradio-container { max-width: 1080px !important; margin: 0 auto !important; }
#hero { text-align: center; padding: 4px 0 2px; }
#hero h1 { font-size: 2rem; margin: 0; letter-spacing: -0.02em; }
#hero p  { margin: 6px 0 0; opacity: .72; font-size: .95rem; }
#legend {
  display: flex; gap: 8px; justify-content: center; flex-wrap: wrap;
  margin: 10px 0 4px; font-size: .82rem; opacity: .85;
}
#legend span { border: 1px solid var(--border-color-primary); border-radius: 999px; padding: 3px 11px; }
#chatbox { height: 60vh !important; min-height: 460px; }
footer { display: none !important; }
"""

with gr.Blocks(title="WanderRAG", theme=gr.themes.Soft(), css=CSS, fill_height=True) as demo:
    gr.HTML(
        """
        <div id="hero">
          <h1>🧭 WanderRAG</h1>
          <p>Grounded travel answers over US State Dept advisories, CDC health notices
             and national tourism boards — 50 countries, 2,220 chunks.</p>
        </div>
        <div id="legend">
          <span>✅ Grounded — cites real sources</span>
          <span>🟡 Thin — rests on a single source</span>
          <span>⚠️ Low confidence — 0 citations, corpus can't answer</span>
        </div>
        """
    )

    gr.ChatInterface(
        fn=respond,
        type="messages",   # keeps back-and-forth history within the session
        chatbot=gr.Chatbot(
            type="messages",
            elem_id="chatbox",
            label=None,
            show_label=False,
            show_copy_button=True,
            bubble_full_width=False,
            placeholder=(
                "<div style='text-align:center;opacity:.6'>"
                "<h3>Ask about a country</h3>"
                "<p>Visas · safety · vaccinations · what to visit</p>"
                "<p><sub>Each answer runs the full graph — expect ~5–20s.</sub></p>"
                "</div>"
            ),
        ),
        textbox=gr.Textbox(
            placeholder="e.g. What should I visit in Italy?",
            container=False,
            scale=7,
        ),
        examples=[
            "What should I visit in Italy?",                      # grounded, ~6 citations
            "Do I need a visa to visit Japan as a US citizen?",
            "What's the safety situation in Mexico right now?",
            "What vaccinations does Brazil require?",
            # Canada is the stable 0-citation case (0 citations in 5/5 audit samples):
            # the corpus has no "what to visit" content, so the gate correctly refuses.
            "What should I visit in Canada?",                     # -> LOW CONFIDENCE
        ],
        cache_examples=False,
    )

    with gr.Accordion("Session cost (real OpenRouter usage)", open=False):
        cost_md = gr.Markdown("_click refresh_")
        gr.Button("Refresh", size="sm").click(
            lambda: f"```\n{session_cost()}\n```", outputs=cost_md
        )


if __name__ == "__main__":
    # Pin the port. Gradio's default behaviour is to silently fall forward to 7861, 7862...
    # if 7860 is taken -- which means a stale server from an earlier run keeps serving the
    # OLD ui on 7860 while the new code lands on a port nobody is looking at.
    # Failing loudly on a busy port is what we want here.
    demo.launch(server_port=7860)
