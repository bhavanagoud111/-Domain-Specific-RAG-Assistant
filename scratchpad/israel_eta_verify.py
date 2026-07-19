"""Verify the Israel ETA-IL omission: live page vs cached HTML vs cleaned JSON.

READ-ONLY. Does not touch Qdrant, does not re-scrape into scraped_data/, does not
overwrite the raw_html cache. The frozen corpus is untouched.
"""
import hashlib, json, re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import settings
from processing.cleaner import clean_html, clean_text

URL = "https://en.wikivoyage.org/wiki/Israel"
cache = Path("raw_html") / (hashlib.sha256(URL.encode()).hexdigest()[:16] + ".html")

def eta_segment(text: str, width: int = 3000) -> str:
    i = text.find("eligible for an ETA")
    if i < 0:
        i = text.find("ETA")
    return text[i : i + width] if i >= 0 else ""

def verdict(label: str, text: str) -> None:
    seg = eta_segment(text)
    has_us = bool(re.search(r"United States|USA\b", seg))
    # what sits between United Kingdom and Uruguay?
    m = re.search(r"United Kingdom(.{0,80}?)Uruguay", seg, re.S)
    between = m.group(1).strip() if m else "<UK..Uruguay pattern not found>"
    print(f"\n--- {label} ---")
    print(f"  chars={len(text)}  ETA segment found={bool(seg)}")
    print(f"  'United States' in ETA segment: {has_us}")
    print(f"  text between 'United Kingdom' and 'Uruguay': {between!r}")
    return seg

# 1. cached HTML (what the scraper actually fetched on 2026-06-28)
if cache.exists():
    raw = cache.read_text(encoding="utf-8", errors="replace")
    print(f"cached HTML: {cache} ({len(raw)} chars)")
    # a) raw HTML source, before any cleaning
    seg_html = eta_segment(re.sub(r"<[^>]+>", " ", raw))
    verdict("CACHED HTML (tags stripped, no cleaner)", re.sub(r"<[^>]+>", " ", raw))
    # b) through the project's own cleaner -- this is what became the corpus
    verdict("CACHED HTML -> clean_html() (the corpus path)", clean_text(clean_html(raw)))
else:
    print(f"no cache at {cache}")

# 2. the stored scraped JSON (the corpus input)
rec = json.loads(Path("scraped_data/tourism/israel.json").read_text(encoding="utf-8"))
verdict("scraped_data/tourism/israel.json (frozen corpus input)", rec["raw_text"])

# 3. LIVE page fetched now (read-only; NOT written to cache)
try:
    r = requests.get(URL, headers={"User-Agent": settings.USER_AGENT}, timeout=45)
    print(f"\nlive fetch: HTTP {r.status_code}, {len(r.text)} chars")
    verdict("LIVE page (tags stripped, no cleaner)", re.sub(r"<[^>]+>", " ", r.text))
    verdict("LIVE page -> clean_html()", clean_text(clean_html(r.text)))

    # How is the eligibility list actually marked up on the live page?
    soup = BeautifulSoup(r.text, "lxml")
    node = soup.find(string=re.compile("eligible for an ETA"))
    if node:
        parent = node.find_parent(["p", "div", "ul", "table"])
        print("\n  --- live markup around the eligibility list ---")
        print("  parent tag:", parent.name if parent else None)
        html_snip = str(parent)[:1500] if parent else ""
        print("  ", html_snip[:1200].replace("\n", " "))
        # Look for US specifically anywhere in that container
        print("\n  'United States' anywhere in that container:",
              bool(re.search(r"United States", str(parent) if parent else "")))
except Exception as e:
    print(f"\nlive fetch FAILED: {type(e).__name__}: {e}")
