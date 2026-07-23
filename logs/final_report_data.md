# WanderRAG — Final Report Data

Compiled 2026-07-19 against the **frozen** corpus (`points_count = 2,319`).
Read-only: no re-scrape, no re-embed, no graph changes. Sources are the machine-written
logs in `logs/`, the Qdrant payloads, and git.

> ### ⚠️ Correction note — 2026-07-23
>
> Three items below were true when compiled on 2026-07-19 but have since been fixed. The
> original text is left intact for history; this note supersedes it.
>
> 1. **§C11 "scrape date display: UI DOES NOT SHOW IT" — FIXED.** `generate_node` now
>    carries `scrape_date` into each citation dict and `app.py` `_render_sources` renders
>    it on every source line (commit `8256883`). The proposal Risk-3 commitment is met.
> 2. **Appendix items 1–2 "fresh-clone verification did not run / Docker cannot execute" —
>    DONE.** Docker Desktop starts normally (the earlier dangling `/usr/local/bin/docker`
>    symlink resolves once Docker is running); Qdrant comes up on `:6333`. A full
>    fresh-clone verification ran on 2026-07-23 — venv, `pip install`, `.env`, Qdrant
>    health, and a real query returning a GROUNDED answer with citations — plus an
>    ingestion-from-cache rebuild reproducing all 2,319 points. See
>    [`logs/week8_prep.md`](week8_prep.md).
> 3. **The frozen corpus is no longer "only inside one container."** The cleaned
>    per-source JSON (`scraped_data/`, 4.9 MB) is now committed, and
>    `run_pipeline.py --from-cache --all` rebuilds the exact 2,319-point corpus with no
>    scraping — so the freeze survives a container loss.
>
> Still open from the Appendix: **nothing is pushed to the remote** (the GitHub repo is
> empty — `git push` is still required), and the Week 6 judging costs remain unlogged.

---

## A. CROSS-WEEK PROJECT NUMBERS

### A1. Total OpenRouter spend — reconciled

**Your quoted figures were undercounts.** Both came from week-log write-ups that were
finalised *before* that week's work finished, and the cost logs kept accruing afterwards.

| | you quoted | actual (from logs) |
|---|---|---|
| through Week 5 | ~$1.10 | **$1.8075** |
| Week 5 alone | ~$0.94 | **$1.3016** |
| **whole project** | — | **$3.1364** |

The `$0.9371` figure is real — it is written at `logs/week5.md:268` — but Week 5 continued
after that line was written (the log file was saved 2026-07-12 20:18; the cost log has
Week 5 entries after it, plus 38 more calls on 07-13).

**By week and purpose:**

| week | dates | ingestion embeddings | graph / dev / eval | total |
|---|---|---:|---:|---:|
| W1–3 | 2026-06-28 | $0.0781 | $0.1544 | **$0.2325** |
| W4 | 2026-07-05 | — | $0.1790 | **$0.1790** |
| W4 techcheck | 2026-07-07 | — | $0.0944 | **$0.0944** |
| W5 | 2026-07-12/13 | — | $1.3016 | **$1.3016** |
| W6 | 2026-07-19 | $0.0075 | $1.3212 | **$1.3287** |
| **TOTAL** | | **$0.0857** | **$3.0507** | **$3.1364** |

**By purpose:**

| purpose | cost | share |
|---|---:|---:|
| ingestion / embedding (corpus build) | $0.0857 | 2.7% |
| generation + graph development + evaluation | $3.0507 | 97.3% |

**By model** (3,172 logged calls, 2,241,774 tokens):

| model | calls | cost |
|---|---:|---:|
| `openai/gpt-4o` (generate) | 644 | $2.8786 |
| `openai/text-embedding-3-large` | 1,687 | $0.0988 |
| `openai/gpt-4o-mini` (rewrite, self_check) | 841 | $0.0733 |

**By node** — `generate` dominates at $2.2300 (455 calls), i.e. **73% of all spend is the
single gpt-4o generation call**. `rewrite` ($0.0177) and `retrieve` ($0.0015) are noise.

> ### Caveat: the true total is higher and is NOT fully logged
> `$3.1364` is what the project's own cost logs captured. **Week 6 evaluation calls to
> `anthropic/claude-sonnet-4.5` — the reference-answer writer, the relevance judge, the
> faithfulness judge, the precision-diagnosis batch scans and the mode control — bypass
> both loggers**, because `build_eval_set.py` / `run_eval.py` call OpenRouter through their
> own `requests.post` rather than through `graph._chat` or `embed_and_load`.
> Roughly 600 unlogged judge/writer calls were made. Report `$3.14` as **logged spend** and
> state that Week 6 evaluation judging is excluded, rather than presenting it as the
> all-in total. This is an instrumentation gap, not a missing receipt.

