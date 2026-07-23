"""End-to-end ingestion: scrape -> clean -> chunk -> embed -> load into Qdrant.

Run the 3-country test before scaling to all 50:
    python run_pipeline.py --countries France Japan Mexico
    python run_pipeline.py --all
    python run_pipeline.py --countries France --no-embed   # scrape+chunk only (no cost)

Prints a summary: chunks per country, scrape failures, and total embedding cost.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any

from config.countries import COUNTRIES, by_name
from embedding.embed_and_load import embed_and_load
from processing.chunker import chunk_record
from scraping import cdc_scraper, state_dept_scraper, tourism_scraper
from scraping.common import save_json
from config import settings


def _scrape(country_names: list[str], force: bool) -> list[dict[str, Any]]:
    """Scrape all three sources for the given countries; return scraped records."""
    records: list[dict[str, Any]] = []
    failures: list[str] = []

    print("\n== State Dept ==")
    for c in (COUNTRIES if not country_names else [by_name(n) for n in country_names]):
        res = state_dept_scraper.scrape_country(c, force=force)
        if not res.get("ok"):
            failures.append(f"state_dept:{c.name}")

    print("\n== CDC ==")
    cdc_scraper.check_cdc_freshness()
    for c in (COUNTRIES if not country_names else [by_name(n) for n in country_names]):
        res = cdc_scraper.scrape_country(c, force=force)
        if not res.get("ok"):
            failures.append(f"cdc:{c.name}")

    print("\n== Tourism (CSV) ==")
    # Bug #2: tourism failures were previously dropped on the floor because the
    # return value of scrape_all() was discarded. Capture it and fold its
    # failures into the same list as State Dept and CDC so the summary count is
    # honest.
    for res in tourism_scraper.scrape_all(country_names, force=force):
        if not res.get("ok"):
            failures.append(f"tourism:{res.get('country', '?')}")

    # Reload everything we just wrote so chunking reads the canonical JSON.
    import json
    for folder in (settings.STATE_DEPT_DIR, settings.CDC_DIR, settings.TOURISM_DIR):
        for path in sorted(folder.glob("*.json")):
            rec = json.loads(path.read_text(encoding="utf-8"))
            if country_names and rec.get("country") not in country_names:
                continue
            records.append(rec)

    _scrape.failures = failures  # type: ignore[attr-defined]
    return records


def main() -> None:
    """CLI entry point: scrape -> chunk -> embed -> load for the selected countries.

    Country selection is ``--all`` (50), an explicit ``--countries`` list, or the default
    3-country test (France/Japan/Mexico). Prints a per-country chunk/failure/cost summary.
    """
    parser = argparse.ArgumentParser(description="Run the WanderRAG ingestion pipeline.")
    parser.add_argument("--countries", nargs="*", default=None, help="Country names (default: 3-country test).")
    parser.add_argument("--all", action="store_true", help="Run all 50 countries.")
    parser.add_argument("--force", action="store_true", help="Bypass HTML cache and refetch.")
    parser.add_argument("--no-embed", action="store_true", help="Scrape + chunk only; skip embedding/cost.")
    args = parser.parse_args()

    if args.all:
        names: list[str] = []  # empty => all 50
    elif args.countries:
        names = args.countries
    else:
        names = ["France", "Japan", "Mexico"]  # default test set

    label = "all 50" if not names else ", ".join(names)
    print(f"=== WanderRAG pipeline: {label} ===")

    records = _scrape(names, force=args.force)
    failures = getattr(_scrape, "failures", [])

    # Chunk
    per_country: dict[str, int] = defaultdict(int)
    all_chunks: list[dict[str, Any]] = []
    for rec in records:
        chunks = chunk_record(rec)
        per_country[rec.get("country", "?")] += len(chunks)
        all_chunks.extend(chunks)

    # Embed + load
    summary = {"chunks": len(all_chunks), "tokens": 0, "cost_usd": 0.0}
    if args.no_embed:
        print("\n[--no-embed] Skipping embedding/load.")
    else:
        print(f"\n== Embedding {len(all_chunks)} chunks ==")
        summary = embed_and_load(all_chunks)

    # Summary report
    print("\n" + "=" * 48)
    print("PIPELINE SUMMARY")
    print("=" * 48)
    for country, n in sorted(per_country.items()):
        print(f"  {country:<22} {n} chunks")
    print(f"  {'TOTAL CHUNKS':<22} {len(all_chunks)}")
    print(f"  Scrape failures        : {len(failures)} {failures if failures else ''}")
    if not args.no_embed:
        print(f"  Embedding tokens       : {summary['tokens']}")
        print(f"  Est. embedding cost    : ${summary['cost_usd']}")
    print("=" * 48)


if __name__ == "__main__":
    main()
