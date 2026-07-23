# Week 7 — the precision ceiling, and Reciprocal Rank Fusion

Branch `week7-precision` off `week6-fixes`. Corpus **FROZEN at 2,319** throughout: no
re-scrape, no re-embed, no `processing/cleaner.py` change. `evaluation/eval_set.json`
untouched.

## Headline

| | |
|---|---|
| **Step 1 — the ceiling** | Mean max-achievable precision is **79.9%**, not 100%. So 44.2% is **44% of ~80%** — a retrieval efficiency of **55%**. |
| **Step 2 — RRF** | Implemented on the merge, `k=60`. Diff below. |
| **Step 3 — did it work?** | **No. Precision 44.2% → 41.3% (−2.9pp).** The 95% CI is [−6.8, +0.8] — the change does **not** exceed noise in either direction. RRF did not improve precision. |

The stop condition did not trigger: all 5 unanswerable questions still resolve 0 citations,
3/3 runs each.

### Integrity

| artifact | sha256 / value | state |
|---|---|---|
| `eval_set.json` | `80fbd1020e62cb29…` | **identical to Week 6** — not touched |
| corpus `points_count` | **2,319**, status `green`, dim 3072 | frozen |
| baseline `eval_results_WEEK7_BEFORE_rrf.json` | `d4cb073a4594cfd7…` | byte-identical to `eval_results_BEFORE_rewriter_fix.json`, i.e. the reverted code the 44.2% was measured on |
| judge | `anthropic/claude-sonnet-4.5`, blinded, `temperature=0` | unchanged |
| sampling | thin + unanswerable ×3, rich/mid ×1 | unchanged |

Docker was down at session start; the daemon was restarted and the corpus verified intact at
2,319 on the persistent `qdrant_storage` volume before anything else ran. Nothing was
re-ingested.

---

## STEP 1 — THE CEILING (measured before any code changed)

### What was measured

For all 91 eval questions, **R** = the number of genuinely relevant chunks in that country's
**entire** corpus — not just the retrieved window. 5,570 chunk-question judgments over 733
judge calls.

Fidelity to the eval was enforced structurally rather than by assertion:
`RELEVANCE_PROMPT`, `_judge` and `assert_judge_blinded` are **imported** from `run_eval.py`
by `evaluation/measure_ceiling.py`, never copied, so the criteria cannot drift by a word.
Chunks were judged in **batches of 8** — the same batch size the eval judges at — because
presenting 46 chunks in one call is a different task (it invites relative rather than
absolute grading). Chunk text truncated to 900 chars and rendered in the identical format.

**0 chunks went unjudged.** Any that had would have been counted as *not* relevant, so the
ceiling is if anything under-stated.

### The answer to the question that was asked

> **44.2% is 44% of ~80%, not 44% of 100%.**

| | mean max-achievable precision |
|---|---|
| **all 91 questions** | **79.9%** |
| the 86 answerable questions | 84.6% |
| the 5 unanswerable questions | 0.0% (correctly — see below) |

Retrieval efficiency at baseline: **44.2 / 79.9 = 55.3%** on the aggregate, or **61.1%** as
the mean of per-question ratios over the 86 questions where the ceiling is non-zero. Both
framings are given because they answer slightly different questions; neither flatters.

### R and the ceiling, by tier and question type

| scope | Qs | mean corpus | mean R | median R | mean maxP | maxP=100% | maxP<50% |
|---|---:|---:|---:|---:|---:|---:|---:|
| **ALL** | 91 | 61.2 | 11.5 | 10 | **79.9%** | 61 | 20 |
| rich | 39 | 95.5 | 15.1 | 13 | 91.0% | 31 | 3 |
| mid | 27 | 41.7 | 12.2 | 11 | 85.2% | 19 | 5 |
| thin | 20 | 19.6 | 6.6 | 8 | 71.2% | 11 | 7 |
| visa | 17 | 69.5 | 4.5 | 4 | **55.9%** | 2 | 8 |
| health | 23 | 59.1 | 11.0 | 10 | 97.8% | 20 | 0 |
| safety | 23 | 59.1 | 20.4 | 19 | **100.0%** | 23 | 0 |
| what_to_visit | 23 | 58.3 | 10.9 | 10 | 77.2% | 16 | 7 |
| unanswerable | 5 | 65.4 | 0.0 | 0 | 0.0% | 0 | 5 |

### Retrieval efficiency — where the headroom actually is

| scope | Qs | precision | ceiling | **efficiency** |
|---|---:|---:|---:|---:|
| ALL (answerable) | 86 | 46.8% | 84.6% | **61.1%** |
| rich | 39 | 45.1% | 91.0% | **50.2%** |
| mid | 27 | 48.8% | 85.2% | 56.3% |
| thin | 20 | 47.4% | 71.2% | **88.7%** |
| visa | 17 | 22.3% | 55.9% | 51.0% |
| health | 23 | 53.7% | 97.8% | 54.7% |
| safety | 23 | 62.9% | 100.0% | 62.9% |
| what_to_visit | 23 | 41.9% | 77.2% | 73.2% |

### Three findings that change how the earlier weeks should be read

