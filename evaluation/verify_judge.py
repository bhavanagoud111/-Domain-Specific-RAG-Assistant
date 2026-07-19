"""Phase 4 (judge audit) — sample judge verdicts for HAND verification.

The brief asks how much to trust the judge's numbers. Auditing an LLM judge with another
LLM just moves the trust problem, so this script does not adjudicate anything: it draws a
reproducible random sample of individual judge verdicts and prints each one alongside the
FULL chunk text it was judging, so a human can read both and record whether the judge was
right.

Adjudications are written back by hand into ``evaluation/judge_audit.json`` and summarised
in ``logs/week6.md``.

    PYTHONPATH=. python evaluation/verify_judge.py            # 12 verdicts, seed 20260719
    PYTHONPATH=. python evaluation/verify_judge.py --n 20 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "eval_results.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12, help="how many verdicts to sample")
    ap.add_argument("--seed", type=int, default=20260719, help="reproducible sample")
    args = ap.parse_args()

    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    results = data["results"]

    # Flatten every individual verdict into one pool, tagged by kind, so the sample can
    # cover both metrics rather than over-weighting whichever produced more verdicts.
    pool = []
    for r in results:
        if r.get("error"):
            continue
        for v in r.get("retrieval", {}).get("verdicts", []):
            idx = v.get("chunk")
            pool.append({"kind": "relevance", "question": r["question"],
                         "country": r["expected_country"], "qtype": r["question_type"],
                         "chunk_no": idx, "verdict": v.get("relevant"),
                         "why": v.get("why", "")})
        for c in r.get("faithfulness", {}).get("claims", []):
            pool.append({"kind": "faithfulness", "question": r["question"],
                         "country": r["expected_country"], "qtype": r["question_type"],
                         "claim": c.get("claim"), "verdict": c.get("supported"),
                         "why": c.get("why", "")})

    rng = random.Random(args.seed)
    sample = rng.sample(pool, min(args.n, len(pool)))

    print(f"JUDGE VERDICT SAMPLE  (n={len(sample)}, seed={args.seed}, pool={len(pool)})")
    print(f"judge = {data.get('judge_model')}\n")

    by_q = {r["question"]: r for r in results}
    for i, s in enumerate(sample, 1):
        r = by_q[s["question"]]
        print("=" * 100)
        print(f"[{i}] kind={s['kind']}  {s['country']} / {s['qtype']}")
        print(f"    Q: {s['question']}")
        print(f"    JUDGE SAID: {s['verdict']}   (\"{s['why']}\")")
        if s["kind"] == "relevance":
            chunks = r.get("retrieved_chunks_text") or []
            n = s.get("chunk_no")
            txt = chunks[n - 1] if (isinstance(n, int) and 0 < n <= len(chunks)) else None
            print(f"\n    CHUNK {n} FULL TEXT:\n{txt if txt else '    <chunk text not stored -- see eval_results.json>'}")
        else:
            print(f"\n    CLAIM: {s.get('claim')}")
            print(f"\n    ANSWER:\n{r.get('final_answer','')[:1500]}")
            print("\n    CITED CHUNKS:")
            for c in r.get("citations_text", []):
                print(f"      {c[:1200]}\n")
        print()


if __name__ == "__main__":
    main()