### A2. Corpus evolution

| stage | `points_count` | when | what changed |
|---|---:|---|---|
| start | 0 | — | empty collection |
| 3-country pilot | **97** | 2026-06-28 14:21 | France / Japan / Mexico test ingest (5 batches, 47,659 tok, $0.0062) |
| full 50-country ingest | **1,128** | 2026-06-28 14:25 | all 50 countries, first pass (57 batches, 553,450 tok, $0.0719) |
| tourism repair / upgrade | **2,220** | 2026-06-28 22:xx | **24 countries** had their tourism source replaced — State Dept substitutes and dead boards swapped for real tourism boards or Wikivoyage. Evidence: `logs/_upgrade_changed.json` (24 countries), `logs/tourism_repair_log.json` (114 entries). Embeddings logged under `week3_cost_log` nodes `upgrade_ingest` ($0.0599) + `repair_ingest` ($0.0374) |
| Week 6 Japan fix | **2,319** | 2026-07-19 08:16 | Japan tourism 15 → 114 chunks; State Dept text replaced with Wikivoyage (6 batches, 58,033 tok, $0.0075) |

The jump from 1,128 → 2,220 is the single largest corpus change in the project and it is
the reason only **one** mislabeled country (Japan) survived into Week 6: that repair pass
fixed 24 of the 25 affected countries and missed Japan.

### A3. Current source mix — **confirmed changed**

| tier | Week 3 | **now (frozen)** |
|---|---:|---:|
| official tourism board | 33 | **33** |
| Wikivoyage fallback | 16 | **17** |
| State Dept substitute | 1 | **0** |

**There are no remaining State Dept substitutes.** Japan moved from substitute → Wikivoyage
in Week 6, which is the whole delta.

The 17 Wikivoyage countries: Cambodia, Croatia, Czech Republic, Egypt, Greece, Iceland,
Israel, **Japan**, Mexico, Morocco, New Zealand, Peru, Saudi Arabia, Singapore, South Korea,
Sri Lanka, Sweden.

### A4. Git

| branch | commits |
|---|---:|
| `main` | 8 |
| `week4-investigation` | 9 |
| `week5` | 13 |
| **`week6`** (current) | **18** |

- **Tracked files: 85**
- **Remote: configured but EMPTY.** `origin` points at
  `github.com/bhavanagoud111/-Domain-Specific-RAG-Assistant.git`, but `git ls-remote --heads
  origin` returns **zero branches**, and `main` shows `[origin/main: gone]`.
  **Nothing is pushed. All 18 Week 6 commits are local only.**
- Working tree: 3 untracked scratchpad analysis scripts at time of writing.

### A5. Codebase size — 27 modules, 3,393 LOC

| subsystem | modules | LOC |
|---|---:|---:|
| evaluation | 6 | 1,170 |
| graph | 2 | 594 |
| scraping | 6 | 581 |
| config | 3 | 225 |
| UI (`app.py`) | 1 | 201 |
| processing | 3 | 188 |
| embedding | 2 | 160 |
| orchestrator (`run_pipeline.py`) | 1 | 117 |
| storage | 2 | 98 |
| CLI (`query.py`) | 1 | 59 |
| **TOTAL** | **27** | **3,393** |

Worth noting for the report: **`evaluation/` (1,170 LOC) is now the largest subsystem** —
larger than the graph it evaluates. That is a defensible reflection of where Week 6 went.

---

## B. PROTOTYPE PERFORMANCE

### B6. Latency — 10 representative queries

| group | n | median | p90 | min | max |
|---|---:|---:|---:|---:|---:|
| **ALL** | 10 | **13.78 s** | **19.85 s** | 5.41 s | 21.46 s |
| no retries | 3 | 5.59 s | 5.59 s | 5.41 s | 6.49 s |
| with retries | 7 | 16.69 s | 19.85 s | 12.78 s | 21.46 s |

**Retries are the entire latency story.** A clean single-pass answer is ~5.5 s; every retry
loop adds roughly 6–7 s. The worst case (21.46 s) is an unanswerable question burning both
retries before refusing — i.e. *the system is slowest exactly when it is about to say
"I don't know."*

