"""Phase 1a — replace Japan's mislabeled tourism chunks with a real tourism source.

Deletes ALL Japan+tourism points first (deterministic ids mean a shorter new
chunk list would otherwise leave stale high-index points behind), then
re-scrapes, re-chunks and re-embeds ONLY Japan tourism.
"""
from qdrant_client.models import FieldCondition, Filter, MatchValue

from config import settings
from embedding.embed_and_load import embed_and_load
from processing.chunker import chunk_file
from scraping.tourism_scraper import scrape_row
from storage.qdrant_setup import get_client

client = get_client()
COLL = settings.QDRANT_COLLECTION
JP_TOURISM = Filter(must=[
    FieldCondition(key="country", match=MatchValue(value="Japan")),
    FieldCondition(key="source_type", match=MatchValue(value="tourism")),
])

def count(f=None):
    return client.count(collection_name=COLL, count_filter=f, exact=True).count

before_total = count()
before_jp = count(JP_TOURISM)
print(f"BEFORE: points_count={before_total}  Japan/tourism={before_jp}")

print("\n[1] deleting stale Japan tourism points...")
client.delete(collection_name=COLL, points_selector=JP_TOURISM, wait=True)
print(f"    Japan/tourism now={count(JP_TOURISM)}  total={count()}")

print("\n[2] scraping new source...")
res = scrape_row({"country": "Japan", "url": "https://en.wikivoyage.org/wiki/Japan",
                  "format": "html"}, force=True)
print("   ", res)
assert res.get("ok"), f"scrape failed: {res}"

print("\n[3] chunking...")
chunks = chunk_file(settings.TOURISM_DIR / "japan.json")
print(f"    {len(chunks)} chunks from the new source")
assert chunks and all(c["source_type"] == "tourism" for c in chunks)
assert "wikivoyage" in chunks[0]["source_url"]

print("\n[4] embedding + upserting...")
summary = embed_and_load(chunks)

after_total = count()
print(f"\nAFTER: points_count={after_total}  Japan/tourism={count(JP_TOURISM)}")
print(f"DELTA: {before_jp} -> {count(JP_TOURISM)} Japan tourism chunks; "
      f"total {before_total} -> {after_total}")
print("EMBED:", summary)
