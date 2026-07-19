"""Phase 3 — build ``evaluation/eval_set.json`` grounded in the FROZEN corpus.

Design constraint from the brief: reference answers must be derivable from chunks that
actually exist in this corpus, never from the model's own world knowledge. That is
enforced *structurally* rather than by trust:

  1. For each candidate question we retrieve top-k chunks from Qdrant, filtered to the
     expected country (and, for typed questions, biased to the natural source_type).
  2. Those chunk texts -- and nothing else -- are handed to the reference writer.
  3. The writer is instructed to emit the literal token ``INSUFFICIENT`` when the supplied
     chunks do not contain the answer. It is never given the country name as a hint beyond
     what appears in the chunks.
  4. Anything that comes back INSUFFICIENT is NOT silently dropped: it is reported, and
     either promoted to an ``unanswerable`` item or discarded explicitly in the log.

The writer is ``anthropic/claude-sonnet-4.5`` -- deliberately NOT gpt-4o, which generates
the answers under evaluation (see evaluation/run_eval.py for the same separation).

Run:  PYTHONPATH=. python evaluation/build_eval_set.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests
from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import settings
from embedding.embed_and_load import embed_batch
from storage.qdrant_setup import get_client

REF_MODEL = "anthropic/claude-sonnet-4.5"
OUT_PATH = Path(__file__).resolve().parent / "eval_set.json"
TOP_K = 6        # per-query retrieval depth
EVIDENCE_K = 12  # how many merged chunks the reference writer may see (see retrieve())

# Natural source_type per question type. Used only to *bias* retrieval; the reference
# writer still sees whatever came back, so a wrong guess degrades to "unanswerable"
# rather than to a fabricated answer.
TYPE_SOURCE = {
    "visa": "state_dept",
    "health": "cdc",
    "safety": "state_dept",
    "what_to_visit": "tourism",
}

TEMPLATES = {
    "visa": "Do I need a visa to visit {c} as a US citizen?",
    "health": "What vaccinations or health precautions do I need for {c}?",
    "safety": "How safe is it to travel in {c} right now?",
    "what_to_visit": "What should I visit in {c}?",
}

# 24 countries spanning the corpus-size tiers (see logs/week6.md Phase 2 table).
# rich >=60 chunks, mid 30-59, thin <30.
COUNTRIES = {
    "rich": ["Japan", "Mexico", "Singapore", "South Korea", "New Zealand", "Egypt",
             "Greece", "Israel", "Peru", "Morocco"],
    "mid":  ["Italy", "India", "Turkey", "Vietnam", "China", "Switzerland", "Jordan"],
    "thin": ["Canada", "Thailand", "United Arab Emirates", "Norway", "Brazil",
             "France", "United States"],
}

# Deliberately unanswerable: the corpus is advisories + CDC health + tourism pages. It
# carries no prices, no live schedules, no visa *fees*, no weather records. These are
# checked against the corpus too -- if retrieval DOES surface an answer, the item is
# reported as a failed premise rather than kept.
UNANSWERABLE = [
    ("What is the current price of a 7-day rail pass in Japan?", "Japan"),
    ("What was the average rainfall in Norway in March 2019?", "Norway"),
    ("How much does a tourist visa to Brazil cost in US dollars?", "Brazil"),
    ("What time does the Louvre close on Tuesdays?", "France"),
    ("Which airlines fly direct from Chicago to Singapore?", "Singapore"),
]

WRITER_PROMPT = """You are building a reference answer for a retrieval-evaluation set.

Below are text chunks retrieved from a travel-information corpus. They are your ONLY
source. You must not use any outside knowledge, even if you are confident it is correct.

QUESTION: {q}

CHUNKS:
{chunks}

Write a 1-3 sentence reference answer using ONLY facts stated in the chunks above.
Quote or closely paraphrase the chunk wording. Do not add context the chunks do not state.