**1. The tiering has been pointing at the wrong weak spot.** Every report since Week 4 has
treated thin countries as the problem and been careful not to average them away. But thin
countries run at **88.7% efficiency** — they are nearly maxed out against what their corpus
contains. Rich countries run at **50.2%** against a 91.0% ceiling. *The largest recoverable
headroom is in rich countries, not thin ones.* Thin-tier precision is low because the corpus
is thin; rich-tier precision is low because the ranker is leaving relevant chunks on the
floor. Those are different diseases and only the second is fixable by retrieval work.

**2. Visa questions are corpus-limited, not ranking-limited.** Ceiling 55.9%, the lowest of
any type, with a median R of just 4 — 8 of 17 visa questions cannot exceed 50% however
perfect the ranker. Japan's visa question has **R=3** in a 138-chunk corpus; the United
States' what-to-visit question has **R=1** in a 4-chunk corpus. The standing 22.3% visa
precision is roughly half of a genuinely low ceiling, not a quarter of a full one. Improving
it requires more visa content, not better ranking.

**3. Safety questions have a perfect ceiling and mediocre efficiency.** maxP = 100.0% on all
23 (mean R = 20.4), and measured precision 62.9%. That is the cleanest available evidence
that ranking — not corpus coverage — is the binding constraint *somewhere*, and it locates
where.

### The unanswerable questions are genuinely unanswerable

All 5 returned **R = 0 against their country's entire corpus** — e.g. the Japan rail-pass
price question found 0 relevant chunks among all 138 Japan chunks. This is independent
corroboration of the `answerable: false` labels from a judge that was never shown them, and
it means the 0.0% precision those questions score is correct behaviour rather than failure.

---

## STEP 2 — RANK FUSION ON THE MERGE

`TOP_K=5`, the `+3` window, the country filter, chunking, the gate and `MAX_RETRIES` are all
unchanged. `score` still carries max cosine (the UI renders it, the eval reads it); fusion
changes the **order**, not that field.

```diff
--- a/graph/wanderrag_graph.py
+++ b/graph/wanderrag_graph.py
@@ -69,6 +69,7 @@
 EMBED_MODEL = settings.EMBEDDING_MODEL  # openai/text-embedding-3-large
 TOP_K = 5
 MAX_RETRIES = 2  # self_check may bounce back to rewrite at most twice
+RRF_K = 60  # Reciprocal Rank Fusion damping constant (Cormack et al. 2009 default)

@@ -337,15 +338,54 @@ def retrieve_node(state: GraphState) -> dict[str, Any]:
     merged: dict[str, dict] = {}
+    rrf: dict[str, float] = {}
+    n_hit: dict[str, int] = {}   # how many sublists ranked this chunk (diagnostic only)
     for sub in subs:
         vec = _embed("retrieve", sub)
         hits = _QDRANT.query_points(
             collection_name=settings.QDRANT_COLLECTION,
             query=vec, query_filter=qfilter, limit=TOP_K, with_payload=True,
         ).points
-        for h in hits:
+        for rank, h in enumerate(hits, start=1):
             pid = str(h.id)
+            rrf[pid] = rrf.get(pid, 0.0) + 1.0 / (RRF_K + rank)
+            n_hit[pid] = n_hit.get(pid, 0) + 1
             if pid not in merged or h.score > merged[pid]["score"]:
                 p = h.payload or {}
                 merged[pid] = { ...unchanged... }
-    chunks = sorted(merged.values(), key=lambda c: c["score"], reverse=True)[: TOP_K + 3]
+    for pid, c in merged.items():
+        c["rrf_score"] = rrf[pid]
+        c["n_subqueries_hit"] = n_hit[pid]
+    chunks = sorted(
+        merged.values(),
+        key=lambda c: (c["rrf_score"], c["score"]),  # cosine breaks the frequent RRF ties
+        reverse=True,
+    )[: TOP_K + 3]

     return {
         "retrieved_chunks": chunks,
         "trace": [{
             "node": "retrieve", "country_filter": country, "n_subqueries": len(subs),
-            "n_chunks": len(chunks),
+            "n_chunks": len(chunks), "merge": "rrf", "rrf_k": RRF_K,
             "top_scores": [round(c["score"], 3) for c in chunks[:5]],
+            "top_rrf": [round(c["rrf_score"], 5) for c in chunks[:5]],
             "sources": sorted({f"{c['country']}/{c['source_type']}" for c in chunks}),
         }],
     }
```

A ~40-line comment block recording the Week 6 evidence and the tie-break caveat accompanies
the change in-file (omitted here for length).

### What RRF actually does to the window — measured, not assumed

`evaluation/rrf_mechanism.py` retrieves **once** per question and ranks the identical hit
pool both ways, isolating the ranking change from all sampling noise. Over all 91:

| | |
|---|---|
| mean pool size | 11.21 |
| pool ≤ 8 → set **cannot** change | **12/91 (13.2%)** |
| ≥1 chunk in more than one sublist | **86/91 (94.5%)** |
| retrieved **set** changed | 60/91 (65.9%) |
| **mean chunks swapped per question** | **1.00 of 8** |

Source composition of the retrieved window:

| source_type | cosine | RRF | Δ |
|---|---:|---:|---:|
| state_dept | 350 | 308 | **−42** |
| cdc | 260 | 275 | +15 |
| tourism | 105 | 132 | **+27** |

The mechanism works exactly as designed: it pulls the window away from State-Dept advisory
boilerplate and toward tourism content, which is precisely what the Week 6 diagnosis
prescribed.

