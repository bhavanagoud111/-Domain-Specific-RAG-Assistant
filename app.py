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

import gradio as gr

from graph.wanderrag_graph import run_query, session_cost


def _render_sources(citations: list[dict]) -> str:
    """One markdown bullet per citation: marker, source_type, country, score, URL."""
    if not citations:
        return ""
    lines = ["\n\n---\n**Sources**"]
    for c in citations:
        url = c.get("source_url") or ""
        label = f"{c.get('source_type', '?')} · {c.get('country', '?')}"
        link = f"[{url}]({url})" if url else "_(no URL on this chunk)_"
        lines.append(f"- `{c['marker']}` **{label}** (score {c.get('score')}) — {link}")
    return "\n".join(lines)


def _render_status(state: dict) -> str:
    """The confidence banner: citation count + low-confidence / thin-pass flags."""
    n = state.get("citations_resolved", len(state.get("citations", [])))
    retries = state.get("retry_count", 0)

    if state.get("low_confidence"):
        head = (f"> ⚠️ **LOW CONFIDENCE** — **{n} citations resolved**. "
                f"No retrieved source could be resolved into a citation, so this answer is "
                f"not grounded in the WanderRAG corpus.")
    elif state.get("thin_pass"):
        head = (f"> 🟡 **THIN GROUNDING** — **{n} citation resolved**. "
                f"This answer clears the citation gate on a single source; treat with caution.")
    else:
        head = f"> ✅ **Grounded** — **{n} citations resolved**."

    return f"{head}\n> _retry loops: {retries}_"


def respond(message: str, history: list[dict]) -> str:
    """One turn: run the existing graph, render answer + status + sources."""
    message = (message or "").strip()
    if not message:
        return "Ask me about visas, safety, vaccinations, or what to see in a country."

    try:
        state = run_query(message, run_id=f"ui_{uuid.uuid4().hex[:8]}")
    except Exception as exc:  # surface failures in the UI rather than dying silently
        return f"❌ The graph failed on that query:\n\n```\n{type(exc).__name__}: {exc}\n```"

    answer = state.get("final_answer", "") or "_(the graph returned no answer)_"
    return f"{_render_status(state)}\n\n{answer}{_render_sources(state.get('citations', []))}"


DESCRIPTION = """\
Grounded travel answers over US State Dept advisories, CDC health notices and national
tourism boards (50 countries, 2,220 chunks in Qdrant).

Every answer shows its **resolved-citation count**. An answer that resolves **0 citations**
is flagged **LOW CONFIDENCE** — the corpus could not support it (try *"What should I visit
in Canada?"*). An answer resting on a **single** source is flagged **THIN** (try Thailand).
"""

with gr.Blocks(title="WanderRAG") as demo:
    gr.Markdown("# 🧭 WanderRAG")
    gr.Markdown(DESCRIPTION)

    gr.ChatInterface(
        fn=respond,
        type="messages",          # keeps back-and-forth history within the session
        examples=[
            "Do I need a visa to visit Japan as a US citizen?",
            "What's the safety situation in Mexico right now?",
            "What should I visit in Italy?",
            "What should I visit in Canada?",       # -> 0 citations, LOW CONFIDENCE
            "What vaccinations does Brazil require?",
        ],
    )

    with gr.Accordion("Session cost (real OpenRouter usage)", open=False):
        cost_md = gr.Markdown("_click refresh_")
        gr.Button("Refresh", size="sm").click(
            lambda: f"```\n{session_cost()}\n```", outputs=cost_md
        )


if __name__ == "__main__":
    demo.launch()
