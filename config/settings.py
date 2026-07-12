"""Central configuration. Secrets come from a ``.env`` file (never hardcoded).

Import the module-level constants elsewhere, e.g.::

    from config.settings import OPENROUTER_API_KEY, QDRANT_URL, CHUNK_SIZE
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root regardless of the current working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# OpenRouter (embeddings)
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-large")
EMBEDDING_DIM = 3072  # text-embedding-3-large native dimensionality
# OpenRouter price for text-embedding-3-large (USD per 1M input tokens).
# Used only for the running cost estimate in the embed logs.
EMBEDDING_USD_PER_1M_TOKENS = float(os.getenv("EMBEDDING_USD_PER_1M_TOKENS", "0.13"))
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "20"))

# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "") or None  # only needed for Qdrant Cloud
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "wanderrag_chunks")

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "512"))      # tokens per chunk
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))  # token overlap between chunks
TIKTOKEN_ENCODING = os.getenv("TIKTOKEN_ENCODING", "cl100k_base")

# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))  # seconds
USER_AGENT = os.getenv(
    "USER_AGENT",
    "WanderRAG/0.1 (class project; contact: student@example.edu)",
)
# A rendered page shorter than this many characters is treated as "mostly empty"
# and re-fetched via the Selenium fallback.
MIN_CONTENT_CHARS = int(os.getenv("MIN_CONTENT_CHARS", "500"))

# ---------------------------------------------------------------------------
# Filesystem layout (created on demand by the modules that write to them)
# ---------------------------------------------------------------------------
RAW_HTML_DIR = PROJECT_ROOT / "raw_html"
SCRAPED_DATA_DIR = PROJECT_ROOT / "scraped_data"
STATE_DEPT_DIR = SCRAPED_DATA_DIR / "state_dept"
CDC_DIR = SCRAPED_DATA_DIR / "cdc"
TOURISM_DIR = SCRAPED_DATA_DIR / "tourism"
LOGS_DIR = PROJECT_ROOT / "logs"
SCRAPE_LOG = LOGS_DIR / "scrape_log.json"
EMBED_COST_LOG = LOGS_DIR / "embed_cost_log.json"
TOURISM_SOURCES_CSV = PROJECT_ROOT / "tourism_sources.csv"


def ensure_dirs() -> None:
    """Create all working directories if they don't exist yet."""
    for d in (
        RAW_HTML_DIR,
        SCRAPED_DATA_DIR,
        STATE_DEPT_DIR,
        CDC_DIR,
        TOURISM_DIR,
        LOGS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def require_openrouter_key() -> str:
    """Return the OpenRouter key or raise a clear error if it's missing."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return OPENROUTER_API_KEY
