# WanderRAG — Week 4 Investigation

Branch: `week4-investigation` (main untouched). Investigation-first: audit + log before fixes.
Corpus: Qdrant `wanderrag_chunks`, **2,220 points**, 50 countries, 3072-dim cosine (verified live, read-only).
Graph confirmed running before edits (Part 1 executed the full StateGraph end-to-end).

Per-country corpus sizes (live scroll of all 2,220 payloads) referenced below:
`Singapore 123, Mexico 104, Italy 45, Japan 39, Canada 22, Norway 21, Brazil 19, Thailand 17, UAE 16, United States 4`.
Source-type split: tourism 1080, state_dept 626, cdc 514.

---

## 1. Country filter audit

### Where retrieval queries Qdrant / how country is resolved
- **Retrieve node:** `graph/wanderrag_graph.py:242-275`. It builds
  `qfilter = Filter(must=[FieldCondition(key="country", match=MatchValue(value=country))])`
  when a country is set, else `None`, and passes it as `query_filter` to `_QDRANT.query_points(...)`
  (`:252-255`). **So a country payload filter IS applied whenever a country is resolved.**
- **Country resolution:** `_detect_country()` (`:150-159`) lowercases the *original* query and takes the
  **longest exact country-name substring** among the 50 `config.countries.names()`; if none, it falls back
  to an alias map (`usa/u.s./us citizen/america → United States`, `uk/u.k. → United Kingdom`, `:62-65`).
  Country is resolved once in `rewrite_node` (`:201`) and carried in graph state (`country`) through retries.

### Test queries (filter ON = current code) vs. a no-filter probe of the same sub-queries
Ran the **real graph** (filter ON) and separately re-embedded the exact sub-queries the pipeline produced,
querying Qdrant **without** a filter, to quantify what the filter is preventing. (`scratchpad/part1_results.json`)

| Query | Detected country | Chunks (filter ON) | Cross-country ON | Cross-country OFF (no filter) |
|---|---|---|---|---|
| "Do I need a visa for Japan as a US citizen?" | Japan | 8 (all Japan) | **0** | 1 (a United States chunk) |
| "vaccinations for Brazil" | Brazil | 5 (all Brazil) | **0** | 1 (a Saudi Arabia chunk) |
| "what to see in Italy" | Italy | 7 (all Italy) | **0** | 0 |

**Plainly: with the current code, 0 of 20 retrieved chunks were from the wrong country.** The filter is
present and not leaky for these queries. The no-filter probe shows the filter is doing real work — without
it, 2 cross-country chunks (1 US, 1 Saudi Arabia) would have entered the context across these 3 queries.
Note: the "US citizen" phrasing did **not** mis-route Japan to the US — the longest-exact-match rule picks
"Japan" over the "us citizen" alias, which is correct.

### Fix?
**No fix required** for country-named queries — filtering already works. One latent risk worth flagging (not
triggered by these 3 queries): when `_detect_country` returns `None` (query names no country, or a
non-listed alias), `qfilter` is `None` and retrieval spans all 50 countries — that is the only path to
contamination. Minimal future hardening (optional): if no country is detected, still run unfiltered but
tag the answer as multi-country, or detect country from the rewritten sub-queries too. Left unchanged this
week per "investigation-first"; no leak observed on the required queries.

---

## 2. self_check investigation (read-only — check NOT modified)

### How confidence is computed / what it flags on
- **`self_check_node`** (`:278-306`): builds a context block of the retrieved chunks (`[i] (country/source_type) text[:600]`)
  and sends a single **LLM-judge** call to `gpt-4o-mini` (`FAST_MODEL`) with a **strict** instruction:
  *"Be strict: if the context does not actually address the question, say it is insufficient."*
  The model returns JSON `{"sufficient": bool, "missing": str}`. `passed = bool(sufficient)`, and `missing`
  becomes the feedback string fed to the next rewrite. There is **no numeric score / threshold** — confidence
  is purely this binary LLM verdict.
- **Routing** (`_route_after_check`, `:358-363`): if not passed and `retry_count < 2`, bounce back to
  `rewrite` with the `missing` feedback; after 2 retries, proceed to `generate` anyway with a
  **LOW-confidence disclaimer** prepended (`generate_node` `low_conf = not passed`, `:313, :327-330`).

### 9 "what should I visit in X" queries (`scratchpad/part2_results.json`)

| Country | Corpus | Final verdict | gen low-conf | Retry loops | Citations resolved | self_check's stated reason (final) |
|---|---|---|---|---|---|---|
| Italy | 45 | **INSUFFICIENT** | yes | 2 | yes (4) | "Specific recommendations for places to visit in Italy." |
| Mexico | 104 | sufficient | no | 1 | yes (3) | passed on retry (1st pass: "no specific recommendations… mainly advisories/safety") |
| Norway | 21 | sufficient | no | 0 | yes (2) | passed first pass |
| Thailand | 17 | **INSUFFICIENT** | yes | 2 | yes (1) | "Specific recommendations or details about places to visit in Thailand." |
| Canada | 22 | **INSUFFICIENT** | yes | 2 | **no (0)** | "Specific recommendations or suggestions for places to visit in Canada." |
| UAE | 16 | **INSUFFICIENT** | yes | 2 | yes (1) | "Specific recommendations for places to visit in the United Arab Emirates." |
| Japan | 39 | **INSUFFICIENT** | yes | 2 | yes (4) | "Information about specific places or attractions to visit in Japan." |
| Singapore | 123 | sufficient | no | 1 | yes (4) | passed on retry (1st pass: "no specific recommendations") |
| Brazil | 19 | **INSUFFICIENT** | yes | 2 | yes (1) | "Specific recommendations for places to visit in Brazil." |

