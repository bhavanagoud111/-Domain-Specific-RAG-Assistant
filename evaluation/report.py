"""Phase 4 reporting — aggregate ``eval_results.json`` into the numbers for the write-up.

Every aggregate is broken out by corpus tier (rich >=60 chunks / mid 30-59 / thin <30).
Thin countries are never averaged into a single headline number without also being shown
separately: they are 19 of the 50 countries and they behave differently from the rest, so a
blended average would hide the system's actual weak spot.

Run:  PYTHONPATH=. python evaluation/report.py
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "eval_results.json"

TIER_ORDER = ["rich", "mid", "thin", "n/a"]
TYPE_ORDER = ["visa", "health", "safety", "what_to_visit", "unanswerable"]


def mean(xs: list[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(statistics.mean(vals), 4) if vals else None


def pct(x: float | None) -> str:
    return "  n/a " if x is None else f"{100 * x:5.1f}%"


def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(rows),
        "runs": sum(r["n_runs"] for r in rows),
        "precision": mean([r.get("mean_precision") for r in rows]),
        "faithfulness": mean([r.get("mean_faithfulness") for r in rows]),
        "gate": mean([r.get("gate_correct_rate") for r in rows]),
        "country": mean([r.get("expected_country_retrieved_rate") for r in rows]),
        "flips": sum(1 for r in rows if r.get("gate_flipped")),
        "flippable": sum(1 for r in rows if r["n_runs"] > 1),
    }


def line(label: str, a: dict[str, Any]) -> str:
    return (f"{label:<16}{a['n']:>4}{a['runs']:>6}  {pct(a['precision'])} "
            f"{pct(a['faithfulness'])} {pct(a['gate'])} {pct(a['country'])}"
            f"{a['flips']:>7}/{a['flippable']:<5}")


def main() -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    rows = [r for r in data["results"] if not r.get("error")]
    errs = [r for r in data["results"] if r.get("error")]

    print(f"judge = {data['judge_model']}   blinded = {data.get('judge_blinded')}")
    print(f"corpus points_count = {data.get('corpus_points_count')} (FROZEN)")
    print(f"questions = {len(rows)}   graph runs = {sum(r['n_runs'] for r in rows)}   "
          f"errors = {len(errs)}")
    print(f"sampling: thin+unanswerable x{data.get('runs_thin')}, rich/mid x{data.get('runs_rich')}\n")

    hdr = (f"{'':<16}{'Qs':>4}{'runs':>6}  {'PRECIS':>6} {'FAITH':>6} {'GATE':>6} "
           f"{'COUNTRY':>6}{'FLIPS':>8}")

    # ---------------- headline ----------------
    print("=" * 78)
    print("AGGREGATE (all questions)")
    print("=" * 78)
    print(hdr)
    print(line("ALL", _agg(rows)))

    # ---------------- by tier ----------------
    print("\n" + "=" * 78)
    print("BY CORPUS TIER  (thin is NOT averaged away)")
    print("=" * 78)
    print(hdr)
    by_tier = defaultdict(list)
    for r in rows:
        by_tier[r["corpus_tier"]].append(r)
    for tier in TIER_ORDER:
        if by_tier.get(tier):
            print(line(tier, _agg(by_tier[tier])))

    # ---------------- by question type ----------------
    print("\n" + "=" * 78)
    print("BY QUESTION TYPE")
    print("=" * 78)
    print(hdr)
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["question_type"]].append(r)
    for t in TYPE_ORDER:
        if by_type.get(t):
            print(line(t, _agg(by_type[t])))

    # ---------------- type x tier ----------------
    print("\n" + "=" * 78)
    print("QUESTION TYPE x TIER")
    print("=" * 78)
    print(hdr)
    for t in TYPE_ORDER:
        for tier in TIER_ORDER:
            sub = [r for r in rows if r["question_type"] == t and r["corpus_tier"] == tier]
            if sub:
                print(line(f"{t[:11]}/{tier}", _agg(sub)))

    # ---------------- flips ----------------
    flipped = [r for r in rows if r.get("gate_flipped")]
    flippable = [r for r in rows if r["n_runs"] > 1]
    print("\n" + "=" * 78)
    print("GATE FLIPS  (verdict not identical across a question's 3 runs)")
    print("=" * 78)
    print(f"  questions sampled 3x : {len(flippable)}")
    print(f"  questions that FLIPPED: {len(flipped)}"
          f"  ({100*len(flipped)/len(flippable):.1f}% of 3x-sampled)" if flippable else "")
    ft = defaultdict(int)
    for r in flipped:
        ft[r["corpus_tier"]] += 1
    print(f"  flips by tier: {dict(ft) or 'none'}")
    for r in flipped:
        print(f"    {r['corpus_tier']:<5} {r['question_type']:<14} {r['expected_country']:<22} "
              f"verdicts={r['gate_verdicts']} cits(mean)={r['mean_citations']}")

    # ---------------- unanswerable ----------------
    print("\n" + "=" * 78)
    print("UNANSWERABLE QUESTIONS  (must resolve 0 citations)")
    print("=" * 78)
    for r in [x for x in rows if x["question_type"] == "unanswerable"]:
        ok = "OK  " if r["gate_correct_rate"] == 1.0 else "BAD "
        print(f"  {ok} {r['expected_country']:<12} verdicts={str(r['gate_verdicts']):<22} "
              f"correct={pct(r['gate_correct_rate'])}  {r['question'][:52]}")

    # ---------------- worst failures ----------------
    print("\n" + "=" * 78)
    print("WORST FAILURES (ranked: gate wrong, then unfaithful, then imprecise)")
    print("=" * 78)

    def badness(r: dict[str, Any]) -> tuple:
        return (
            -(1 - (r.get("gate_correct_rate") or 0)),
            (r.get("mean_faithfulness") if r.get("mean_faithfulness") is not None else 1.0),
            (r.get("mean_precision") if r.get("mean_precision") is not None else 1.0),
        )

    for r in sorted(rows, key=badness)[:8]:
        print(f"\n  {r['expected_country']} / {r['question_type']} [{r['corpus_tier']}]")
        print(f"    {r['question']}")
        print(f"    gate_correct={pct(r['gate_correct_rate'])} verdicts={r['gate_verdicts']} "
              f"faith={pct(r.get('mean_faithfulness'))} prec={pct(r.get('mean_precision'))} "
              f"country_retrieved={pct(r.get('expected_country_retrieved_rate'))}")

    if errs:
        print("\n" + "=" * 78)
        print(f"ERRORED QUESTIONS: {len(errs)}")
        for e in errs:
            print(f"  {e['expected_country']:<20} {e.get('error','')[:90]}")


if __name__ == "__main__":
    main()
