"""Token-based chunking with overlap, attaching per-chunk metadata.

Uses tiktoken (``cl100k_base``) as a token-count approximation. Each scraped
JSON record becomes a list of chunk dicts ready for embedding, where every chunk
carries: ``country``, ``source_type``, ``source_url``, ``scrape_date``,
``chunk_index`` (plus ``region`` and ``text``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import tiktoken

from config import settings
from processing.cleaner import clean_text

_ENCODER = tiktoken.get_encoding(settings.TIKTOKEN_ENCODING)


def count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def _split_tokens(text: str, size: int, overlap: int) -> Iterator[str]:
    """Yield overlapping token windows decoded back to text."""
    tokens = _ENCODER.encode(text)
    if not tokens:
        return
    step = max(1, size - overlap)
    for start in range(0, len(tokens), step):
        window = tokens[start : start + size]
        if not window:
            break
        yield _ENCODER.decode(window)
        if start + size >= len(tokens):
            break


def chunk_record(
    record: dict[str, Any],
    *,
    size: int | None = None,
    overlap: int | None = None,
) -> list[dict[str, Any]]:
    """Turn one scraped record into a list of metadata-rich chunk dicts."""
    size = size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP

    text = clean_text(record.get("raw_text", ""))
    if not text:
        return []

    base_meta = {
        "country": record.get("country"),
        "region": record.get("region"),
        "source_type": record.get("source_type"),
        "source_url": record.get("source_url"),
        "scrape_date": record.get("scrape_date"),
    }

    chunks: list[dict[str, Any]] = []
    for i, piece in enumerate(_split_tokens(text, size, overlap)):
        piece = piece.strip()
        if not piece:
            continue
        chunks.append({**base_meta, "chunk_index": i, "text": piece})
    return chunks


def chunk_file(path: Path) -> list[dict[str, Any]]:
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    return chunk_record(record)


def chunk_all_scraped() -> list[dict[str, Any]]:
    """Chunk every scraped JSON across all three source folders."""
    all_chunks: list[dict[str, Any]] = []
    for folder in (settings.STATE_DEPT_DIR, settings.CDC_DIR, settings.TOURISM_DIR):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            all_chunks.extend(chunk_file(path))
    return all_chunks


if __name__ == "__main__":
    chunks = chunk_all_scraped()
    print(f"Produced {len(chunks)} chunks from scraped_data/.")
    if chunks:
        sample = chunks[0]
        print(f"Sample chunk: country={sample['country']} source={sample['source_type']} "
              f"tokens~{count_tokens(sample['text'])}")