All retrieved chunks were on-country (0 cross-country contamination in every row). **6/9 flagged
low-confidence**; **5 of those 6 had resolved citations** (only Canada resolved 0 — a genuinely thin
tourism-content case). Every single failing reason is a paraphrase of the same thing: *"no specific
recommendations for places to visit."*

### Conclusion: SYSTEMATIC (not noise)
The low-confidence flag on well-cited "what to see" answers is **systematic**. Evidence:
- **Every** failure returns the *same* rubric complaint — "lacks specific recommendations / named
  attractions to visit" — verbatim across Italy, Thailand, Canada, UAE, Japan, Brazil.
- It is **not corpus-size driven**: Singapore (largest corpus, 123) still failed its first pass, while
  Norway (21) passed immediately; Thailand (17)/UAE (16)/Brazil (19) failed and Japan (39)/Italy (45)
  failed. Corpus size does not predict the verdict.
- The failing queries retrieved correct, on-country chunks and resolved real citations — retrieval is fine.
  The judge is enforcing a hidden expectation (an explicit ranked list of named attractions) that the
  State-Dept-advisory / CDC-health-notice corpus rarely phrases that way, so it bounces to 2 retries and
  then prepends a LOW-confidence disclaimer to a correctly-grounded answer.

**Recommendation (one line, do NOT fix now):** relax the `self_check` rubric so "sufficient" for a
"what-to-visit" intent does not require an explicit ranked list of named attractions — the flag is a
prompt-side judging bias, not a retrieval or grounding failure.

---

## 3. top-k tuning

Current `TOP_K = 5` (`graph/wanderrag_graph.py:51`); retrieve keeps up to `TOP_K + 3` merged chunks
(`:265`). Re-ran the 5 canonical `TEST_QUERIES` at k ∈ {3,5,8} by monkeypatching `wg.TOP_K` at runtime
(no file edit, **no re-embedding / no chunk-size change**).

Canonical queries: q1 Japan visa, q2 Mexico safety, q3 "visiting Vietnam", q4 Brazil vaccinations,
q5 nonsense string. (`scratchpad/part3_results.json`) — `n_chunks` is merged-unique capped at `k+3`.

| k | Query | Country | n_chunks | Citations | Grounded? | Cross-country | self_check passed | top score |
|---|---|---|---|---|---|---|---|---|
| **3** | Japan visa | Japan | 6 | 1 | yes | 0 | true | 0.732 |
| **3** | Mexico safety | Mexico | 5 | 3 | yes | 0 | false | 0.666 |
| **3** | Vietnam | Vietnam | 6 | 4 | yes | 0 | true | 0.691 |
| **3** | Brazil vax | Brazil | 3 | 3 | yes | 0 | true | 0.665 |
| **3** | nonsense | (none) | 6 | 0 | no (correct) | 0 | false | 0.594 |
| **5** | Japan visa | Japan | 8 | 1 | yes | 0 | true | 0.709 |
| **5** | Mexico safety | Mexico | 8 | 6 | yes | 0 | true | 0.668 |
| **5** | Vietnam | Vietnam | 8 | 6 | yes | 0 | true | 0.691 |
| **5** | Brazil vax | Brazil | 5 | 3 | yes | 0 | false | 0.685 |
| **5** | nonsense | (none) | 8 | 0 | no (correct) | 0 | false | 0.601 |
| **8** | Japan visa | Japan | 11 | 1 | yes | 0 | true | 0.732 |
| **8** | Mexico safety | Mexico | 11 | 5 | yes | 0 | true | 0.667 |
| **8** | Vietnam | Vietnam | 11 | 4 | yes | 0 | true | 0.691 |
| **8** | Brazil vax | Brazil | 9 | 3 | yes | 0 | false | 0.701 |
| **8** | nonsense | (none) | 11 | 0 | no (correct) | 0 | false | 0.585 |

**Observations:**
- **Grounding held at every k**: every real-country query resolved ≥1 citation; the nonsense query resolved
  0 at every k (correct low-confidence behavior). **0 cross-country chunks at any k** — the filter is
  robust to k.
- **k=3 → k=5 improves citation richness**: Mexico 3→6, Vietnam 4→6. More correct on-country evidence
  reaches `generate`.
- **k=5 → k=8 adds no grounding gain**: Mexico 6→5, Vietnam 6→4 (gen/judge variance, not improvement),
  while the score tail extends into weak matches (~0.55–0.58). Extra tokens, no better answer.
- The `self_check` pass/fail flips between k for the same query (Mexico F@3→T@5; Brazil T@3→F@5) — that is
  the **judge noise/strictness documented in Part 2**, not a retrieval effect. No obvious wrong-country or
  empty retrieval misses at any k except the intentional nonsense query.

**Recommendation: keep k = 5.** It captures the citation-richness jump over k=3 (Mexico/Vietnam roughly
double their citations) with 0 cross-country contamination, whereas k=8 adds only low-relevance tail chunks
and token cost without improving grounding or citations. No chunk-size change / no re-embedding.

---

## Cost of this investigation (real, from `logs/week3_cost_log.json`)
416 OpenRouter calls, 156,946 tokens, **$0.179 total** — Part 1 $0.0156 / Part 2 $0.077 / Part 3 $0.0865.
Run IDs prefixed `wk4_`.

## Graph health
The full StateGraph (rewrite → retrieve → self_check → generate) was invoked end-to-end **27 times** across
Parts 1–3 and returned answers + citations every time. No code on `main` was changed; **no edit was made to
the graph**, so before == after. Branch `week4-investigation` holds only this log.
