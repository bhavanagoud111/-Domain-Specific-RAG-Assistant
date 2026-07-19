"""WanderRAG Week 3 — LangGraph agentic RAG pipeline (Week 5: citation-keyed self_check).

Graph shape (StateGraph)::

    START -> rewrite -> retrieve -> generate -> self_check --(passed | retries>=2)--> finalize -> END
                ^                                    |
                +----(0 citations resolved & retries<2, with feedback)----+

Nodes
-----
* ``rewrite``     decompose a vague query into 1-3 specific sub-queries (first
                  pass) or refine them using the self-check feedback (retry pass).
* ``retrieve``    embed each sub-query (``openai/text-embedding-3-large`` via
                  OpenRouter), query Qdrant top-k, optionally filtered by country.
* ``generate``    answer the original query with inline ``[n]`` citations mapped to
                  real chunk metadata. This is where citations are *resolved*.
* ``self_check``  the sufficiency gate. Runs AFTER generate because "resolved
                  citations" only exist once the answer has been written (see below).
* ``finalize``    terminal node; stamps ``low_confidence`` and prepends the
                  LOW-confidence disclaimer when the gate failed.

Why self_check runs after generate (Week 5)
-------------------------------------------
A *resolved citation* is defined in ``generate_node``: the inline ``[n]`` markers the
model actually emitted, bounds-checked against the retrieved chunks. It is therefore a
**post-generation fact** — at the old pre-generate position, ``self_check`` could not
read it and instead used an LLM judge, which systematically flagged correct, well-cited
"what should I visit in X" answers as insufficient because it wanted a ranked list of
named attractions the corpus doesn't phrase that way (Week 4 investigation: 6/9 flagged,
5 of those with real citations). The gate now keys on citation resolution:

* ``citations_resolved >= 1``  -> PASS, unconditionally (not intent-aware, not judge-aware).
* ``citations_resolved == 0``  -> FAIL, unconditionally (the Canada / nonsense case).

The LLM judge is retained ONLY to author the ``missing`` feedback string that the next
``rewrite`` consumes on a retry; it no longer votes on pass/fail, and it is skipped
entirely once retries are exhausted (nothing would consume its output).

Every OpenRouter call (chat *and* embedding) is logged with real token counts and
OpenRouter's reported USD cost to ``logs/week3_cost_log.json`` — no estimates.

Run the 5-query test suite::

    python -m graph.wanderrag_graph
"""

from __future__ import annotations

import json
import operator
import re
from typing import Annotated, Any, Optional, TypedDict

import requests
from langgraph.graph import END, START, StateGraph
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import settings
from config.countries import names as country_names
from scraping.common import utc_now_iso

# --------------------------------------------------------------------------- #
# Models (constrained to what the dev OpenRouter key can actually reach:
# only openai/* endpoints resolve on this account — gemini/claude 404).
# --------------------------------------------------------------------------- #
FAST_MODEL = "openai/gpt-4o-mini"   # rewrite + self_check (cheap/fast)
GEN_MODEL = "openai/gpt-4o"          # generate (stronger)
EMBED_MODEL = settings.EMBEDDING_MODEL  # openai/text-embedding-3-large
TOP_K = 5
MAX_RETRIES = 2  # self_check may bounce back to rewrite at most twice

COST_LOG = settings.LOGS_DIR / "week3_cost_log.json"

