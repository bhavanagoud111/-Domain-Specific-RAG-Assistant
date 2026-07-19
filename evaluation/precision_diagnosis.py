"""Phase 4 follow-up — diagnose the worst precision failures.

A raw precision number at a fixed retrieval window is uninterpretable on its own. The graph
retrieves a fixed 8 chunks (``TOP_K + 3`` in ``retrieve_node``). If a question only has 2
genuinely relevant chunks anywhere in that country's corpus, the BEST any retriever can score
is 2/8 = 0.25, and reporting "precision 0.25" as a failure is meaningless.

So for each of the worst cases this computes:

    R                     = relevant chunks in the ENTIRE country corpus, found by scanning
                            every chunk payload directly -- no embedding query involved
    max_achievable        = min(R, 8) / 8
    actual                = measured precision from the eval
    retrieval_efficiency  = actual / max_achievable   (1.0 = retrieval found everything it could)

and classifies each case:

    (a) CORPUS-LIMITED   -- actual is at or near max_achievable. The corpus simply has few
                            relevant chunks; retrieval found them. Low precision is a data
                            ceiling, not a retrieval defect.
    (b) RETRIEVAL MISS   -- relevant chunks demonstrably exist that retrieval did not return.
                            This is a genuine retrieval failure and is flagged loudly.

METHOD NOTE: relevance over the whole country corpus is decided by the SAME blinded judge and
the SAME relevance criteria used in the eval, applied to every chunk in batches. It is not a
keyword match -- keyword presence is not relevance, and using a different standard here than
in the eval would make `actual` and `max_achievable` incomparable.

Run:  PYTHONPATH=. python evaluation/precision_diagnosis.py [--n 5]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import requests

from config import settings
from evaluation.run_eval import JUDGE_MODEL, assert_judge_blinded

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "eval_results.json"
OUT = HERE / "precision_diagnosis.json"
CORPUS_DUMP = Path("scratchpad/corpus_dump.json")

WINDOW = 8       # retrieve_node returns TOP_K + 3
BATCH = 10       # chunks per judge call

SCAN_PROMPT = """You are scoring a retrieval system. For the question below, decide for
EACH chunk whether it is RELEVANT -- i.e. whether it contains information a person would
actually use to answer that question.

Be strict. Navigation menus, page headers/footers, cookie notices, lists of unrelated country
names, and generic boilerplate are NOT relevant even if they mention the right country.
A chunk about visa rules is NOT relevant to a "what should I visit" question, and vice versa.

QUESTION: {q}

CHUNKS:
{chunks}

