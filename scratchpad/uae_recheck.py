from graph.wanderrag_graph import run_query
for i in range(3):
    st = run_query("What should I visit in United Arab Emirates?", run_id=f"uae_{i}")
    print(f"  sample {i+1}: cits={st.get('citations_resolved')} thin={bool(st.get('thin_pass'))} "
          f"low_conf={bool(st.get('low_confidence'))}")
