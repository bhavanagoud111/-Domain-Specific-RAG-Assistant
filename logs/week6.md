# Week 6 — corpus repair, freeze, evaluation, ship

Branch `week6` off `week5`. Final build week: the deliverable is a frozen corpus, a real
evaluation with numbers I can defend, and a prototype that runs from a fresh clone.

---

## PHASE 1 — CORPUS FIXES

### 1a. Japan tourism source was State Dept text

**What was wrong.** All 15 chunks tagged `source_type=tourism` for Japan were scraped from
`travel.state.gov/.../International-Travel-Country-Information-Pages/Japan.html`. Chunk 0
opens literally `"Japan Travel Advisory | Travel.state.gov"`. Chunks 12–14 are the State
Dept site's country-picker nav (`Afghanistan Albania Algeria Andorra…`) and page footer
(`Owned by Overseas Citizens Services`) — boilerplate, not travel content at all.

**This was not a scraper bug — it was a deliberate past decision that rotted.**
`tourism_sources.csv` tagged the row `state_dept_substitute(deliberate:visa)` with a header
note: *"Japan is a deliberate State Dept choice (visa query needs entry requirements;
japan.travel has none)."* Someone traded Japan's "what to visit" coverage for visa
coverage. That trade is what made the query unanswerable.

**The trade was also unnecessary.** Two measurements:

| check | result |
|---|---|
| Japan tourism chunks with a ≥0.60-similar twin in Japan's *own* `state_dept` chunks | **11 / 15** (most at 0.78–0.86) |
| Japan tourism chunks containing any "what to visit" vocabulary | **1 / 15** (a single stray "onsen") |

Japan's 15 properly-tagged `state_dept` chunks (from the *advisory* URL) already carry the
visa/entry text — `sd idx=1` has *"1 blank page required per entry stamp"*, `sd idx=2` the
fingerprinting/landing procedures. The substitution bought nothing and cost the whole
tourism slot. So removal was safe: **the visa query loses no source.**

**Replacement source.** Re-probed `japan.travel` (the JNTO official board) — unreliable:
`https://www.japan.travel/en/` read-times-out at 30s, `/en/destinations/` returns HTTP 502.
That is presumably why it was abandoned originally. Used
`https://en.wikivoyage.org/wiki/Japan` instead — the same `wikivoyage_fallback` the corpus
already uses for Peru (53 chunks) and South Korea (84 chunks), so this introduces no new
source class.

| | old | new |
|---|---|---|
| Japan tourism chunks | 15 | **114** |
| scraped chars | — | 226,121 |
| visit-vocabulary hits in source | ~0 | 260 |
| State Dept contamination in source | 15 chunks | **0** |
| `points_count` | 2,220 | **2,319** |

Embedding cost for the re-embed: **58,033 tokens ≈ $0.0075**.

Stale points were **deleted by filter first**, not overwritten. Point ids are
`uuid5("country|source_type|chunk_index")`, so upserting 114 chunks over 15 would have
overwritten `0–14` and left nothing stale — but had the new source been *shorter*, the
high-index stale points would have silently survived. Delete-then-insert is correct
regardless of length.

### 1b. Audit of all 50 countries

Detection is by **content and source URL, never by the `source_type` tag**:
a tourism-tagged chunk is flagged if its `source_url` contains `state.gov`/`cdc.gov`, or if
its text matches ≥2 State Dept / CDC phrase patterns.

