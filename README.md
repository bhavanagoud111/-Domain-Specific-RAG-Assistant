# WanderRAG

A retrieval-augmented travel assistant over **real** government and tourism documents for
**50 countries**. Ask about visas, health requirements, safety, or what to see — every
answer is grounded in scraped source text and carries citations back to the exact chunk it
came from. When the corpus cannot answer, it says so instead of guessing.

This is a **local research prototype**, not a deployed service. Production deployment is
explicitly out of scope (see [Known limitations](#known-limitations)).

## What it is

```
scrape → clean → chunk (512 tok / 50 overlap) → embed → Qdrant
                                                          ↓
              rewrite → retrieve → generate → self_check → finalize
                            ↑___________________|  (retry ≤2 on 0 citations)
```

**Sources** — three per country where available:
- US State Dept travel advisories (`travel.state.gov`)
- CDC destination health pages (`wwwnc.cdc.gov`)
- National tourism boards, with Wikivoyage as a documented fallback

**The citation gate.** `generate` emits inline `[n]` markers, which are bounds-checked
against the chunks actually retrieved. `self_check` keys purely on that count:
`≥1 resolved citation → pass`, `0 → fail`. A failed answer is stamped **LOW CONFIDENCE**
and tells the user plainly that the corpus could not support an answer. Passing on exactly
one citation is surfaced as a **THIN** result rather than hidden.

## Setup

### Prerequisites

- **Python 3.9+** — developed and tested on 3.9.6; 3.11+ recommended. The `gradio`
  pin in `requirements.txt` is what keeps 3.9 working (see the note there).
- **Docker Desktop** (or Docker Engine + Compose v2). **Start it and confirm
  `docker info` succeeds _before_ running `docker compose` below** — a stopped Docker
  daemon is the most common first-run failure.
- **macOS or Linux.** The commands below assume a POSIX shell. On Windows use WSL2, or
  replace `source .venv/bin/activate` with `.venv\Scripts\activate`.
- **Google Chrome / Chromium** — only needed for a **live re-scrape** (Path B below), where
  some JS-rendered tourism pages fall back to headless Chrome via Selenium
  (`webdriver-manager` fetches the matching driver automatically). **Not needed** for the
  recommended cache rebuild (Path A) or to run the app against a populated store.

### 1. Clone and install

```bash
git clone https://github.com/bhavanagoud111/-Domain-Specific-RAG-Assistant.git wanderrag
cd wanderrag

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get an OpenRouter API key

WanderRAG calls **OpenRouter** for embeddings and generation, both on `openai/*` models —
embeddings via `text-embedding-3-large`, answers via `gpt-4o` / `gpt-4o-mini`. The
**evaluation harness** deliberately judges with a *different* model family,
`anthropic/claude-sonnet-4.5` (blinded), so the grader is never scoring its own generator's
output. You need a key with credit:

1. Sign up at <https://openrouter.ai>, then create a key at <https://openrouter.ai/keys>
   (it looks like `sk-or-...`).
2. Add a few dollars of credit under Billing — this is a paid API. A from-scratch corpus
   build plus normal querying costs well under $1, but a $0 balance returns HTTP 402.

```bash
cp .env.example .env          # then edit: OPENROUTER_API_KEY=sk-or-...
```

Only `OPENROUTER_API_KEY` is required; everything else in `.env` has working defaults.

### 3. Start Qdrant

```bash
docker compose up -d               # Qdrant on :6333 (dashboard at /dashboard)
python -m storage.qdrant_setup     # create collection + payload indexes (idempotent)
```

Confirm it is healthy — open <http://localhost:6333/dashboard>, or:

```bash
curl http://localhost:6333/collections/wanderrag_chunks
```

### 4. Populate the corpus

The vector store starts **empty**, so you must ingest before any query returns results.
There are two paths — **use the cache rebuild** unless you specifically want fresher data.

#### Path A (recommended) — rebuild the exact frozen corpus from cache, no scraping

A fresh clone **ships the cleaned per-source JSON** in `scraped_data/` (4.9 MB, from the
2026-06-28 scrape). `--from-cache` chunks and embeds that directly — no network scraping —
and reproduces the **exact 2,319-point corpus** every reported number was measured against:

```bash
python run_pipeline.py --from-cache --all
```

- **Exact & deterministic** — reproduces 2,319 points with the same per-source split
  (state_dept 626 / cdc 514 / tourism 1179), verified on a fresh clone 2026-07-23.
- **Cost ~$0.15** — measured **$0.1497** (1.15M tokens) in embeddings
  (`text-embedding-3-large` at $0.13/1M tokens); the only cost is embedding, since nothing
  is scraped. Spend is logged to `logs/embed_cost_log.json`.
- **Runtime ~4–5 min** (measured ~260 s; embedding-bound — no HTTP, no Selenium).
- **This is the only way to get the State Dept advisories today** — `travel.state.gov` is
  now Cloudflare-blocked and cannot be re-scraped (see Path B).

#### Path B (optional) — live re-scrape to refresh the data

Only if you want newer source content than the 2026-06-28 snapshot. This **scrapes live**
and, as of 2026-07-23, **does NOT reproduce the frozen corpus** — several sources are down.

```bash
python run_pipeline.py --countries France Japan Mexico   # always test 3 first
python run_pipeline.py --all                             # then all 50
```

Measured on a fresh clone on **2026-07-23** (3 countries — Greece, Italy, France):

- **Time** — 3 countries in **~25 s**; extrapolated **~10–20 min for all 50** (live HTTP
  plus headless-Chrome fallbacks on JS-heavy tourism boards). Chrome/Chromium must be
  installed for the Selenium fallback.
- **Cost** — the 3-country run embedded 101 chunks / 50 k tokens for **~$0.007**. A full
  50-country build is **~$0.11–0.15** in embeddings.
- Per-source scrape failures are **counted and printed in the run summary** rather than
  aborting the pipeline, so a rebuild always completes with whatever it could reach.

##### ⚠️ Source availability — a live re-scrape does NOT reproduce the frozen corpus (as of 2026-07-23)

The **2,319-chunk frozen corpus was scraped on 2026-06-28**, before several sources locked
down. A live rebuild today is **incomplete** (use Path A for an exact corpus). Verified by
a fresh-clone ingestion test:

| Source | Status today | Effect on a rebuild |
|---|---|---|
| **US State Dept** (`travel.state.gov`) | **BROKEN** — the whole domain is now behind a Cloudflare "Just a moment…" bot challenge; plain requests get **HTTP 403** and even headless Chrome only captures the challenge page. | **0 advisory chunks for all 50 countries** — the entire visa/entry/safety backbone (**626 of 2,319 chunks, ~27%**) is missing. |
| **CDC** (`wwwnc.cdc.gov`) | **Healthy** — reproduced the frozen per-country counts exactly. | Full. |
| **Tourism — Wikivoyage** (17 countries) | **Healthy** — 17/17 return 200; Greece reproduced its 53 chunks exactly. | Full. |
| **Tourism — official boards** (33 countries) | **Mostly OK** — 26/33 return 200; **7 fail** (403/406): Norway, Thailand, Malaysia, United States, Brazil, UAE, Switzerland. | Those 7 countries get **0 tourism chunks**. |

**Bottom line:** cloning and rebuilding gives you a working system for **CDC + Wikivoyage +
26 official-board tourism sources**, but with **no State Dept advisories** and 7 missing
tourism sources. The committed evaluation numbers were all measured against the **frozen**
corpus, which captured the State Dept content before the lockdown. Treat the frozen corpus
as the corpus of record; a from-scratch rebuild is a partial, best-effort refresh.

#### What to do if a source fails

- **A 403 / "Just a moment…" page (State Dept, and the 7 tourism boards above):** the host
  is blocking automated access. There is no clean fix from this repo — options are a
  Cloudflare-aware fetcher (e.g. `cloudscraper`, `undetected-chromedriver`) or a manual
  save of the page HTML into `raw_html/`. The pipeline will simply record the failure and
  continue.
- **A thin / JS-only page (200 but little text):** the scraper already retries via headless
  Chrome (needs Chrome/Chromium installed). Confirm Chrome is present if tourism boards
  come back nearly empty.
- **A timeout:** raise `REQUEST_TIMEOUT` in `.env` and re-run just that country with
  `--countries <Name> --force`.
- **Check what actually landed:** the run summary lists every failure by
  `source:country`, and `logs/scrape_log.json` records per-source detail.

## Running it

**Chat UI** — `python app.py` → http://127.0.0.1:7860

Opens on a **country gallery** — all 50 countries as a scrolling slider (with region
filter chips, search, and ‹ › arrows), each card a Wikivoyage/Wikimedia photo plus its
live source count. Click a country to open a chat **scoped to it**: the country name is
injected into the query so retrieval locks to that country (no graph change). Each turn
shows the answer, every citation as a source link with its scrape date and score, the
resolved-citation count, and the GROUNDED / THIN / LOW-CONFIDENCE banner. Expect ~5–20s
per turn (the full graph runs per question, including up to 2 retry loops).

Country photos live in `assets/countries/` and are committed; rebuild them any time with
`python scratchpad/fetch_country_images.py` (pulls Wikivoyage page-banners via the
Wikimedia API). Photo credits + licences are in `assets/countries/manifest.json`.

**CLI**

```bash
# one question through the full graph, with the node-by-node trace
python -m graph.wanderrag_graph

# retrieval only -- no generation, no cost beyond one embedding
python query.py "Japan visa requirements"
python query.py "vaccines for Mexico" --country Mexico --source cdc --k 5
```

**Evaluation** (see `evaluation/`)

```bash
PYTHONPATH=. python evaluation/build_eval_set.py   # rebuild the Q/A set from the corpus
PYTHONPATH=. python evaluation/run_eval.py         # score retrieval / faithfulness / gate
PYTHONPATH=. python evaluation/verify_judge.py     # sample judge verdicts for hand-audit
```

## Corpus stats (frozen)

Frozen **2026-07-19**. All reported evaluation numbers are measured against exactly this
corpus; nothing was re-scraped or re-embedded afterwards.

| | |
|---|---|
| **`points_count`** | **2,319** |
| countries | 50 |
| `state_dept` / `cdc` / `tourism` | 626 / 514 / 1,179 |
| chunk size | 512 tokens, 50 overlap |
| embedding model | `openai/text-embedding-3-large` (3072-d, cosine) |

Coverage is **very uneven** — this is the single most important caveat when reading any
aggregate number:

| tier | chunks/country | countries |
|---|---|---|
| rich | ≥60 | 16 |
| mid | 30–59 | 15 |
| **thin** | **<30** | **19** |

Range: Japan 138 chunks → United States 4. Per-country table in
[`logs/week6_corpus_frozen.md`](logs/week6_corpus_frozen.md).

## Advanced capability

Beyond a baseline "embed → retrieve → generate" RAG, WanderRAG adds a measured
**abstention** capability and the harness to prove it works:

- **Citation-resolution gate + abstention** — the named optional extension of Track 1.
  `generate` emits inline `[n]` markers that are bounds-checked against the retrieved
  chunks; `self_check_node` ([`graph/wanderrag_graph.py`](graph/wanderrag_graph.py))
  then passes on ≥1 resolved citation and *refuses* (LOW CONFIDENCE) on 0, rather than
  guessing. Measured **98.9% gate correctness** (see [Results](#results)).
- **Country gallery UI** — [`app.py`](app.py) opens on a scrolling gallery of all 50
  countries (region chips, search, photos, live source counts); picking one scopes the
  chat to that country and surfaces every citation with its source, scrape date and score.
- **Evaluation harness** — [`evaluation/`](evaluation/) builds a Q/A set from the corpus
  and scores retrieval precision, faithfulness, and the gate with a blinded
  cross-family judge (`anthropic/claude-sonnet-4.5`).

## Results

Measured over the frozen 2,319-point corpus — **91 questions / 141 graph runs**, judged
blinded by `anthropic/claude-sonnet-4.5`. Full write-up in [`logs/week6.md`](logs/week6.md).

| metric | value |
|---|---|
| retrieval precision | **52.5%** (baseline 44.2%) |
| faithfulness | **86.6%** |
| gate correctness | **98.9%** |
| correct-country retrieved | **100%** |

Retrieval precision is read against the corpus's own measured **79.9% ceiling** (the best
any reranker could do at this window over these relevant-chunk sets; see
[`logs/week7_feasibility.md`](logs/week7_feasibility.md)) — so 52.5% is ~66% of what is
achievable, not of a hypothetical 100%.

## Known limitations

- **Thin countries answer poorly, by design of the data rather than the code.** 19 of 50
  countries have under 30 chunks. Canada has exactly **1** tourism chunk, so "what should I
  visit in Canada" correctly returns 0 citations and refuses. That refusal is the system
  working, but it is still a coverage failure from the user's point of view.
- **Attribution is measured, not enforced.** The gate checks that citations *resolve to
  real chunks* — it does **not** verify that a cited chunk actually supports the claim
  attached to it. Measured faithfulness is reported in `logs/week6.md`; it is not 100%, and
  nothing in the pipeline blocks an unsupported-but-cited claim from reaching the user.
- **Boundary countries are not reproducible.** Countries whose tourism content is
  borderline (e.g. the UAE, whose 2 tourism chunks are page chrome plus a bare list of
  district names) flip between passing and refusing across runs at `temperature=0.3`. The
  UAE passed 3/3 in Week 5 and failed 3/4 in Week 6 with an **unchanged corpus and
  unchanged code**. Single-sample scores for such countries carry real variance.
- **The cleaner deletes standalone place names.** `processing/cleaner.py`'s
  repeated-short-line rule drops any short line that recurs ≥3×, which strips genuine
  navigation chrome — but on tourism pages every destination is a link, so bare place
  names get deleted document-wide. Measured across the cached tourism sources: **37 of 45
  affected, 643 distinct content-like tokens removed**; Nepal loses *Everest, Lumbini and
  Annapurna* to **0** occurrences. This is not fixed because rechunking would change the
  corpus and break the freeze every reported number is measured against. Full analysis in
  [`logs/week6.md`](logs/week6.md).
- **Point-in-time snapshot.** Every chunk was scraped on a fixed date and is never
  refreshed. Travel advisories, entry rules and health notices change frequently; treat
  answers as "what these sources said when scraped", not current guidance. Chunks carry a
  `scrape_date` payload field. **Do not use this for real travel decisions.**
- **Not deployed, no auth, no streaming, single user.** Qdrant runs locally with no
  authentication. Out of scope per the project proposal.
- **English-only**, and US-centric: State Dept advisories are written for US citizens, so
  visa answers assume a US passport.

## Repo layout

```
config/       countries.py (the 50) · settings.py (.env-driven)
scraping/     state_dept · cdc · tourism · selenium_fallback · common
processing/   cleaner.py (boilerplate) · chunker.py (512/50)
embedding/    embed_and_load.py (batch embed + cost log + upsert)
storage/      qdrant_setup.py (collection + payload indexes)
graph/        wanderrag_graph.py (the LangGraph pipeline + citation gate)
evaluation/   build_eval_set.py · run_eval.py · verify_judge.py · eval_set.json
scraped_data/ cleaned per-source JSON (state_dept · cdc · tourism) — the frozen corpus
assets/       hero.jpg · countries/ (50 photos + manifest.json with credits/licences)
scratchpad/   one-off audit/probe/fix scripts (not part of the pipeline)
app.py        Gradio chat UI          query.py  retrieval spot-check
run_pipeline.py  end-to-end ingestion orchestrator
logs/         weekly investigation write-ups (week4–week8) + machine cost/scrape logs
DATA_SOURCES.md  source URLs, slug quirks, and per-country source notes
```

**Committed** (present in a fresh clone): `scraped_data/` (4.9 MB — **Path A depends on
it**; the repo's `.gitignore` keeps it *out* of the ignore list on purpose), `assets/`,
`scratchpad/`, `evaluation/*.json`, all `logs/*.md`, and `DATA_SOURCES.md`.

**Created on demand** (gitignored): `raw_html/` (cached HTML, ~62 MB), `logs/*.json`
(machine cost/scrape logs), and `scratchpad/corpus_dump.json`.

See [`DATA_SOURCES.md`](DATA_SOURCES.md) for source URLs and slug quirks, and
[`logs/week6.md`](logs/week6.md) for the corpus repair, the freeze, and the full evaluation.
