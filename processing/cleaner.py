"""Text cleaning: strip boilerplate/nav/footer and normalize whitespace.

Two entry points:
- ``clean_html(html)`` - parse raw HTML, drop nav/footer/script/style/cookie
  banners, return readable text.
- ``clean_text(text)`` - normalize whitespace and drop repeated boilerplate
  lines from already-extracted text (used right before chunking).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from bs4 import BeautifulSoup

# Tags whose content is never useful body text.
_DROP_TAGS = ["script", "style", "nav", "footer", "header", "noscript", "form", "svg"]

# Common .gov boilerplate fragments that survive tag-stripping. Lines containing
# any of these (case-insensitive) are dropped.
_BOILERPLATE_MARKERS = [
    "official website of the united states government",
    "here's how you know",
    "lock (",
    "https means you've safely connected",
    "skip to main content",
    "privacy policy",
    "accessibility",
    "freedom of information act",
    "no fear act",
    "sign up for",
    "subscribe to",
    "cookie",
    "all rights reserved",
    "follow us on",
]

_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def clean_html(html: str) -> str:
    """Parse HTML, drop chrome/boilerplate tags, return normalized text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    # Drop obvious cookie/consent containers by id/class hints.
    for el in soup.find_all(attrs={"class": re.compile("cookie|consent|banner", re.I)}):
        el.decompose()
    text = soup.get_text(separator="\n")
    return clean_text(text)


def _is_boilerplate(line: str) -> bool:
    low = line.lower()
    return any(marker in low for marker in _BOILERPLATE_MARKERS)


def clean_text(text: str, *, drop_repeated: bool = True) -> str:
    """Normalize whitespace and remove boilerplate / repeated short lines."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [_WHITESPACE_RE.sub(" ", ln) for ln in lines]

    # Identify short lines that repeat many times across the doc - almost always
    # menu items / footer links rather than real content.
    repeated: set[str] = set()
    if drop_repeated:
        counts = Counter(ln for ln in lines if ln)
        repeated = {ln for ln, n in counts.items() if n >= 3 and len(ln) < 40}

    kept: list[str] = []
    for ln in lines:
        if not ln:
            kept.append("")
            continue
        if _is_boilerplate(ln) or ln in repeated:
            continue
        kept.append(ln)

    cleaned = "\n".join(kept)
    cleaned = _MULTI_NEWLINE_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def looks_empty(text: str, min_chars: int) -> bool:
    """True if extracted text is too short to be real content (triggers fallback)."""
    return len(text.strip()) < min_chars


def join_nonempty(parts: Iterable[str]) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())