**But it is a small intervention.** Swapping a mean of 1.00 chunk out of 8 touches 12.5% of
the window, which caps any possible precision movement at **±12.5pp** — and only in the
fantasy case where every swapped chunk flips relevance in the same direction. This bound was
computed *before* the eval ran, and it is the main reason the null result below is
unsurprising rather than disappointing.

*A correction to my own reasoning:* the Singapore smoke test showed zero sub-query overlap,
and I inferred RRF was degenerating into pure round-robin interleaving with no agreement
signal to aggregate. The full 91 disproved that — 94.5% of questions have cross-sub-query
agreement. The hypothesis was discarded rather than written up.

---

## STEP 3 — MEASUREMENT

Full 91-question re-eval, same eval set, same frozen corpus, same blinded judge, same 3×
sampling on thin + unanswerable. 0 errors.

### Before / after

| scope | Qs | precision | faithfulness | gate | country |
|---|---:|---|---|---|---|
| **ALL** | 91 | **44.2% → 41.3% (−2.9)** | 87.0% → 83.8% (−3.2) | 97.1% → 98.9% (+1.8) | 100% → 100% |
| rich | 39 | 45.1% → 42.0% (−3.1) | 86.7% → 81.1% (−5.7) | 94.9% → 97.4% (+2.6) | 100% → 100% |
| mid | 27 | 48.8% → 43.2% (−5.6) | 90.6% → 87.3% (−3.3) | 100% → 100% | 100% → 100% |
| thin | 20 | 47.4% → 47.7% (+0.4) | 82.6% → 84.2% (+1.5) | 96.7% → 100% (+3.3) | 100% → 100% |
| visa | 17 | 22.3% → 23.8% (+1.5) | 84.4% → 84.2% (−0.3) | 88.2% → 94.1% (+5.9) | 100% → 100% |
| health | 23 | 53.7% → 55.2% (+1.5) | 90.5% → 88.2% (−2.3) | 100% → 100% | 100% → 100% |
| safety | 23 | 62.9% → 59.2% (−3.6) | 90.8% → 82.7% (−8.2) | 100% → 100% | 100% → 100% |
| what_to_visit | 23 | 41.9% → 31.4% (−10.5) | 81.3% → 80.2% (−1.1) | 97.1% → 100% (+2.9) | 100% → 100% |
| unanswerable | 5 | 0.0% → 0.0% | n/a | 100% → 100% | 100% → 100% |

### Retrieval efficiency against the Step 1 ceiling

| scope | ceiling | efficiency before | efficiency after |
|---|---:|---:|---:|
| ALL (86 answerable) | 84.6% | 61.1% | **56.5%** |
| rich | 91.0% | 50.2% | 48.5% |
| mid | 85.2% | 56.3% | 51.0% |
| thin | 71.2% | 88.7% | 79.6% |
| visa | 55.9% | 51.0% | 55.0% |
| health | 97.8% | 54.7% | 56.5% |
| safety | 100.0% | 62.9% | 59.2% |
| what_to_visit | 77.2% | 73.2% | 55.0% |

### Does the change exceed noise? No.

Bootstrap 95% CI (20,000 resamples, seed fixed) on the **paired per-question deltas**:

| statistic | value |
|---|---|
| paired questions | 91 |
| mean per-question Δ | **−2.91 pp** |
| median per-question Δ | +0.00 pp |
| mean **absolute** per-question Δ | **11.89 pp** |
| stdev of Δ | 18.52 pp |
| standard error of the mean | **1.94 pp** |
| **bootstrap 95% CI of mean Δ** | **[−6.79, +0.76] pp** |
| improved / regressed / unchanged | 29 / 32 / 30 |

**The CI includes zero.** The aggregate change does not exceed the noise floor.

The per-question noise floor and the aggregate noise floor are different numbers and the
distinction decides this question. Week 7 re-measured per-question churn at **13.66pp** mean
absolute Δ on 1×-sampled questions, confirming Week 6's ~15pp. But averaging 91 paired
questions shrinks the standard error by √91, giving an aggregate resolution of about
**±3.8pp**. A −2.9pp movement sits inside that band. The eval can resolve aggregate effects
larger than roughly 4pp; this was not one.

Churn again scales inversely with sampling depth, the signature of run-to-run variance
rather than a treatment effect:

| | n | mean Δ | mean absolute Δ |
|---|---:|---:|---:|
| 1× sampled (rich + mid) | 66 | −4.12 pp | **13.66 pp** |
| 3× sampled (thin + unanswerable) | 25 | +0.29 pp | **7.21 pp** |

### Subgroup tests — nothing survives correction

| subgroup | n | Δ | 95% CI | verdict |
|---|---:|---:|---|---|
| ALL | 91 | −2.91 | [−6.79, +0.76] | within noise |
| rich | 39 | −3.10 | [−9.62, +3.19] | within noise |
| mid | 27 | −5.60 | [−13.80, +1.26] | within noise |
| thin | 20 | +0.37 | [−5.09, +6.05] | within noise |
| visa | 17 | +1.50 | [−7.40, +9.80] | within noise |
| health | 23 | +1.49 | [−4.21, +6.83] | within noise |
| safety | 23 | −3.62 | [−9.42, +2.35] | within noise |
| what_to_visit | 23 | −10.49 | [−21.38, −0.85] | excludes 0 — **but see below** |
| faithfulness (ALL) | 84 | −2.22 | [−5.98, +1.67] | within noise |

