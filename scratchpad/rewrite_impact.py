"""Quantify the rewriter's retrieval cost: raw question vs graph rewrite+merge.

Scores both against the SAME validated relevance set R from precision_diagnosis.json,
so no new judging is involved and the two are directly comparable.
"""
import json
from qdrant_client.models import FieldCondition, Filter, MatchValue
from config import settings
from embedding.embed_and_load import embed_batch
from storage.qdrant_setup import get_client

client = get_client()
diag = json.load(open("evaluation/precision_diagnosis.json"))
res = {r["question"]: r for r in json.load(open("evaluation/eval_results.json"))["results"]}

print(f"{'country/type':<26}{'graph prec':>12}{'RAW prec':>10}{'R':>5}{'max_ach':>9}{'gain':>8}")
print("-"*72)
tot_g = tot_r = 0
for d in diag:
    R = {(c["source_type"], c["chunk_index"]) for c in d["relevant_chunks"]}
    vec = embed_batch([d["question"]])[0]
    hits = client.query_points(collection_name=settings.QDRANT_COLLECTION, query=vec, limit=8,
        query_filter=Filter(must=[FieldCondition(key="country",
                                                 match=MatchValue(value=d["country"]))]),
        with_payload=True).points
    raw_rel = sum(1 for h in hits if (h.payload["source_type"], h.payload["chunk_index"]) in R)
    raw_prec = raw_rel / 8
    graph_prec = d["actual_precision"]
    tot_g += graph_prec; tot_r += raw_prec
    print(f"{d['country'][:14]+'/'+d['question_type'][:10]:<26}{graph_prec:>12.3f}{raw_prec:>10.3f}"
          f"{d['R_relevant_in_corpus']:>5}{d['max_achievable_precision']:>9}"
          f"{raw_prec-graph_prec:>+8.3f}")
print("-"*72)
n=len(diag)
print(f"{'MEAN':<26}{tot_g/n:>12.3f}{tot_r/n:>10.3f}{'':>5}{'':>9}{(tot_r-tot_g)/n:>+8.3f}")
print(f"\nRaw-question retrieval is {(tot_r/tot_g if tot_g else float('inf')):.1f}x more precise "
      f"than the graph's rewrite+merge on these 5 questions.")
