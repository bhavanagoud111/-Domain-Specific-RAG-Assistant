"""Week 7 feasibility — is 65-75% end-to-end precision reachable? Computed OFFLINE.

Decides whether to spend a ~40-minute eval run, before spending it.

NO JUDGE CALLS. Relevance is reused from the Step 1 ceiling analysis (``ceiling.json``,
``relevant_chunk_ids``). The only live work is one depth-20 raw-question retrieval per
question -- 91 embedding calls -- because top-N for every N <= 20 is a prefix of the same
ranked list, so one retrieval serves all three parts.

  PART 1  D2  -- truncate the current C1 window to N in {4,5,6,8}
  PART 2  D1  -- rerank depth 20 down to 8
  PART 3  D1+D2 -- rerank depth 20 down to 5

TWO MEASUREMENT SPACES -- THE WHOLE POINT OF THE CALIBRATION BELOW
------------------------------------------------------------------
Everything here is computed in **R-set space**: precision = |retrieved and R| / N, where R
comes from the ceiling judge scoring every chunk in a country's corpus. The eval measures
precision in **eval-judge space**: its judge scores the actually-retrieved chunks in
context. Week 7 established these two spaces do NOT agree per question type (safety +17.6pp,
what_to_visit -23.4pp), and that R-set projections are systematically optimistic -- the
depth diagnostic predicted a +26.3pp raw-question gain and the eval delivered +8.3pp.

Projecting an R-set number straight into "expected eval precision" would therefore repeat
exactly the error that was already made once this week. Two corrections are reported:

  1. CALIBRATED (primary). C1 is now measured in BOTH spaces: offline here, and 52.5% by
     the eval. That anchor gives a multiplicative calibration factor which is applied to
     every projection. This is empirically grounded rather than assumed.

  2. DISCOUNTED (as instructed). The gain over C1 is divided by a discount factor and added
     back. Reported at the requested 2x AND at the empirically measured ratio, because the
     measured over-prediction on the one case where both numbers exist is
     26.3 / 8.3 = 3.17x, not 2x -- and quoting the rosier factor without saying so would
     overstate feasibility.

Run:  PYTHONPATH=. python evaluation/feasibility.py
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import settings
from graph.wanderrag_graph import _QDRANT, _detect_country, _embed

HERE = Path(__file__).resolve().parent
CEILING = HERE / "ceiling.json"
EVAL_SET = HERE / "eval_set.json"
OUT = HERE / "feasibility.json"

DEPTH = 20
D2_NS = [4, 5, 6, 8]
TIERS = ["rich", "mid", "thin"]
TYPES = ["visa", "health", "safety", "what_to_visit"]

# C1 as the eval actually measured it, over all 91 questions.
EVAL_C1_PRECISION = 0.525
# Measured over-prediction of the R-set diagnostic on the one case where both exist.
DISCOUNT_INSTRUCTED = 2.0
DISCOUNT_MEASURED = 26.3 / 8.3


def retrieve_depth(question: str) -> list[str]:
    """C1 retrieval, extended to DEPTH: raw question, country-filtered, ranked by cosine."""
    country = _detect_country(question)
    qfilter = (
        Filter(must=[FieldCondition(key="country", match=MatchValue(value=country))])
        if country else None
    )
    vec = _embed("feasibility", question)
    hits = _QDRANT.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=vec, query_filter=qfilter, limit=DEPTH, with_payload=False,
    ).points
    return [str(h.id) for h in hits]


def pct(x: float | None) -> str:
    return "   n/a" if x is None else f"{100*x:5.1f}%"


def d2_stats(rows: list[dict], n: int) -> dict[str, Any]:
    """D2: truncate the C1 ranked list to top-n."""
    ceil = statistics.mean(min(r["R"], n) / n for r in rows)
    hits = [len(set(r["ranked"][:n]) & set(r["R_ids"])) for r in rows]
    prec = statistics.mean(h / n for h in hits)
    return {"ceiling": ceil, "precision": prec,
            "efficiency": (prec / ceil) if ceil else None,
            "mean_relevant": statistics.mean(hits)}


def rerank_stats(rows: list[dict], n: int, depth: int = DEPTH) -> dict[str, Any]:
    """D1: a PERFECT reranker over top-`depth` fills n slots with as many relevant as it found."""
    ceil = statistics.mean(min(r["R"], n) / n for r in rows)
    hits = [len(set(r["ranked"][:depth]) & set(r["R_ids"])) for r in rows]
    prec = statistics.mean(min(h, n) / n for h in hits)
    recall = (sum(hits) / sum(r["R"] for r in rows)) if sum(r["R"] for r in rows) else None
    return {"ceiling": ceil, "precision": prec,
            "efficiency": (prec / ceil) if ceil else None,
            "mean_relevant": statistics.mean(min(h, n) for h in hits),
            "recall": recall}


def calibrate(offline: float, k: float) -> float:
    return offline * k


def discount(offline_proj: float, offline_c1: float, factor: float) -> float:
    """Keep 1/factor of the projected GAIN over C1, in offline space."""
    return offline_c1 + (offline_proj - offline_c1) / factor


def main() -> None:
    ceil_rows = {r["question"]: r for r in json.loads(CEILING.read_text(encoding="utf-8"))["results"]}
    items = json.loads(EVAL_SET.read_text(encoding="utf-8"))["items"]

    cache: dict[str, Any] = {}
    if OUT.exists():
        cache = {r["question"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))["results"]}

    rows: list[dict[str, Any]] = []
    for i, it in enumerate(items, 1):
        q = it["question"]
        if q in cache:
            rows.append(cache[q])
            continue
        c = ceil_rows[q]
        rec = {"question": q, "expected_country": it["expected_country"],
               "question_type": it["question_type"], "corpus_tier": it["corpus_tier"],
               "answerable": it["answerable"], "R": c["R"], "R_ids": c["relevant_chunk_ids"],
               "ranked": retrieve_depth(q)}
        rows.append(rec)
        OUT.write_text(json.dumps({"depth": DEPTH, "results": rows}, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
        print(f"  [{i}/{len(items)}] {it['question_type']:<14}{it['expected_country']:<22}"
              f"R={rec['R']:>3} depth20={len(rec['ranked'])}", flush=True)

    all91 = rows
    scored = [r for r in rows if r["R"] > 0]      # 86; the 5 unanswerable have R=0

    # ---- calibration anchor -------------------------------------------------
    offline_c1_91 = d2_stats(all91, 8)["precision"]
    k = EVAL_C1_PRECISION / offline_c1_91

    print("\n" + "=" * 96)
    print("CALIBRATION — anchoring R-set space to eval-judge space using C1, measured in both")
    print("=" * 96)
    print(f"  C1 precision@8, offline (R-set space, all 91) : {pct(offline_c1_91)}")
    print(f"  C1 precision@8, measured by the eval (all 91) : {pct(EVAL_C1_PRECISION)}")
    print(f"  calibration factor k                          : {k:.4f}")
    print(f"  discount factors: instructed {DISCOUNT_INSTRUCTED:.2f}x, "
          f"measured {DISCOUNT_MEASURED:.2f}x (26.3pp predicted / 8.3pp actual)")

    def block(title: str, groups: list[tuple[str, list[dict]]], fn, ns: list[int]) -> None:
        print("\n" + "=" * 96)
        print(title)
        print("=" * 96)
        print(f"  {'scope':<16}{'Qs':>4}" + "".join(
            f"{'N='+str(n):>26}" for n in ns))
        print(f"  {'':<16}{'':>4}" + "".join(
            f"{'ceil':>7}{'proj':>7}{'eff':>7}{'rel/ans':>7}" for _ in ns))
        for name, rs in groups:
            if not rs:
                continue
            line = f"  {name:<16}{len(rs):>4}"
            for n in ns:
                s = fn(rs, n)
                line += (f"{pct(s['ceiling']):>7}{pct(s['precision']):>7}"
                         f"{pct(s['efficiency']):>7}{s['mean_relevant']:>7.2f}")
            print(line)

    by_tier = defaultdict(list)
    by_type = defaultdict(list)
    for r in all91:
        by_tier[r["corpus_tier"]].append(r)
        by_type[r["question_type"]].append(r)

    groups = ([("ALL (91)", all91), ("answerable(86)", scored)]
              + [(t, by_tier[t]) for t in TIERS] + [(t, by_type[t]) for t in TYPES])

    block("PART 1 — D2: truncate the C1 window to top-N  [OFFLINE, R-set space]",
          groups, d2_stats, D2_NS)
    block("PART 2/3 — D1: PERFECT reranker over depth 20 -> N slots  [OFFLINE, upper bound]",
          groups, rerank_stats, [8, 5])

    # ---- recall@20 ----------------------------------------------------------
    print("\n" + "=" * 96)
    print("recall@20 (raw question, country-filtered) — what a depth-20 reranker has to work with")
    print("=" * 96)
    for name, rs in [("ALL answerable", scored)] + [(t, [r for r in scored if r["corpus_tier"] == t]) for t in TIERS] \
            + [(t, [r for r in scored if r["question_type"] == t]) for t in TYPES]:
        if not rs:
            continue
        tot = sum(r["R"] for r in rs)
        hit = sum(len(set(r["ranked"][:DEPTH]) & set(r["R_ids"])) for r in rs)
        print(f"  {name:<16}{len(rs):>4}  recall@20 = {pct(hit/tot if tot else None)}")

    # ---- THE DECISION TABLE -------------------------------------------------
    print("\n" + "=" * 96)
    print("PROJECTED END-TO-END PRECISION (all 91) — three ways of translating to eval space")
    print("=" * 96)
    print(f"  {'config':<28}{'offline':>9}{'calibrated':>12}{'disc 2.0x':>11}"
          f"{'disc 3.17x':>12}{'in 65-75%?':>12}")

    configs: list[tuple[str, float]] = [("C1 (current, N=8)", offline_c1_91)]
    for n in D2_NS:
        if n != 8:
            configs.append((f"D2  window N={n}", d2_stats(all91, n)["precision"]))
    configs.append(("D1  rerank 20->8 (perfect)", rerank_stats(all91, 8)["precision"]))
    configs.append(("D1+D2 rerank 20->5 (perfect)", rerank_stats(all91, 5)["precision"]))

    for name, off in configs:
        cal = calibrate(off, k)
        d2v = calibrate(discount(off, offline_c1_91, DISCOUNT_INSTRUCTED), k)
        d3v = calibrate(discount(off, offline_c1_91, DISCOUNT_MEASURED), k)
        band = "YES" if 0.65 <= cal <= 0.75 else ("above" if cal > 0.75 else "no")
        print(f"  {name:<28}{pct(off):>9}{pct(cal):>12}{pct(d2v):>11}{pct(d3v):>12}{band:>12}")

    print("\n  'calibrated' = offline x k (anchored on C1 measured in both spaces).")
    print("  'disc' rows keep only 1/factor of the projected GAIN over C1, then calibrate.")
    print("  Perfect-rerank rows are UPPER BOUNDS: they assume a reranker that never errs.")

    # ---- citation supply ----------------------------------------------------
    print("\n" + "=" * 96)
    print("CITATION SUPPLY — mean relevant chunks available to cite per answer (all 91)")
    print("=" * 96)
    for n in D2_NS:
        s = d2_stats(all91, n)
        print(f"  D2 N={n}: {s['mean_relevant']:.2f} relevant of {n} retrieved")
    for n in (8, 5):
        s = rerank_stats(all91, n)
        print(f"  perfect rerank 20->{n}: {s['mean_relevant']:.2f} relevant of {n} retrieved")
    zero = {n: sum(1 for r in all91 if r["R"] > 0
                   and len(set(r["ranked"][:n]) & set(r["R_ids"])) == 0) for n in D2_NS}
    print(f"\n  answerable questions with ZERO relevant chunks retrieved (citation starvation risk):")
    for n in D2_NS:
        print(f"    N={n}: {zero[n]}/86")

    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
