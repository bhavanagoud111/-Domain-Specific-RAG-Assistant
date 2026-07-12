"""CDC Travelers' Health destination scraper.

Before scraping, run a freshness check (``check_cdc_freshness``) that hits the
CDC destination list and reports whether the site looks live or archived. As of
the last manual check the site was LIVE (see DATA_SOURCES.md). If it ever
appears frozen, set ``CDC_USE_MIRROR=1`` to fall back to the restoredcdc.org
mirror.

Run standalone:
    python -m scraping.cdc_scraper --check          # freshness check only
    python -m scraping.cdc_scraper France Japan Mexico
    python -m scraping.cdc_scraper --all
"""

from __future__ import annotations

import os
import sys
from typing import Any

from bs4 import BeautifulSoup

from config import settings
from config.countries import COUNTRIES, Country, by_name
from processing.cleaner import clean_html, looks_empty
from scraping.common import fetch_html, log_scrape_event, save_json, today
from scraping.selenium_fallback import fetch_rendered_html

SOURCE_TYPE = "cdc"

CDC_LIST_URL = "https://wwwnc.cdc.gov/travel/destinations/list"
MIRROR_BASE = "https://data.restoredcdc.org"


def _destination_url(country: Country) -> str:
    slug = country.cdc_slug or country.slug
    if os.getenv("CDC_USE_MIRROR") == "1":
        return f"{MIRROR_BASE}/travel/destinations/traveler/none/{slug}"
    return country.cdc_url


def check_cdc_freshness() -> dict[str, Any]:
    """Fetch the CDC destination list and report whether the site looks live.

    Prints a clear warning if the page is empty/unreachable (a sign the site has
    been archived/frozen) so the user can switch to the mirror.
    """
    html, meta = fetch_html(CDC_LIST_URL, force=True)
    result: dict[str, Any] = {"checked_url": CDC_LIST_URL, "date": today(), **meta}

    if html is None:
        print("[cdc] WARNING: CDC list page unreachable - site may be archived/frozen.")
        print("[cdc] Consider setting CDC_USE_MIRROR=1 to use restoredcdc.org.")
        result["live"] = False
    else:
        text = clean_html(html)
        live = not looks_empty(text, settings.MIN_CONTENT_CHARS)
        result["live"] = live
        result["chars"] = len(text)
        if live:
            print(f"[cdc] OK: destination list returned live content ({len(text)} chars).")
        else:
            print("[cdc] WARNING: destination list looks empty - site may be frozen.")
    log_scrape_event({"source": SOURCE_TYPE, "event": "freshness_check", **result})
    return result


def scrape_country(country: Country, *, force: bool = False) -> dict[str, Any]:
    url = _destination_url(country)
    html, meta = fetch_html(url, force=force)

    if html is None:
        log_scrape_event({"source": SOURCE_TYPE, "country": country.name, "ok": False, **meta})
        return {"country": country.name, "ok": False, "error": meta.get("error")}

    raw_text = clean_html(html)
    if looks_empty(raw_text, settings.MIN_CONTENT_CHARS):
        rendered = fetch_rendered_html(url)
        if rendered:
            raw_text = clean_html(rendered)

    record = {
        "country": country.name,
        "region": country.region,
        "source_type": SOURCE_TYPE,
        "source_url": url,
        "scrape_date": today(),
        "raw_text": raw_text,
    }
    save_json(settings.CDC_DIR / f"{country.slug}.json", record)

    ok = not looks_empty(raw_text, settings.MIN_CONTENT_CHARS)
    log_scrape_event(
        {
            "source": SOURCE_TYPE,
            "country": country.name,
            "ok": ok,
            "chars": len(raw_text),
            "from_cache": meta.get("from_cache"),
            "url": url,
        }
    )
    return {"country": country.name, "ok": ok, "chars": len(raw_text)}


def scrape_many(names: list[str], *, force: bool = False) -> list[dict[str, Any]]:
    countries = COUNTRIES if not names else [by_name(n) for n in names]
    results = []
    for c in countries:
        res = scrape_country(c, force=force)
        flag = "ok" if res.get("ok") else "FAIL"
        print(f"  [{flag}] {c.name}: chars={res.get('chars', 0)}")
        results.append(res)
    return results


def main() -> None:
    argv = sys.argv[1:]
    if "--check" in argv:
        check_cdc_freshness()
        return
    args = [a for a in argv if a not in ("--all", "--force")]
    force = "--force" in argv
    names = [] if ("--all" in argv or not args) else args

    # Always run the freshness check first so the warning is visible in logs.
    check_cdc_freshness()
    print(f"Scraping CDC pages ({'all 50' if not names else ', '.join(names)})...")
    scrape_many(names, force=force)


if __name__ == "__main__":
    main()
