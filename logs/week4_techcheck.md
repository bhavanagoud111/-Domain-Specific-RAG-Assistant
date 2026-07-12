# WanderRAG — Week 4 Tech Check (read-only audit)

Date: 2026-07-07 · Scope: read-first inventory + cold-boot verify. No code changed, nothing re-embedded/re-ingested. Only write side-effect: one row appended to `logs/week3_cost_log.json` by the single approved end-to-end query (B4).

---

## PART A — INVENTORY

### 1. Graph (`graph/wanderrag_graph.py`)
All 4 nodes are **defined AND wired** — no orphans.

```python
# build_graph(), lines 366-378
g.add_node("rewrite", rewrite_node)
g.add_node("retrieve", retrieve_node)
g.add_node("self_check", self_check_node)
g.add_node("generate", generate_node)
g.add_edge(START, "rewrite")
g.add_edge("rewrite", "retrieve")
g.add_edge("retrieve", "self_check")
g.add_conditional_edges("self_check", _route_after_check,
                        {"rewrite": "rewrite", "generate": "generate"})
g.add_edge("generate", END)
```

Retry cap = 2, enforced in the router:
```python
# _route_after_check(), lines 358-363
if state.get("self_check_passed"):
    return "generate"
if state.get("retry_count", 0) >= MAX_RETRIES:   # MAX_RETRIES = 2 (line 52)
    return "generate"
return "rewrite"
```
`retry_count` increments only on a rewrite that follows a failed self_check (lines 199-200). Recursion limit 25 (line 387) is a safety net above the 2-retry logical cap. **Node wiring: PASS.**

### 2. Retrieval — country payload filter (retrieve_node, lines 242-265)
Filter is built and applied:
```python
qfilter = (
    Filter(must=[FieldCondition(key="country", match=MatchValue(value=country))])
    if country else None
)
...
hits = _QDRANT.query_points(
    collection_name=settings.QDRANT_COLLECTION,
    query=vec, query_filter=qfilter, limit=TOP_K, with_payload=True,
).points
```
Country is auto-detected from the query (`_detect_country`, longest exact name match + alias table: usa/uk/america/etc.). Filter is `None` when no country detected (unfiltered search — correct fallback).

**`TOP_K = 5`** (line 51). Retrieval fetches TOP_K per sub-query, merges/dedups by point id keeping max score, then keeps the top **`TOP_K + 3 = 8`** chunks (line 265). Payload index on `country` (KEYWORD) exists in `storage/qdrant_setup.py`, so the filter is index-backed.

### 3. Config — what the code actually references
| Item | Value (in code) |
|---|---|
| Countries | 50, hardcoded in `config/countries.py` (`assert len==50`) — 18 Europe / 15 Asia-Pacific / 10 Americas / 7 ME&Africa |
| Fast model (rewrite + self_check) | `openai/gpt-4o-mini` |
| Gen model (generate) | `openai/gpt-4o` |
| Embedding model | `openai/text-embedding-3-large` (dim 3072, cosine) |
| TOP_K | 5 (keeps top 8 after merge) |
| MAX_RETRIES | 2 |
| CHUNK_SIZE / OVERLAP | 512 / 50 tokens (cl100k_base) |
| MIN_CONTENT_CHARS | 500 (Selenium-fallback trigger) |
| Qdrant | `http://localhost:6333`, collection `wanderrag_chunks` |

**Gemini → OpenAI swap CONFIRMED at the code level.** The *only* mention of "gemini" in the entire codebase is a comment (line 46) explaining that gemini/claude 404 on the dev OpenRouter key, so `openai/*` is used. No `gemini`, `google.generativeai`, `anthropic`, or `claude` is ever *called*. The module docstring still narrates a "Gemini" design in prose — docs are stale, code is not. LLM strings are hardcoded constants in the graph module (NOT env-overridable); only `EMBEDDING_MODEL`, base URL, Qdrant, and chunking are env-driven.

### 4. Ingestion modules — all COMPLETE (none stubbed)
| Module | Status | Notes |
|---|---|---|
| `scraping/state_dept_scraper.py` | Complete | `scrape_country()`, real fetch + advisory-level parse |
| `scraping/cdc_scraper.py` | Complete | `scrape_country()` + `check_cdc_freshness()` |
| `scraping/tourism_scraper.py` | Complete | CSV-driven, html+pdf, Selenium fallback; hardened CSV comment parsing |
| `scraping/selenium_fallback.py` | Complete | JS-render fallback (64 lines) |
| `scraping/common.py` | Complete | fetch/cache/log helpers |
| `processing/cleaner.py` | Complete | HTML strip + boilerplate/repeat-line removal |
| `processing/chunker.py` | Complete | tiktoken windowed chunking + metadata |
| `embedding/embed_and_load.py` | Complete | batched OpenRouter embed, uuid5 stable ids, tenacity backoff, cost log |
| `storage/qdrant_setup.py` | Complete | collection create + `country`/`source_type` keyword indexes |
| `run_pipeline.py` | Complete | scrape→clean→chunk→embed orchestrator |

