"""Is thin-tier thinness SOURCE thinness or CLEANER loss?

READ-ONLY. Replays the cleaning pipeline stage by stage over cached HTML.
No scraping, no embedding, no Qdrant writes.

Stages:
  1. raw HTML chars
  2. tag-drop + get_text()          -> all visible text the page actually offers
  3. clean_text()                   -> what became the corpus
Loss from 2 -> 3 is what OUR cleaner removed.
"""
import hashlib, json, re
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from processing.cleaner import (_BOILERPLATE_MARKERS, _DROP_TAGS, _WHITESPACE_RE,
                                _is_boilerplate, clean_text)

TARGETS = ["Canada", "United Arab Emirates", "Thailand", "Brazil", "Argentina"]
# A few rich countries as a control, to show what a healthy source looks like.
CONTROL = ["Japan", "Cambodia", "Greece"]

corpus = json.load(open("scratchpad/corpus_dump.json"))
tour_counts = Counter(p["payload"]["country"] for p in corpus
                      if p["payload"]["source_type"] == "tourism")
total_counts = Counter(p["payload"]["country"] for p in corpus)

ATTRACTION = re.compile(
    r"museum|temple|palace|park|beach|falls|tower|cathedral|mosque|castle|island|"
    r"canyon|reef|ruins|market|bazaar|gallery|monument|basilica|garden|lagoon|"
    r"national|old town|square|bridge|zoo|aquarium", re.I)


def stages(country: str):
    p = Path("scraped_data/tourism") / (country.lower().replace(" ", "-") + ".json")
    if not p.exists():
        return None
    rec = json.loads(p.read_text(encoding="utf-8"))
    url = rec["source_url"]
    cache = Path("raw_html") / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".html")
    if not cache.exists():
        return {"country": country, "url": url, "error": "no cached HTML"}
    html = cache.read_text(encoding="utf-8", errors="replace")

    soup = BeautifulSoup(html, "lxml")
    for t in soup(_DROP_TAGS):
        t.decompose()
    for el in soup.find_all(attrs={"class": re.compile("cookie|consent|banner", re.I)}):
        el.decompose()
    visible = soup.get_text(separator="\n")

    lines = [_WHITESPACE_RE.sub(" ", ln.strip()) for ln in visible.splitlines()]
    counts = Counter(ln for ln in lines if ln)
    repeated = {ln for ln, n in counts.items() if n >= 3 and len(ln) < 40}

    dropped_boiler, dropped_repeat = [], []
    for ln in lines:
        if not ln:
            continue
        if _is_boilerplate(ln):
            dropped_boiler.append(ln)
        elif ln in repeated:
            dropped_repeat.append(ln)

    final = clean_text(visible)
    lost = len(visible) - len(final)
    attractions_killed = sorted({ln for ln in dropped_repeat if ATTRACTION.search(ln)})
    named_killed = sorted({ln for ln in set(dropped_repeat)
                           if re.fullmatch(r"[A-Z][\w'’\-]*(?: [A-Z][\w'’\-]*){0,3}", ln)})
    return {
        "country": country, "url": url,
        "raw_html": len(html), "visible": len(visible), "final": len(final),
        "lost": lost, "pct_lost": round(100 * lost / len(visible), 1) if visible else 0,
        "n_dropped_repeat_types": len(set(dropped_repeat)),
        "n_dropped_boiler": len(dropped_boiler),
        "attractions_killed": attractions_killed,
        "named_killed": named_killed,
        "tourism_chunks": tour_counts.get(country, 0),
        "total_chunks": total_counts.get(country, 0),
    }


def show(rows, title):
    print("\n" + "=" * 104)
    print(title)
    print("=" * 104)
    print(f"{'country':<22}{'tour_chunks':>12}{'raw_html':>10}{'visible':>9}{'final':>8}"
          f"{'lost':>8}{'%lost':>7}{'names_killed':>14}")
    print("-" * 104)
    for r in rows:
        if not r or r.get("error"):
            print(f"{(r or {}).get('country','?'):<22} {(r or {}).get('error','missing')}")
            continue
        print(f"{r['country']:<22}{r['tourism_chunks']:>12}{r['raw_html']:>10}{r['visible']:>9}"
              f"{r['final']:>8}{r['lost']:>8}{r['pct_lost']:>6}%{len(r['named_killed']):>14}")


thin = [stages(c) for c in TARGETS]
ctrl = [stages(c) for c in CONTROL]
show(thin, "THIN-TIER COUNTRIES (the ones in the report)")
show(ctrl, "CONTROL: rich-tier countries")

print("\n" + "=" * 104)
print("WHAT THE CLEANER DELETED, per thin country")
print("=" * 104)
for r in thin:
    if not r or r.get("error"):
        continue
    print(f"\n--- {r['country']}  ({r['url']}) ---")
    print(f"    visible text on page: {r['visible']:,} chars -> corpus: {r['final']:,} chars "
          f"({r['pct_lost']}% removed by our cleaner)")
    print(f"    named lines deleted ({len(r['named_killed'])}): {r['named_killed'][:14]}")
    print(f"    attraction-like deleted ({len(r['attractions_killed'])}): {r['attractions_killed'][:10]}")

json.dump([r for r in thin + ctrl if r], open("scratchpad/thin_tier_audit.json", "w"), indent=2)
