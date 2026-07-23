"""Week 7 — ceiling, retrieval efficiency, and whether a measured change beats noise.

Three things the plain before/after table cannot tell you:

CEILING (Step 1). ``ceiling.json`` holds R, the number of genuinely relevant chunks in each
country's whole corpus, judged by the SAME blinded judge under the SAME relevance criteria
as the eval. Max achievable precision is min(R, 8)/8, because the system retrieves an 8-chunk
window and precision is measured over it. This converts "44.2%" from an uninterpretable
number into either "44% of a reachable 100%" or "44% of a reachable 70%".

RETRIEVAL EFFICIENCY. actual precision / max achievable. Defined only where the ceiling is
non-zero, so the 5 unanswerable questions (R=0 by construction, and correctly so) are
excluded rather than counted as 0/0 -- averaging them in would be arithmetically undefined
and rhetorically convenient.

NOISE (Step 3). Week 6 measured a per-question noise floor of ~15pp at 1x sampling. That is
a PER-QUESTION figure and it does NOT transfer to the aggregate: averaging n paired
questions shrinks the standard error by sqrt(n). This module therefore reports the aggregate
mean delta with a bootstrap 95% CI over the paired per-question deltas, and states whether
that CI excludes zero. A change whose CI straddles zero is reported as not distinguishable
from noise, regardless of its sign.

Run:  PYTHONPATH=. python evaluation/week7_analysis.py BEFORE.json AFTER.json
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CEILING = HERE / "ceiling.json"
TIERS = ["rich", "mid", "thin", "n/a"]
TYPES = ["visa", "health", "safety", "what_to_visit", "unanswerable"]
BOOT = 20000
SEED = 20260721


def mean(xs: list[float | None]) -> float | None:
    v = [x for x in xs if x is not None]
    return statistics.mean(v) if v else None


def pct(x: float | None) -> str:
    return "   n/a" if x is None else f"{100 * x:5.1f}%"


def bootstrap_ci(deltas: list[float], iters: int = BOOT) -> tuple[float, float]:
    """Percentile bootstrap 95% CI for the mean of paired per-question deltas."""
    rng = random.Random(SEED)
    n = len(deltas)
    means = []
    for _ in range(iters):
        means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def load_results(path: Path) -> dict[str, dict]:
    return {r["question"]: r
            for r in json.loads(path.read_text(encoding="utf-8"))["results"]
            if not r.get("error")}


# --------------------------------------------------------------------------- #
# Step 1 — the ceiling
# --------------------------------------------------------------------------- #
def report_ceiling(ceil: dict[str, dict], results: dict[str, dict] | None,
                   label: str) -> None:
    rows = list(ceil.values())
    print("=" * 92)
    print(f"STEP 1 — RETRIEVAL CEILING  (R = relevant chunks in the country's WHOLE corpus)")
    print("=" * 92)

    def block(title: str, groups: list[tuple[str, list[dict]]]) -> None:
        print(f"\n{title}")
        print(f"  {'':<16}{'Qs':>4}{'corpus':>8}{'R mean':>8}{'R med':>7}"
              f"{'maxP mean':>11}{'maxP=100%':>11}{'maxP<50%':>10}")
        for name, rs in groups:
            if not rs:
                continue
            mp = [r["max_achievable_precision"] for r in rs]
            print(f"  {name:<16}{len(rs):>4}"
                  f"{statistics.mean(r['country_corpus_size'] for r in rs):>8.1f}"
                  f"{statistics.mean(r['R'] for r in rs):>8.1f}"
                  f"{statistics.median(r['R'] for r in rs):>7.0f}"
                  f"{100*statistics.mean(mp):>10.1f}%"
                  f"{sum(1 for x in mp if x >= 1.0):>11}"
                  f"{sum(1 for x in mp if x < 0.5):>10}")

    block("ALL QUESTIONS", [("ALL", rows)])
    by_tier = defaultdict(list)
    for r in rows:
        by_tier[r["corpus_tier"]].append(r)
    block("BY CORPUS TIER", [(t, by_tier[t]) for t in TIERS])
    by_type = defaultdict(list)
    for r in rows:
        by_type[r["question_type"]].append(r)
    block("BY QUESTION TYPE", [(t, by_type[t]) for t in TYPES])

    ans = [r for r in rows if r["answerable"]]
    una = [r for r in rows if not r["answerable"]]
    print(f"\n  answerable questions  : n={len(ans)}  mean maxP = "
          f"{100*statistics.mean(r['max_achievable_precision'] for r in ans):.1f}%")
    print(f"  unanswerable questions: n={len(una)}  mean R = "
          f"{statistics.mean(r['R'] for r in una):.2f}  "
          f"(R=0 for {sum(1 for r in una if r['R']==0)}/{len(una)}) "
          f"-- independent confirmation the 'unanswerable' labels are real")
    unj = sum(r["n_unjudged"] for r in rows)
    print(f"  unjudged chunks       : {unj} "
          f"(counted as NOT relevant, so the ceiling is if anything UNDER-stated)")


# --------------------------------------------------------------------------- #
# Retrieval efficiency
# --------------------------------------------------------------------------- #
def report_efficiency(ceil: dict[str, dict], runs: dict[str, dict[str, dict]]) -> None:
    print("\n" + "=" * 92)
    print("RETRIEVAL EFFICIENCY  =  actual precision / max achievable precision")
    print("=" * 92)
    print("  (defined only where maxP > 0; the 5 unanswerable questions are excluded)")

    labels = list(runs.keys())
    hdr = f"  {'':<16}{'Qs':>4}" + "".join(
        f"{l[:9]+' prec':>16}{l[:9]+' eff':>16}" for l in labels)
    print("\n" + hdr)

    def line(name: str, qs: list[str]) -> None:
        if not qs:
            return
        out = f"  {name:<16}{len(qs):>4}"
        for l in labels:
            rs = runs[l]
            ps, es = [], []
            for q in qs:
                p = rs.get(q, {}).get("mean_precision")
                mp = ceil[q]["max_achievable_precision"]
                if p is None or mp <= 0:
                    continue
                ps.append(p)
                es.append(p / mp)
            out += f"{pct(mean(ps)):>16}{pct(mean(es)):>16}"
        print(out)

    scored = [q for q in ceil
              if ceil[q]["max_achievable_precision"] > 0
              and any(runs[l].get(q, {}).get("mean_precision") is not None for l in labels)]
    line("ALL", scored)
    print()
    for t in TIERS:
        line(t, [q for q in scored if ceil[q]["corpus_tier"] == t])
    print()
    for t in TYPES:
        line(t, [q for q in scored if ceil[q]["question_type"] == t])


# --------------------------------------------------------------------------- #
# Noise
# --------------------------------------------------------------------------- #
def report_noise(before: dict[str, dict], after: dict[str, dict]) -> None:
    print("\n" + "=" * 92)
    print("IS THE AGGREGATE CHANGE BIGGER THAN NOISE?")
    print("=" * 92)

    pairs = [(q, before[q]["mean_precision"], after[q]["mean_precision"])
             for q in before if q in after
             and before[q].get("mean_precision") is not None
             and after[q].get("mean_precision") is not None]
    deltas = [b - a for _, a, b in pairs]
    n = len(deltas)
    m = statistics.mean(deltas)
    sd = statistics.stdev(deltas) if n > 1 else 0.0
    se = sd / (n ** 0.5)
    lo, hi = bootstrap_ci(deltas)

    print(f"  paired questions              : {n}")
    print(f"  mean per-question delta       : {100*m:+.2f} pp")
    print(f"  median per-question delta     : {100*statistics.median(deltas):+.2f} pp")
    print(f"  mean ABSOLUTE per-question Δ  : {100*statistics.mean(abs(d) for d in deltas):.2f} pp"
          f"   <- per-question churn (Week 6 measured ~15pp at 1x)")
    print(f"  stdev of per-question delta   : {100*sd:.2f} pp")
    print(f"  standard error of the mean    : {100*se:.2f} pp   (= stdev / sqrt({n}))")
    print(f"  bootstrap 95% CI of mean Δ    : [{100*lo:+.2f}, {100*hi:+.2f}] pp")
    print(f"  improved / regressed / same   : "
          f"{sum(1 for d in deltas if d > 0)} / {sum(1 for d in deltas if d < 0)} / "
          f"{sum(1 for d in deltas if d == 0)}")

    excludes_zero = (lo > 0) or (hi < 0)
    print(f"\n  CI excludes zero              : {'YES' if excludes_zero else 'NO'}")
    if excludes_zero:
        print("  => the aggregate change EXCEEDS the noise floor.")
    else:
        print("  => the aggregate change is NOT distinguishable from noise.")
        print("     Per-question churn is large in both directions and nets out; the")
        print("     aggregate mean is inside the interval a null effect would produce.")

    # Churn by sampling depth -- the Week 6 tell for noise vs treatment.
    print("\n  churn by sampling depth (a real effect persists under averaging; noise shrinks):")
    for label, sel in (("1x sampled (rich+mid)", lambda q: before[q]["n_runs"] == 1),
                       ("3x sampled (thin+unans)", lambda q: before[q]["n_runs"] > 1)):
        ds = [b - a for q, a, b in pairs if sel(q)]
        if ds:
            print(f"    {label:<24} n={len(ds):>3}  mean Δ {100*statistics.mean(ds):+6.2f} pp   "
                  f"mean |Δ| {100*statistics.mean(abs(d) for d in ds):5.2f} pp")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    before_p, after_p = Path(sys.argv[1]), Path(sys.argv[2])
    ceil_data = json.loads(CEILING.read_text(encoding="utf-8"))
    ceil = {r["question"]: r for r in ceil_data["results"]}
    before = load_results(before_p)
    after = load_results(after_p)

    print(f"ceiling judge = {ceil_data['judge_model']}  blinded = {ceil_data['judge_blinded']}")
    print(f"corpus = {ceil_data['corpus_points_count']} (FROZEN)   "
          f"ceiling questions = {len(ceil)}")
    print(f"before = {before_p.name} ({len(before)} q)   after = {after_p.name} ({len(after)} q)\n")

    report_ceiling(ceil, before, "before")
    report_efficiency(ceil, {"before": before, "after": after})
    report_noise(before, after)


if __name__ == "__main__":
    main()