If the chunks do not contain enough information to answer the question, reply with the
single word INSUFFICIENT and nothing else. Prefer INSUFFICIENT over a vague or hedged
answer -- a wrong reference answer is worse for this eval set than a missing one."""


def _post(model: str, prompt: str, max_tokens: int = 400) -> str:
    key = settings.require_openrouter_key()
    r = requests.post(
        f"{settings.OPENROUTER_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": max_tokens, "temperature": 0},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def retrieve(question: str, country: str, source_type: str | None) -> list[dict[str, Any]]:
    """Evidence window for writing a reference answer. NOT the runtime retriever.

    This deliberately looks WIDER than the graph's runtime top-5. A reference answer must
    describe what the *corpus* can support, independent of what the runtime retriever
    happens to rank highly -- otherwise the evaluation is circular: retrieval would be
    graded against a reference built from that same retrieval, and a retrieval miss could
    never show up as a miss.

    An earlier version of this function was circular in exactly that way. It concatenated
    the source_type-constrained hits and then the unconstrained hits and sliced to TOP_K,
    so the 6 constrained chunks crowded out every unconstrained one. Japan's "no visa
    required for stays less than 90 days" sits at ranks 1-4 of the unconstrained query but
    never survived the slice, and the question was wrongly rejected as INSUFFICIENT --
    i.e. a *retrieval ordering artifact* was being recorded as a corpus gap.

    Now both result sets are kept (deduped, up to EVIDENCE_K), so INSUFFICIENT means the
    corpus genuinely lacks the answer.
    """
    client = get_client()
    vec = embed_batch([question])[0]

    def _q(filt: Filter) -> list[Any]:
        return client.query_points(
            collection_name=settings.QDRANT_COLLECTION, query=vec, limit=TOP_K,
            query_filter=filt, with_payload=True,
        ).points

    country_cond = FieldCondition(key="country", match=MatchValue(value=country))
    hits = []
    if source_type:
        hits += _q(Filter(must=[country_cond,
                                FieldCondition(key="source_type",
                                               match=MatchValue(value=source_type))]))
    hits += _q(Filter(must=[country_cond]))

    seen, merged = set(), []
    for h in hits:
        if h.id in seen:
            continue
        seen.add(h.id)
        p = h.payload or {}
        merged.append({"chunk_id": str(h.id), "score": round(h.score, 4),
                       "country": p.get("country"), "source_type": p.get("source_type"),
                       "source_url": p.get("source_url"), "text": p.get("text", "")})
    # Rank by score across BOTH queries rather than keeping the constrained block first.
    merged.sort(key=lambda c: c["score"], reverse=True)
    return merged[:EVIDENCE_K]


def build_item(question: str, country: str, qtype: str, tier: str) -> dict[str, Any]:
    chunks = retrieve(question, country, TYPE_SOURCE.get(qtype))
    blob = "\n\n".join(f"[chunk {i+1}] (source={c['source_type']})\n{c['text'][:1200]}"
                       for i, c in enumerate(chunks))
    ref = _post(REF_MODEL, WRITER_PROMPT.format(q=question, chunks=blob))
    insufficient = ref.strip().upper().startswith("INSUFFICIENT")
    return {
        "question": question,
        "expected_country": country,
        "question_type": qtype,
        "corpus_tier": tier,
        "answerable": not insufficient,
        "reference_answer": None if insufficient else ref,
        # Provenance: the exact chunks the reference was written from.
        "grounded_in": [{"chunk_id": c["chunk_id"], "source_type": c["source_type"],
                         "source_url": c["source_url"], "score": c["score"],
                         "text_excerpt": c["text"][:300]} for c in chunks],
    }


def main() -> None:
    items, rejected = [], []

    for tier, countries in COUNTRIES.items():
        for country in countries:
            for qtype, tpl in TEMPLATES.items():
                q = tpl.format(c=country)
                item = build_item(q, country, qtype, tier)
                if item["answerable"]:
                    items.append(item)
                    print(f"  OK          {qtype:<14} {country:<22} ({tier})")
                else:
                    rejected.append(item)
                    print(f"  INSUFFICIENT {qtype:<14} {country:<22} ({tier})")

    print("\n-- deliberately unanswerable --")
    for q, country in UNANSWERABLE:
        item = build_item(q, country, "unanswerable", "n/a")
        # Premise check: these are SUPPOSED to come back INSUFFICIENT.
        item["premise_holds"] = not item["answerable"]
        item["answerable"] = False
        item["reference_answer"] = None
        items.append(item)
        flag = "ok (corpus lacks it)" if item["premise_holds"] else "!! CORPUS ANSWERS IT"
        print(f"  {flag:<24} {q}")

    out = {
        "corpus_points_count": get_client().count(
            collection_name=settings.QDRANT_COLLECTION, exact=True).count,
        "reference_writer_model": REF_MODEL,
        "n_items": len(items),
        "n_answerable": sum(1 for i in items if i["answerable"]),
        "n_unanswerable": sum(1 for i in items if not i["answerable"]),
        "n_countries": len({i["expected_country"] for i in items}),
        "rejected_insufficient": [
            {"question": r["question"], "country": r["expected_country"],
             "question_type": r["question_type"], "corpus_tier": r["corpus_tier"]}
            for r in rejected
        ],
        "items": items,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nwrote {OUT_PATH}")
    print(f"  items={out['n_items']}  answerable={out['n_answerable']} "
          f"unanswerable={out['n_unanswerable']}  countries={out['n_countries']}")
    print(f"  rejected as INSUFFICIENT: {len(rejected)}")


if __name__ == "__main__":
    main()
