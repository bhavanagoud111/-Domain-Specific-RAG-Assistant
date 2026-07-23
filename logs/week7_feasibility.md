# Week 7 feasibility — is 65–75% precision reachable? (offline, before spending an eval run)

Branch `week7-precision`. Corpus **FROZEN at 2,319**. `eval_set.json` untouched
(`80fbd1020e62cb29…`). **Nothing implemented.** No full eval run. **No judge calls** —
relevance reused from the Step 1 R sets (`ceiling.json`).

Live work was 91 embedding calls (one depth-20 raw-question retrieval per question, since
top-N for every N ≤ 20 is a prefix of the same ranked list) plus 60 graph runs for Part 4.

## VERDICT — no. 65–75% is not reachable.

> **The only configuration that touches the band is a PERFECT reranker down to 5 slots
> (66.3% calibrated) — and "perfect" means a reranker that never makes a mistake, which does
> not exist.** Every realistic estimate lands at **55–61%**.
>
> Best *available* option is D2 at N=5/N=6 (~57–59% projected) for zero cost and zero
> latency — but its gain is substantially an artifact of dividing by a smaller number, and it
> is not obviously an improvement to the product. Details below.

## The calibration this whole report rests on

Everything in Parts 1–3 is computed in **R-set space** (precision = |retrieved ∩ R| / N).
The eval measures in **eval-judge space**. Week 7 already established these disagree, and
that R-set projections are optimistic — the depth diagnostic predicted a +26.3pp
raw-question gain and the eval delivered +8.3pp.

C1 is now measured in **both** spaces, which gives an empirical anchor rather than an assumed one:

| | |
|---|---|
| C1 precision@8, offline (R-set space, all 91) | **67.0%** |
| C1 precision@8, measured by the eval (all 91) | **52.5%** |
| **calibration factor k** | **0.7832** |

R-set space is optimistic by ~28%. Every projection below is reported raw *and* multiplied
by k. Two discount variants are also shown: the requested **2.0×** on the gain over C1, and
the **3.17×** actually measured (26.3pp predicted / 8.3pp actual) — because quoting only the
rosier factor would overstate feasibility.

*Assumption, stated:* calibration is multiplicative and stable across configs. It is anchored
on one point. Treat calibrated numbers as best estimates, not guarantees.

---

## PART 1 — D2 (tighter window), offline

Truncating the current C1 ranked list. R-set space:

| scope | N=4 ceil / proj / eff / rel | N=5 | N=6 | N=8 (current) |
|---|---|---|---|---|
| **ALL (91)** | 87.4 / **77.7** / 89.0 / **3.11** | 85.3 / **74.9** / 87.9 / **3.75** | 83.5 / **72.2** / 86.4 / **4.33** | 79.9 / **67.0** / 83.8 / **5.36** |
| answerable (86) | 92.4 / 82.3 / 89.0 / 3.29 | 90.2 / 79.3 / 87.9 / 3.97 | 88.4 / 76.4 / 86.4 / 4.58 | 84.6 / 70.9 / 83.8 / 5.67 |
| rich | 97.4 / 85.9 / 88.2 / 3.44 | 95.9 / 84.6 / 88.2 / 4.23 | 94.0 / 82.5 / 87.7 / 4.95 | 91.0 / 76.9 / 84.5 / 6.15 |
| mid | 93.5 / 81.5 / 87.1 / 3.26 | 91.1 / 78.5 / 86.2 / 3.93 | 89.5 / 74.7 / 83.4 / 4.48 | 85.2 / 70.4 / 82.6 / 5.63 |
| thin | 81.2 / 76.2 / 93.8 / 3.05 | 78.0 / 70.0 / 89.7 / 3.50 | 75.8 / 66.7 / 87.9 / 4.00 | 71.2 / 60.0 / 84.2 / 4.80 |
| visa | 82.4 / 61.8 / 75.0 / 2.47 | 75.3 / 57.6 / 76.6 / 2.88 | 68.6 / 52.9 / 77.1 / 3.18 | 55.9 / 40.4 / 72.4 / 3.24 |
| health | 100.0 / 91.3 / 91.3 / 3.65 | 100.0 / 89.6 / 89.6 / 4.48 | 100.0 / 86.2 / 86.2 / 5.17 | 97.8 / 79.3 / 81.1 / 6.35 |
| safety | 100.0 / 92.4 / 92.4 / 3.70 | 100.0 / 90.4 / 90.4 / 4.52 | 100.0 / 89.1 / 89.1 / 5.35 | 100.0 / 88.6 / 88.6 / 7.09 |
| what_to_visit | 84.8 / 78.3 / 92.3 / 3.13 | 81.7 / 73.9 / 90.4 / 3.70 | 79.7 / 71.0 / 89.1 / 4.26 | 77.2 / 67.4 / 87.3 / 5.39 |