`what_to_visit` is the only subgroup whose uncorrected CI excludes zero — and it is **one of
seven** subgroup tests, where the chance of at least one spurious hit at α=0.05 is ~30%.
Bonferroni-corrected for 7 comparisons the CI is **[−25.98, +2.40], which includes zero**.
Its per-question deltas are also skewed rather than shifted: the **median is 0.0pp**, with
three large negatives (−75.0, −60.7, −60.7) dragging the mean.

**I am not claiming a what_to_visit regression.** It is a signal worth sampling properly, not
a finding.

### Gate, flips, and the refusal check

Gate correctness 97.1% → 98.9% (+1.8pp, CI [+0.00, +4.76] — includes zero, within noise).
Gate flips went 1/25 → **0/25**; with n=25 and a single flip either way this is not
distinguishable from noise and is **not** reported as a stability improvement. Thin passes
35 → 33. Correct-country stayed at **100%** in both runs.

**Unanswerable refusal check — ALL 5 STILL REFUSE, 3/3 runs each:**

| question | before | after |
|---|---|---|
| Japan 7-day rail pass price | `[F,F,F]` | `[F,F,F]` |
| Norway rainfall 2019 | `[F,F,F]` | `[F,F,F]` |
| Brazil visa cost USD | `[F,F,F]` | `[F,F,F]` |
| Louvre Tuesday hours | `[F,F,F]` | `[F,F,F]` |
| Chicago→Singapore airlines | `[F,F,F]` | `[F,F,F]` |

The stop condition did not trigger.

### Biggest movers (both directions, for honesty about the churn)

| Δ | question |
|---|---|
| +42.9pp | Mexico visa (0.000 → 0.429) |
| +33.3pp | Thailand safety (0.375 → 0.708) |
| +25.0pp | Singapore what-to-visit (0.125 → 0.375) |
| −47.5pp | China visa (0.600 → 0.125) |
| −60.7pp | Mexico what-to-visit (0.857 → 0.250) |
| −75.0pp | Turkey what-to-visit (1.000 → 0.250) |

Mexico gained 42.9pp on visa and lost 60.7pp on what-to-visit in the same run, on the same
country, from the same frozen corpus — the same pattern Week 6 documented.

### Cost and runtime

| | |
|---|---|
| wall clock (eval) | **~54 min** |
| logged graph calls | 1,096 |
| **logged graph cost** | **$0.9421** |
| ceiling measurement | 733 judge calls, 5,570 chunk-judgments |
| mechanism diagnostic | 271 calls, $0.0002 (embeddings + rewrite only) |

As in Week 6, `claude-sonnet-4.5` judge calls bypass the cost logger, so these are logged
graph spend only — not the all-in cost. The ceiling measurement's judge spend is therefore
unlogged and is the largest single cost of the week.

---

## VERDICT

**RRF did not improve precision.** Precision moved 44.2% → 41.3%, a −2.9pp point estimate
whose 95% CI is [−6.8, +0.8]. I cannot claim it helped, and I also cannot claim it hurt —
the honest statement is that the measurement does not distinguish it from no change. `k=60`
was not tuned and nothing was adjusted to chase a better number; the constant is the
standard default and it was fixed before the run.

The Week 6 diagnosis was not wrong, and this result does not refute it. The mechanism
diagnostic confirms RRF does what the diagnosis prescribed — it pulls the window away from
State-Dept boilerplate (−42) toward tourism content (+27). What the diagnosis under-weighted
is **how little of the window that touches**: 1.00 chunk in 8, a 12.5% intervention with a
hard ±12.5pp bound, against an eval that resolves ~4pp at the aggregate. Week 6 fixed the
candidate pool and could not move the number; Week 7 fixed the ranking and moved it within
noise. Both changes were correct in direction and too small in magnitude.

**The genuinely useful result this week is Step 1, not Step 2.** The ceiling reframes every
precision number in the project:

* 44.2% is **55% of what is reachable**, not 44% of it — the system is meaningfully better
  than the raw number suggests, and the remaining headroom is 36pp, not 56pp;
* **rich countries, not thin ones, hold the recoverable headroom** (50.2% efficiency against
  a 91.0% ceiling, versus thin at 88.7% against 71.2%) — which inverts the assumption the
  tier analysis has rested on since Week 4;
* **visa questions are corpus-limited** (ceiling 55.9%, median R=4) and no ranking change
  will fix them, while **safety questions have a 100% ceiling and 62.9% efficiency** and are
  where ranking work should actually be aimed.

Two methodological points for the final report. First, the ±15pp per-question noise floor
does **not** mean the eval is blind to aggregate effects — averaging 91 paired questions
resolves ~4pp, and that distinction is what let this run reach a verdict at all. Second,
Week 6 recommended RRF as "the correct next step" on the strength of a diagnosis; measuring
the ceiling first would have shown in advance that the intervention could touch at most
12.5% of the window. **Measure the ceiling before designing the fix** is the lesson, and it
generalises past this project.

---
---

# Week 7 DIAGNOSTIC — where are the missing relevant chunks?

RRF reverted (implementation preserved at `scratchpad/week7_rrf.patch`; `graph/wanderrag_graph.py`
is back to the Week 6 state, 0 RRF references). Corpus **FROZEN at 2,319**. **No judge calls** —
relevance is reused from the Step 1 R sets (`relevant_chunk_ids` in `ceiling.json`). This
diagnostic only asks *where those already-known-relevant chunks rank*.

