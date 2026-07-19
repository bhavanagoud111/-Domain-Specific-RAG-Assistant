"""Quick check the fix actually lands before spending an hour on the full eval."""
from graph.wanderrag_graph import run_query
for q in ["What should I visit in Singapore?", "Do I need a visa to visit Mexico as a US citizen?"]:
    st = run_query(q, run_id="p3smoke")
    subs = next((s["sub_queries"] for s in st["trace"] if s.get("node")=="rewrite"), [])
    chunks = st.get("retrieved_chunks", [])
    from collections import Counter
    mix = Counter(c["source_type"] for c in chunks)
    print(f"\n{q}")
    print(f"  sub_queries ({len(subs)}): {subs}")
    print(f"  retrieved source mix: {dict(mix)}   citations={st.get('citations_resolved')}")
