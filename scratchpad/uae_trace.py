import json
from graph.wanderrag_graph import run_query
st = run_query("What should I visit in United Arab Emirates?", run_id="uae_trace")
print("country:", st.get("country"), "| cits:", st.get("citations_resolved"),
      "| low_conf:", bool(st.get("low_confidence")))
for s in st.get("trace", []):
    if s.get("node") == "retrieve":
        print(f"\n[retrieve] filter={s['country_filter']} n_chunks={s['n_chunks']} "
              f"sources={s['sources']} scores={s['top_scores']}")
    if s.get("node") == "rewrite":
        print(f"[rewrite] detected={s['detected_country']} subs={s['sub_queries']}")
print("\nRETRIEVED CHUNKS:")
for c in st.get("retrieved_chunks", []):
    print(f"  {c['score']:.3f} {c['country']}/{c['source_type']}: {c['text'][:180]}...")
print("\nANSWER:\n", st.get("final_answer","")[:900])