Per-query detail:

| query | s | retries | citations |
|---|---:|---:|---:|
| Brazil vaccinations | 5.41 | 0 | 1 |
| Norway safety | 5.59 | 0 | 2 |
| Mexico safety | 6.49 | 0 | 4 |
| Japan visa | 12.78 | 1 | 1 |
| Mexico visa | 13.64 | 1 | 1 |
| Italy what-to-visit | 13.91 | 1 | 6 |
| Japan what-to-visit | 16.69 | 1 | 6 |
| Canada what-to-visit | 19.57 | 2 | 0 |
| nonsense query | 19.85 | 2 | 0 |
| Japan rail-pass (unanswerable) | 21.46 | 2 | 0 |

### B7. Cost per query (146 logged eval runs)

| statistic | USD |
|---|---:|
| median | **$0.0058** |
| mean | $0.0073 |
| p90 | **$0.0125** |
| max | **$0.0151** |
| min | $0.0000 |

At the median, **~172 queries per dollar**. The `$0.0000` minimum is a run whose
OpenRouter response reported no cost.

### B8. Retry distribution across the 91-question eval (141 runs)

| retries | runs | share |
|---:|---:|---:|
| 0 | 96 | **68.1%** |
| 1 | 24 | 17.0% |
| 2 | 21 | 14.9% |

By tier:

| tier | 0 retries | 1 | 2 |
|---|---:|---:|---:|
| rich | 31 (79%) | 6 (15%) | 2 (5%) |
| mid | 23 (85%) | 4 (15%) | 0 |
| thin | 42 (70%) | 14 (23%) | 4 (7%) |
| unanswerable | 0 | 0 | **15 (100%)** |

**Every unanswerable question burned the full 2 retries** — 15/15. That is the retry loop
working as designed (0 citations → retry → still 0 → retry → refuse), but it means the
refusal path is the most expensive path in both time and money. Thin-tier questions retry
roughly twice as often as mid-tier (30% vs 15%).

---

## C. SCOPE COMPLIANCE

### C9. The five "what I will definitely build" items

| # | item | verdict | evidence |
|---|---|---|---|
| 1 | 50-country scraping + ingestion into Docker Qdrant | **DELIVERED** | 50 countries, 2,319 points, 3 sources each (state_dept 626 / cdc 514 / tourism 1,179). Qdrant via `docker-compose.yml`. |
| 2 | LangGraph 4-node pipeline with conditional loop | **DELIVERED, with deviation** | `graph/wanderrag_graph.py:498-509` — but there are **5 nodes**, not 4 (`rewrite, retrieve, generate, self_check, finalize`), and the order changed (see C10). Conditional edge + `MAX_RETRIES=2` present. |
| 3 | Country-level payload filtering | **DELIVERED** | `retrieve_node` builds `Filter(must=[FieldCondition(key="country", ...)])`; payload indexes on `country` + `source_type` created in `storage/qdrant_setup.py`. Eval measured **100% correct-country retrieval across all 141 runs**. |
| 4 | Generation with inline citations (source URL + doc type) | **DELIVERED** | `generate_node` builds citations carrying `marker`, `country`, `source_type`, `source_url`, `score`. Verified rendering in the live UI (§D12). |
| 5 | Gradio chat UI | **DELIVERED** | `app.py` (201 LOC), verified running end-to-end today (§D12). |

**All five delivered.** Two carry deviations worth declaring (below) rather than being
found by a reader.

### C10. Every deviation from the proposal

| # | deviation | reason |
|---|---|---|
| 1 | **4 nodes → 5 nodes** (`finalize` added) | Needed a terminal node to stamp `low_confidence` and prepend the disclaimer after the gate failed. |
| 2 | **`self_check` moved after `generate`** | A "resolved citation" only exists once the answer is written. At the proposed pre-generate position the gate could not read it and had to use an LLM judge instead (Week 5). |
| 3 | **`self_check` semantics changed** from LLM sufficiency judge → deterministic citation count | The LLM judge systematically failed correct, well-cited answers (Week 4: 6/9 flagged, 5 with real citations). Gate is now `citations_resolved >= 1`. |
| 4 | **Model swap: Gemini → `openai/gpt-4o`** | Only `openai/*` endpoints resolved on the dev OpenRouter key at Week 3. *(Re-probed 2026-07-19: `anthropic/*` now resolves — which is why the Week 6 judge could be cross-vendor.)* |
| 5 | **Japan tourism source changed** State Dept substitute → Wikivoyage | The substitute made "what to visit in Japan" unanswerable; 11/15 of its chunks were near-duplicates of Japan's own `state_dept` chunks anyway. |
| 6 | **24 further tourism sources replaced** in the Week 2 repair pass | Dead/JS-only boards; swapped for working boards or Wikivoyage (`logs/_upgrade_changed.json`). |
| 7 | **Anti-spray clause added to the generation prompt** | Without an explicit licence to decline, the model attached every available marker to a hedged non-answer (Week 5 audit). |
| 8 | **`TOP_K = 5`, but `retrieve_node` returns `TOP_K + 3 = 8`** | Sub-query merge keeps a slightly wider candidate pool. Worth stating because it is the denominator of every precision number. |

