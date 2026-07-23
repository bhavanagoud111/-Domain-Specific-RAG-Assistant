"""Week 7 Step 1 — measure the RETRIEVAL CEILING, before changing any retrieval code.

THE QUESTION THIS ANSWERS
-------------------------
Week 6 reported mean retrieval precision of 44.2%. That number is uninterpretable on its
own, because precision is capped by how much genuinely relevant material *exists*. If a
country's corpus contains only 3 chunks that could answer "what should I visit in X", then
retrieving 8 chunks can never score above 3/8 = 37.5%, and a 44.2% system is not
under-performing -- it is near the ceiling. Conversely if 40 relevant chunks exist,
44.2% means the ranker is leaving most of them on the floor.

So for every eval question we compute:

    R  = number of genuinely relevant chunks in that country's ENTIRE corpus
    max achievable precision = min(R, 8) / 8      (8 = TOP_K + 3, the retrieval window)
    retrieval efficiency     = actual precision / max achievable

IDENTICAL JUDGE, IDENTICAL CRITERIA -- BY IMPORT, NOT BY COPY
-------------------------------------------------------------
``RELEVANCE_PROMPT``, ``_judge`` and ``assert_judge_blinded`` are IMPORTED from
``run_eval`` rather than reproduced here. A copy could drift from the original by a word
and silently make the ceiling incomparable to the measurement it is the ceiling for. The
import makes divergence impossible.

Chunks are judged in batches of 8 -- the same batch size the eval judges at (it scores the
TOP_K+3 = 8 retrieved chunks in a single call). Judging 46 chunks in one call would be a
different task presented to the judge (longer context, more opportunity for relative rather
than absolute grading), so the batch size is held constant even though it costs more calls.

Chunk text is truncated to 900 chars and rendered in exactly the format ``one_run`` uses.

WHAT THIS SCRIPT DOES NOT TOUCH
-------------------------------
It is READ-ONLY with respect to the corpus (Qdrant ``scroll``, no writes) and with respect
to ``eval_set.json``. It changes no retrieval code -- it runs BEFORE the Step 2 change, so
the ceiling is a property of the corpus, not of any ranker.

Run:  PYTHONPATH=. python evaluation/measure_ceiling.py
"""

from __future__ import annotations

import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from config import settings
# Same judge, same criteria -- imported, never copied. See module docstring.
from evaluation.run_eval import JUDGE_MODEL, RELEVANCE_PROMPT, _judge

HERE = Path(__file__).resolve().parent
EVAL_SET = HERE / "eval_set.json"
OUT = HERE / "ceiling.json"

BATCH = 8        # == TOP_K + 3, the eval's own judging batch size
WINDOW = 8       # == TOP_K + 3, the retrieval window precision is measured over
WORKERS = 8
MAX_ATTEMPTS = 3

_LOCK = threading.Lock()