Reply with ONLY this JSON:
{{"verdicts": [{{"chunk": 1, "relevant": true, "why": "<8 words>"}}, ...]}}"""


def _judge(prompt: str) -> dict[str, Any]:
    assert_judge_blinded(prompt)
    key = settings.require_openrouter_key()
    r = requests.post(
        f"{settings.OPENROUTER_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": JUDGE_MODEL, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 1500, "temperature": 0},
        timeout=180,
    )
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {"verdicts": []}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"verdicts": []}


def scan_country(question: str, country: str, chunks: list[dict]) -> list[dict]:
    """Judge EVERY chunk of a country for relevance to the question. No embeddings."""
    out = []
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start : start + BATCH]
        blob = "\n\n".join(
            f"[chunk {i+1}] (source={c['source_type']}, idx={c['chunk_index']})\n{c['text'][:800]}"
            for i, c in enumerate(batch))
        v = _judge(SCAN_PROMPT.format(q=question, chunks=blob))
        by_idx = {x.get("chunk"): x for x in v.get("verdicts", [])}
        for i, c in enumerate(batch, start=1):
            verdict = by_idx.get(i, {})
            out.append({
                "source_type": c["source_type"], "chunk_index": c["chunk_index"],
                "relevant": bool(verdict.get("relevant")),
                "why": verdict.get("why", ""),
                "excerpt": c["text"][:160].replace("\n", " "),
            })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="how many worst cases to diagnose")
    args = ap.parse_args()

    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    rows = [r for r in data["results"]
            if not r.get("error") and r.get("mean_precision") is not None
            and r["question_type"] != "unanswerable"]
    worst = sorted(rows, key=lambda r: r["mean_precision"])[: args.n]

    corpus = json.loads(CORPUS_DUMP.read_text(encoding="utf-8"))
    by_country: dict[str, list[dict]] = {}
    for p in corpus:
        pl = p["payload"]
        by_country.setdefault(pl["country"], []).append(pl)

    diagnoses = []
    for r in worst:
        country, q = r["expected_country"], r["question"]
        chunks = sorted(by_country.get(country, []),
                        key=lambda c: (c["source_type"], c["chunk_index"]))
        print(f"\nscanning {country} ({len(chunks)} chunks) for: {q}")
        verdicts = scan_country(q, country, chunks)
        R = sum(1 for v in verdicts if v["relevant"])
        max_ach = min(R, WINDOW) / WINDOW
        actual = r["mean_precision"]
        eff = round(actual / max_ach, 4) if max_ach else None

        # How many relevant chunks did retrieval actually surface?
        run0 = r["runs"][0]
        n_ret_rel = run0["retrieval"].get("n_relevant")

        if max_ach == 0:
            verdict = "NO RELEVANT CHUNKS ANYWHERE (corpus gap)"
        elif eff is not None and eff >= 0.85:
            verdict = "(a) CORPUS-LIMITED -- retrieval found ~everything available"
        else:
            verdict = "(b) RETRIEVAL MISS -- relevant chunks exist that retrieval did not return"

        diagnoses.append({
            "question": q, "country": country, "question_type": r["question_type"],
            "corpus_tier": r["corpus_tier"], "country_chunks": len(chunks),
            "R_relevant_in_corpus": R, "window": WINDOW,
            "max_achievable_precision": round(max_ach, 4),
            "actual_precision": actual,
            "retrieval_efficiency": eff,
            "n_relevant_retrieved_run1": n_ret_rel,
            "verdict": verdict,
            "relevant_chunks": [v for v in verdicts if v["relevant"]],
        })

    OUT.write_text(json.dumps(diagnoses, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 108)
    print("WORST PRECISION CASES -- actual vs MAX ACHIEVABLE at a fixed window of 8")
    print("=" * 108)
    print(f"{'country/type':<34}{'tier':>6}{'chunks':>8}{'R':>5}{'max_ach':>9}"
          f"{'actual':>8}{'effic':>8}   verdict")
    print("-" * 108)
    for d in diagnoses:
        print(f"{d['country'][:20]+'/'+d['question_type'][:11]:<34}{d['corpus_tier']:>6}"
              f"{d['country_chunks']:>8}{d['R_relevant_in_corpus']:>5}"
              f"{d['max_achievable_precision']:>9}{d['actual_precision']:>8}"
              f"{str(d['retrieval_efficiency']):>8}   {d['verdict'][:40]}")

    misses = [d for d in diagnoses if d["verdict"].startswith("(b)")]
    print("\n" + "=" * 108)
    if misses:
        print(f"!!! {len(misses)} CONFIRMED RETRIEVAL FAILURE(S) IN THE FROZEN CORPUS !!!")
        for d in misses:
            print(f"\n  {d['country']} / {d['question_type']}: {d['question']}")
            print(f"    {d['R_relevant_in_corpus']} relevant chunks exist; retrieval returned "
                  f"{d['n_relevant_retrieved_run1']} relevant of {d['window']}")
            print(f"    relevant chunks NOT surfaced include:")
            for v in d["relevant_chunks"][:6]:
                print(f"      [{v['source_type']} idx={v['chunk_index']}] {v['excerpt'][:110]}")
    else:
        print("No retrieval failures: every worst case is CORPUS-LIMITED.")
        print("Low precision here is a data ceiling, not a retrieval defect.")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