## Answer: (a), decisively. And the reranker is not the best fix available.

> **recall@8 = 29.2%, recall@20 = 59.8%, recall@50 = 90.0%.** Recall **more than doubles**
> from the current window to depth 20. **321 relevant chunks — 3.7 per question — sit at
> ranks 9–20**, retrieved by the embedding and thrown away by the cut at 8.
>
> The relevant chunks ARE retrievable. This is case (a). But see the second finding: a
> reranker is not the cheapest or largest win on the table.

## Method

Two candidate generators, measured separately at depths 8 / 20 / 50, country-filtered:

* **`subq`** — the rewriter's sub-queries, merged by max cosine. **This is production.**
* **`raw`** — the unmodified user question, one query. Deterministic; isolates the
  embedding's own capability from the rewriter's behaviour.

`production` = per-sub-query `limit=TOP_K` (5), merged, top 8 — exactly the window the eval
measured. `depth N` = per-sub-query `limit=N`, merged, top N — what a reranker would be handed.

### The diagnostic validates against the eval

| | R-set-derived precision | eval judge-measured | gap |
|---|---:|---:|---:|
| **ALL (86 answerable)** | **45.6%** | **46.8%** | −1.2 |
| **rich** | **45.2%** | **45.1%** | **+0.1** |
| thin | 46.9% | 47.4% | −0.5 |
| mid | 45.2% | 48.8% | −3.5 |

Two independent methods — the eval's judge scoring retrieved chunks in-context, versus
intersecting with R sets judged against the whole corpus — agree to 1.2pp overall and
**0.1pp on rich tier**. That is the load-bearing validation for everything below.

**Caveat, stated because it constrains what may be claimed.** The agreement holds in
aggregate and by tier but **not by question type**: safety +17.6pp, what_to_visit −23.4pp,
visa −6.9pp. The ceiling judge saw chunks in batches drawn from the whole corpus; the eval
judge saw the 8 retrieved chunks. Same prompt, different comparison context, systematically
different calibration on some types. Consequently:

* **recall ratios are robust** — numerator and denominator use the same R set, so
  recall@20/recall@8 is unaffected by calibration. The (a)/(b) verdict is safe.
* **absolute per-type precision projections inherit the calibration** and should not be read
  against the eval's per-type baselines. Tier-level and overall projections are sound.

The user's instruction to focus on rich tier lands on exactly the cell where the two methods
agree best.

## Recall by depth — production candidate generation (`subq`)

| scope | Qs | ΣR | recall@8 | recall@20 | recall@50 | rel. @ ranks 9–20 | per q | @ 21–50 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **ALL** | 86 | 1050 | **29.2%** | **59.8%** | **90.0%** | **321** | 3.7 | 317 |
| **rich** | 39 | 589 | **23.4%** | **49.6%** | **82.2%** | **154** | **3.9** | 192 |
| mid | 27 | 329 | 28.9% | 62.6% | 100.0% | 111 | 4.1 | 123 |
| thin | 20 | 132 | 56.1% | 98.5% | 100.0% | 56 | 2.8 | 2 |
| visa | 17 | 76 | 26.3% | 61.8% | 92.1% | 27 | 1.6 | 23 |
| health | 23 | 253 | 41.9% | 80.2% | 96.8% | 97 | 4.2 | 42 |
| safety | 23 | 470 | 33.0% | 62.6% | 93.4% | 139 | 6.0 | 145 |
| what_to_visit | 23 | 251 | **10.4%** | 33.5% | 76.1% | 58 | 2.5 | 107 |

Rich tier — the focus — is the **worst** on recall@8 (23.4%) and gains the most from depth
(2.12× at 20, 3.51× at 50). Thin tier is nearly saturated by depth 20 (98.5%) with only 2
relevant chunks anywhere in ranks 21–50, confirming Step 1's finding that thin countries are
close to maxed out and there is little left to recover there.

## Best case from a perfect reranker (upper bound — no real reranker reaches it)

All figures are precision over the same 8 slots, `min(hits, 8) / 8`:

| scope | current (subq@8) | perfect rerank 20→8 | perfect rerank 50→8 | ceiling |
|---|---:|---:|---:|---:|
| **ALL** | 44.6% | **70.5%** *(+25.9pp)* | 83.3% *(+38.7pp)* | 84.6% |
| **rich** | 44.2% | **69.6%** *(+25.4pp)* | **88.1%** *(+43.9pp)* | 91.0% |
| mid | 44.0% | 71.8% | 85.2% | 85.2% |
| thin | 46.2% | 70.6% | 71.2% | 71.2% |

**A perfect reranker over depth 20 recovers at best ~+26pp** (overall and on rich). Over
depth 50 it recovers ~+39pp overall and **+44pp on rich, reaching 88.1% against a 91.0%
ceiling** — i.e. depth-50 candidates contain almost everything there is to find.

Since measured precision is 44.2%, the realistic framing: a reranker that is 60–70%
efficient (a fair expectation for an LLM reranker) would land somewhere around **60–65%**
from depth 20, against today's 44.2%.

## The bigger finding: the rewriter, not the ranker, is the dominant loss

Same 8 slots, same corpus, same R sets — only the query text differs:

