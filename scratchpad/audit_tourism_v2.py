"""Phase 1b (v2) — tightened detector. v1 false-positived on the ordinary word "step"."""
import json, re
from collections import defaultdict

pts = json.load(open("scratchpad/corpus_dump.json"))

# Case-SENSITIVE / phrase-anchored. No bare \bSTEP\b, no generic "before you travel".
STATE_PAT = [
    r"travel\.state\.gov", r"Travel Advisory \| Travel\.state\.gov",
    r"Enroll in STEP", r"Smart Traveler Enrollment Program", r"Review how STEP works",
    r"Reconsider [Tt]ravel to", r"Level [1-4]: .{0,40}(Exercise|Reconsider|Do Not)",
    r"Bureau of Consular Affairs", r"Department of State advises",
    r"U\.S\. Emb(assy|assies)", r"U\.S\. [Cc]onsulate", r"Worldwide Caution",
]
CDC_PAT = [
    r"wwwnc\.cdc\.gov", r"Centers for Disease Control", r"CDC recommends",
    r"Travelers' Health", r"routine vaccines", r"vaccine-preventable",
    r"Clinician view", r"Make sure you are up-to-date",
]
S_RE = re.compile("|".join(STATE_PAT))          # case-sensitive
C_RE = re.compile("|".join(CDC_PAT))

by_country = defaultdict(lambda: defaultdict(list))
for p in pts:
    pl = p["payload"]
    by_country[pl["country"]][pl["source_type"]].append((p["id"], pl))

rows = []
for country in sorted(by_country):
    tour = by_country[country].get("tourism", [])
    mis = []
    for pid, pl in tour:
        url = (pl.get("source_url") or "").lower()
        txt = pl.get("text", "") or ""
        url_bad = ("state.gov" in url) or ("cdc.gov" in url)
        txt_bad = len(S_RE.findall(txt)) >= 2 or len(C_RE.findall(txt)) >= 2
        if url_bad or txt_bad:
            mis.append((pid, url_bad, txt_bad))
    rows.append({
        "country": country, "tourism": len(tour),
        "state_dept": len(by_country[country].get("state_dept", [])),
        "cdc": len(by_country[country].get("cdc", [])),
        "mislabeled": len(mis),
        "by_url": sum(1 for _, u, _ in mis if u),
        "by_text_only": sum(1 for _, u, t in mis if t and not u),
        "urls": sorted({(pl.get("source_url") or "") for _, pl in tour}),
        "ids": [m[0] for m in mis],
    })
json.dump(rows, open("scratchpad/audit_rows_v2.json", "w"), indent=2)

print(f"{'country':<22}{'tourism':>8}{'state_dept':>11}{'cdc':>5}{'MISLABELED':>12}")
print("-" * 58)
for r in rows:
    flag = "  <<< MISLABELED" if r["mislabeled"] else ""
    print(f"{r['country']:<22}{r['tourism']:>8}{r['state_dept']:>11}{r['cdc']:>5}{r['mislabeled']:>12}{flag}")
print("-" * 58)
print(f"{'TOTAL':<22}{sum(r['tourism'] for r in rows):>8}"
      f"{sum(r['state_dept'] for r in rows):>11}{sum(r['cdc'] for r in rows):>5}"
      f"{sum(r['mislabeled'] for r in rows):>12}")
aff = [r for r in rows if r["mislabeled"]]
print(f"\nAFFECTED COUNTRIES: {len(aff)} -> {[(r['country'], r['mislabeled'], r['tourism']) for r in aff]}")
for r in aff:
    print(f"  {r['country']}: tourism URLs = {r['urls']}")
