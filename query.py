"""Quick retrieval spot-check against the Qdrant collection.

Embeds a query with the same model and prints the top matching chunks. Use this
to sanity-check before scaling to all 50, e.g.:

    python query.py "Japan visa requirements"
    python query.py "vaccines for Mexico" --country Mexico --source cdc --k 5
"""

from __future__ import annotations

import argparse

from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import settings
from embedding.embed_and_load import embed_batch
from storage.qdrant_setup import get_client


def search(query: str, *, k: int = 5, country: str | None = None, source: str | None = None):
    client = get_client()
    vector = embed_batch([query])[0]

    must = []
    if country:
        must.append(FieldCondition(key="country", match=MatchValue(value=country)))
    if source:
        must.append(FieldCondition(key="source_type", match=MatchValue(value=source)))
    query_filter = Filter(must=must) if must else None

    return client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=vector,
        limit=k,
        query_filter=query_filter,
        with_payload=True,
    ).points


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the WanderRAG collection.")
    parser.add_argument("query", help="Natural-language query.")
    parser.add_argument("--k", type=int, default=5, help="Number of results.")
    parser.add_argument("--country", default=None, help="Filter by country.")
    parser.add_argument("--source", default=None, help="Filter by source_type (state_dept/cdc/tourism).")
    args = parser.parse_args()

    hits = search(args.query, k=args.k, country=args.country, source=args.source)
    print(f"\nTop {len(hits)} results for: {args.query!r}\n")
    for i, hit in enumerate(hits, start=1):
        p = hit.payload or {}
        snippet = (p.get("text", "") or "")[:240].replace("\n", " ")
        print(f"[{i}] score={hit.score:.4f} | {p.get('country')} / {p.get('source_type')}")
        print(f"    {snippet}...\n")


if __name__ == "__main__":
    main()
