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

Requires **Python 3.9+** and **Docker**.

```bash
git clone <repo> && cd wanderrag

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit: OPENROUTER_API_KEY=sk-or-...
```

Only `OPENROUTER_API_KEY` is required; everything else has working defaults.

```bash
docker compose up -d               # Qdrant on :6333 (dashboard /dashboard)
python -m storage.qdrant_setup     # create collection + payload indexes
```

The vector store starts **empty**. To populate it:

```bash
python run_pipeline.py --countries France Japan Mexico   # always test 3 first
python run_pipeline.py --all                             # then all 50
```

Populating all 50 costs roughly **$0.30** in embeddings (`text-embedding-3-large` at
$0.13/1M tokens); live spend is logged per batch to `logs/embed_cost_log.json`.

## Running it

**Chat UI** — `python app.py` → http://127.0.0.1:7860

Shows the answer, every citation as a source link, the resolved-citation count, and the
GROUNDED / THIN / LOW-CONFIDENCE banner. Expect ~5–20s per turn (the full graph runs per
question, including up to 2 retry loops).

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
app.py        Gradio chat UI          query.py  retrieval spot-check
run_pipeline.py  end-to-end ingestion orchestrator
logs/         weekly investigation write-ups (week3–week6) + machine cost/scrape logs
```

Gitignored working dirs, created on demand: `raw_html/`, `scraped_data/`, `logs/*.json`.

See [`DATA_SOURCES.md`](DATA_SOURCES.md) for source URLs and slug quirks, and
[`logs/week6.md`](logs/week6.md) for the corpus repair, the freeze, and the full evaluation.