Evidence it has actually run: `scraped_data/` holds **state_dept 49, cdc 50, tourism 50** real JSON records (US State Dept page correctly absent → 49). `logs/week3_cost_log.json` has 619+ logged calls. **Not run during this audit.**

### 5. UI + eval — BOTH ABSENT
- **No Gradio / Streamlit / web UI file exists.** No `gradio`/`streamlit` import anywhere; neither is in `requirements.txt`. Entry points are CLI only (`query.py`, `run_pipeline.py`, `python -m graph.wanderrag_graph`).
- **No formal eval set exists.** The only "test set" is `TEST_QUERIES` — 5 hardcoded strings inside the graph module's `__main__` harness (lines 393-399). No golden answers, no scored eval, no eval file on disk.

### 6. Implemented / Partial / Not-started
| Component | Status |
|---|---|
| Scrapers (state_dept / cdc / tourism) | ✅ Implemented |
| Cleaning + chunking | ✅ Implemented |
| Embedding + Qdrant load | ✅ Implemented |
| Qdrant collection + payload indexes | ✅ Implemented |
| LangGraph 4-node agentic graph + 2-retry loop | ✅ Implemented |
| Country-filtered retrieval | ✅ Implemented |
| Inline citations mapped to real chunks | ✅ Implemented |
| Cost logging (real token/USD) | ✅ Implemented |
| Scraped corpus on disk (149 records) | ✅ Present |
| Formal eval set (golden Q/A, scoring) | ❌ Not started |
| Gradio / web UI | ❌ Not started |
| Docstrings vs code (Gemini prose) | ⚠️ Partial — stale docs only |

---

## PART B — COLD-BOOT VERIFY  (all steps executed)

1. **Persistence:** `docker-compose.yml` uses a **named volume** `qdrant_storage:/qdrant/storage` (+ `restart: unless-stopped`) → data **persists across restarts**. Safe. ✅
2. **Container / points_count:** ✅ Verified live.
   - Container `wanderrag-qdrant` — **Up**, ports `6333-6334` mapped.
   - `curl http://localhost:6333/collections/wanderrag_chunks` → status `green`, **points_count = 2220** (matches expected ~2,220), vector size 3072.
   - (Note: the `docker` CLI is not on the default shell PATH — it lives under `/Applications/Docker.app/...` / `/usr/local/bin/docker`. Docker Desktop must be running for the stack to be reachable.)
3. **OpenRouter key:** ✅ Present and non-empty in `.env` (73 chars, `sk-or…` prefix). Read via `config/settings.py` → `load_dotenv(PROJECT_ROOT/.env)` → `OPENROUTER_API_KEY`, gated by `require_openrouter_key()`. Value not printed.
4. **One end-to-end query — RAN through the real graph:** ✅ PASS.
   - Query: `"Do I need a visa for Japan as a US citizen?"`
   - Detected country: **Japan** · retry loops: **0**
   - **Answer:** *"As a US citizen, you do not need a visa to visit Japan for stays of less than 90 days [2]."*
   - **Citations: 1** → `[2] Japan/tourism` score 0.652 — `https://travel.state.gov/.../Japan.html`
   - **Cost:** 6 OpenRouter calls · 3,104 tokens · **$0.004875** · ~10.1 s wall. One row logged to `logs/week3_cost_log.json` (run_id `week4_techcheck_japan`).
5. **Verdict (does the full stack work start-to-finish right now?):**
   > **YES — the full stack works end-to-end right now.** Docker up → Qdrant populated (2,220 pts, green) → OpenRouter key loaded → real 4-node graph returned a grounded answer with a valid citation for $0.0049. Cold-boot confirmed against live services, not memory.

---

## Broken / missing — decide before demo
- 🟡 **No formal eval set** — only 5 ad-hoc test queries; no scored/golden eval to demo accuracy numbers.
- 🟡 **No Gradio/UI** — CLI only; no visual demo surface.
- ⚪ **Docker CLI not on PATH** — Docker Desktop must be launched manually before the stack is reachable; `docker` isn't on the default shell PATH (env footgun, not a code bug).
- ⚪ **Stale docstring** — graph module prose still describes a "Gemini" design; code uses gpt-4o-mini / gpt-4o. Cosmetic.
- ⚪ **Answer used 1 citation of 8 retrieved** — expected for a narrow factual query; not a defect.

*Nothing was fixed or modified. Only change on disk: one cost-log row from the approved B4 query. Main untouched.*
