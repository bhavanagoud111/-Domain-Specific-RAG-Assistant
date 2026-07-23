"""Week 7 diagnostic — are the missing relevant chunks BELOW the window, or absent entirely?

THE FORK THIS SETTLES
---------------------
Step 1 measured a ceiling of 79.9% and a retrieval efficiency of 55%: roughly 36pp of
precision exists in the corpus and is not being retrieved. There are exactly two places
that missing material can be, and they imply opposite next steps:

  (a) The relevant chunks ARE surfaced by the embedding, just ranked below the 8-chunk
      window. Then recall@20 >> recall@8, a reranker (retrieve 20 -> LLM-rerank to 8) can
      reach them, and it is the right fix.

  (b) The relevant chunks are NOT surfaced at any depth. Then recall@20 ~ recall@8, the
      embedding/query is the constraint, no reranker can help, and optimising the ranker
      is wasted effort.

NO JUDGE CALLS. Relevance is not re-judged: the R sets (``relevant_chunk_ids``) come from
the Step 1 ceiling analysis, which judged every chunk in every country's corpus with the
blinded judge. This script only asks WHERE those already-known-relevant chunks rank.

TWO CANDIDATE GENERATORS, MEASURED SEPARATELY
---------------------------------------------
* ``subq`` -- the rewriter's sub-queries, merged by max cosine. This is production.
* ``raw``  -- the unmodified user question, one query. Deterministic, and it isolates the
  embedding's own capability from the rewriter's behaviour.

Both are reported because they answer different questions. If ``raw`` reaches chunks that
``subq`` does not at the same depth, the rewriter is discarding recall and the fix is
upstream of any reranker. Week 6 found the raw question 6.2x more precise on the 5 worst
questions, so this is a live hypothesis, not a formality.

DEPTH SEMANTICS -- stated because it is easy to get subtly wrong
---------------------------------------------------------------
* ``production`` = per-sub-query ``limit=TOP_K`` (5), merged, top 8. This is EXACTLY the
  window the eval measured, and the honest baseline for "recall@8".
* ``depth N``    = per-sub-query ``limit=N``, merged, top N. This is what a reranker would
  be handed. Note depth 8 is therefore slightly deeper than production (it draws 8 per
  sub-query rather than 5), so the two are reported separately rather than conflated.

BEST-CASE RERANKER PRECISION
----------------------------
A perfect reranker over a depth-N candidate list fills the 8-slot window with as many
relevant chunks as that list contains:

    best_precision@8 = min(|R and topN|, 8) / 8

That is an upper bound no real reranker reaches -- it assumes the reranker never makes a
mistake. It is the correct number for "how much could this recover AT BEST".

Corpus is FROZEN and only read. Run:
    PYTHONPATH=. python evaluation/depth_diagnostic.py
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import settings
from graph.wanderrag_graph import TOP_K, _QDRANT, _detect_country, _embed, rewrite_node

HERE = Path(__file__).resolve().parent
CEILING = HERE / "ceiling.json"
EVAL_SET = HERE / "eval_set.json"
OUT = HERE / "depth_diagnostic.json"

DEPTHS = [8, 20, 50]
WINDOW = TOP_K + 3          # 8 -- the slots a reranker would fill
TIERS = ["rich", "mid", "thin"]
TYPES = ["visa", "health", "safety", "what_to_visit"]


def ranked_ids(queries: list[str], country: str | None, limit: int) -> list[str]:
    """Query each sub-query at `limit`, merge by max cosine, return ranked chunk ids."""
    qfilter = (
        Filter(must=[FieldCondition(key="country", match=MatchValue(value=country))])
        if country else None
    )
    best: dict[str, float] = {}
    for q in queries:
        vec = _embed("depth_diag", q)
        hits = _QDRANT.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=vec, query_filter=qfilter, limit=limit, with_payload=False,
        ).points
        for h in hits:
            pid = str(h.id)
            if pid not in best or float(h.score) > best[pid]:
                best[pid] = float(h.score)
    return [pid for pid, _ in sorted(best.items(), key=lambda kv: kv[1], reverse=True)]


def analyse(item: dict[str, Any], R: set[str]) -> dict[str, Any]:
    q = item["question"]
    country = _detect_country(q)
    rec: dict[str, Any] = {
        "question": q,
        "expected_country": item["expected_country"],
        "detected_country": country,
        "country_ok": country == item["expected_country"],
        "question_type": item["question_type"],
        "corpus_tier": item["corpus_tier"],
        "R": len(R),
    }

    subs = rewrite_node({"original_query": q, "retry_count": 0, "trace": []})["sub_queries"]
    rec["sub_queries"] = subs

    for mode, queries in (("subq", subs), ("raw", [q])):
        m: dict[str, Any] = {}
        # production window: limit=TOP_K per sub-query, top 8
        prod = ranked_ids(queries, country, TOP_K)[:WINDOW]
        m["production_hits"] = len(R & set(prod))
        m["production_n"] = len(prod)

        deepest = ranked_ids(queries, country, max(DEPTHS))
        for d in DEPTHS:
            topd = set(deepest[:d])
            hits = len(R & topd)
            m[f"hits@{d}"] = hits
            m[f"recall@{d}"] = (hits / len(R)) if R else None
            # A perfect reranker over this candidate list fills 8 slots.
            m[f"best_precision@8_from_{d}"] = min(hits, WINDOW) / WINDOW
        m["hits_ranks_9_20"] = m["hits@20"] - m["hits@8"]
        m["hits_ranks_21_50"] = m["hits@50"] - m["hits@20"]
        m["pool_at_50"] = len(deepest)
        rec[mode] = m
    return rec


def agg(rows: list[dict], mode: str) -> dict[str, Any]:
    """Micro-averaged recall (sum hits / sum R) plus macro means."""
    tot_R = sum(r["R"] for r in rows)
    out: dict[str, Any] = {"n": len(rows), "R_total": tot_R,
                           "R_mean": statistics.mean(r["R"] for r in rows) if rows else 0}
    for d in DEPTHS:
        out[f"recall@{d}"] = (sum(r[mode][f"hits@{d}"] for r in rows) / tot_R) if tot_R else None
        out[f"best_prec_from_{d}"] = statistics.mean(
            r[mode][f"best_precision@8_from_{d}"] for r in rows) if rows else None
    out["prod_recall"] = (sum(r[mode]["production_hits"] for r in rows) / tot_R) if tot_R else None
    out["prod_precision"] = statistics.mean(
        r[mode]["production_hits"] / r[mode]["production_n"] for r in rows
        if r[mode]["production_n"]) if rows else None
    out["hits_9_20_total"] = sum(r[mode]["hits_ranks_9_20"] for r in rows)
    out["hits_9_20_mean"] = statistics.mean(r[mode]["hits_ranks_9_20"] for r in rows) if rows else 0
    out["hits_21_50_total"] = sum(r[mode]["hits_ranks_21_50"] for r in rows)
    return out


def pct(x: float | None) -> str:
    return "   n/a" if x is None else f"{100*x:5.1f}%"


def table(title: str, groups: list[tuple[str, list[dict]]], mode: str) -> None:
    print(f"\n{title}   [candidate generator: {mode}]")
    print(f"  {'':<16}{'Qs':>4}{'ΣR':>6}{'rec@8':>8}{'rec@20':>8}{'rec@50':>8}"
          f"{'@9-20':>8}{'/q':>6}{'@21-50':>8}")
    for name, rows in groups:
        if not rows:
            continue
        a = agg(rows, mode)
        print(f"  {name:<16}{a['n']:>4}{a['R_total']:>6}"
              f"{pct(a['recall@8']):>8}{pct(a['recall@20']):>8}{pct(a['recall@50']):>8}"
              f"{a['hits_9_20_total']:>8}{a['hits_9_20_mean']:>6.1f}"
              f"{a['hits_21_50_total']:>8}")


def main() -> None:
    ceil = {r["question"]: r for r in json.loads(CEILING.read_text(encoding="utf-8"))["results"]}
    items = json.loads(EVAL_SET.read_text(encoding="utf-8"))["items"]

    done: dict[str, Any] = {}
    if OUT.exists():
        done = {r["question"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))["results"]}
        print(f"[resume] {len(done)} done")

    rows: list[dict[str, Any]] = []
    for i, it in enumerate(items, 1):
        q = it["question"]
        if q in done:
            rows.append(done[q])
            continue
        R = set(ceil[q]["relevant_chunk_ids"])
        rec = analyse(it, R)
        rows.append(rec)
        OUT.write_text(json.dumps({"depths": DEPTHS, "window": WINDOW, "results": rows},
                                  indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  [{i}/{len(items)}] {it['question_type']:<14}{it['expected_country']:<22}"
              f"{it['corpus_tier']:<5} R={rec['R']:>3} "
              f"subq r@8={pct(rec['subq']['recall@8'])} r@20={pct(rec['subq']['recall@20'])} "
              f"r@50={pct(rec['subq']['recall@50'])}", flush=True)

    scored = [r for r in rows if r["R"] > 0]      # excludes the 5 unanswerable (R=0)
    rich = [r for r in scored if r["corpus_tier"] == "rich"]

    print("\n" + "=" * 92)
    print(f"DEPTH DIAGNOSTIC — {len(scored)} questions with R>0 "
          f"(the 5 unanswerable have R=0 and are excluded)")
    print(f"country detection correct: {sum(1 for r in rows if r['country_ok'])}/{len(rows)}")
    print("=" * 92)

    for mode in ("subq", "raw"):
        by_tier = defaultdict(list)
        by_type = defaultdict(list)
        for r in scored:
            by_tier[r["corpus_tier"]].append(r)
            by_type[r["question_type"]].append(r)
        table("OVERALL", [("ALL", scored)], mode)
        table("BY CORPUS TIER", [(t, by_tier[t]) for t in TIERS], mode)
        table("BY QUESTION TYPE", [(t, by_type[t]) for t in TYPES], mode)

    # ---- the decision numbers -------------------------------------------
    print("\n" + "=" * 92)
    print("BEST-CASE PRECISION FROM A PERFECT RERANKER  (upper bound; no real reranker reaches it)")
    print("=" * 92)
    print(f"  {'scope':<16}{'mode':<6}{'current':>9}{'rerank20':>10}{'rerank50':>10}"
          f"{'ceiling':>9}")
    for name, rows_ in (("ALL", scored), ("rich", rich)):
        for mode in ("subq", "raw"):
            a = agg(rows_, mode)
            ceil_mean = statistics.mean(
                min(r["R"], WINDOW) / WINDOW for r in rows_)
            print(f"  {name:<16}{mode:<6}{pct(a['prod_precision']):>9}"
                  f"{pct(a['best_prec_from_20']):>10}{pct(a['best_prec_from_50']):>10}"
                  f"{pct(ceil_mean):>9}")

    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