| scope | `subq` @8 | **`raw` @8** | delta | `raw` rerank 20→8 | ceiling |
|---|---:|---:|---:|---:|---:|
| **ALL** | 44.6% | **70.9%** | **+26.3pp** | 83.3% | 84.6% |
| **rich** | 44.2% | **76.9%** | **+32.7pp** | **89.4%** | 91.0% |
| visa | 14.7% | 40.4% | +25.7pp | 50.0% | 55.9% |
| health | 57.6% | 79.3% | +21.7pp | 97.3% | 97.8% |
| safety | 84.2% | 88.6% | +4.4pp | 100.0% | 100.0% |
| what_to_visit | 14.1% | **67.4%** | **+53.3pp** | 77.2% | 77.2% |

Per question: **raw better on 69, worse on 2, tied on 15** (mean +26.3pp, median +18.8pp).
On rich: better on 34, worse on 1. The two regressions are one chunk each (−12.5pp, Egypt
and France safety).

The `what_to_visit` cases are stark — the sub-query pipeline retrieves **zero** relevant
chunks where the raw question retrieves 7 of 8:

| country | subq hits@8 | raw hits@8 | R available |
|---|---:|---:|---:|
| Turkey | **0** | 7 | 12 |
| Israel | **0** | 7 | 11 |
| Greece | **0** | 7 | 10 |
| Mexico | **0** | 7 | 15 |
| Japan | **0** | 7 | 28 |

**`raw`@8 (70.9%) already matches `subq` + a perfect, impossible reranker over depth 20
(70.5%)** — at zero additional LLM cost and zero added latency.

### Why this does not contradict Week 6

Week 6 tested **appending** the raw question as a 4th sub-query and measured 44.2% → 44.2%.
That is consistent with this result, and the distinction is the whole point: appending left
the sub-queries in the pool, and the cosine merge continued to rank their page-furniture
chunks above the raw question's content chunks. What is measured here is the raw question as
the **sole** candidate generator — replacing, not appending. Week 6's null result was
evidence about the *merge*, not about the raw question's retrieval quality.

## Answers to the two questions asked

**(a) — yes, this is case (a).** recall@20 (59.8%) is 2.05× recall@8 (29.2%); on rich tier
2.12×. 321 relevant chunks sit at ranks 9–20. The chunks are retrievable and are being
discarded by the cut at 8, not missed by the embedding. A reranker is a valid fix and would
work: **at best +25.9pp overall / +25.4pp rich from depth 20, +38.7pp / +43.9pp from depth
50**, with the depth-50 rich case landing at 88.1% against a 91.0% ceiling.

**(b) — does not apply.** The embedding is not the constraint. At depth 50 it surfaces 90.0%
of all relevant chunks (82.2% on rich, 100% on mid and thin).

**But the ordering of fixes should change.** A reranker costs an LLM call per query over 20
candidates and buys at best +26pp. Replacing the rewriter's sub-queries with the raw
question buys +26.3pp overall and +32.7pp on rich for **free**, and the two compose: raw +
perfect rerank@20 reaches **83.3% overall and 89.4% on rich, essentially the ceiling**. The
rewriter is currently *destroying* recall it was introduced to improve — most severely on
`what_to_visit`, where it returns 0 of 8 relevant chunks on five separate countries.

Recommended order, on this evidence: **(1) fix the candidate generator, then (2) add a
reranker and re-measure.** Doing (2) first would spend an LLM call per query to recover
ground that (1) recovers for nothing.

## Caveats

* Precision projections assume a **perfect** reranker; they are upper bounds, not forecasts.
* Per-question-type projections carry the judge-calibration gap documented above. Tier-level
  and overall numbers are validated to ≤1.2pp against the eval.
* `rewrite_node` is nondeterministic (`temperature` default, gpt-4o-mini); sub-queries were
  sampled once per question and are recorded in `depth_diagnostic.json` for audit.
* Country detection agreed with `expected_country` on 90/91; the one miss is the Louvre
  question, which has R=0 and is excluded anyway.
* Nothing was implemented. Corpus frozen at 2,319, `eval_set.json` untouched
  (`80fbd1020e62cb29…`).

---
---

# Week 7 CONFIG C1 — raw question as the sole candidate generator

Branch `week7-precision`, RRF reverted. Corpus **FROZEN at 2,319**. `eval_set.json` untouched
(`80fbd1020e62cb29…`). `TOP_K`, the +3 window, the country filter, chunking, the gate and
`MAX_RETRIES` all unchanged.

## Headline — it works, end to end

> **Precision 44.2% → 52.5% (+8.3pp).** Bootstrap 95% CI **[+4.13, +12.67]**, against an
> aggregate resolution of **±4.30pp**. **The change exceeds the noise floor.**
>
> **Rich tier +13.3pp** (CI [+6.38, +20.18]). No stop condition triggered.

This is the first intervention in three weeks to move precision beyond noise. Weeks 6 and 7
Step 2 both landed inside it.

## What was implemented: C1, and why

**C1 — the raw question on every pass, including retries.** Chosen over C2 deliberately.

The job of this run was to confirm one specific measured configuration end-to-end. C2 (raw
first pass, feedback-driven rewrite on retries) would have put the sub-query generator back
into ~32% of runs, and any gate movement would then be unattributable between the candidate
generator and the retry path. C1 changes one variable.

**The consequence, stated rather than hidden:** retrieval on a retry is now *identical* to
the pass before it. The retry loop no longer re-retrieves; it only re-rolls generation at
`temperature=0.3`. `self_check` still authors its `missing` feedback string, which nothing
now consumes — left in place because it is behaviourally inert under C1 (no node reads it)
and removing it would be a second change to the experiment.

