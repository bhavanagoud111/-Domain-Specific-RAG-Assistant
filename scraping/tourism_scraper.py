"""Generic tourism/embassy/visa source loader, driven by ``tourism_sources.csv``.

The CSV is filled in manually (these URLs vary too much to auto-discover) with
columns: ``country, url, format`` where format is ``html`` or ``pdf``. For each
row we fetch + extract text and write ``scraped_data/tourism/<slug>.json``.

Run standalone:
    python -m scraping.tourism_scraper            # process every row in the CSV
    python -m scraping.tourism_scraper France     # only matching countries
"""

from __future__ import annotations

import csv
import io
import sys
from typing import Any

import requests

from config import settings
from config.countries import by_name
from processing.cleaner import clean_html, clean_text, looks_empty
from scraping.common import fetch_html, log_scrape_event, save_json, today
from scraping.selenium_fallback import fetch_rendered_html

SOURCE_TYPE = "tourism"


def _read_csv() -> list[dict[str, str]]:
    path = settings.TOURISM_SOURCES_CSV
    if not path.exists():
        print(f"[tourism] No CSV at {path} - nothing to do. (Fill it in manually.)")
        return []

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    # Drop comment lines (starting with '#') and blank lines BEFORE csv parsing.
    # Previously comments were filtered post-parse via url.startswith('#'), which
    # silently failed for a comment line containing a comma: csv split it into a
    # fake country + a non-'#' url that leaked through (e.g. "# Examples (replace
    # with real, verified URLs):" -> country="# Examples (replace with real").
    data_lines = [ln for ln in raw_lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not data_lines:
        return []

    rows = [
        {k.strip(): (v or "").strip() for k, v in row.items()}
        for row in csv.DictReader(io.StringIO("\n".join(data_lines)))
    ]
    # Assertion: parsed rows must equal non-comment/non-blank lines minus the
    # header. Guards against the comma-in-comment regression above.
    expected = len(data_lines) - 1  # minus header row
    assert len(rows) == expected, (
        f"tourism CSV parse mismatch: parsed {len(rows)} rows but expected "
        f"{expected} non-comment data lines. Check for malformed/comment rows."
    )
    # Skip rows with no real URL yet (blank or a leftover #TODO placeholder).
    return [r for r in rows if r.get("url") and not r["url"].lstrip().startswith("#")]


def _extract_pdf(url: str) -> str:
    """Download a PDF and extract its text with pdfplumber."""
    import pdfplumber  # lazy import; only needed for PDF rows

    resp = requests.get(
        url,
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return clean_text("\n".join(pages))


def scrape_row(row: dict[str, str], *, force: bool = False) -> dict[str, Any]:
    country_name = row["country"]
    url = row["url"]
    fmt = (row.get("format") or "html").lower()

    try:
        country = by_name(country_name)
        slug = country.slug
        region = country.region
    except KeyError:
        # Allow CSV countries outside the canonical 50, but flag it.
        slug = country_name.strip().lower().replace(" ", "-")
        region = "unknown"

    try:
        if fmt == "pdf":
            raw_text = _extract_pdf(url)
            from_cache = False
        else:
            html, meta = fetch_html(url, force=force)
            if html is None:
                raise RuntimeError(meta.get("error", "fetch failed"))
            raw_text = clean_html(html)
            from_cache = meta.get("from_cache", False)
            if looks_empty(raw_text, settings.MIN_CONTENT_CHARS):
                rendered = fetch_rendered_html(url)
                if rendered:
                    raw_text = clean_html(rendered)
    except Exception as exc:
        log_scrape_event(
            {"source": SOURCE_TYPE, "country": country_name, "ok": False, "url": url, "error": str(exc)}
        )
        return {"country": country_name, "ok": False, "error": str(exc)}

    record = {
        "country": country_name,
        "region": region,
        "source_type": SOURCE_TYPE,
        "source_url": url,
        "format": fmt,
        "scrape_date": today(),
        "raw_text": raw_text,
    }
    save_json(settings.TOURISM_DIR / f"{slug}.json", record)

    ok = not looks_empty(raw_text, settings.MIN_CONTENT_CHARS)
    log_scrape_event(
        {"source": SOURCE_TYPE, "country": country_name, "ok": ok, "chars": len(raw_text),
         "format": fmt, "from_cache": from_cache, "url": url}
    )
    return {"country": country_name, "ok": ok, "chars": len(raw_text)}


def scrape_all(filter_names: list[str], *, force: bool = False) -> list[dict[str, Any]]:
    rows = _read_csv()
    if filter_names:
        wanted = {n.lower() for n in filter_names}
        rows = [r for r in rows if r["country"].lower() in wanted]
    results = []
    for row in rows:
        res = scrape_row(row, force=force)
        flag = "ok" if res.get("ok") else "FAIL"
        print(f"  [{flag}] {res['country']} ({row.get('format', 'html')}): chars={res.get('chars', 0)}")
        results.append(res)
    if not rows:
        print("[tourism] No rows to process.")
    return results


def main() -> None:
    argv = sys.argv[1:]
    force = "--force" in argv
    names = [a for a in argv if a != "--force"]
    print("Loading tourism sources from CSV...")
    scrape_all(names, force=force)


if __name__ == "__main__":
    main()