# --------------------------------------------------------------------------- #
# ANTI-SPRAY CLAUSE  (Week 5 — deliberate, load-bearing. Do not delete.)
#
# WHAT IT PREVENTS: citation spray on content-poor retrieval.
#
# Without an explicit licence to decline, a model told to "answer the question AND cite
# every claim" will, when the retrieved chunks contain no answer, satisfy the citation
# instruction by attaching EVERY available marker to a hedged non-answer. Measured on the
# Week 4 prompt (Week 5 audit, 5 samples each, logs/week5.md):
#
#     Japan  -> cited ALL 8 chunks [1]..[8] in 1/5 samples; audited 0/8 substantively
#               supported, while the answer text itself said the sources contain no
#               recommendations for places to visit in Japan.
#     Canada -> cited ALL 7 chunks in 1/5 samples.
#
# Those sprayed citations are structurally valid (every [n] maps to a real retrieved
# chunk) but substantively empty — which is exactly what would fool the citation-keyed
# self_check gate into passing an ungrounded answer. With this clause, Japan and Canada
# return 0 citations in 5/5 samples and say plainly that the corpus cannot answer, while
# content-rich countries (Italy 5-6, Norway 2-4 citations) are unaffected.
#
# SCOPE — this clause stops *reference* spray and NOTHING ELSE. It does not verify that a
# cited chunk actually supports the claim it is attached to. Attribution is deliberately
# NOT gated this week, so Thailand still passes on 1 citation that the audit found
# unsupported (0/1) — that is surfaced as a THIN pass, not suppressed.
#
# Do NOT extend this clause into an attribution instruction (e.g. "don't cite sources that
# don't support the claim"). Tried on 2026-07-12: it works, but it silently flipped
# Thailand from a thin pass to a 0-citation fail — i.e. it is an attribution gate wearing
# a prompt's clothing, and that is a bigger decision than a prompt tweak should make.
# --------------------------------------------------------------------------- #
NO_ANSWER_CLAUSE = (
    "If the sources genuinely do not support an answer, say so and cite nothing."
)

# Set per run so cost-log rows can be grouped by query.
_RUN = {"id": None}

_QDRANT = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)

# Country aliases beyond exact-name substring matching.
_ALIASES = {
    "usa": "United States", "u.s.": "United States", "us citizen": "United States",
    "america": "United States", "uk": "United Kingdom", "u.k.": "United Kingdom",
}