### C11. Risk 3 — scrape date display: **DATA EXISTS, UI DOES NOT SHOW IT**

- `scrape_date` is present on **100% of chunks** (0 missing), with two values:
  `2026-06-28` (2,205 chunks) and `2026-07-19` (114 chunks, the Japan fix).
- **`grep scrape_date app.py graph/wanderrag_graph.py` → no matches.** The field is never
  propagated into the citation dicts and never rendered.

**This is an unmet proposal commitment, and it is a cheap fix**: add `scrape_date` to the
citation dict in `generate_node` (one line, alongside `source_url`) and render it in
`_render_sources` in `app.py` (one line). Not done here — the graph is frozen.

---

## D. PROTOTYPE STILL WORKS?

### D12. Live UI verification — all four queries PASS

Launched `python app.py`, drove the real Gradio UI in a browser. **The prototype works
end-to-end on the post-Japan-fix corpus.**

| query | banner | citations | sources rendered | verdict |
|---|---|---|---|---|
| What should I visit in **Japan**? | ✅ GROUNDED · retry loops: 1 | **5** | 5 × `en.wikivoyage.org` with scores 0.675→0.58 | **PASS** — the Week 6 fix is visible in the product; answer names Nijo Castle, Kyoto, the Japanese Alps, Okinawa/Peace Park, Mount Fuji |
| What should I visit in **Canada**? | ⚠️ LOW CONFIDENCE · 0 citations · retry loops: 2 | 0 | none (correctly omitted) | **PASS** — honest refusal, explanatory note rendered |
| What should I visit in **Italy**? | ✅ GROUNDED · retry loops: 1 | **6** | 6 × `italia.it` with scores | **PASS** — names Trentino, South Tyrol, Veneto, Aosta Valley, Dolomites |
| nonsense query | ⚠️ LOW CONFIDENCE · 0 citations · retry loops: 2 | 0 | none | **PASS** — states no country named "xyz nonsense country" exists in sources |

Answer text, citation markers, source-type labels ("Tourism board"), country, similarity
scores, clickable domain links, resolved-citation count and the retry counter **all render
correctly**.

#### One bug found

**`app.py:144` hardcodes the corpus size in the page header: "50 countries, 2,220 chunks".**
The frozen corpus is **2,319**. The UI has been advertising a stale number since the Japan
fix. One-line fix; not applied (report-only).

#### One thing not exercised

None of the four queries resolved **exactly one** citation, so the 🟡 **THIN GROUNDING**
banner was not triggered in this session. Its code path is unchanged from Week 5 (where it
was verified for Thailand and Brazil), but it is untested *today*. Stated rather than
assumed.

---

## E. FUTURE WORK, SPECIFIED

*(Specifications only. None of these are implemented — the corpus and graph are frozen.)*

### (a) Rewrite node — add the raw question as a fourth sub-query

`rewrite_node` currently discards the user's question and retrieves using only
source-oriented sub-queries (`"Singapore travel advisories"`, `"CDC health notices Mexico"`).
Those match source **page furniture** rather than content: the header
`"Singapore Travel Advisory | Travel.State.gov"` scores **0.761** against its sub-query,
above every genuine Singapore tourism chunk (0.576–0.681), and the score-sorted merge then
crowds real content out — for "What should I visit in Singapore?" the graph returned 6 State
Dept boilerplate chunks from a country holding 99 tourism chunks. Measured against the same
validated relevance sets, the graph's rewrite+merge path scores **0.100** mean precision
against **0.625** for the raw question passed straight through — **6.2× worse**. The fix is
to append the unmodified user question to `sub_queries` before retrieval so the merge always
contains at least one candidate set built from the actual information need, and to consider
rank-fusion (RRF) instead of raw score-sorting so one lexically-inflated header cannot
dominate. Priority: **highest** — this is the project's centrepiece node measurably harming
its own pipeline, and the fix is roughly one line plus a re-run of the eval.

