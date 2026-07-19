"""Phase 1b — audit ALL tourism-tagged chunks for State Dept / CDC contamination.

Detection is by CONTENT and by SOURCE URL, never by trusting source_type.
"""
import json, re
from collections import defaultdict

pts = json.load(open("scratchpad/corpus_dump.json"))

STATE_PAT = [
    r"travel\.state\.gov", r"Travel Advisory \|", r"Smart Traveler Enrollment Program",
    r"\bSTEP\b", r"Reconsider [Tt]ravel", r"Exercise [Ii]ncreased [Cc]aution",
    r"Do Not Travel", r"Level [1-4]:", r"Bureau of Consular Affairs",
    r"U\.S\. Embassy", r"Country Summary",
]
CDC_PAT = [
    r"wwwnc\.cdc\.gov", r"Centers for Disease Control", r"Travelers.{0,3} Health",
    r"CDC recommends", r"routine vaccines", r"Talk to your doctor about",
    r"before you travel", r"Clinician view", r"vaccine-preventable",
]
S_RE = re.compile("|".join(STATE_PAT), re.I)
C_RE = re.compile("|".join(CDC_PAT), re.I)

by_country = defaultdict(lambda: defaultdict(list))
for p in pts:
    pl = p["payload"]
    by_country[pl["country"]][pl["source_type"]].append((p["id"], pl))

rows = []
for country in sorted(by_country):
    tour = by_country[country].get("tourism", [])
    bad_url, bad_text, hits = [], [], []
    for pid, pl in tour:
        url = (pl.get("source_url") or "").lower()
        txt = pl.get("text", "") or ""
        url_bad = ("state.gov" in url) or ("cdc.gov" in url)
        s_hits = S_RE.findall(txt)
        c_hits = C_RE.findall(txt)
        txt_bad = len(s_hits) >= 2 or len(c_hits) >= 2
        if url_bad:
            bad_url.append(pid)
        if txt_bad:
            bad_text.append(pid)
        if url_bad or txt_bad:
            hits.append((pid, pl, url_bad, s_hits[:3], c_hits[:3]))
    rows.append({
        "country": country,
        "tourism": len(tour),
        "state_dept": len(by_country[country].get("state_dept", [])),
        "cdc": len(by_country[country].get("cdc", [])),
        "bad_url": len(bad_url),
        "bad_text": len(bad_text),
        "mislabeled": len(set(bad_url) | set(bad_text)),
        "tourism_urls": sorted({(pl.get("source_url") or "") for _, pl in tour}),
        "hits": hits,
    })

json.dump([{k: v for k, v in r.items() if k != "hits"} for r in rows],
          open("scratchpad/audit_rows.json", "w"), indent=2)

print(f"{'country':<22}{'tour':>5}{'sd':>5}{'cdc':>5}{'badURL':>8}{'badTXT':>8}{'MISLAB':>8}")
print("-" * 61)
tot_t = tot_m = 0
for r in rows:
    flag = "  <<<" if r["mislabeled"] else ""
    print(f"{r['country']:<22}{r['tourism']:>5}{r['state_dept']:>5}{r['cdc']:>5}"
          f"{r['bad_url']:>8}{r['bad_text']:>8}{r['mislabeled']:>8}{flag}")
    tot_t += r["tourism"]; tot_m += r["mislabeled"]
print("-" * 61)
print(f"{'TOTAL':<22}{tot_t:>5}{'':>5}{'':>5}{'':>8}{'':>8}{tot_m:>8}")
print(f"\ncountries with >=1 mislabeled: {sum(1 for r in rows if r['mislabeled'])}")
print(f"countries with 0 tourism chunks at all: {[r['country'] for r in rows if r['tourism']==0]}")
