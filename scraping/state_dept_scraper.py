"""US State Department travel advisory scraper.

For a given country it builds the advisory URL, fetches it (cached), extracts
the advisory level + body text + last-updated date, and writes
``scraped_data/state_dept/<slug>.json``. Failures (404s, structure changes) are
logged to ``logs/scrape_log.json`` rather than crashing the run - expected for
countries with no advisory page (e.g. United States).

Run standalone:
    python -m scraping.state_dept_scraper France Japan Mexico
    python -m scraping.state_dept_scraper --all
"""

from __future__ import annotations

import re
import sys
from typing import Any, Optional

from bs4 import BeautifulSoup

from config import settings
from config.countries import COUNTRIES, Country, by_name
from processing.cleaner import clean_html, looks_empty
from scraping.common import fetch_html, log_scrape_event, save_json, today
from scraping.selenium_fallback import fetch_rendered_html

SOURCE_TYPE = "state_dept"

# Advisory banners read "Level 3: Reconsider Travel", etc.
_LEVEL_RE = re.compile(r"Level\s*([1-4])\s*[:\-]?\s*([A-Za-z ]+)?", re.I)
_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},\s+\d{4}",
)


def _extract_level(soup: BeautifulSoup, text: str) -> Optional[str]:
    # Prefer an explicit alert/level element; if that element is missing OR is
    # present but contains no "Level N" banner, fall back to a regex over the
    # *full* scraped text. (Bug #1: previously we only searched the matched
    # element or text[:2000], so a banner rendered elsewhere on the page was
    # missed and advisory_level came back null for every country.)
    el = soup.find(class_=re.compile("tsg-rwd-emergency|advisory|alert", re.I))
    candidates: list[str] = []
    if el:
        candidates.append(el.get_text(" ", strip=True))
    candidates.append(text or "")  # full-text fallback
    for candidate in candidates:
        m = _LEVEL_RE.search(candidate or "")
        if not m:
            continue
        level = f"Level {m.group(1)}"
        if m.group(2):
            level += f" - {m.group(2).strip()}"
        return level
    return None


def _extract_last_updated(text: str) -> Optional[str]:
    m = _DATE_RE.search(text)
    return m.group(0) if m else None


def scrape_country(country: Country, *, force: bool = False) -> dict[str, Any]:
    """Scrape one country's advisory. Returns a result dict and writes JSON on success."""
    url = country.state_dept_url
    html, meta = fetch_html(url, force=force)

    if html is None:
        log_scrape_event(
            {"source": SOURCE_TYPE, "country": country.name, "ok": False, **meta}
        )
        return {"country": country.name, "ok": False, "error": meta.get("error")}

    raw_text = clean_html(html)

    # If the static fetch produced almost nothing, retry via Selenium.
    if looks_empty(raw_text, settings.MIN_CONTENT_CHARS):
        rendered = fetch_rendered_html(url)
        if rendered:
            raw_text = clean_html(rendered)

    soup = BeautifulSoup(html, "lxml")
    advisory_level = _extract_level(soup, raw_text)
    last_updated = _extract_last_updated(raw_text)

    record = {
        "country": country.name,
        "region": country.region,
        "source_type": SOURCE_TYPE,
        "source_url": url,
        "scrape_date": today(),
        "advisory_level": advisory_level,
        "last_updated": last_updated,
        "raw_text": raw_text,
    }
    save_json(settings.STATE_DEPT_DIR / f"{country.slug}.json", record)

    ok = not looks_empty(raw_text, settings.MIN_CONTENT_CHARS)
    log_scrape_event(
        {
            "source": SOURCE_TYPE,
            "country": country.name,
            "ok": ok,
            "advisory_level": advisory_level,
            "chars": len(raw_text),
            "from_cache": meta.get("from_cache"),
            "url": url,
        }
    )
    return {
        "country": country.name,
        "ok": ok,
        "advisory_level": advisory_level,
        "chars": len(raw_text),
    }


def scrape_many(names: list[str], *, force: bool = False) -> list[dict[str, Any]]:
    countries = COUNTRIES if not names else [by_name(n) for n in names]
    results = []
    for c in countries:
        res = scrape_country(c, force=force)
        flag = "ok" if res.get("ok") else "FAIL"
        print(f"  [{flag}] {c.name}: level={res.get('advisory_level')} chars={res.get('chars', 0)}")
        results.append(res)
    return results


def main() -> None:
    args = [a for a in sys.argv[1:] if a not in ("--all", "--force")]
    force = "--force" in sys.argv[1:]
    names = [] if ("--all" in sys.argv[1:] or not args) else args
    print(f"Scraping State Dept advisories ({'all 50' if not names else ', '.join(names)})...")
    scrape_many(names, force=force)


if __name__ == "__main__":
    main()
