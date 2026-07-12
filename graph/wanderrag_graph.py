"""WanderRAG Week 3 — LangGraph agentic RAG pipeline.

Graph shape (StateGraph)::

    START -> rewrite -> retrieve -> self_check --(sufficient | retries>=2)--> generate -> END
                ^                        |
                +----(insufficient & retries<2, with feedback)----+

Nodes
-----
* ``rewrite``     decompose a vague query into 1-3 specific sub-queries (first
                  pass) or refine them using the self-check feedback (retry pass).
* ``retrieve``    embed each sub-query (``openai/text-embedding-3-large`` via
                  OpenRouter), query Qdrant top-k, optionally filtered by country.
* ``self_check``  LLM judges whether the retrieved chunks can answer the original
                  query; emits a ``missing`` feedback string used by the next rewrite.
* ``generate``    answer the original query with inline ``[n]`` citations mapped to
                  real chunk metadata; low-confidence disclaimer if retries exhausted.

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
    original = state["original_query"]
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return {
            "self_check_passed": False, "self_check_feedback": "no chunks retrieved",
            "trace": [{"node": "self_check", "passed": False, "reason": "empty retrieval"}],
        }
    context = "\n\n".join(
        f"[{i+1}] ({c['country']}/{c['source_type']}) {c['text'][:600]}"
        for i, c in enumerate(chunks)
    )
    prompt = (
        "You are judging whether retrieved context is sufficient to answer a "
        "traveler's question. Be strict: if the context does not actually address "
        "the question, say it is insufficient.\n"
        f"Question: {original!r}\n\nContext:\n{context}\n\n"
        "Respond as JSON: {\"sufficient\": true|false, \"missing\": \"<what's missing, or empty>\"}"
    )
    raw = _chat("self_check", FAST_MODEL,
                [{"role": "user", "content": prompt}], max_tokens=200, json_mode=True)
    parsed = _parse_json(raw)
    passed = bool(parsed.get("sufficient", False))
    missing = str(parsed.get("missing", "") or "")
    return {
        "self_check_passed": passed, "self_check_feedback": missing,
        "trace": [{"node": "self_check", "passed": passed, "missing": missing,
                   "method": "LLM-judge (gpt-4o-mini)"}],
    }


def generate_node(state: GraphState) -> dict[str, Any]:
    original = state["original_query"]
    chunks = state.get("retrieved_chunks", [])
    passed = state.get("self_check_passed", False)
    low_conf = (not passed)  # we only reach generate unpassed when retries are exhausted

    if not chunks:
        answer = ("⚠️ Low confidence: I couldn't find any relevant information in the "
                  "WanderRAG corpus for this query, so I can't give a grounded answer.")
        return {"final_answer": answer, "citations": [],
                "trace": [{"node": "generate", "low_confidence": True, "n_citations": 0,
                           "reason": "no chunks"}]}

    numbered = "\n\n".join(
        f"[{i+1}] source_type={c['source_type']} | country={c['country']} | "
        f"url={c['source_url']}\n{c['text'][:800]}"
        for i, c in enumerate(chunks)
    )
    disclaimer = (
        "Begin your answer with one sentence flagging that confidence is LOW because "
        "the retrieved sources may not fully cover the question. "
    ) if low_conf else ""
    prompt = (
        "Answer the traveler's question using ONLY the numbered sources below. "
        "Cite sources inline as [n] immediately after each claim, using only the "
        "numbers shown. Do not invent sources or facts not present in the context. "
        f"{disclaimer}\n\nQuestion: {original!r}\n\nSources:\n{numbered}"
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
                              "score": round(c["score"], 3)})
    return {
        "final_answer": answer, "citations": citations,
        "trace": [{"node": "generate", "model": GEN_MODEL, "low_confidence": low_conf,
                   "n_citations": len(citations),
                   "cited_markers": [c["marker"] for c in citations]}],
    }


def _route_after_check(state: GraphState) -> str:
    if state.get("self_check_passed"):
        return "generate"
    if state.get("retry_count", 0) >= MAX_RETRIES:
        return "generate"
    return "rewrite"


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("rewrite", rewrite_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("self_check", self_check_node)
    g.add_node("generate", generate_node)
    g.add_edge(START, "rewrite")
    g.add_edge("rewrite", "retrieve")
    g.add_edge("retrieve", "self_check")
    g.add_conditional_edges("self_check", _route_after_check,
                            {"rewrite": "rewrite", "generate": "generate"})
    g.add_edge("generate", END)
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
        elif node == "self_check":
            print(f"  [self_check] passed={step['passed']} missing={step.get('missing')!r}")
        elif node == "generate":
            print(f"  [generate] low_confidence={step['low_confidence']} "
                  f"citations={step['n_citations']} markers={step.get('cited_markers')}")
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
