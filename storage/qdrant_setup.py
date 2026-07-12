"""Create / reset the Qdrant ``wanderrag_chunks`` collection.

Usage:
    python -m storage.qdrant_setup            # create if missing
    python -m storage.qdrant_setup --reset    # drop and recreate (testing)
    python -m storage.qdrant_setup --info      # show current collection status
"""

from __future__ import annotations

import argparse

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

from config.settings import (
    EMBEDDING_DIM,
    QDRANT_API_KEY,
    QDRANT_COLLECTION,
    QDRANT_URL,
)

# Payload fields we want to filter retrieval by later (e.g. "Japan" + "cdc").
INDEXED_PAYLOAD_FIELDS = {
    "country": PayloadSchemaType.KEYWORD,
    "source_type": PayloadSchemaType.KEYWORD,
}


def get_client() -> QdrantClient:
    """A Qdrant client for either local Docker or Qdrant Cloud (if an API key is set)."""
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


def collection_exists(client: QdrantClient) -> bool:
    return client.collection_exists(QDRANT_COLLECTION)


def create_collection(client: QdrantClient, *, reset: bool = False) -> None:
    if reset and collection_exists(client):
        print(f"Dropping existing collection '{QDRANT_COLLECTION}'...")
        client.delete_collection(QDRANT_COLLECTION)

    if collection_exists(client):
        print(f"Collection '{QDRANT_COLLECTION}' already exists - leaving as is.")
    else:
        print(f"Creating collection '{QDRANT_COLLECTION}' (dim={EMBEDDING_DIM}, cosine)...")
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )

    # Payload indexes are idempotent-ish: creating an existing one is a no-op error
    # we can safely ignore, so each field is wrapped individually.
    for field_name, schema in INDEXED_PAYLOAD_FIELDS.items():
        try:
            client.create_payload_index(
                collection_name=QDRANT_COLLECTION,
                field_name=field_name,
                field_schema=schema,
            )
            print(f"  + payload index on '{field_name}'")
        except Exception as exc:  # index already present, etc.
            print(f"  . payload index on '{field_name}' skipped ({exc})")


def print_info(client: QdrantClient) -> None:
    if not collection_exists(client):
        print(f"Collection '{QDRANT_COLLECTION}' does not exist.")
        return
    info = client.get_collection(QDRANT_COLLECTION)
    count = client.count(QDRANT_COLLECTION, exact=True).count
    print(f"Collection '{QDRANT_COLLECTION}':")
    print(f"  points      : {count}")
    print(f"  status      : {info.status}")
    print(f"  vector size : {info.config.params.vectors.size}")
    print(f"  distance    : {info.config.params.vectors.distance}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up the WanderRAG Qdrant collection.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate the collection.")
    parser.add_argument("--info", action="store_true", help="Print collection status and exit.")
    args = parser.parse_args()

    client = get_client()
    print(f"Connected to Qdrant at {QDRANT_URL}")

    if args.info:
        print_info(client)
        return

    create_collection(client, reset=args.reset)
    print_info(client)


if __name__ == "__main__":
    main()