# --------------------------------------------------------------------------- #
# Cost logging
# --------------------------------------------------------------------------- #
def _log_call(node: str, model: str, kind: str, usage: dict[str, Any]) -> float:
    """Append one OpenRouter call to the cost log. Returns its USD cost."""
    cost = float(usage.get("cost") or 0.0)
    rec = {
        "timestamp": utc_now_iso(),
        "run_id": _RUN["id"],
        "node": node,
        "model": model,
        "kind": kind,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost_usd": cost,
    }
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    if COST_LOG.exists():
        try:
            history = json.loads(COST_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    history.append(rec)
    COST_LOG.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return cost


def session_cost(run_id: Optional[str] = None) -> dict[str, Any]:
    """Aggregate the cost log, optionally for a single run_id."""
    if not COST_LOG.exists():
        return {"calls": 0, "total_tokens": 0, "cost_usd": 0.0}
    rows = json.loads(COST_LOG.read_text(encoding="utf-8"))
    if run_id is not None:
        rows = [r for r in rows if r.get("run_id") == run_id]
    return {
        "calls": len(rows),
        "total_tokens": sum(r.get("total_tokens") or 0 for r in rows),
        "cost_usd": round(sum(r.get("cost_usd") or 0.0 for r in rows), 6),
    }


# --------------------------------------------------------------------------- #
# OpenRouter primitives
# --------------------------------------------------------------------------- #
def _chat(node: str, model: str, messages: list[dict], *, max_tokens: int,
          temperature: float = 0.2, json_mode: bool = False) -> str:
    body: dict[str, Any] = {
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    resp = requests.post(
        f"{settings.OPENROUTER_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {settings.require_openrouter_key()}",
                 "Content-Type": "application/json"},
        json=body, timeout=settings.REQUEST_TIMEOUT * 3,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter chat HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    _log_call(node, model, "chat", data.get("usage", {}))
    return data["choices"][0]["message"]["content"] or ""


def _embed(node: str, text: str) -> list[float]:
    resp = requests.post(
        f"{settings.OPENROUTER_BASE_URL}/embeddings",
        headers={"Authorization": f"Bearer {settings.require_openrouter_key()}",
                 "Content-Type": "application/json"},
        json={"model": EMBED_MODEL, "input": [text]},
        timeout=settings.REQUEST_TIMEOUT * 2,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter embed HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    _log_call(node, EMBED_MODEL, "embed", data.get("usage", {}))
    return data["data"][0]["embedding"]


def _detect_country(query: str) -> Optional[str]:
    q = query.lower()
    # Prefer the longest exact-name match (so "United States" beats nothing).
    matches = [n for n in country_names() if n.lower() in q]
    if matches:
        return max(matches, key=len)
    for alias, canonical in _ALIASES.items():
        if alias in q:
            return canonical
    return None


def _parse_json(raw: str) -> dict[str, Any]:
    """Best-effort JSON parse (handles fenced or noisy LLM output)."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


# --------------------------------------------------------------------------- #
# Graph state
# --------------------------------------------------------------------------- #
class GraphState(TypedDict, total=False):
    original_query: str
    current_query: str
    sub_queries: list[str]
    country: Optional[str]
    retry_count: int
    retrieved_chunks: list[dict]
    self_check_passed: bool
    self_check_feedback: str
    final_answer: str
    citations: list[dict]
    citations_resolved: int   # count of [n] markers that mapped to a real chunk
    low_confidence: bool      # True iff the gate failed terminally (0 citations)
    thin_pass: bool           # True iff the gate passed on exactly 1 citation
    #  ^ A thin pass is a REAL pass (the >=1 rule stands) but a fragile one: it clears the
    #    gate on a single citation. Week 5 audit found Thailand passing thin on a citation
    #    that does NOT substantively support its claim (0/1 supported). We surface that
    #    rather than hide it. NOTE: this flag says "only one citation", NOT "the citation is
    #    wrong" -- attribution is deliberately NOT gated this week.
    trace: Annotated[list[dict], operator.add]  # append-only per-node log


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def rewrite_node(state: GraphState) -> dict[str, Any]:
    original = state["original_query"]
    # A retry is any rewrite that runs after a failed self_check.
    is_retry = bool(state.get("retrieved_chunks")) and state.get("self_check_passed") is False
    retry_count = state.get("retry_count", 0) + (1 if is_retry else 0)
    country = state.get("country") if is_retry else _detect_country(original)
    feedback = state.get("self_check_feedback", "")

    if is_retry:
        prompt = (
            "You are refining travel-information search queries that previously "
            "returned insufficient results.\n"
            f"Original user question: {original!r}\n"
            f"What was missing last time: {feedback!r}\n"
            "Produce 1-3 NEW, more targeted search queries that would surface the "
            "missing information. Respond as JSON: {\"sub_queries\": [...]}"
        )
    else:
        prompt = (
            "Decompose a traveler's question into 1-3 specific search queries for a "
            "vector database of US State Dept advisories, CDC health notices, and "
            "tourism pages. Keep the country name in each sub-query. If the question "
            "is already specific, a single focused query is fine.\n"
            f"Question: {original!r}\n"
            "Respond as JSON: {\"sub_queries\": [...]}"
        )
    raw = _chat("rewrite", FAST_MODEL,
                [{"role": "user", "content": prompt}], max_tokens=300, json_mode=True)
    parsed = _parse_json(raw)
    subs = [s.strip() for s in parsed.get("sub_queries", []) if isinstance(s, str) and s.strip()]
    if not subs:
        subs = [original]  # fail safe: never leave retrieve with nothing

    # ------------------------------------------------------------------ #
    # TRIED AND REVERTED (Week 6 fixes, 2026-07-19): appending the unmodified user
    # question here as an extra sub-query.
    #
    # The DIAGNOSIS behind it still stands and is independently evidenced: this node
    # emits SOURCE-ORIENTED sub-queries ("Singapore travel advisories"), which match
    # source PAGE FURNITURE rather than content -- the header "Singapore Travel
    # Advisory | Travel.State.gov" scores 0.761 against its own sub-query, above EVERY
    # genuine Singapore tourism chunk (0.576-0.681). Querying with the raw question
    # ALONE scored 0.625 mean precision vs 0.100 for this node's output (6.2x) on the
    # 5 worst eval questions.
    #
    # But the REMEDY did not work. A full 91-question / 141-run re-eval on the frozen
    # corpus measured precision 44.2% -> 44.2% (-0.0pp). Per-question deltas were pure
    # sampling noise: 26 improved / 30 regressed / 30 unchanged, mean -0.04pp, yet mean
    # ABSOLUTE delta 12.62pp -- and churn scaled inversely with sampling depth (1x
    # questions churned 14.87pp, 3x questions 5.21pp), the signature of run-to-run
    # variance at temperature=0.3 rather than a treatment effect.
    #
    # Root cause of the miss: retrieve_node merges by RAW COSINE SCORE, so a 0.761
    # page-furniture chunk still outranks real content at 0.576-0.681 even once good
    # candidates are in the pool. Adding a candidate set cannot fix a broken ranking.
    # The binding constraint is the MERGE, not the query text -- the next thing to try
    # is Reciprocal Rank Fusion over the per-sub-query result lists.
    #
    # Reverted so this node matches the state the frozen Week 6 evaluation was measured
    # against. Full write-up: logs/week6_fixes.md.
    # ------------------------------------------------------------------ #

    return {
        "sub_queries": subs,
        "current_query": " | ".join(subs),
        "country": country,
        "retry_count": retry_count,
        "trace": [{
            "node": "rewrite", "pass": retry_count, "is_retry": is_retry,
            "detected_country": country, "feedback_used": feedback if is_retry else None,
            "sub_queries": subs,
        }],
    }


def retrieve_node(state: GraphState) -> dict[str, Any]:
    subs = state.get("sub_queries") or [state["original_query"]]
    country = state.get("country")
    qfilter = (
        Filter(must=[FieldCondition(key="country", match=MatchValue(value=country))])
        if country else None
    )
    merged: dict[str, dict] = {}
    for sub in subs:
        vec = _embed("retrieve", sub)
        hits = _QDRANT.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=vec, query_filter=qfilter, limit=TOP_K, with_payload=True,
        ).points
        for h in hits:
            pid = str(h.id)
            if pid not in merged or h.score > merged[pid]["score"]:
                p = h.payload or {}
                merged[pid] = {
                    "id": pid, "score": float(h.score),
                    "country": p.get("country"), "source_type": p.get("source_type"),
                    "source_url": p.get("source_url"), "text": p.get("text", ""),
                    # Metadata only -- carried so generate_node can attach it to citations
                    # for the UI. Nothing in retrieval, ranking or the gate reads it.
                    "scrape_date": p.get("scrape_date"),
                }
    chunks = sorted(merged.values(), key=lambda c: c["score"], reverse=True)[: TOP_K + 3]

    return {
        "retrieved_chunks": chunks,
        "trace": [{
            "node": "retrieve", "country_filter": country, "n_subqueries": len(subs),
            "n_chunks": len(chunks),
            "top_scores": [round(c["score"], 3) for c in chunks[:5]],
            "sources": sorted({f"{c['country']}/{c['source_type']}" for c in chunks}),
        }],
    }


def self_check_node(state: GraphState) -> dict[str, Any]:
    """Sufficiency gate, keyed on CITATION RESOLUTION (not on query intent).

    Runs after ``generate``, because ``citations_resolved`` is produced there and does
    not exist any earlier. The rule is deterministic — no LLM votes on pass/fail:

        citations_resolved >= 1  ->  PASS   (grounded: the answer cites real chunks)
        citations_resolved == 0  ->  FAIL   (ungrounded: nothing resolved)

    A 1-citation pass is a *thin* pass and is marked as such in the trace/state rather
    than being hidden or upgraded.
    """
    original = state["original_query"]
    chunks = state.get("retrieved_chunks", [])
    n_resolved = len(state.get("citations", []))
    retry_count = state.get("retry_count", 0)

    if n_resolved >= 1:
        return {
            "self_check_passed": True,
            "self_check_feedback": "",
            "citations_resolved": n_resolved,
            "thin_pass": n_resolved == 1,   # passes, but on a single citation -> surfaced
            "trace": [{
                "node": "self_check", "passed": True,
                "method": "citation-resolution gate (>=1 resolved)",
                "citations_resolved": n_resolved, "thin": n_resolved == 1,
            }],
        }

    # 0 citations resolved -> ungrounded, gate FAILS. The LLM judge is called only to
    # author retry feedback for the next rewrite, and only if a retry will actually run.
    missing = "no chunks retrieved" if not chunks else ""
    if chunks and retry_count < MAX_RETRIES:
        context = "\n\n".join(
            f"[{i+1}] ({c['country']}/{c['source_type']}) {c['text'][:600]}"
            for i, c in enumerate(chunks)
        )
        prompt = (
            "A grounded-answer attempt over the context below produced ZERO usable "
            "citations. Name what the context is missing so a better search query can "
            "be written. Do not judge sufficiency; only describe the gap.\n"
            f"Question: {original!r}\n\nContext:\n{context}\n\n"
            "Respond as JSON: {\"missing\": \"<what's missing>\"}"
        )
        raw = _chat("self_check", FAST_MODEL,
                    [{"role": "user", "content": prompt}], max_tokens=200, json_mode=True)
        missing = str(_parse_json(raw).get("missing", "") or "") or "no citable evidence"

    return {
        "self_check_passed": False,
        "self_check_feedback": missing,
        "citations_resolved": 0,
        "thin_pass": False,
        "trace": [{
            "node": "self_check", "passed": False,
            "method": "citation-resolution gate (0 resolved)",
            "citations_resolved": 0, "missing": missing,
        }],
    }


def finalize_node(state: GraphState) -> dict[str, Any]:
    """Terminal node: stamp low_confidence and prepend the disclaimer if the gate failed."""
    passed = state.get("self_check_passed", False)
    n_resolved = state.get("citations_resolved", len(state.get("citations", [])))
    answer = state.get("final_answer", "") or ""
    low_conf = not passed

    if low_conf:
        answer = (
            "⚠️ Low confidence: none of the retrieved sources could be resolved into a "
            "citation for this question, so the answer below is not grounded in the "
            "WanderRAG corpus.\n\n" + answer
        )

    thin = passed and n_resolved == 1
    if thin:
        # Passes the >=1 rule, but on a single citation. Say so out loud rather than
        # shipping it indistinguishable from a 6-citation answer.
        answer += ("\n\n_Note: this answer rests on a single supporting source "
                   "(thin grounding) — treat it with extra caution._")

    return {
        "final_answer": answer,
        "low_confidence": low_conf,
        "citations_resolved": n_resolved,
        "thin_pass": thin,
        "trace": [{"node": "finalize", "low_confidence": low_conf,
                   "citations_resolved": n_resolved, "thin": thin}],
    }


def generate_node(state: GraphState) -> dict[str, Any]:
    """Write the grounded answer and RESOLVE CITATIONS.

    This is the only place a citation becomes real: the model's inline ``[n]`` markers,
    bounds-checked against the retrieved chunks. ``self_check`` reads the count this
    node produces. No low-confidence disclaimer is injected here any more — that verdict
    isn't known until the gate has seen this node's citation count (see ``finalize``).
    """
    original = state["original_query"]
    chunks = state.get("retrieved_chunks", [])

    if not chunks:
        answer = ("I couldn't find any relevant information in the WanderRAG corpus for "
                  "this query, so I can't give a grounded answer.")
        return {"final_answer": answer, "citations": [], "citations_resolved": 0,
                "trace": [{"node": "generate", "n_citations": 0, "reason": "no chunks"}]}

    numbered = "\n\n".join(
        f"[{i+1}] source_type={c['source_type']} | country={c['country']} | "
        f"url={c['source_url']}\n{c['text'][:800]}"
        for i, c in enumerate(chunks)
    )
    prompt = (
        "Answer the traveler's question using ONLY the numbered sources below. "
        "Cite sources inline as [n] immediately after each claim, using only the "
        "numbers shown. Do not invent sources or facts not present in the context. "
        # Deliberate anti-spray clause -- see NO_ANSWER_CLAUSE above. Removing this
        # re-enables citation spray on content-poor retrieval (Japan/Canada cite all
        # 7-8 chunks with 0/8 substantive support), which would defeat the
        # citation-keyed self_check gate.
        f"{NO_ANSWER_CLAUSE}"
        f"\n\nQuestion: {original!r}\n\nSources:\n{numbered}"
    )
    answer = _chat("generate", GEN_MODEL,
                   [{"role": "user", "content": prompt}], max_tokens=700, temperature=0.3)

    # Build citations only for source numbers the model actually referenced ->
    # guarantees citations map to real retrieved chunks (no hallucinated refs).
    cited_nums = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    citations = []
    for n in cited_nums:
        if 1 <= n <= len(chunks):
            c = chunks[n - 1]
            citations.append({"marker": f"[{n}]", "country": c["country"],
                              "source_type": c["source_type"], "source_url": c["source_url"],
                              # Week 6: carried through so the UI can show the point-in-time
                              # stamp (proposal Risk 3). METADATA ONLY -- this field is never
                              # read by retrieve, generate, self_check or the citation gate.
                              "scrape_date": c.get("scrape_date"),
                              "score": round(c["score"], 3)})
    return {
        "final_answer": answer, "citations": citations,
        "citations_resolved": len(citations),
        "trace": [{"node": "generate", "model": GEN_MODEL,
                   "n_citations": len(citations),
                   "cited_markers": [c["marker"] for c in citations]}],
    }


def _route_after_check(state: GraphState) -> str:
    if state.get("self_check_passed"):
        return "finalize"
    if state.get("retry_count", 0) >= MAX_RETRIES:
        return "finalize"
    return "rewrite"


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("rewrite", rewrite_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("generate", generate_node)
    g.add_node("self_check", self_check_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "rewrite")
    g.add_edge("rewrite", "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "self_check")
    g.add_conditional_edges("self_check", _route_after_check,
                            {"rewrite": "rewrite", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()


GRAPH = build_graph()


def run_query(query: str, run_id: Optional[str] = None) -> GraphState:
    _RUN["id"] = run_id or query[:40]
    init: GraphState = {"original_query": query, "retry_count": 0, "trace": []}
    return GRAPH.invoke(init, config={"recursion_limit": 25})


# --------------------------------------------------------------------------- #
# Test harness
# --------------------------------------------------------------------------- #
TEST_QUERIES = [
    "Do I need a visa to visit Japan as a US citizen?",
    "What's the safety situation in Mexico right now?",
    "Tell me about visiting Vietnam",
    "What vaccinations does Brazil require?",
    "asdkjasd current safety xyz nonsense country",
]


def _print_trace(i: int, query: str, state: GraphState) -> None:
    rid = f"q{i}"
    print("\n" + "=" * 78)
    print(f"Q{i}: {query!r}")
    print("=" * 78)
    retries = state.get("retry_count", 0)
    print(f"  retry loops triggered: {retries}")
    for step in state.get("trace", []):
        node = step.get("node")
        if node == "rewrite":
            print(f"  [rewrite pass={step['pass']} retry={step['is_retry']}] "
                  f"country={step['detected_country']} subs={step['sub_queries']}")
            if step.get("feedback_used"):
                print(f"            feedback_used: {step['feedback_used']!r}")
        elif node == "retrieve":
            print(f"  [retrieve] filter={step['country_filter']} "
                  f"n_chunks={step['n_chunks']} top_scores={step['top_scores']}")
            print(f"            sources={step['sources']}")
        elif node == "generate":
            print(f"  [generate] citations={step['n_citations']} "
                  f"markers={step.get('cited_markers')}")
        elif node == "self_check":
            print(f"  [self_check] passed={step['passed']} "
                  f"citations_resolved={step.get('citations_resolved')} "
                  f"{'(THIN) ' if step.get('thin') else ''}"
                  f"method={step.get('method')!r} missing={step.get('missing')!r}")
        elif node == "finalize":
            print(f"  [finalize] low_confidence={step['low_confidence']} "
                  f"citations_resolved={step['citations_resolved']}"
                  f"{' (THIN)' if step.get('thin') else ''}")
    print("\n  --- FINAL ANSWER ---")
    print("  " + (state.get("final_answer", "") or "").replace("\n", "\n  "))
    print("\n  --- CITATIONS ---")
    for c in state.get("citations", []):
        print(f"    {c['marker']} {c['country']}/{c['source_type']} "
              f"(score={c['score']}) {c['source_url']}")
    print(f"\n  per-query cost: {session_cost(rid)}")


def main() -> None:
    before = session_cost()
    results = []
    for i, q in enumerate(TEST_QUERIES, 1):
        state = run_query(q, run_id=f"q{i}")
        results.append(state)
        _print_trace(i, q, state)

    after = session_cost()
    session_delta = round(after["cost_usd"] - before["cost_usd"], 6)
    print("\n" + "#" * 78)
    print("SESSION TOTAL (this run)")
    print("#" * 78)
    print(f"  calls this run : {after['calls'] - before['calls']}")
    print(f"  tokens this run: {after['total_tokens'] - before['total_tokens']}")
    print(f"  cost this run  : ${session_delta}")
    print(f"  cost log       : {COST_LOG}")


if __name__ == "__main__":
    main()
