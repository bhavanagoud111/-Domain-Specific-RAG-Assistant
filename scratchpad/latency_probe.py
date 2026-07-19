"""B6 -- latency of 10 representative queries through the real graph. READ-ONLY."""
import json, statistics, time
from graph.wanderrag_graph import run_query

QUERIES = [
    ("What should I visit in Japan?",                        "rich/what_to_visit"),
    ("What should I visit in Italy?",                        "mid/what_to_visit"),
    ("What should I visit in Canada?",                       "thin/refusal-expected"),
    ("Do I need a visa to visit Japan as a US citizen?",      "rich/visa"),
    ("Do I need a visa to visit Mexico as a US citizen?",     "rich/visa"),
    ("What vaccinations does Brazil require?",                "thin/health"),
    ("What's the safety situation in Mexico right now?",      "rich/safety"),
    ("How safe is it to travel in Norway right now?",         "thin/safety"),
    ("What is the current price of a 7-day rail pass in Japan?", "unanswerable"),
    ("asdkjasd current safety xyz nonsense country",          "nonsense"),
]

rows = []
for q, label in QUERIES:
    t0 = time.perf_counter()
    st = run_query(q, run_id=f"lat_{abs(hash(q))%10**6}")
    dt = time.perf_counter() - t0
    rows.append({"query": q, "label": label, "seconds": round(dt, 2),
                 "retries": st.get("retry_count", 0),
                 "citations": st.get("citations_resolved", 0),
                 "low_conf": bool(st.get("low_confidence"))})
    print(f"  {dt:6.2f}s  retries={rows[-1]['retries']} cits={rows[-1]['citations']:<2} "
          f"{label:<22} {q[:44]}")

def stats(vals):
    v = sorted(vals)
    return (round(statistics.median(v), 2),
            round(v[max(0, int(0.9*len(v))-1)], 2),
            round(min(v), 2), round(max(v), 2))

allv = [r["seconds"] for r in rows]
no_r = [r["seconds"] for r in rows if r["retries"] == 0]
wi_r = [r["seconds"] for r in rows if r["retries"] > 0]
print("\n=== LATENCY (wall clock, n=10) ===")
print(f"  {'group':<22}{'n':>4}{'median':>9}{'p90':>8}{'min':>8}{'max':>8}")
for name, v in (("ALL", allv), ("no retries", no_r), ("with retries", wi_r)):
    if v:
        m, p, lo, hi = stats(v)
        print(f"  {name:<22}{len(v):>4}{m:>9}{p:>8}{lo:>8}{hi:>8}")
json.dump(rows, open("scratchpad/latency.json", "w"), indent=2)