**The first version of this detector was wrong and I caught it by hand-checking.** v1 used
a case-insensitive `\bSTEP\b` (for the State Dept's "Smart Traveler Enrollment Program") and
the generic phrase `"before you travel"`. It flagged 5 countries. Reading the actual chunk
text showed 4 were false positives — it was matching the ordinary English word *step*:

- Argentina — *"Tax Free in Argentina: a **step**-by-**step** guide"* (argentina.travel)
- United Kingdom — *"**Step** back in time…", "**Step** into Britain's costume drama scene"* (visitbritain.com)
- Peru — *"…it may be cheaper to exchange USD…"* (wikivoyage)
- Vietnam — legitimate destination copy (vietnam.travel)

All four are genuine tourism content from genuine tourism domains. v2 made the State Dept
patterns case-**sensitive** and phrase-anchored (`Enroll in STEP`, `Review how STEP works`)
and dropped the generic CDC phrases. **Had I trusted v1, I would have reported 5 affected
countries and re-scraped 4 clean ones for nothing.**

Full table: see `logs/week6_audit_table.md`. Summary across all 50 countries:

| | chunks |
|---|---|
| tourism-tagged total (pre-fix) | 1,080 |
| **mislabeled (v2 detector)** | **15 — all Japan** |
| affected countries | **1 of 50** |

Post-fix re-run of the same detector: **0 mislabeled chunks, 0 affected countries.**

### 1c. Scope decision

**1 country affected, not >5 — so no stop was needed and I proceeded with the fix.**
Japan was the only country where mislabeling made "what to visit" unanswerable. No other
country required re-scraping.

### 1d. Post-fix verification — the 9 "what should I visit" queries

Compared against the Week 5 shipped-prompt audit (`logs/week5.md`, table at line 207).

| country | Week 5 citations | Week 6 citations | verdict |
|---|---|---|---|
| Italy | 4–6 | 6 | pass, unchanged |
| Mexico | 3–4 | 3 | pass, unchanged |
| Norway | 2–4 | 3 | pass, unchanged |
| Thailand | 1–2 | 2 | pass, unchanged |
| Canada | 0 (`0,0,0,0,0`) | **0** | correct refusal, unchanged |
| UAE | 2 (`2,2,2`) | **0–1, flapping** | **regressed — see note** |
| **Japan** | **0** (`0,0,0,0,0`) | **5** | **FIXED** |
| Singapore | 2 | 3 | pass, unchanged |
| Brazil | 1 (thin) | 1 (thin) | pass, unchanged |

- **Japan now resolves 5 citations, all `tourism/Japan`** — the Phase 1 objective. Week 5
  recorded 0 citations in 5/5 samples with the answer text stating the corpus had no
  recommendations; that is now false, correctly.
- **Canada still returns 0 and still flags `low_confidence`.** This is the intended
  behaviour, not a regression: Canada has exactly **1** tourism chunk, so the gate is
  right to refuse. Canada remains the corpus's honest-refusal case.
- **One country DID regress: the UAE.** Everything else holds.

#### UAE regression — investigated, and it is not the Japan change

My first draft of this log recorded UAE as "1 citation, still a pass, just stochasticity."
Re-sampling proved that wrong, so the corrected finding:

| run | citations |
|---|---|
| Week 5 audit | `2, 2, 2` |
| Week 6 9-query run | `1` |
| Week 6 re-sample ×3 | `0, 0, 0` (all `low_confidence`) |

UAE now **fails the gate in 3/4 Week 6 samples**, where Week 5 passed it 3/3.

**It is not caused by the Japan re-embed.** I traced a full UAE run. Retrieval is
country-filtered (`filter=United Arab Emirates`), and all 8 retrieved chunks are UAE's own —
Japan's 114 new chunks are structurally incapable of entering UAE's candidate set. I had
specifically hypothesised that 114 new Japan chunks might crowd a global top-k; the trace
rules that out, because the top-k is never global when a country is detected.

**The actual root cause is that UAE's tourism content is not substantive.** Its 2 tourism
chunks, in full, are:

1. the visitdubai.com page chrome — *"Skip to content / Skip to search / Plan your ultimate
   summer in Dubai"*
2. a bare list of Dubai district names — *"Al Seef, Al Quoz, Business Bay, Dubai
   International Financial Centre, … Palm Jumeirah"* — place names with **no descriptions**

Generation runs at `temperature=0.3`. Whether a model treats a naked list of district names
as *supporting* a "what should I visit" answer is a genuine coin-flip, and the
`NO_ANSWER_CLAUSE` explicitly licenses declining. Week 5 sampled the citing side; Week 6
sampled the declining side.

**Why this matters for the report.** UAE sits exactly on the citation gate's boundary, and
its pass/fail outcome is **not reproducible across weeks even with a frozen corpus and
unchanged code**. That is a property of the gate, not of the corpus — and it means any
single-sample eval number for a boundary country carries real variance. Phase 4 measures
this rather than papering over it.

---

## PHASE 2 — CORPUS FROZEN

### FROZEN `points_count` = **2,319**

Frozen 2026-07-19, after the Phase 1 Japan repair. **From this point on: no re-scraping, no
re-embedding.** Every number in Phases 3–5 is measured against this exact corpus.

- 50 countries
- `state_dept` 626 · `cdc` 514 · `tourism` 1,179
- tiers: **rich** (≥60 chunks) 16 countries · **mid** (30–59) 15 · **thin** (<30) 19

Per-country table: `logs/week6_corpus_frozen.md`.

The tier spread is the single most important context for reading the Phase 4 numbers: the
corpus is **not uniform**. It ranges from Japan at 138 chunks to the United States at 4.
Aggregate scores average over a corpus that is genuinely rich for a third of its countries
and genuinely threadbare for another third.

---

## PHASE 3 — THE EVAL SET

`evaluation/eval_set.json`, built by `evaluation/build_eval_set.py` against the frozen
corpus. Four question types (`visa`, `health`, `safety`, `what_to_visit`) across 24
countries spanning all three tiers, plus 5 deliberately-unanswerable questions.

### Reference answers are grounded structurally, not on trust

The brief requires reference answers derivable from chunks that exist in *this* corpus. That
is enforced by construction rather than by asking a model to behave:

1. retrieve an evidence window from Qdrant, filtered to the expected country;
2. hand the writer **those chunk texts and nothing else** — no country hint, no outside context;
3. instruct it to emit the literal token `INSUFFICIENT` when the chunks don't contain the
   answer, and to prefer that over a hedged guess;
4. record the exact chunk ids the reference was written from, in `grounded_in`.

The writer is `anthropic/claude-sonnet-4.5` — deliberately not gpt-4o, which generates the
answers under evaluation.

### The first version of this eval set was circular — caught and fixed

The first build rejected 12 questions as `INSUFFICIENT`, including **`visa` for Japan,
Mexico, Israel and Italy** — all rich countries. That was suspicious: I had read Japan's
visa text myself during Phase 1a (`state_dept idx=0`: *"No visa required for stays less than
90 days"*). Probing confirmed the corpus does contain it, at ranks 1–4 of a country-filtered
query.

The bug was in my own builder. `retrieve()` ran a source_type-constrained query and an
unconstrained one, concatenated them, and sliced to `TOP_K=6` — so the 6 constrained
`state_dept` chunks crowded out **every** unconstrained result. The chunk holding the answer
never reached the writer.

**Why this mattered more than a missing question.** It would have made the whole evaluation
circular: reference answers built from the runtime retriever's top-k, then used to grade
that same retriever. A retrieval miss could never have shown up as a miss — it would have
been silently reclassified as "the corpus doesn't have it", which is exactly the error that
flatters a RAG system's scores.

Fixed by scoring both result sets together and widening the reference window to
`EVIDENCE_K=12`, so the reference describes **what the corpus can support**, independent of
runtime ranking. Japan, Mexico and other visa questions now build correctly. The circular v1
is kept at `scratchpad/eval_set_v1_circular.json` for comparison.

This is the second time in Week 6 that my own measurement instrument was wrong in the
direction that would have made the results look cleaner (the first being the `\bSTEP\b`
false positives in 1b). Both were caught by checking a surprising result against raw text
rather than accepting it.
