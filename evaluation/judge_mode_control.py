"""Control: does BATCH-mode relevance judging agree with EVAL-mode relevance judging?

WHY THIS EXISTS
---------------
``precision_diagnosis.py`` computes R (relevant chunks in the whole country corpus) by
judging every chunk in batches of 10. ``run_eval.py`` computed ``actual`` precision by
judging the 8 retrieved chunks in a single call. Those are two different prompting
conditions, and the efficiency ratio ``actual / max_achievable`` silently assumes they
apply the SAME relevance bar.

If batch mode is more lenient, R is inflated, max_achievable is inflated, efficiency is
deflated, and corpus-limited cases get misreported as RETRIEVAL FAILURES -- the single
most consequential claim in the evaluation.

THE CONTROL
-----------
Re-judge, in BATCH mode, the exact 8 chunks the eval already judged in EVAL mode, and
compare verdict-by-verdict. Any disagreement is a mode offset, not a retrieval finding.

Run:  PYTHONPATH=. python evaluation/judge_mode_control.py
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.precision_diagnosis import SCAN_PROMPT, _judge

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "eval_results.json"
DIAG = HERE / "precision_diagnosis.json"
OUT = HERE / "judge_mode_control.json"


def main() -> None:
    results = {r["question"]: r for r in json.loads(RESULTS.read_text())["results"]}
    diag = json.loads(DIAG.read_text())

    rows, agree, disagree = [], 0, 0
    flips_to_relevant, flips_to_irrelevant = 0, 0

    for d in diag:
        r = results[d["question"]]
        run = r["runs"][0]
        eval_verdicts = run["retrieval"]["verdicts"]          # EVAL mode
        chunk_texts = run["retrieved_chunks_text"]            # same 8 chunks
        if not eval_verdicts or not chunk_texts:
            continue

        # Re-judge those same 8 chunks, but in the BATCH prompt condition.
        blob = "\n\n".join(f"[chunk {i+1}] {t[:800]}" for i, t in enumerate(chunk_texts))
        v = _judge(SCAN_PROMPT.format(q=d["question"], chunks=blob))
        batch = {x.get("chunk"): bool(x.get("relevant")) for x in v.get("verdicts", [])}

        per = []
        for ev in eval_verdicts:
            i = ev.get("chunk")
            e_rel, b_rel = bool(ev.get("relevant")), batch.get(i)
            if b_rel is None:
                continue
            same = e_rel == b_rel
            agree += same
            disagree += (not same)
            if not same:
                flips_to_relevant += (b_rel and not e_rel)
                flips_to_irrelevant += (e_rel and not b_rel)
            per.append({"chunk": i, "eval_mode": e_rel, "batch_mode": b_rel, "agree": same})

        n_eval_rel = sum(1 for p in per if p["eval_mode"])
        n_batch_rel = sum(1 for p in per if p["batch_mode"])
        rows.append({
            "question": d["question"], "country": d["country"],
            "n_compared": len(per),
            "eval_mode_relevant": n_eval_rel, "batch_mode_relevant": n_batch_rel,
            "delta": n_batch_rel - n_eval_rel, "per_chunk": per,
        })
        print(f"  {d['country']:<14} same 8 chunks -> eval-mode says {n_eval_rel} relevant, "
              f"batch-mode says {n_batch_rel}  (delta {n_batch_rel - n_eval_rel:+d})")

    total = agree + disagree
    summary = {
        "chunks_compared": total,
        "agreements": agree,
        "disagreements": disagree,
        "agreement_rate": round(agree / total, 4) if total else None,
        "batch_called_relevant_when_eval_did_not": flips_to_relevant,
        "eval_called_relevant_when_batch_did_not": flips_to_irrelevant,
        "rows": rows,
    }
    OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 88)
    print("JUDGE-MODE CONSISTENCY CONTROL")
    print("=" * 88)
    print(f"  chunks compared          : {total}")
    print(f"  agreement rate           : {summary['agreement_rate']}")
    print(f"  batch MORE lenient (0->1): {flips_to_relevant}")
    print(f"  batch MORE strict  (1->0): {flips_to_irrelevant}")
    net = flips_to_relevant - flips_to_irrelevant
    print(f"  net leniency of batch    : {net:+d} chunks over {len(rows)} questions")
    if net > 0:
        print("\n  => BATCH MODE IS MORE LENIENT. R is INFLATED, max_achievable is INFLATED,")
        print("     efficiency is DEFLATED, and the 'RETRIEVAL MISS' verdicts are NOT SAFE")
        print("     to report as confirmed retrieval failures.")
    elif net == 0:
        print("\n  => modes agree on balance; efficiency ratios are usable as computed.")
    else:
        print("\n  => batch mode is STRICTER; efficiency ratios are, if anything, conservative.")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
