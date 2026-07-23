"""Before/after comparison of two eval runs.

Compares two eval_results.json files produced from the SAME eval set, the SAME frozen
corpus (2,319) and the SAME blinded judge, differing only in the retrieval change under
test. Written for the Week 6 rewriter fix; parameterised in Week 7 so the same comparator
serves the RRF change without editing the Week 6 defaults out of existence.

Reports precision / faithfulness / gate correctness / correct-country overall, by tier and
by question type, plus the flip count and the unanswerable-refusal check.

Run:  PYTHONPATH=. python evaluation/compare_runs.py [BEFORE.json] [AFTER.json]
      (defaults reproduce the Week 6 rewriter-fix comparison)
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BEFORE = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "eval_results_BEFORE_rewriter_fix.json"
AFTER = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "eval_results.json"

TIERS = ["rich", "mid", "thin", "n/a"]
TYPES = ["visa", "health", "safety", "what_to_visit", "unanswerable"]


def mean(xs):
    v = [x for x in xs if x is not None]
    return statistics.mean(v) if v else None


def agg(rows: list[dict]) -> dict[str, Any]:
    return {
        "n": len(rows),
        "precision": mean([r.get("mean_precision") for r in rows]),
        "faithfulness": mean([r.get("mean_faithfulness") for r in rows]),
        "gate": mean([r.get("gate_correct_rate") for r in rows]),
        "country": mean([r.get("expected_country_retrieved_rate") for r in rows]),
        "flips": sum(1 for r in rows if r.get("gate_flipped")),
        "flippable": sum(1 for r in rows if r.get("n_runs", 1) > 1),
    }


def pct(x):
    return "   n/a" if x is None else f"{100*x:5.1f}%"


def delta(a, b):
    if a is None or b is None:
        return "     -"
    d = 100 * (b - a)
    return f"{d:+6.1f}"


def row(label, A, B):
    return (f"{label:<20}{A['n']:>4}  "
            f"{pct(A['precision'])} {pct(B['precision'])} {delta(A['precision'],B['precision'])}   "
            f"{pct(A['faithfulness'])} {pct(B['faithfulness'])} {delta(A['faithfulness'],B['faithfulness'])}   "
            f"{pct(A['gate'])} {pct(B['gate'])} {delta(A['gate'],B['gate'])}   "
            f"{pct(A['country'])} {pct(B['country'])}")


def main() -> None:
    before = {r["question"]: r for r in json.loads(BEFORE.read_text())["results"] if not r.get("error")}
    after = {r["question"]: r for r in json.loads(AFTER.read_text())["results"] if not r.get("error")}
    common = [q for q in before if q in after]

    A = [before[q] for q in common]
    B = [after[q] for q in common]

    print(f"questions compared: {len(common)}   "
          f"(before {len(before)}, after {len(after)})")
    hdr = (f"{'':<20}{'Qs':>4}  {'PRECISION':^22}   {'FAITHFULNESS':^22}   "
           f"{'GATE':^22}   {'COUNTRY':^13}")
    sub = (f"{'':<20}{'':>4}  {'before':>6} {'after':>6} {'Δpp':>6}   "
           f"{'before':>6} {'after':>6} {'Δpp':>6}   {'before':>6} {'after':>6} {'Δpp':>6}   "
           f"{'before':>6} {'after':>6}")

    print("\n" + "=" * 108)
    print("OVERALL")
    print("=" * 108)
    print(hdr); print(sub); print("-" * 108)
    print(row("ALL", agg(A), agg(B)))

    print("\n" + "=" * 108)
    print("BY CORPUS TIER")
    print("=" * 108)
    print(hdr); print(sub); print("-" * 108)
    for t in TIERS:
        a = [r for r in A if r["corpus_tier"] == t]
        b = [after[r["question"]] for r in a]
        if a:
            print(row(t, agg(a), agg(b)))

    print("\n" + "=" * 108)
    print("BY QUESTION TYPE")
    print("=" * 108)
    print(hdr); print(sub); print("-" * 108)
    for t in TYPES:
        a = [r for r in A if r["question_type"] == t]
        b = [after[r["question"]] for r in a]
        if a:
            print(row(t, agg(a), agg(b)))

    # ---- flips ----
    ga, gb = agg(A), agg(B)
    print("\n" + "=" * 108)
    print("GATE FLIPS (questions sampled 3x whose verdict was not identical across runs)")
    print("=" * 108)
    print(f"  before: {ga['flips']} / {ga['flippable']}      after: {gb['flips']} / {gb['flippable']}")
    for label, rows in (("before", A), ("after", B)):
        f = [r for r in rows if r.get("gate_flipped")]
        for r in f:
            print(f"    {label:<7} {r['corpus_tier']:<5} {r['question_type']:<14} "
                  f"{r['expected_country']:<22} verdicts={r['gate_verdicts']}")

    # ---- unanswerable safety check ----
    print("\n" + "=" * 108)
    print("UNANSWERABLE REFUSAL CHECK  (must still resolve 0 citations)")
    print("=" * 108)
    broke = []
    for q in common:
        r = after[q]
        if r["question_type"] != "unanswerable":
            continue
        ok = all(v is False for v in r["gate_verdicts"])
        if not ok:
            broke.append(r)
        print(f"  {'OK  ' if ok else 'BROKE'} {r['expected_country']:<12} "
              f"before={before[q]['gate_verdicts']}  after={r['gate_verdicts']}  "
              f"{q[:46]}")
    print(f"\n  => {'ALL 5 STILL REFUSE CORRECTLY' if not broke else f'!!! {len(broke)} BROKE -- STOP !!!'}")

    # ---- per-question biggest movers ----
    print("\n" + "=" * 108)
    print("BIGGEST PRECISION MOVERS")
    print("=" * 108)
    movers = []
    for q in common:
        pa, pb = before[q].get("mean_precision"), after[q].get("mean_precision")
        if pa is not None and pb is not None:
            movers.append((pb - pa, q, pa, pb, before[q]["corpus_tier"], before[q]["question_type"]))
    movers.sort(reverse=True)
    print("  improved:")
    for d, q, pa, pb, t, qt in movers[:6]:
        print(f"    {d*100:+6.1f}pp  {pa:.3f} -> {pb:.3f}  [{t}/{qt}] {q[:52]}")
    print("  regressed:")
    for d, q, pa, pb, t, qt in movers[-6:]:
        if d < 0:
            print(f"    {d*100:+6.1f}pp  {pa:.3f} -> {pb:.3f}  [{t}/{qt}] {q[:52]}")


if __name__ == "__main__":
    main()
