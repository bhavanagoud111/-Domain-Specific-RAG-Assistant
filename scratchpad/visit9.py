"""Phase 1d — the 9 'what should I visit' queries against the fixed corpus."""
import json, sys
from graph.wanderrag_graph import run_query

COUNTRIES = ["Italy","Mexico","Norway","Thailand","Canada","United Arab Emirates","Japan","Singapore","Brazil"]
out = []
for c in COUNTRIES:
    q = f"What should I visit in {c}?"
    st = run_query(q, run_id=f"p1d_{c.replace(' ','_')}")
    cits = st.get("citations", [])
    row = {
        "country": c, "query": q,
        "citations_resolved": st.get("citations_resolved", len(cits)),
        "low_confidence": bool(st.get("low_confidence")),
        "thin_pass": bool(st.get("thin_pass")),
        "retries": st.get("retry_count", 0),
        "cited_sources": [f"{x.get('source_type')}/{x.get('country')}" for x in cits],
        "answer_head": (st.get("final_answer","") or "")[:200].replace("\n"," "),
    }
    out.append(row)
    print(f"{c:<22} cits={row['citations_resolved']:<3} low_conf={str(row['low_confidence']):<6} "
          f"thin={str(row['thin_pass']):<6} retries={row['retries']}  {row['cited_sources'][:4]}")
json.dump(out, open("scratchpad/phase1d_visit9.json","w"), indent=2)
