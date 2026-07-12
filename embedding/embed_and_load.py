"""Embed chunks via OpenRouter and upsert them into Qdrant.

- Batches chunks (default 20) and calls OpenRouter's OpenAI-compatible
  ``/embeddings`` endpoint with ``text-embedding-3-large``.
- Logs a running token count + estimated USD cost to ``logs/embed_cost_log.json``
  after every batch so spend can be tracked against the $20 budget in real time.
- Upserts each embedded chunk into the ``wanderrag_chunks`` collection with its
  metadata as the point payload.
- Retries on rate limits / transient errors with exponential backoff.

Run standalone (embeds everything currently in scraped_data/):
    python -m embedding.embed_and_load
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterable

import requests
from qdrant_client.models import PointStruct
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings
from processing.chunker import chunk_all_scraped, count_tokens
from scraping.common import utc_now_iso
from storage.qdrant_setup import create_collection, get_client

# Stable namespace so the same chunk (country+source+index) always maps to the
# same Qdrant point id -> re-running upserts updates rather than duplicates.
_ID_NAMESPACE = uuid.UUID("d3b07384-d9a7-4f1e-8c2a-000000000001")


class EmbeddingError(RuntimeError):
    pass


def _point_id(chunk: dict[str, Any]) -> str:
    key = f"{chunk['country']}|{chunk['source_type']}|{chunk['chunk_index']}"
    return str(uuid.uuid5(_ID_NAMESPACE, key))


def _batched(items: list[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


@retry(
    retry=retry_if_exception_type((requests.RequestException, EmbeddingError)),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
def embed_batch(texts: list[str]) -> list[list[float]]:
    """Call OpenRouter for a batch of texts; returns one vector per text."""
    api_key = settings.require_openrouter_key()
    resp = requests.post(
        f"{settings.OPENROUTER_BASE_URL}/embeddings",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"model": settings.EMBEDDING_MODEL, "input": texts},
        timeout=settings.REQUEST_TIMEOUT * 2,
    )
    if resp.status_code == 429 or resp.status_code >= 500:
        # Transient -> let tenacity back off and retry.
        raise EmbeddingError(f"transient HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code != 200:
        raise EmbeddingError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json().get("data", [])
    # Sort by index to guarantee alignment with the input order.
    data.sort(key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in data]


def _log_cost(state: dict[str, Any]) -> None:
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = settings.EMBED_COST_LOG
    history: list[dict[str, Any]] = []
    if log_file.exists():
        try:
            history = json.loads(log_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    history.append({"timestamp": utc_now_iso(), **state})
    log_file.write_text(json.dumps(history, indent=2), encoding="utf-8")


def embed_and_load(chunks: list[dict[str, Any]], *, batch_size: int | None = None) -> dict[str, Any]:
    """Embed all chunks and upsert into Qdrant. Returns a summary dict."""
    if not chunks:
        print("[embed] No chunks to embed.")
        return {"chunks": 0, "tokens": 0, "cost_usd": 0.0}

    batch_size = batch_size or settings.EMBED_BATCH_SIZE
    client = get_client()
    create_collection(client)  # ensure collection + indexes exist

    total_tokens = 0
    total_cost = 0.0
    total_points = 0
    num_batches = (len(chunks) + batch_size - 1) // batch_size

    for b, batch in enumerate(_batched(chunks, batch_size), start=1):
        texts = [c["text"] for c in batch]
        batch_tokens = sum(count_tokens(t) for t in texts)

        vectors = embed_batch(texts)
        if len(vectors) != len(batch):
            raise EmbeddingError(
                f"Got {len(vectors)} vectors for {len(batch)} inputs in batch {b}."
            )

        points = [
            PointStruct(id=_point_id(c), vector=vec, payload=c)
            for c, vec in zip(batch, vectors)
        ]
        client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)

        total_tokens += batch_tokens
        total_points += len(points)
        total_cost = total_tokens / 1_000_000 * settings.EMBEDDING_USD_PER_1M_TOKENS

        _log_cost(
            {
                "batch": b,
                "of": num_batches,
                "batch_chunks": len(batch),
                "batch_tokens": batch_tokens,
                "cumulative_tokens": total_tokens,
                "cumulative_cost_usd": round(total_cost, 6),
                "cumulative_points": total_points,
            }
        )
        print(
            f"  batch {b}/{num_batches}: {len(batch)} chunks, "
            f"{batch_tokens} tok | total {total_tokens} tok ~ ${total_cost:.4f}"
        )

    summary = {"chunks": total_points, "tokens": total_tokens, "cost_usd": round(total_cost, 4)}
    print(f"[embed] Done: {total_points} points, {total_tokens} tokens, ~${total_cost:.4f}")
    return summary


def main() -> None:
    chunks = chunk_all_scraped()
    print(f"[embed] Chunked scraped_data/ -> {len(chunks)} chunks.")
    embed_and_load(chunks)


if __name__ == "__main__":
    main()
