"""Is the Mexico / Israel visa gap a CORPUS gap or a RETRIEVAL failure?

Step 1: direct payload text scan over every chunk (no embeddings involved).
Step 2: for whatever text exists, check whether it ever ranks in an embedding k=20.
"""
import json, re
from qdrant_client.models import FieldCondition, Filter, MatchValue
from config import settings
from embedding.embed_and_load import embed_batch
from storage.qdrant_setup import get_client

TERMS = {
    "visa":               re.compile(r"\bvisas?\b", re.I),
    "90 days":            re.compile(r"90 days", re.I),
    "visa-free":          re.compile(r"visa[- ]free", re.I),
    "entry requirements": re.compile(r"entry requirement", re.I),
    "tourist stay":       re.compile(r"tourist stay|tourist visa|stay of|length of stay", re.I),
    "passport valid":     re.compile(r"passport (must be |should be )?valid|valid passport", re.I),
}

pts = json.load(open("scratchpad/corpus_dump.json"))
client = get_client()

for country in ["Mexico", "Israel"]:
    chunks = [p for p in pts if p["payload"]["country"] == country]
    print("=" * 100)
    print(f"{country}: {len(chunks)} chunks total")
    print("-" * 100)

    # ---------- STEP 1: direct text scan ----------
    matched = {}
    for p in chunks:
        pl = p["payload"]; t = pl["text"]
        hits = {name: len(rx.findall(t)) for name, rx in TERMS.items() if rx.search(t)}
        if hits:
            key = (pl["source_type"], pl["chunk_index"])
            matched[key] = (hits, t, str(p["id"]))
    print(f"STEP 1 -- direct payload scan: {len(matched)} / {len(chunks)} chunks contain visa/entry terms")
    for (st, idx), (hits, t, _) in sorted(matched.items()):
        print(f"  [{st} idx={idx}] {hits}")

    # Show the actual text around the strongest signals.
    print(f"\n  --- ACTUAL MATCHING TEXT ({country}) ---")
    shown = 0
    for (st, idx), (hits, t, _) in sorted(matched.items(), key=lambda kv: -sum(kv[1][0].values())):
        if shown >= 4:
            break
        strong = [n for n in ("visa-free", "90 days", "entry requirements", "tourist stay") if n in hits]
        rx = TERMS[strong[0]] if strong else TERMS["visa"]
        m = rx.search(t); i = m.start()
        print(f"\n  [{st} idx={idx}] ...{t[max(0,i-250):i+350]}...".replace("\n", " "))
        shown += 1

    # ---------- STEP 2: does it ever rank? ----------
    q = f"Do I need a visa to visit {country} as a US citizen?"
    vec = embed_batch([q])[0]
    hits20 = client.query_points(
        collection_name=settings.QDRANT_COLLECTION, query=vec, limit=20,
        query_filter=Filter(must=[FieldCondition(key="country", match=MatchValue(value=country))]),
        with_payload=True).points
    ranked_ids = [str(h.id) for h in hits20]
    matched_ids = {v[2] for v in matched.values()}
    ranks = [i + 1 for i, hid in enumerate(ranked_ids) if hid in matched_ids]
    print(f"\n  STEP 2 -- embedding retrieval k=20 for {q!r}")
    print(f"    chunks containing visa/entry terms that appear in top-20: ranks {ranks or 'NONE'}")
    print(f"    of {len(matched)} text-matching chunks, {len(ranks)} ranked in top-20")
    top5 = [(i+1, h.payload['source_type'], h.payload['chunk_index'], str(h.id) in matched_ids)
            for i, h in enumerate(hits20[:5])]
    print(f"    top-5 (rank, source, idx, contains_visa_terms): {top5}")
    print()
