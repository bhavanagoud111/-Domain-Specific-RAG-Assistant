"""Phase 4 (judge audit) — sample judge verdicts for HAND verification, BOTH directions.

The brief asks how much to trust the judge's numbers. Auditing an LLM judge with another LLM
just moves the trust problem, so this script adjudicates nothing: it draws a reproducible
STRATIFIED sample and prints each verdict alongside the full text the judge was looking at,
so a human can read both and record whether the judge was right.

Stratified deliberately. Sampling only the suspicious (UNSUPPORTED) verdicts would measure
the judge's false-rejection rate and say nothing about rubber-stamping. Accuracy is therefore
reported SEPARATELY per direction, because the two errors bias the headline in opposite ways:

    judge wrongly REJECTS supported claims -> faithfulness is UNDERSTATED
    judge wrongly APPROVES unsupported ones -> faithfulness is OVERSTATED

A blended "judge was 85% accurate" hides which way the 87.0% headline leans.

    PYTHONPATH=. python evaluation/verify_judge.py                  # 6 + 6, seed 20260719
    PYTHONPATH=. python evaluation/verify_judge.py --n 8 --seed 7
    PYTHONPATH=. python evaluation/verify_judge.py --pin "Mexico,Japan"   # force-include

Adjudications are recorded by hand in ``evaluation/judge_audit.json``.
"""

from __future__ import annotations

import argparse
import json
import random
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "eval_results.json"


def wrap(text: str, width: int = 96, indent: str = "      ") -> str:
    out = []
    for para in (text or "").split("\n"):
        out.extend(textwrap.wrap(para, width=width, initial_indent=indent,
                                 subsequent_indent=indent) or [indent])
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="verdicts per direction")
    ap.add_argument("--seed", type=int, default=20260719)
    ap.add_argument("--pin", default="", help="comma-separated countries to force-include")
    args = ap.parse_args()

    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    results = [r for r in data["results"] if not r.get("error")]
    pinned = {c.strip() for c in args.pin.split(",") if c.strip()}

    # Flatten every faithfulness claim, tagged by direction.
    pool = []
    for r in results:
        for run in r.get("runs", []):
            for c in run.get("faithfulness", {}).get("claims", []):
                pool.append({
                    "question": r["question"], "country": r["expected_country"],
                    "qtype": r["question_type"], "tier": r["corpus_tier"],
                    "run": run["run"], "claim": c.get("claim"),
                    "supported": bool(c.get("supported")), "why": c.get("why", ""),
                    "answer": run.get("final_answer", ""),
                    "cited": run.get("citations_text", []),
                })

    sup = [p for p in pool if p["supported"]]
    uns = [p for p in pool if not p["supported"]]
    rng = random.Random(args.seed)

    def draw(bucket, n):
        forced = [p for p in bucket if p["country"] in pinned]
        # keep at most one forced verdict per pinned country, then fill randomly
        seen, keep = set(), []
        for p in forced:
            if p["country"] not in seen:
                seen.add(p["country"]); keep.append(p)
        rest = [p for p in bucket if p not in keep]
        keep += rng.sample(rest, max(0, min(n - len(keep), len(rest))))
        return keep[:max(n, len(keep))]

    sample_uns = draw(uns, args.n)
    sample_sup = draw(sup, args.n)

    print("=" * 104)
    print("JUDGE VERDICT AUDIT -- stratified, hand-verification material")
    print("=" * 104)
    print(f"judge  = {data.get('judge_model')}   blinded = {data.get('judge_blinded')}")
    print(f"pool   = {len(pool)} claim-level verdicts "
          f"({len(sup)} SUPPORTED / {len(uns)} UNSUPPORTED)")
    print(f"sample = {len(sample_uns)} UNSUPPORTED + {len(sample_sup)} SUPPORTED  "
          f"(seed={args.seed}, pinned={sorted(pinned) or 'none'})")
    print("\nAccuracy MUST be reported per direction:")
    print("  wrong REJECTIONS -> headline faithfulness is UNDERSTATED")
    print("  wrong APPROVALS  -> headline faithfulness is OVERSTATED\n")

    for label, sample in (("JUDGE SAID: UNSUPPORTED", sample_uns),
                          ("JUDGE SAID: SUPPORTED", sample_sup)):
        print("\n" + "#" * 104)
        print(f"# {label}   (n={len(sample)})")
        print("#" * 104)
        for i, s in enumerate(sample, 1):
            print("\n" + "=" * 104)
            print(f"[{label.split(':')[1].strip()} {i}] {s['country']} / {s['qtype']} "
                  f"[{s['tier']}]  run {s['run']}")
            print(f"  Q: {s['question']}")
            print(f"  JUDGE REASON: {s['why']!r}")
            print(f"\n  CLAIM UNDER TEST:")
            print(wrap(s["claim"]))
            print(f"\n  FULL ANSWER:")
            print(wrap(s["answer"][:1200]))
            print(f"\n  CITED CHUNK TEXT (what the judge compared against):")
            for c in s["cited"]:
                print(wrap(c[:1600]))
                print()

    print("\n" + "=" * 104)
    print("Record adjudications in evaluation/judge_audit.json:")
    print('  {"direction": "unsupported", "country": ..., "judge_said": false,')
    print('   "human_verdict": false, "judge_correct": true, "note": "..."}')


if __name__ == "__main__":
    main()
