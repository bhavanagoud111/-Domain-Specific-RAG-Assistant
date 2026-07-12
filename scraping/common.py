"""Shared scraping helpers: cached HTTP fetch and structured failure logging.

These keep the individual scrapers small and ensure we never hammer live
government sites during development - every successful fetch is cached to
``raw_html/`` and reused on subsequent runs unless ``force=True``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import requests

from config import settings


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def today() -> str:
    return _dt.date.today().isoformat()


def _cache_path(url: str) -> Path:
    """A stable filename for a URL's cached HTML (hash keeps it filesystem-safe)."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return settings.RAW_HTML_DIR / f"{digest}.html"


def fetch_html(url: str, *, force: bool = False) -> tuple[Optional[str], dict[str, Any]]:
    """Fetch ``url``, returning ``(html, meta)``.

    ``html`` is None on failure (caller decides how to handle). ``meta`` always
    carries ``url``, ``from_cache``, ``status`` and - on failure - ``error``.
    Successful responses are cached to ``raw_html/`` and reused next time.
    """
    settings.ensure_dirs()
    cache_file = _cache_path(url)

    if cache_file.exists() and not force:
        return cache_file.read_text(encoding="utf-8"), {
            "url": url,
            "from_cache": True,
            "status": 200,
        }

    headers = {"User-Agent": settings.USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=settings.REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        return None, {"url": url, "from_cache": False, "status": None, "error": str(exc)}

    if resp.status_code != 200:
        return None, {
            "url": url,
            "from_cache": False,
            "status": resp.status_code,
            "error": f"HTTP {resp.status_code}",
        }

    cache_file.write_text(resp.text, encoding="utf-8")
    return resp.text, {"url": url, "from_cache": False, "status": 200}


def log_scrape_event(event: dict[str, Any]) -> None:
    """Append a structured event to ``logs/scrape_log.json`` (a JSON array)."""
    settings.ensure_dirs()
    event = {"timestamp": utc_now_iso(), **event}

    log_file = settings.SCRAPE_LOG
    existing: list[dict[str, Any]] = []
    if log_file.exists():
        try:
            existing = json.loads(log_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []  # corrupt/partial log -> start fresh rather than crash
    existing.append(event)
    log_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
