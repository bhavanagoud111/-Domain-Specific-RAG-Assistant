"""Week 7 Part 4 — does narrowing the window starve answers of citations? LIVE, 10 queries.

D2 raises precision by retrieving FEWER chunks. Precision is a ratio, so shrinking the
denominator flatters it even when the answer gets worse. Week 4 widened the window to
TOP_K+3 = 8 specifically for citation richness, and the citation-keyed gate passes only on
>=1 resolved citation -- so a narrower window risks flipping passes into low-confidence
refusals. That risk is invisible to every offline projection in ``feasibility.py``, which is
why it is measured live here.

WHAT IS VARIED, AND HOW -- no source file is modified.
``retrieve_node`` reads the module-level ``TOP_K`` at call time in exactly two places: the
fetch limit (``TOP_K + 3``) and the window slice (``[: TOP_K + 3]``). Setting ``TOP_K = 2``
in-process therefore yields fetch=5 and window=5, which with C1's single generator is
exactly the top-5 window. Nothing else in the graph reads ``TOP_K``. The gate, MAX_RETRIES,
the country filter, chunking and generation are untouched.

3 runs per query per config, because generation runs at temperature=0.3 and Week 6 measured
gate verdicts flipping at the boundary on single runs. The question "did anything that
passed at 8 fail at 5" cannot be answered by 1 sample.

Run:  PYTHONPATH=. python evaluation/window_citation_check.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import graph.wanderrag_graph as wg

HERE = Path(__file__).resolve().parent
OUT = HERE / "window_citation_check.json"
RUNS = 3

# Mix of tiers and question types; the four required cases are marked.
QUERIES = [
    ("Japan",        "what_to_visit", "rich", "What should I visit in Japan?"),            # required
    ("Canada",       "what_to_visit", "thin", "What should I visit in Canada?"),           # required
    ("Japan",        "visa",          "rich", "Do I need a visa to visit Japan as a US citizen?"),  # required
    ("-",            "nonsense",      "n/a",  "asdkjasd current safety xyz nonsense country"),      # required
    ("Italy",        "safety",        "mid",  "How safe is it to travel in Italy right now?"),
    ("Thailand",     "health",        "thin", "What vaccinations or health precautions do I need for Thailand?"),
    ("Singapore",    "what_to_visit", "rich", "What should I visit in Singapore?"),
    ("Norway",       "safety",        "thin", "How safe is it to travel in Norway right now?"),
    ("Greece",       "what_to_visit", "rich", "What should I visit in Greece?"),
    ("United Arab Emirates", "what_to_visit", "thin", "What should I visit in United Arab Emirates?"),
]


def run_config(window: int) -> dict[str, list[dict]]:
    """window=8 -> TOP_K=5 (production C1); window=5 -> TOP_K=2."""
    wg.TOP_K = window - 3
    out: dict[str, list[dict]] = {}
    for country, qtype, tier, q in QUERIES:
        runs = []
        for i in range(RUNS):
            st = wg.run_query(q, run_id=f"win{window}_{abs(hash(q))%10**6}_{i}")
            runs.append({
                "citations": st.get("citations_resolved", 0),
                "gate_passed": st.get("citations_resolved", 0) >= 1,
                "low_confidence": bool(st.get("low_confidence")),
                "thin_pass": bool(st.get("thin_pass")),
                "n_retrieved": len(st.get("retrieved_chunks", []) or []),
                "retries": st.get("retry_count", 0),
            })
        out[q] = runs
        cits = [r["citations"] for r in runs]
        print(f"  w={window} {qtype:<14}{country:<22} cits={cits} "
              f"gate={[r['gate_passed'] for r in runs]} n_ret={runs[0]['n_retrieved']}",
              flush=True)
    return out


def main() -> None:
    print(f"LIVE window comparison — {len(QUERIES)} queries x {RUNS} runs x 2 configs "
          f"= {len(QUERIES)*RUNS*2} graph runs\n")
    print("window 8 (production C1):")
    w8 = run_config(8)
    print("\nwindow 5 (D2):")
    w5 = run_config(5)
    wg.TOP_K = 5   # restore

    OUT.write_text(json.dumps({"runs_per_config": RUNS, "window8": w8, "window5": w5},
                              indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 100)
    print("CITATION SUPPLY AND GATE STABILITY — window 8 vs window 5")
    print("=" * 100)
    print(f"  {'type':<14}{'country':<22}{'cits@8':>16}{'cits@5':>16}"
          f"{'mean8':>7}{'mean5':>7}{'gate8':>8}{'gate5':>8}{'REGRESSION':>12}")
    regressions = []
    for country, qtype, tier, q in QUERIES:
        a, b = w8[q], w5[q]
        ca = [r["citations"] for r in a]
        cb = [r["citations"] for r in b]
        pa = sum(1 for r in a if r["gate_passed"])
        pb = sum(1 for r in b if r["gate_passed"])
        # A regression that matters: it passed at 8 (any run) and never passes at 5.
        reg = pa > 0 and pb == 0
        if reg:
            regressions.append((qtype, country))
        print(f"  {qtype:<14}{country:<22}{str(ca):>16}{str(cb):>16}"
              f"{statistics.mean(ca):>7.1f}{statistics.mean(cb):>7.1f}"
              f"{pa:>5}/{RUNS}{pb:>6}/{RUNS}{('YES' if reg else ''):>12}")

    m8 = statistics.mean(r["citations"] for q in w8 for r in w8[q])
    m5 = statistics.mean(r["citations"] for q in w5 for r in w5[q])
    p8 = sum(1 for q in w8 for r in w8[q] if r["gate_passed"])
    p5 = sum(1 for q in w5 for r in w5[q] if r["gate_passed"])
    t8 = sum(1 for q in w8 for r in w8[q] if r["thin_pass"])
    t5 = sum(1 for q in w5 for r in w5[q] if r["thin_pass"])
    tot = len(QUERIES) * RUNS

    print("\n  " + "-" * 96)
    print(f"  mean citations resolved : {m8:.2f} (w8) -> {m5:.2f} (w5)   "
          f"[{100*(m5-m8)/m8:+.1f}%]")
    print(f"  gate passes             : {p8}/{tot} -> {p5}/{tot}")
    print(f"  THIN passes (1 citation): {t8}/{tot} -> {t5}/{tot}   "
          f"<- fragile passes; more is worse")
    print(f"  pass->fail regressions  : {len(regressions)}  {regressions or ''}")

    print("\n  nonsense query must resolve 0 citations in BOTH configs:")
    nq = QUERIES[3][3]
    print(f"    w8: {[r['citations'] for r in w8[nq]]}   w5: {[r['citations'] for r in w5[nq]]}")

    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
