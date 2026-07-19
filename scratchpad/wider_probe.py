"""Does a WIDER retrieval window surface the visa answer the top-6 missed?"""
import re
from qdrant_client.models import FieldCondition, Filter, MatchValue
from config import settings
from embedding.embed_and_load import embed_batch
from storage.qdrant_setup import get_client

client = get_client()
PAT = re.compile(r"no visa required|visa[- ]free|without a visa", re.I)
for c in ["Japan", "Mexico", "Israel", "Italy"]:
    q = f"Do I need a visa to visit {c} as a US citizen?"
    vec = embed_batch([q])[0]
    for k in (6, 20):
        hits = client.query_points(
            collection_name=settings.QDRANT_COLLECTION, query=vec, limit=k,
            query_filter=Filter(must=[FieldCondition(key="country", match=MatchValue(value=c))]),
            with_payload=True).points
        found = [i+1 for i, h in enumerate(hits) if PAT.search(h.payload.get("text",""))]
        print(f"  {c:<8} k={k:<3} chunks containing explicit visa-free language at ranks: {found or 'NONE'}")
    print()