### (b) Cleaner — scope the repeated-short-line rule to navigation regions

`processing/cleaner.py` deletes any line occurring ≥3 times and shorter than 40 characters,
document-wide. Because `soup.get_text(separator="\n")` puts every `<a>` on its own line, and
because tourism pages link every place name, this deletes **the destination names
themselves**. Measured across all 45 cached tourism sources: **37 of 45 affected, 643
distinct content-like tokens deleted** — Nepal loses Everest, Lumbini and Annapurna to **0
occurrences**; Switzerland loses Zermatt entirely; Israel loses "United States" from its ETA
eligibility list (5 standalone occurrences), which is why the corpus cannot answer whether a
US citizen needs an Israeli visa even though the live page can. The fix is to restrict the
repeated-line heuristic to text extracted from `<nav>`, `<header>`, `<footer>` and
`role="navigation"` subtrees, or to require that a candidate line repeat ≥3 times *and*
never appear inside a sentence-bearing block, rather than applying it globally. Priority:
**high** — it silently degrades the corpus for the exact question type ("what should I
visit") the project is built around, and it is invisible without a live-page diff.

### (c) `MIN_CONTENT_CHARS` — replace the length check with a content-quality check

The Selenium fallback fires when extracted text is shorter than `MIN_CONTENT_CHARS = 500`.
This is backwards for JS-rendered tourism boards: Canada's static fetch returned **1,235
characters of pure navigation**, sailed past the 500-char threshold, and the fallback never
fired — while Argentina (165 chars) and UAE (281 chars) *did* trigger it. A page can be
long and empty. The fix is to gate the fallback on content quality rather than length:
require a minimum count of sentence-like lines (e.g. ≥5 lines of >80 chars containing a
verb-bearing clause), or a minimum ratio of prose characters to link-text characters, and
fall back whenever that fails regardless of total length. Evidence for impact: Canada ended
with **1** tourism chunk and is the corpus's standing example of an unanswerable
"what to visit"; the thin tier is 19 of 50 countries and is overwhelmingly composed of
JS-rendered boards (UAE 705 KB of HTML → 281 chars of text). Priority: **high**, and it is
the prerequisite for fixing the thin tier at all.

### (d) Attribution as a measured eval metric, not a runtime gate

The citation gate checks that markers *resolve to real retrieved chunks* — it does **not**
check that a cited chunk supports the claim attached to it. Week 6 measured that gap
systematically for the first time: faithfulness **87.0%** across 91 questions, with concrete
failures where the answer is factually correct but the citation is wrong (Mexico and Japan
visa answers both cite chunks containing no visa content; Switzerland's answer invents
"unique dining experience with stunning views" for a chunk holding only the restaurant's
name). The recommendation is deliberately **not** to gate on attribution at runtime: Week 5
tried an attribution instruction in the prompt and it silently flipped Thailand from a thin
pass to a 0-citation refusal, i.e. it acted as a hidden gate. Instead, keep attribution as a
**reported metric** — run the blinded cross-vendor judge over a fixed eval set each time the
prompt or model changes, and treat a drop in faithfulness as a release blocker rather than
suppressing individual answers. Note the judge's measured bias when doing so: hand-verifying
12 verdicts showed it correct on **6/6 approvals** but only **4/6 rejections**, so it
over-rejects and 87.0% should be read as a **conservative floor**. Priority: **medium** —
it changes what is reported, not what ships.

---

## Appendix: what is NOT verified

1. **Phase 5 fresh-clone verification did not run.** `/usr/local/bin/docker` is a dangling
   symlink to `/Volumes/Docker/...`, an unmounted DMG. `docker compose up -d` as documented
   in the README **cannot execute on this machine**. The running Qdrant (v1.17.0) is a
   leftover container.
2. **Consequence:** the frozen 2,319-point corpus exists only inside that container, and it
   cannot be restarted if it stops. Re-ingesting would break the freeze and invalidate every
   number in this document. **Reinstall Docker Desktop before Week 7.**
3. **Nothing is pushed to the remote** (`git ls-remote --heads origin` → empty).
4. **Week 6 evaluation judging costs are unlogged** (~600 `claude-sonnet-4.5` calls), so
   `$3.1364` is logged spend, not all-in spend.