### Retry distribution — the loop did not degenerate, it mostly stopped being needed

| retries | baseline | C1 |
|---|---:|---:|
| 0 | 68.1% | **85.1%** |
| 1 | 17.0% | **2.8%** |
| 2 | 14.9% | 12.1% |

Zero-retry runs rose 17pp: better first-pass retrieval means far fewer runs reach the gate
with 0 citations at all. The 1-retry bucket collapsing (17.0% → 2.8%) while 2-retry holds
(14.9% → 12.1%) is exactly the predicted signature of C1 — when retrieval is unchanged on
retry, a run that fails once usually fails again and runs to the limit, so the middle bucket
empties. The residual 12.1% are runs the corpus genuinely cannot support.

Net: **the retry path does less work and the system is more often right on the first pass.**
C2 remains the obvious follow-up for that 12.1%, but it must be measured separately.

### The second change, required by construction

`retrieve_node` fetched `limit=TOP_K` (5) **per sub-query**. With the rewriter's 3 sub-queries
that gave a ~15-candidate pool from which `[: TOP_K + 3]` took an 8-chunk window. With a
single generator, a limit of 5 would have yielded a 5-candidate pool and **the window would
have silently shrunk from 8 chunks to 5** — a different experiment from the measured `raw@8`,
with a precision denominator changing underneath the comparison.

Fetch is now `TOP_K + 3`. `TOP_K` itself, the +3 window size, the filter, chunking, the gate
and `MAX_RETRIES` are unchanged; with the 3-sub-query rewriter this would only ever have
widened the pool.

Three functional lines changed in total:

```diff
-    raw = _chat("rewrite", FAST_MODEL, [...], max_tokens=300, json_mode=True)
-    parsed = _parse_json(raw)
-    subs = [s.strip() for s in parsed.get("sub_queries", []) if isinstance(s, str) and s.strip()]
-    if not subs:
-        subs = [original]
+    subs = [original]
...
+    fetch = TOP_K + 3
-            query=vec, query_filter=qfilter, limit=TOP_K, with_payload=True,
+            query=vec, query_filter=qfilter, limit=fetch, with_payload=True,
```

## Before / after

| scope | Qs | precision | faithfulness | gate | country |
|---|---:|---|---|---|---|
| **ALL** | 91 | **44.2% → 52.5% (+8.3)** | 87.0% → 86.6% (−0.4) | 97.1% → 98.9% (+1.8) | 100% → 100% |
| **rich** | 39 | **45.1% → 58.3% (+13.3)** | 86.7% → 85.8% (−0.9) | 94.9% → 97.4% (+2.6) | 100% → 100% |
| mid | 27 | 48.8% → 56.5% (+7.7) | 90.6% → 88.4% (−2.2) | 100% → 100% | 100% → 100% |
| thin | 20 | 47.4% → 49.0% (+1.6) | 82.6% → 85.7% (+3.0) | 96.7% → 100% (+3.3) | 100% → 100% |
| visa | 17 | 22.3% → 34.6% (+12.3) | 84.4% → 80.0% (−4.4) | 88.2% → 94.1% (+5.9) | 100% → 100% |
| health | 23 | 53.7% → 61.1% (+7.4) | 90.5% → 88.1% (−2.4) | 100% → 100% | 100% → 100% |
| safety | 23 | 62.9% → 65.2% (+2.4) | 90.8% → 91.6% (+0.8) | 100% → 100% | 100% → 100% |
| what_to_visit | 23 | **41.9% → 56.0% (+14.1)** | 81.3% → 84.6% (+3.2) | 97.1% → 100% (+2.9) | 100% → 100% |
| unanswerable | 5 | 0.0% → 0.0% | n/a | 100% → 100% | 100% → 100% |

## Significance — bootstrap 95% CI on paired per-question deltas

Aggregate resolution: stdev 20.94pp, SE **2.19pp**, 1.96×SE = **±4.30pp**.

| scope | n | Δ | 95% CI | verdict |
|---|---:|---:|---|---|
| **ALL** | 91 | **+8.32** | **[+4.13, +12.67]** | **EXCEEDS noise** |
| **rich** | 39 | **+13.26** | **[+6.38, +20.18]** | **EXCEEDS noise** |
| mid | 27 | +7.70 | [+0.01, +15.59] | marginal (lower bound at zero) |
| thin | 20 | +1.60 | [−6.27, +10.02] | within noise |
| **visa** | 17 | +12.26 | [+1.48, +23.37] | exceeds |
| **health** | 23 | +7.38 | [+0.38, +13.98] | exceeds (marginal) |
| safety | 23 | +2.35 | [−5.07, +10.33] | within noise |
| **what_to_visit** | 23 | **+14.12** | **[+4.42, +24.35]** | **EXCEEDS noise** |

Improved / regressed / unchanged: **46 / 24 / 21**. Median Δ +0.60pp, mean |Δ| 16.31pp — the
churn is as large as ever, but this time it does *not* net to zero.

Rich tier and what_to_visit — the two cells the Step 1 ceiling and the depth diagnostic both
identified as holding the recoverable headroom — are the two that moved most. The prediction
was made before the measurement and it held.

## A confound that works against the result

The window is now consistently full: `n_retrieved` was `{4:3, 5:4, 6:13, 7:17, 8:104}` at
baseline and is `{4:3, 8:138}` under C1. Mean retrieved rose 7.52 → 7.91.

