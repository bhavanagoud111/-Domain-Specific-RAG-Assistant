"""Week 7 — what does RRF actually CHANGE about the retrieved window?

This is a mechanism diagnostic, not a quality measurement. It answers three questions the
headline eval cannot, because it isolates the ranking change from every other source of
run-to-run variance:

  1. OVERLAP. RRF is normally motivated by rank AGREEMENT across sublists. That mechanism
     requires the sublists to overlap. If the rewriter's sub-queries retrieve disjoint
     sets, every chunk contributes exactly one 1/(k+rank) term and RRF collapses into
     round-robin INTERLEAVING of the sublists. Those are different interventions and the
     write-up must not claim the first if the system is doing the second.

  2. SET CHURN. Precision is set-based (n_relevant / n_retrieved), so reordering alone
     cannot move it. Only chunks that enter or leave the top-8 window can. This measures
     how many chunks actually swap per question -- the true size of the intervention.

  3. SOURCE MIX. If interleaving is the mechanism, its visible effect should be forcing
     source-type diversity into a window that cosine-sorting let one source dominate.

Method: retrieve ONCE per question, then rank the identical hit pool both ways -- old
(max-cosine sort) and new (RRF) -- so the comparison is exact and free of sampling noise.
No generation, no judging: embeddings only.

Run:  PYTHONPATH=. python evaluation/rrf_mechanism.py
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import settings
from graph.wanderrag_graph import RRF_K, TOP_K, _QDRANT, _embed, rewrite_node

HERE = Path(__file__).resolve().parent
EVAL_SET = HERE / "eval_set.json"
OUT = HERE / "rrf_mechanism.json"
WINDOW = TOP_K + 3


def analyse(question: str) -> dict[str, Any]:
    state = {"original_query": question, "retry_count": 0, "trace": []}
    rw = rewrite_node(state)
    subs = rw["sub_queries"]
    country = rw["country"]
    qfilter = (
        Filter(must=[FieldCondition(key="country", match=MatchValue(value=country))])
        if country else None
    )

    sublists: list[list[tuple[str, float]]] = []
    payload: dict[str, dict] = {}
    for sub in subs:
        vec = _embed("rrf_diag", sub)
        hits = _QDRANT.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=vec, query_filter=qfilter, limit=TOP_K, with_payload=True,
        ).points
        lst = []
        for h in hits:
            pid = str(h.id)
            lst.append((pid, float(h.score)))
            p = h.payload or {}
            if pid not in payload or float(h.score) > payload[pid]["score"]:
                payload[pid] = {"score": float(h.score), "source_type": p.get("source_type")}
        sublists.append(lst)

    # --- old ranking: union sorted by max cosine -------------------------
    old = sorted(payload.items(), key=lambda kv: kv[1]["score"], reverse=True)[:WINDOW]
    old_ids = [pid for pid, _ in old]

    # --- new ranking: RRF, cosine tie-break ------------------------------
    rrf: dict[str, float] = {}
    n_hit: Counter = Counter()
    for lst in sublists:
        for rank, (pid, _s) in enumerate(lst, start=1):
            rrf[pid] = rrf.get(pid, 0.0) + 1.0 / (RRF_K + rank)
            n_hit[pid] += 1
    new = sorted(payload.items(),
                 key=lambda kv: (rrf[kv[0]], kv[1]["score"]), reverse=True)[:WINDOW]
    new_ids = [pid for pid, _ in new]

    pool = len(payload)
    entered = [p for p in new_ids if p not in old_ids]
    left = [p for p in old_ids if p not in new_ids]

    return {
        "question": question,
        "n_subqueries": len(subs),
        "pool_size": pool,
        "pool_capped": pool <= WINDOW,          # <= window => set cannot change
        "max_sublist_hits": max(n_hit.values()) if n_hit else 0,
        "n_chunks_in_multiple_sublists": sum(1 for v in n_hit.values() if v > 1),
        "set_changed": sorted(old_ids) != sorted(new_ids),
        "n_swapped": len(entered),
        "order_changed": old_ids != new_ids,
        "old_sources": Counter(payload[p]["source_type"] for p in old_ids),
        "new_sources": Counter(payload[p]["source_type"] for p in new_ids),
    }


def main() -> None:
    items = json.loads(EVAL_SET.read_text(encoding="utf-8"))["items"]
    out = []
    for i, it in enumerate(items, 1):
        try:
            r = analyse(it["question"])
        except Exception as exc:
            print(f"  [{i}/{len(items)}] ERROR {type(exc).__name__}: {exc}")
            continue
        r["question_type"] = it["question_type"]
        r["corpus_tier"] = it["corpus_tier"]
        out.append(r)
        print(f"  [{i}/{len(items)}] pool={r['pool_size']:>2} "
              f"multi={r['n_chunks_in_multiple_sublists']:>2} "
              f"swapped={r['n_swapped']} {it['question_type']:<14} {it['expected_country']}",
              flush=True)
        OUT.write_text(json.dumps(out, indent=2, default=dict), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"questions analysed            : {len(out)}")
    print(f"mean pool size                : {statistics.mean(r['pool_size'] for r in out):.2f}")
    capped = sum(1 for r in out if r['pool_capped'])
    print(f"pool <= {WINDOW} (set CANNOT change) : {capped}/{len(out)} "
          f"({100*capped/len(out):.1f}%)")
    multi = sum(1 for r in out if r['n_chunks_in_multiple_sublists'] > 0)
    print(f"questions w/ ANY chunk in >1 sublist: {multi}/{len(out)} "
          f"({100*multi/len(out):.1f}%)   <- RRF 'agreement' mechanism")
    changed = sum(1 for r in out if r['set_changed'])
    print(f"questions where the SET changed : {changed}/{len(out)} "
          f"({100*changed/len(out):.1f}%)")
    print(f"mean chunks swapped per question: "
          f"{statistics.mean(r['n_swapped'] for r in out):.2f}")

    old_s: Counter = Counter()
    new_s: Counter = Counter()
    for r in out:
        old_s.update(r["old_sources"])
        new_s.update(r["new_sources"])
    print("\nsource_type composition of the retrieved window:")
    print(f"  {'source':<14}{'cosine':>9}{'rrf':>9}{'delta':>9}")
    for k in sorted(set(old_s) | set(new_s), key=lambda x: -(old_s[x] + new_s[x])):
        print(f"  {str(k):<14}{old_s[k]:>9}{new_s[k]:>9}{new_s[k]-old_s[k]:>+9}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
