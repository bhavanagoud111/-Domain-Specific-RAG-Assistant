"""Probe candidate Japan tourism sources WITHOUT touching the corpus."""
import re, requests
from processing.cleaner import clean_html, clean_text
from config import settings

CANDIDATES = [
    ("JNTO official board", "https://www.japan.travel/en/"),
    ("JNTO destinations",   "https://www.japan.travel/en/destinations/"),
    ("Wikivoyage Japan",    "https://en.wikivoyage.org/wiki/Japan"),
]
VISIT = re.compile(r"temple|shrine|museum|festival|itinerary|sightsee|attraction|must-see|things to do|garden|castle|onsen|Mount Fuji|Kyoto|Osaka|Hokkaido|cherry blossom", re.I)
STATE = re.compile(r"travel\.state\.gov|Bureau of Consular Affairs|Enroll in STEP")

for name, url in CANDIDATES:
    try:
        r = requests.get(url, headers={"User-Agent": settings.USER_AGENT}, timeout=30)
        txt = clean_text(clean_html(r.text))
        hits = VISIT.findall(txt)
        print(f"\n{'='*70}\n{name}\n  {url}\n  HTTP {r.status_code} | chars={len(txt)} "
              f"| visit-vocab hits={len(hits)} distinct={len(set(h.lower() for h in hits))} "
              f"| state-dept contamination={len(STATE.findall(txt))}")
        print("  sample:", txt[:300].replace("\n", " "))
    except Exception as e:
        print(f"\n{name}: FAILED {type(e).__name__}: {e}")
