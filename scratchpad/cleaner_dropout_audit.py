"""Quantify the clean_text() 'repeated short line' dropout across the tourism corpus.

READ-ONLY: replays the cleaner over cached HTML. No scraping, no embedding, no Qdrant.
"""
import hashlib, json, re
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup
from processing.cleaner import _DROP_TAGS, _is_boilerplate, _WHITESPACE_RE

def dropped_lines(html: str):
    """Re-run the cleaner's logic but RECORD what the repeated-line rule deletes."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for el in soup.find_all(attrs={"class": re.compile("cookie|consent|banner", re.I)}):
        el.decompose()
    text = soup.get_text(separator="\n")
    lines = [_WHITESPACE_RE.sub(" ", ln.strip()) for ln in text.splitlines()]
    counts = Counter(ln for ln in lines if ln)
    repeated = {ln: n for ln, n in counts.items() if n >= 3 and len(ln) < 40}
    # split into plausible-nav vs plausible-content
    return repeated, counts

rows = []
tour = sorted(Path("scraped_data/tourism").glob("*.json"))
for p in tour:
    rec = json.loads(p.read_text(encoding="utf-8"))
    url = rec["source_url"]
    cache = Path("raw_html") / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".html")
    if not cache.exists():
        continue
    html = cache.read_text(encoding="utf-8", errors="replace")
    repeated, counts = dropped_lines(html)
    # A dropped line looks like real CONTENT (not nav) if it is a capitalised
    # word/phrase with no nav-ish punctuation -- e.g. a country or city name.
    contentish = {ln: n for ln, n in repeated.items()
                  if re.fullmatch(r"[A-Z][\w'’\-]*(?: [A-Z][\w'’\-]*){0,3}", ln)}
    rows.append({
        "country": rec["country"], "url": url,
        "n_dropped_types": len(repeated),
        "n_dropped_contentish": len(contentish),
        "dropped_occurrences": sum(repeated.values()),
        "examples": sorted(contentish.items(), key=lambda kv: -kv[1])[:8],
        "is_wikivoyage": "wikivoyage" in url,
    })

rows.sort(key=lambda r: -r["n_dropped_contentish"])
print(f"{'country':<22}{'wikivoy':>8}{'dropped':>9}{'content-like':>14}{'occurrences':>13}")
print("-" * 68)
for r in rows:
    print(f"{r['country']:<22}{str(r['is_wikivoyage']):>8}{r['n_dropped_types']:>9}"
          f"{r['n_dropped_contentish']:>14}{r['dropped_occurrences']:>13}")
print("-" * 68)
wv = [r for r in rows if r["is_wikivoyage"]]
print(f"\nsources audited: {len(rows)}  (wikivoyage: {len(wv)})")
print(f"sources dropping >=1 content-like token: {sum(1 for r in rows if r['n_dropped_contentish'])}")
print(f"total content-like token TYPES dropped:  {sum(r['n_dropped_contentish'] for r in rows)}")
print("\n=== worst offenders: what is actually being deleted ===")
for r in rows[:6]:
    print(f"\n{r['country']} ({'wikivoyage' if r['is_wikivoyage'] else 'board'}):")
    print("   ", [f"{k} x{v}" for k, v in r["examples"]])
json.dump(rows, open("scratchpad/cleaner_dropout.json", "w"), indent=2)