**Which N projects into 65–75%? None, once calibrated.** In eval space: N=4 → 60.9%,
N=5 → 58.7%, N=6 → 56.5%. Only the *uncalibrated* R-set numbers appear to reach the band,
and those are exactly the numbers already shown to run ~28% hot.

**What it costs in citable material** — mean relevant chunks per answer:

| N | relevant/answer | vs N=8 |
|---|---:|---:|
| 8 (current) | **5.36** | — |
| 6 | 4.33 | **−19%** |
| 5 | 3.75 | **−30%** |
| 4 | 3.11 | **−42%** |

**Efficiency barely moves** (83.8% → 89.0% from N=8 to N=4) because the ceiling rises in
lockstep with the projection. That is the tell: D2 is not finding anything new.

---

## PART 2 — D1 (reranker at depth 20), offline

**recall@20 (raw question, country-filtered) = 73.2%** on answerable questions — rich 64.2%,
mid 79.0%, thin 99.2%, visa 89.5%, health 85.0%, safety 64.3%, what_to_visit 73.3%.
This is the hard cap on any depth-20 reranker.

| | offline | **calibrated** | disc 2.0× | disc 3.17× |
|---|---:|---:|---:|---:|
| **D1 perfect rerank 20→8** | 78.7% | **61.6%** | 57.1% | 55.4% |

Perfect-rerank efficiency is 98.5% of ceiling — i.e. depth 20 already contains nearly
everything needed to fill 8 slots. **The 8-slot window, not candidate depth, is the binder.**

Deeper candidates add almost nothing:

| | offline | calibrated |
|---|---:|---:|
| perfect rerank 20→8 | 78.7% | 61.6% |
| perfect rerank **50**→8 | 79.7% | **62.4%** |

Despite recall rising 73.2% → 93.4%, calibrated projection moves +0.8pp — because filling 8
slots rarely needs more than depth 20 supplies. **A reranker should use depth 20; depth 50 is
wasted spend.**

---

## PART 3 — D1 + D2 (rerank depth 20 → 5), offline

| | offline | **calibrated** | disc 2.0× | disc 3.17× |
|---|---:|---:|---:|---:|
| **perfect rerank 20→5** | 84.6% | **66.3%** | 59.4% | 56.8% |
| perfect rerank 50→5 | 85.3% | 66.8% | 59.6% | 57.0% |

Ceiling@5 = 85.3%, efficiency 99.2%. **This is the only config that enters 65–75%, and only
under the perfect-reranker assumption.** Apply any realism discount and it falls to 57–59%.

### Decision table (all 91, calibrated to eval space)

| config | offline | **calibrated** | disc 2.0× | disc 3.17× | in 65–75%? |
|---|---:|---:|---:|---:|:--:|
| C1 (current, N=8) | 67.0% | **52.5%** | 52.5% | 52.5% | no |
| D2 window N=6 | 72.2% | 56.5% | 54.5% | 53.8% | no |
| D2 window N=5 | 74.9% | 58.7% | 55.6% | 54.5% | no |
| D2 window N=4 | 77.7% | 60.9% | 56.7% | 55.1% | no |
| D1 rerank 20→8 (perfect) | 78.7% | 61.6% | 57.1% | 55.4% | no |
| **D1+D2 rerank 20→5 (perfect)** | 84.6% | **66.3%** | 59.4% | 56.8% | **only here** |

---

## PART 4 — citation risk check (LIVE, 10 queries × 3 runs × 2 configs = 60 graph runs)

No source file was modified. `retrieve_node` reads `TOP_K` at call time in exactly two places
(fetch limit and window slice), so setting `TOP_K=2` in-process yields fetch=5/window=5 —
exactly a top-5 window under C1's single generator. 3 runs per config because gate verdicts
flip at the boundary at `temperature=0.3`.