def load_corpus() -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Scroll the whole frozen corpus and group chunks by country. READ-ONLY."""
    client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    points: list[Any] = []
    offset = None
    while True:
        batch, offset = client.scroll(
            collection_name=settings.QDRANT_COLLECTION, limit=1000,
            offset=offset, with_payload=True, with_vectors=False,
        )
        points.extend(batch)
        if offset is None:
            break

    by_country: dict[str, list[dict[str, Any]]] = {}
    for p in points:
        pay = p.payload or {}
        by_country.setdefault(pay.get("country"), []).append({
            "id": str(p.id),
            "country": pay.get("country"),
            "source_type": pay.get("source_type"),
            "source_url": pay.get("source_url"),
            "text": pay.get("text", "") or "",
        })
    # Stable order so the run is reproducible and auditable by chunk id.
    for v in by_country.values():
        v.sort(key=lambda c: c["id"])
    return by_country, len(points)


def judge_batch(question: str, chunks: list[dict[str, Any]]) -> list[bool | None]:
    """Judge one batch of chunks for relevance to ``question``.

    Renders chunks exactly as ``run_eval.one_run`` does. Returns one verdict per chunk;
    ``None`` marks a chunk the judge did not return a verdict for (counted as NOT relevant
    in R, and reported separately -- an unjudged chunk must never inflate the ceiling).
    """
    blob = "\n\n".join(
        f"[chunk {i+1}] (country={c.get('country')}, source={c.get('source_type')})\n"
        f"{(c.get('text') or '')[:900]}"
        for i, c in enumerate(chunks)
    )
    prompt = RELEVANCE_PROMPT.format(q=question, chunks=blob)

    for attempt in range(MAX_ATTEMPTS):
        try:
            v = _judge(prompt)
            if "_parse_error" in v:
                raise ValueError(f"judge parse error: {v['_parse_error'][:120]}")
            out: list[bool | None] = [None] * len(chunks)
            for x in v.get("verdicts", []):
                idx = int(x.get("chunk", 0)) - 1
                if 0 <= idx < len(chunks):
                    out[idx] = bool(x.get("relevant"))
            return out
        except Exception:
            if attempt == MAX_ATTEMPTS - 1:
                raise
    return [None] * len(chunks)


def ceiling_for_question(item: dict[str, Any],
                         corpus: dict[str, list[dict[str, Any]]],
                         progress: dict[str, int]) -> dict[str, Any]:
    q = item["question"]
    country = item["expected_country"]
    chunks = corpus.get(country, [])

    verdicts: list[bool | None] = []
    for start in range(0, len(chunks), BATCH):
        verdicts.extend(judge_batch(q, chunks[start:start + BATCH]))

    n_unjudged = sum(1 for v in verdicts if v is None)
    relevant_ids = [c["id"] for c, v in zip(chunks, verdicts) if v is True]
    R = len(relevant_ids)
    max_prec = min(R, WINDOW) / WINDOW

    with _LOCK:
        progress["done"] += 1
        print(f"  [{progress['done']}/{progress['total']}] {item['question_type']:<14} "
              f"{country:<22} {item['corpus_tier']:<5} "
              f"corpus={len(chunks):>4} R={R:>3} maxP={max_prec:.3f}"
              + (f"  UNJUDGED={n_unjudged}" if n_unjudged else ""), flush=True)

    return {
        "question": q,
        "expected_country": country,
        "question_type": item["question_type"],
        "corpus_tier": item["corpus_tier"],
        "answerable": item["answerable"],
        "country_corpus_size": len(chunks),
        "n_judged": len(chunks) - n_unjudged,
        "n_unjudged": n_unjudged,
        "R": R,
        "max_achievable_precision": round(max_prec, 4),
        "relevant_chunk_ids": relevant_ids,
    }


def main() -> None:
    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    items = data["items"]
    corpus, total_points = load_corpus()

    print(f"judge = {JUDGE_MODEL} (imported from run_eval)   blinded = True")
    print(f"corpus points_count = {total_points} (FROZEN, read-only scroll)")
    n_calls = sum(math.ceil(len(corpus.get(i['expected_country'], [])) / BATCH) for i in items)
    n_judg = sum(len(corpus.get(i['expected_country'], [])) for i in items)
    print(f"questions = {len(items)}   chunk-judgments = {n_judg}   "
          f"judge calls = {n_calls} (batch={BATCH})\n")

    done: dict[str, Any] = {}
    if OUT.exists():
        done = {r["question"]: r for r in json.loads(OUT.read_text(encoding="utf-8")).get("results", [])}
        print(f"[resume] {len(done)} questions already done\n")

    todo = [i for i in items if i["question"] not in done]
    progress = {"done": len(done), "total": len(items)}

    results: list[dict[str, Any]] = []
    if todo:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(ceiling_for_question, it, corpus, progress) for it in todo]
            for f in futures:
                rec = f.result()
                results.append(rec)
                done[rec["question"]] = rec
                with _LOCK:
                    ordered = [done[i["question"]] for i in items if i["question"] in done]
                    OUT.write_text(json.dumps({
                        "judge_model": JUDGE_MODEL, "judge_blinded": True,
                        "corpus_points_count": total_points,
                        "batch_size": BATCH, "window": WINDOW,
                        "results": ordered,
                    }, indent=2, ensure_ascii=False), encoding="utf-8")

    ordered = [done[i["question"]] for i in items if i["question"] in done]
    OUT.write_text(json.dumps({
        "judge_model": JUDGE_MODEL, "judge_blinded": True,
        "corpus_points_count": total_points,
        "batch_size": BATCH, "window": WINDOW,
        "results": ordered,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {OUT}  ({len(ordered)} questions)")


if __name__ == "__main__":
    main()
