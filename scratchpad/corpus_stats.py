"""Phase 2 — frozen corpus stats: total + per-country/per-source chunk counts."""
import json
from collections import defaultdict
pts = json.load(open("scratchpad/corpus_dump.json"))
by = defaultdict(lambda: defaultdict(int))
for p in pts:
    pl = p["payload"]; by[pl["country"]][pl["source_type"]] += 1
rows = []
for c in sorted(by):
    d = by[c]; t = sum(d.values())
    rows.append({"country": c, "state_dept": d.get("state_dept",0), "cdc": d.get("cdc",0),
                 "tourism": d.get("tourism",0), "total": t})
tot = sum(r["total"] for r in rows)
print(f"TOTAL points_count = {tot}   countries = {len(rows)}\n")
print(f"{'country':<22}{'state_dept':>11}{'cdc':>6}{'tourism':>9}{'TOTAL':>7}   tier")
print("-"*62)
for r in rows:
    tier = "RICH" if r["total"] >= 60 else ("thin" if r["total"] < 30 else "mid")
    print(f"{r['country']:<22}{r['state_dept']:>11}{r['cdc']:>6}{r['tourism']:>9}{r['total']:>7}   {tier}")
print("-"*62)
print(f"{'TOTAL':<22}{sum(r['state_dept'] for r in rows):>11}{sum(r['cdc'] for r in rows):>6}"
      f"{sum(r['tourism'] for r in rows):>9}{tot:>7}")
json.dump(rows, open("scratchpad/corpus_stats.json","w"), indent=2)
rich=[r['country'] for r in rows if r['total']>=60]; thin=[r['country'] for r in rows if r['total']<30]
print(f"\nRICH (>=60): {len(rich)} {rich}")
print(f"\nTHIN (<30):  {len(thin)} {thin}")
