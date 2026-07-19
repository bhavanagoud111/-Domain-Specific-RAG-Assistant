"""Final thin-tier accounting, using the ACTUAL corpus input (scraped_data json)."""
import hashlib, json, re
from collections import Counter
from pathlib import Path
from bs4 import BeautifulSoup
from processing.cleaner import _DROP_TAGS, _WHITESPACE_RE, clean_text

corpus = json.load(open("scratchpad/corpus_dump.json"))
tour = Counter(p["payload"]["country"] for p in corpus if p["payload"]["source_type"]=="tourism")
tot  = Counter(p["payload"]["country"] for p in corpus)

ROWS = [("Canada","canada"),("United Arab Emirates","united-arab-emirates"),
        ("Thailand","thailand"),("Brazil","brazil"),("Argentina","argentina")]
CTRL = [("Japan","japan"),("Cambodia","cambodia"),("Greece","greece")]

def row(name, slug):
    d = json.loads((Path("scraped_data/tourism")/f"{slug}.json").read_text(encoding="utf-8"))
    url, final = d["source_url"], len(d["raw_text"])
    cache = Path("raw_html")/(hashlib.sha256(url.encode()).hexdigest()[:16]+".html")
    raw = visible = cleaner_lost = None
    if cache.exists():
        html = cache.read_text(encoding="utf-8", errors="replace")
        raw = len(html)
        s = BeautifulSoup(html,"lxml")
        for t in s(_DROP_TAGS): t.decompose()
        for el in s.find_all(attrs={"class":re.compile("cookie|consent|banner",re.I)}): el.decompose()
        vis = s.get_text(separator="\n")
        visible = len(vis)
        cleaner_lost = visible - len(clean_text(vis))
    return dict(country=name, url=url, raw_html=raw, visible=visible,
                corpus_text=final, cleaner_lost=cleaner_lost,
                tourism_chunks=tour.get(name,0), total_chunks=tot.get(name,0),
                wikivoyage="wikivoyage" in url)

print(f"{'country':<22}{'src':>6}{'raw_html':>10}{'static_txt':>12}{'CORPUS_TXT':>12}"
      f"{'cleaner_lost':>14}{'tour_chunks':>12}")
print("-"*100)
for name,slug in ROWS+CTRL:
    r = row(name,slug)
    tag = "wv" if r["wikivoyage"] else "board"
    rh = f"{r['raw_html']:,}" if r['raw_html'] else "n/a"
    vs = f"{r['visible']:,}" if r['visible'] is not None else "n/a"
    cl = f"{r['cleaner_lost']:,}" if r['cleaner_lost'] is not None else "n/a"
    if name=="Japan": print("-"*100)
    print(f"{r['country']:<22}{tag:>6}{rh:>10}{vs:>12}{r['corpus_text']:>12,}{cl:>14}"
          f"{r['tourism_chunks']:>12}")
