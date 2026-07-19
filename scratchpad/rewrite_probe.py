"""Does the rewrite node degrade retrieval? Compare raw question vs the sub-queries it emits."""
from qdrant_client.models import FieldCondition, Filter, MatchValue
from config import settings
from embedding.embed_and_load import embed_batch
from storage.qdrant_setup import get_client
from graph.wanderrag_graph import run_query

client = get_client()

def top(q, country, k=8):
    vec = embed_batch([q])[0]
    hits = client.query_points(collection_name=settings.QDRANT_COLLECTION, query=vec, limit=k,
        query_filter=Filter(must=[FieldCondition(key="country", match=MatchValue(value=country))]),
        with_payload=True).points
    return [(h.payload["source_type"], h.payload["chunk_index"], round(h.score,3)) for h in hits]

for q, c in [("What should I visit in Singapore?", "Singapore"),
             ("Do I need a visa to visit Mexico as a US citizen?", "Mexico")]:
    print("="*95); print(q)
    print("\n  RAW QUESTION -> top 8:")
    for s in top(q, c): print("   ", s)
    st = run_query(q, run_id="probe")
    subs = []
    for step in st.get("trace", []):
        if step.get("node") == "rewrite":
            subs = step["sub_queries"]; break
    print(f"\n  REWRITER EMITTED SUB-QUERIES: {subs}")
    for sq in subs:
        print(f"\n  sub-query {sq!r} -> top 4:")
        for s in top(sq, c, 4): print("   ", s)