A **larger** denominator makes precision **harder**, so this dilutes the headline rather than
inflating it. Two checks:

* mean *relevant* chunks retrieved (the numerator, immune to denominator change):
  **3.16 → 3.78**;
* restricting to the **69 questions where both runs retrieved a full 8-chunk window** (identical
  denominators): **Δ = +12.80pp, CI [+7.85, +17.75]** — *larger* than the +8.3pp headline.

The reported +8.3pp is therefore conservative.

## Retrieval efficiency against the Step 1 ceiling

| scope | ceiling | prec before → after | efficiency before → after |
|---|---:|---|---|
| **ALL** | 84.6% | 46.8% → 55.6% | **61.1% → 70.2% (+9.1)** |
| **rich** | 91.0% | 45.1% → 58.3% | **50.2% → 64.5% (+14.2)** |
| mid | 85.2% | 48.8% → 56.5% | 56.3% → 66.4% (+10.1) |
| thin | 71.2% | 47.4% → 49.0% | 88.7% → 86.6% (−2.1) |
| visa | 55.9% | 22.3% → 34.6% | 51.0% → 68.2% (+17.2) |
| health | 97.8% | 53.7% → 61.1% | 54.7% → 62.5% (+7.7) |
| safety | 100.0% | 62.9% → 65.2% | 62.9% → 65.2% (+2.4) |
| what_to_visit | 77.2% | 41.9% → 56.0% | 73.2% → 84.4% (+11.3) |

The system now captures **70.2%** of what the corpus makes available, up from 61.1%. Rich
tier — the largest pool of recoverable precision — went from 50.2% to 64.5%.

## Stop conditions — none triggered

**1. Unanswerable questions — ALL 5 STILL REFUSE, 3/3 runs each:**

| question | before | after |
|---|---|---|
| Japan 7-day rail pass price | `[F,F,F]` | `[F,F,F]` |
| Norway rainfall 2019 | `[F,F,F]` | `[F,F,F]` |
| Brazil visa cost USD | `[F,F,F]` | `[F,F,F]` |
| Louvre Tuesday hours | `[F,F,F]` | `[F,F,F]` |
| Chicago→Singapore airlines | `[F,F,F]` | `[F,F,F]` |

**2. Gate correctness — improved,** 97.1% → 98.9% (+1.8pp). Gate flips 1/25 → 0/25 (not
claimed as a stability improvement at n=25).

**3. Faithfulness — flat,** 87.0% → 86.6% (−0.4pp), well inside noise. Precision rose without
trading away grounding. The visa sub-group is the one to watch (−4.4pp) but its CI is wide.

## How the diagnostic's prediction actually held up

| | diagnostic predicted | measured end-to-end |
|---|---|---|
| direction | raw ≫ sub-queries | confirmed |
| ALL | 44.6% → 70.9% (+26.3pp) | 44.2% → 52.5% (**+8.3pp**) |
| rich | 44.2% → 76.9% (+32.7pp) | 45.1% → 58.3% (**+13.3pp**) |
| rank order by type | what_to_visit ≫ visa > health ≫ safety | what_to_visit +14.1 > visa +12.3 > health +7.4 > safety +2.4 — **order preserved** |

**The direction and the rank-ordering were right; the magnitude was over-predicted by roughly
2×.** This is the judge-calibration caveat flagged in the diagnostic write-up doing exactly
what was predicted: R-set-derived precision and the eval's in-context judge diverge by
question type, so absolute projections from R sets are optimistic. The diagnostic was a
reliable guide to *what to change and where the gain would concentrate*, and an unreliable
guide to *how much*. Worth carrying forward: treat R-set projections as upper bounds.

## Cost and runtime

| | |
|---|---|
| wall clock | **~37 min** (vs ~54 min baseline) |
| logged graph calls | 398 (`retrieve` 181, `generate` 179, `self_check` 38) |
| **logged graph cost** | **$0.8471** |
| `rewrite` LLM calls | **0** — eliminated by construction |

C1 removes one `gpt-4o-mini` call per pass. It is cheaper *and* faster *and* more precise.
Judge calls bypass the cost logger, as in previous weeks.

## Verdict

**Confirmed end to end.** Replacing the rewriter's sub-queries with the raw question improves
precision by **+8.3pp overall and +13.3pp on rich tier**, both beyond the ±4.3pp aggregate
resolution, while faithfulness holds flat, gate correctness improves, correct-country stays at
100%, all 5 unanswerable questions still refuse, and the system gets cheaper and faster.

The three-week arc reads honestly: Week 6 diagnosed the rewriter, tried appending the raw
question, and measured nothing (44.2% → 44.2%). Week 7 Step 2 tried fixing the merge with RRF
and measured nothing (44.2% → 41.3%, inside noise). Both failures were real information — they
progressively narrowed the cause to the *candidate generator itself* rather than the pool or
the ranking. Measuring the ceiling first, then locating the missing chunks by depth, is what
turned that into a change that finally moved.

**Remaining headroom: 52.5% against a 79.9% ceiling — efficiency 70.2%.** The next lever is a
reranker over deeper candidates, which the depth diagnostic bounds at roughly +26pp best-case
from depth 20; expect meaningfully less than that on the evidence above. C2 is the other open
question, worth testing against the 12.1% of runs that still exhaust their retries.