| type | country | cits@8 | cits@5 | mean8 | mean5 | gate8 | gate5 |
|---|---|---|---|---:|---:|---:|---:|
| what_to_visit | Japan | [4,4,5] | [4,4,4] | 4.3 | 4.0 | 3/3 | 3/3 |
| what_to_visit | Canada | [0,0,0] | [0,0,0] | 0.0 | 0.0 | 0/3 | 0/3 |
| visa | Japan | [1,1,1] | [1,1,1] | 1.0 | 1.0 | 3/3 | 3/3 |
| nonsense | — | [0,0,0] | [0,0,0] | 0.0 | 0.0 | 0/3 | 0/3 |
| safety | Italy | [6,5,5] | [5,2,4] | 5.3 | **3.7** | 3/3 | 3/3 |
| health | Thailand | [4,5,4] | [4,4,4] | 4.3 | 4.0 | 3/3 | 3/3 |
| what_to_visit | Singapore | [3,4,4] | [3,3,2] | 3.7 | **2.7** | 3/3 | 3/3 |
| safety | Norway | [2,2,2] | [2,2,2] | 2.0 | 2.0 | 3/3 | 3/3 |
| what_to_visit | Greece | [4,3,5] | [3,3,4] | 4.0 | 3.3 | 3/3 | 3/3 |
| what_to_visit | UAE | [2,1,1] | [2,2,1] | 1.3 | 1.7 | 3/3 | 3/3 |

| | window 8 | window 5 |
|---|---:|---:|
| mean citations resolved | 2.60 | **2.23 (−14.1%)** |
| gate passes | 24/30 | **24/30** |
| THIN passes (1 citation) | 5/30 | 4/30 |
| **pass → fail regressions** | — | **0** |

**Nothing that passed at 8 failed at 5.** Canada correctly refuses in both (0/3), and the
nonsense query resolves 0 citations in both. The refusal behaviour is intact.

Citation supply falls 14.1% — less than the 30% drop in *available* relevant chunks, because
the model was never citing all of them. Italy safety (5.3 → 3.7) and Singapore
what-to-visit (3.7 → 2.7) are the real losses; these are content-rich answers getting thinner.

**Caveat:** 10 queries is a screening check, not an eval. It establishes that window 5 does
not *break* the gate; it does not establish that answer quality holds.

---

## VERDICT

**65–75% end-to-end precision is not reachable from here.** Plainly:

* Every free or cheap config projects to **56–61%** calibrated.
* The only config touching the band (66.3%) assumes a **perfect** reranker. Discounted by the
  factor this project has already measured on itself, it gives **57–59%**.
* The corpus ceiling is **79.9%**, and C1 already captures **70.2%** of it. The remaining
  headroom is smaller than the target implies.

### Why D2's gain is not what it looks like

D2 raises precision by **retrieving less**. It finds nothing new: efficiency moves only
83.8% → 89.0% from N=8 to N=4 because ceiling and projection rise together. Meanwhile
relevant chunks per answer fall **5.36 → 3.11 (−42%)**, and live citations fall 14.1%.

Precision is a ratio. Shrinking the denominator improves it by construction. Reporting
"58.7% precision" from N=5 against "52.5%" from N=8 compares two different products — one
that offers the user ~5.4 relevant sources and one that offers ~3.8. **Recommending D2 to hit
a precision target would be optimising the metric rather than the system**, and it partly
undoes Week 4's deliberate widening to 8 for citation richness.

### Recommendation

1. **Do not chase 65–75%.** No honest configuration reaches it. Re-baselining the target
   against the measured 79.9% ceiling would be the useful move.
2. **Do not spend the eval run on D2 alone.** Its projected +4–6pp is largely a denominator
   artifact, and Part 4 shows it costs 14% of citations for no new information.
3. **If one eval run is available, spend it on D1+D2 (rerank 20→5)** — the only config with a
   real mechanism (it genuinely reorders) *and* the highest projection. Expect **57–59%**,
   not 66%. Budget one LLM call per query; use depth 20, since depth 50 adds +0.8pp.
4. **The largest remaining constraint is the corpus, not retrieval.** Visa is the worst type
   at every N (ceiling 55.9%, median R=4). No reranker or window change fixes it — that needs
   visa content. Safety and health already sit at 88–92% efficiency offline.
5. **C1 remains a good place to stand:** 52.5%, 70.2% efficiency, cheaper and faster than the
   sub-query baseline it replaced.

### What would change this answer

A materially higher ceiling (more/better corpus, especially visa), or a reranker that beats
the 3.17× discount this project has measured on itself. Neither is established, and neither
should be assumed in the write-up.
