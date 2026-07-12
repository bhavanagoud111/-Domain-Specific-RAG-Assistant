# WanderRAG — Ingestion Pipeline (Weeks 1–2)

A RAG-based travel-planning assistant over real government & tourism documents
for **50 countries**. This phase builds the ingestion pipeline: **scrape →
clean → chunk → embed → load** into a local Qdrant vector store.

## Tech stack
Python 3.9+ (3.11+ recommended) · `requests` + `BeautifulSoup4` (static scrape) ·
`selenium` (JS fallback) · `pdfplumber` (PDFs) · `tiktoken` (chunking) ·
OpenRouter `text-embedding-3-large` (embeddings) · Qdrant (vectors, via Docker).

## Project layout
```
wanderrag/
├── config/          countries.py (the 50 countries) · settings.py (.env-driven config)
├── scraping/        state_dept_scraper · cdc_scraper · tourism_scraper · selenium_fallback · common
├── processing/      cleaner.py (strip boilerplate) · chunker.py (512-tok chunks, 50 overlap)
├── embedding/       embed_and_load.py (batch embed + cost log + Qdrant upsert)
├── storage/         qdrant_setup.py (collection + payload indexes)
├── run_pipeline.py  end-to-end orchestrator (scrape→…→load) with a summary report
├── query.py         retrieval spot-check
├── docker-compose.yml · requirements.txt · .env.example · tourism_sources.csv · DATA_SOURCES.md
```
Working dirs (gitignored, created on demand): `raw_html/` (HTML cache),
`scraped_data/{state_dept,cdc,tourism}/`, `logs/{scrape_log,embed_cost_log}.json`.

## Setup

1. **Python deps**
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Secrets** — copy and fill in your OpenRouter key (never commit `.env`):
   ```bash
   cp .env.example .env
   # edit .env -> OPENROUTER_API_KEY=sk-or-...
   ```
   Only `OPENROUTER_API_KEY` is required; everything else has sane defaults.

3. **Start Qdrant** (needs Docker Desktop installed):
   ```bash
   docker compose up -d            # REST :6333  ·  dashboard http://localhost:6333/dashboard
   python -m storage.qdrant_setup  # create the wanderrag_chunks collection + indexes
   ```
   Reset during testing: `python -m storage.qdrant_setup --reset`.

## Run it

**Always test 3 countries before scaling to 50.**

```bash
# 1. Sanity-check the CDC site is still live (logged to DATA_SOURCES.md / scrape_log)
python -m scraping.cdc_scraper --check

# 2. Full pipeline for the test set (France, Japan, Mexico)
python run_pipeline.py --countries France Japan Mexico

# 3. Spot-check retrieval
python query.py "Japan visa requirements"
python query.py "vaccines for Mexico" --country Mexico --source cdc

# 4. Scale to all 50 once the above looks right
python run_pipeline.py --all
```

Scrape + chunk only (no embedding cost): `python run_pipeline.py --countries France --no-embed`.

Run a single scraper directly:
```bash
python -m scraping.state_dept_scraper France Japan
python -m scraping.cdc_scraper --all
python -m scraping.tourism_scraper           # processes tourism_sources.csv
```

## Cost tracking
Budget is ~$20 total. `text-embedding-3-large` on OpenRouter is **$0.13 / 1M
input tokens**. After every batch, `logs/embed_cost_log.json` records cumulative
tokens and estimated USD so you can watch spend live. The end-of-run summary
prints total chunks, scrape failures, tokens, and cost.

## Notes / gotchas
- **HTML is cached** to `raw_html/` so re-runs don't hit live `.gov` sites. Use
  `--force` to bypass the cache.
- **Failures don't crash the run** — 404s and structure changes are logged to
  `logs/scrape_log.json`. The US State Dept page for the US itself 404s by design.
- **Slugs:** unknown slugs show up as logged 404s; fix them in `config/countries.py`.
- **Selenium** is only used as a fallback when a static fetch returns near-empty
  content; State Dept and CDC are static and normally don't need it.
- See **DATA_SOURCES.md** for source URLs, slug quirks, and the CDC freshness check.
