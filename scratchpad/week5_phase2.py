"""Week 5 / Phase 2 — verify the citation-keyed self_check against the Week 4 baseline.

Runs the SAME 9 "what should I visit in X" queries, then the 5 canonical TEST_QUERIES.
No re-embedding, no re-ingestion, no retrieval/TOP_K/filter/chunking changes.
"""
from __future__ import annotations

import json
from pathlib import Path

from graph.wanderrag_graph import TEST_QUERIES, run_query, session_cost

OUT = Path(__file__).parent / "week5_phase2_results.json"

# Country -> the query used. Full official names so _detect_country fires the filter.
NINE = [
    ("Italy", "What should I visit in Italy?"),
    ("Mexico", "What should I visit in Mexico?"),
    ("Norway", "What should I visit in Norway?"),
    ("Thailand", "What should I visit in Thailand?"),
    ("Canada", "What should I visit in Canada?"),
    ("UAE", "What should I visit in the United Arab Emirates?"),
    ("Japan", "What should I visit in Japan?"),
    ("Singapore", "What should I visit in Singapore?"),
    ("Brazil", "What should I visit in Brazil?"),
]

# Week 4 baseline, transcribed from logs/week4_investigation.md section 2.
WK4 = {
    "Italy":     {"verdict": "INSUFFICIENT", "retries": 2, "citations": 4},
    "Mexico":    {"verdict": "sufficient",   "retries": 1, "citations": 3},
    "Norway":    {"verdict": "sufficient",   "retries": 0, "citations": 2},
    "Thailand":  {"verdict": "INSUFFICIENT", "retries": 2, "citations": 1},
    "Canada":    {"verdict": "INSUFFICIENT", "retries": 2, "citations": 0},
    "UAE":       {"verdict": "INSUFFICIENT", "retries": 2, "citations": 1},
    "Japan":     {"verdict": "INSUFFICIENT", "retries": 2, "citations": 4},
    "Singapore": {"verdict": "sufficient",   "retries": 1, "citations": 4},
    "Brazil":    {"verdict": "INSUFFICIENT", "retries": 2, "citations": 1},
}
WK4_PART2_COST_USD = 0.077  # week4_investigation.md "Cost of this investigation"

# What the brief says must happen. Anything else => STOP.
EXPECTED = {
    "Italy": "sufficient", "Thailand": "sufficient", "UAE": "sufficient",
    "Japan": "sufficient", "Brazil": "sufficient",          # flagged-but-cited -> flip
    "Canada": "INSUFFICIENT",                                # 0 citations -> stays flagged
    "Mexico": "sufficient", "Norway": "sufficient", "Singapore": "sufficient",  # stay passing
}


def summarize(state) -> dict:
    chunks = state.get("retrieved_chunks", [])
    country = state.get("country")
    return {
        "verdict": "sufficient" if state.get("self_check_passed") else "INSUFFICIENT",
        "retries": state.get("retry_count", 0),
        "citations": state.get("citations_resolved", len(state.get("citations", []))),
        "low_confidence": bool(state.get("low_confidence")),
        "country": country,
        "n_chunks": len(chunks),
        "cross_country": sum(
            1 for c in chunks if country and c.get("country") != country
        ),
        "gate_method": next(
            (t.get("method") for t in reversed(state.get("trace", []))
             if t.get("node") == "self_check"), None),
        "answer_head": (state.get("final_answer") or "")[:160].replace("\n", " "),
        "cited_urls": [c["source_url"] for c in state.get("citations", [])],
    }


def main() -> None:
    results = {"nine": {}, "canonical": {}}

    print("=" * 96)
    print('PHASE 2a — the 9 "what should I visit in X" queries')
    print("=" * 96)
    nine_cost = 0.0
    for label, q in NINE:
        rid = f"wk5_p2_{label}"
        s = run_query(q, run_id=rid)
        r = summarize(s)
        c = session_cost(rid)
        r["cost_usd"] = c["cost_usd"]
        r["tokens"] = c["total_tokens"]
        r["calls"] = c["calls"]
        nine_cost += c["cost_usd"]
        results["nine"][label] = r
        b = WK4[label]
        ok = "OK " if r["verdict"] == EXPECTED[label] else "DEVIATION"
        print(f"  {ok:9} {label:10} wk4[{b['verdict']:12} r={b['retries']} c={b['citations']}]"
              f" -> wk5[{r['verdict']:12} r={r['retries']} c={r['citations']}]"
              f"  xcountry={r['cross_country']} ${r['cost_usd']:.4f}")

    print("\n" + "=" * 96)
    print("PHASE 2b — the 5 canonical queries (regression check)")
    print("=" * 96)
    canon_cost = 0.0
    for i, q in enumerate(TEST_QUERIES, 1):
        rid = f"wk5_p2_canon{i}"
        s = run_query(q, run_id=rid)
        r = summarize(s)
        c = session_cost(rid)
        r["cost_usd"] = c["cost_usd"]
        r["tokens"] = c["total_tokens"]
        r["query"] = q
        canon_cost += c["cost_usd"]
        results["canonical"][f"q{i}"] = r
        print(f"  q{i} {q[:44]:46} country={str(r['country']):20} "
              f"{r['verdict']:12} r={r['retries']} c={r['citations']} "
              f"lowconf={r['low_confidence']} ${r['cost_usd']:.4f}")

    # --- verdicts -----------------------------------------------------------
    deviations = [
        f"{k}: expected {EXPECTED[k]}, got {v['verdict']}"
        for k, v in results["nine"].items() if v["verdict"] != EXPECTED[k]
    ]
    nonsense = results["canonical"]["q5"]
    nonsense_ok = nonsense["citations"] == 0 and nonsense["low_confidence"]

    wk4_retries = sum(b["retries"] for b in WK4.values())
    wk5_retries = sum(v["retries"] for v in results["nine"].values())

    results["summary"] = {
        "deviations": deviations,
        "nonsense_still_0_citations_and_low_conf": nonsense_ok,
        "retries_wk4": wk4_retries, "retries_wk5": wk5_retries,
        "nine_cost_wk4_usd": WK4_PART2_COST_USD,
        "nine_cost_wk5_usd": round(nine_cost, 6),
        "canonical_cost_wk5_usd": round(canon_cost, 6),
        "nine_tokens_wk5": sum(v["tokens"] for v in results["nine"].values()),
    }

    print("\n" + "#" * 96)
    print(f"  retry loops (9 queries): wk4={wk4_retries}  ->  wk5={wk5_retries}")
    print(f"  cost (9 queries)       : wk4=${WK4_PART2_COST_USD}  ->  wk5=${nine_cost:.4f}"
          f"  (delta ${nine_cost - WK4_PART2_COST_USD:+.4f})")
    print(f"  nonsense query intact  : {nonsense_ok} "
          f"(citations={nonsense['citations']}, low_conf={nonsense['low_confidence']})")
    print(f"  cross-country chunks   : "
          f"{sum(v['cross_country'] for v in results['nine'].values())}")
    print(f"  DEVIATIONS             : {deviations or 'none'}")
    print("#" * 96)

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
