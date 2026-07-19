"""Post-revert: gate verdicts must match the Week 6 baseline."""
from graph.wanderrag_graph import run_query
BASE = {
    "What should I visit in Japan?":            ("pass", "wk6: 5 citations, GROUNDED"),
    "What should I visit in Canada?":           ("fail", "wk6: 0 citations, low_confidence"),
    "asdkjasd current safety xyz nonsense country": ("fail", "wk6: 0 citations, low_confidence"),
}
allok = True
for q, (exp, note) in BASE.items():
    st = run_query(q, run_id="revert_verify")
    n = st.get("citations_resolved", 0)
    gate = "pass" if n >= 1 else "fail"
    subs = next((s["sub_queries"] for s in st["trace"] if s.get("node") == "rewrite"), [])
    ok = gate == exp
    allok &= ok
    print(f"  {'OK  ' if ok else 'MISMATCH'} {q[:46]:<48} citations={n:<2} gate={gate:<5} "
          f"(expected {exp})  low_conf={bool(st.get('low_confidence'))}")
    print(f"        sub_queries={len(subs)} -> {subs}")
    print(f"        {note}")
print(f"\n  ALL GATE VERDICTS MATCH BASELINE: {allok}")
