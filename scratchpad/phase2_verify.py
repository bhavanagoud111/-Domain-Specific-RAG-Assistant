"""Phase 2b proof: carrying scrape_date changes citations/gate for NOBODY."""
import json
from graph.wanderrag_graph import run_query

EXPECT = {  # from the frozen-corpus Week 6 baseline
    "What should I visit in Japan?":  {"gate": "pass", "wk6": "5 citations"},
    "What should I visit in Canada?": {"gate": "fail", "wk6": "0 citations, low_conf"},
    "What should I visit in Italy?":  {"gate": "pass", "wk6": "6 citations"},
}
for q, exp in EXPECT.items():
    st = run_query(q, run_id="p2verify")
    cits = st.get("citations", [])
    n = st.get("citations_resolved", len(cits))
    gate = "pass" if n >= 1 else "fail"
    ok = gate == exp["gate"]
    dates = sorted({c.get("scrape_date") for c in cits})
    print(f"  {q}")
    print(f"    citations={n}  gate={gate} (expected {exp['gate']}) {'OK' if ok else 'MISMATCH'}"
          f"  low_conf={bool(st.get('low_confidence'))}  wk6 baseline: {exp['wk6']}")
    print(f"    scrape_date present on all citations: "
          f"{all(c.get('scrape_date') for c in cits) if cits else 'n/a (no citations)'}  values={dates}")
    # the field must never appear in the answer text
    assert "scrape_date" not in st.get("final_answer",""), "leaked into answer text!"
print("\n  assertion passed: 'scrape_date' never appears in any answer text")
