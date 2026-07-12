# Data Sources

WanderRAG ingests three source types per country (50 countries total).

## 1. US State Department travel advisories
- **URL pattern:** `https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/<slug>-travel-advisory.html`
- **Slug note:** the page slug ends in `-travel-advisory.html` (e.g. `france-travel-advisory.html`), not just `<country>.html`. A few countries use non-obvious slugs (Czech Republic → `czechia`, Israel → `israel-the-west-bank-and-gaza`); these are set as overrides in `config/countries.py`. The US has no advisory page for itself — that 404 is expected and logged.
- **Type:** static HTML (no JS rendering needed).
- **Status:** ✅ live — verified working (sample: France = "Level 2 — Exercise increased caution", last updated **August 11, 2025**).

## 2. CDC Travelers' Health destination pages
- **URL pattern:** `https://wwwnc.cdc.gov/travel/destinations/traveler/none/<slug>`
- **Freshness check (REQUIRED before scraping):** `python -m scraping.cdc_scraper --check` fetches `https://wwwnc.cdc.gov/travel/destinations/list` and reports whether the site is live.
- **Status as of 2026-06-19:** ✅ **LIVE / not archived.** The destination list returns live content (actively showing a Global Measles Travel Health Notice). No update date is printed on the list page itself; individual destination pages carry their own dates.
- **Fallback:** if the freshness check ever reports the site is frozen/archived, set the env var `CDC_USE_MIRROR=1` to route requests through the `https://data.restoredcdc.org` mirror. The `--check` command prints this instruction automatically when it detects an empty/unreachable page.

## 3. Official tourism board / embassy visa pages
- **Driven by:** `tourism_sources.csv` (columns: `country, url, format`; format = `html` or `pdf`).
- **Why manual:** these URLs vary too much per country to auto-discover reliably, so the CSV is filled in by hand. The loader (`scraping/tourism_scraper.py`) skips blank/`#TODO` rows.

---

### Verification log
| Date | Source | Result |
|------|--------|--------|
| 2026-06-19 | State Dept (france) | Live; slug confirmed `…-travel-advisory.html`; Level 2, updated 2025-08-11 |
| 2026-06-19 | CDC destination list | Live; not archived; measles THN visible |
