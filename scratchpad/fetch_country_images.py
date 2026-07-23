"""One-off: fetch a scenic photo for each of the 50 WanderRAG countries.

Primary source: the Wikivoyage {{pagebanner}} image (a curated wide travel photo),
resolved to its Wikimedia Commons file and downloaded at a sane width. Falls back to
the Wikivoyage summary thumbnail (skipping flags/maps), then to a generated gradient
placeholder so all 50 countries always have a card.

Writes:  assets/countries/<slug>.jpg   (max width 900, JPEG)
         assets/countries/manifest.json (source + license/author for attribution)

Run:  PYTHONPATH=. python scratchpad/fetch_country_images.py
"""
from __future__ import annotations

import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config.countries import COUNTRIES

UA = "WanderRAG/0.1 (class project; contact: bediga@2build.ai)"
OUT = Path(__file__).resolve().parent.parent / "assets" / "countries"
MAX_W = 900

# Regional accent colours for the gradient placeholders.
REGION_COLORS = {
    "Europe": ((37, 99, 235), (14, 165, 233)),
    "Asia-Pacific": ((219, 39, 119), (147, 51, 234)),
    "Americas": ((234, 88, 12), (202, 138, 4)),
    "Middle East & Africa": ((13, 148, 136), (5, 150, 105)),
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read()


def _get_json(url: str) -> dict:
    return json.loads(_get(url).decode("utf-8", "replace"))


def banner_filename(title: str) -> str | None:
    """Extract the Wikivoyage pagebanner image filename for a country article."""
    url = "https://en.wikivoyage.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "parse", "page": title, "prop": "wikitext",
         "format": "json", "redirects": 1})
    try:
        wt = _get_json(url)["parse"]["wikitext"]["*"]
    except Exception:
        return None
    m = re.search(r"\{\{\s*[Pp]age ?banner\s*\|\s*([^|}\n]+)", wt)
    if not m:
        m = re.search(r"\bbanner\s*=\s*([^|}\n]+)", wt)
    if not m:
        return None
    name = m.group(1).strip()
    return name or None


def commons_image(filename: str) -> tuple[str, dict] | None:
    """Resolve a File: name to a scaled thumbnail URL + attribution metadata."""
    title = filename if filename.lower().startswith("file:") else f"File:{filename}"
    url = "https://en.wikivoyage.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "titles": title, "prop": "imageinfo",
         "iiprop": "url|extmetadata", "iiurlwidth": str(MAX_W),
         "format": "json"})
    try:
        pages = _get_json(url)["query"]["pages"]
        info = next(iter(pages.values()))["imageinfo"][0]
    except Exception:
        return None
    src = info.get("thumburl") or info.get("url")
    if not src:
        return None
    meta = info.get("extmetadata", {})
    attr = {
        "artist": re.sub("<[^>]+>", "", (meta.get("Artist", {}) or {}).get("value", "") or "").strip(),
        "license": (meta.get("LicenseShortName", {}) or {}).get("value", "") or "",
        "file": title,
    }
    return src, attr


def summary_thumb(title: str) -> str | None:
    """Wikivoyage summary thumbnail, skipping SVG flags / maps."""
    enc = urllib.parse.quote(title.replace(" ", "_"))
    try:
        d = _get_json(f"https://en.wikivoyage.org/api/rest_v1/page/summary/{enc}")
    except Exception:
        return None
    src = (d.get("originalimage") or d.get("thumbnail") or {}).get("source")
    if not src:
        return None
    low = src.lower()
    if low.endswith(".svg.png") or ".svg" in low or "map" in low or "regions" in low:
        return None
    return src


def save_photo(raw: bytes, dest: Path) -> None:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    if img.width > MAX_W:
        img = img.resize((MAX_W, round(img.height * MAX_W / img.width)), Image.LANCZOS)
    img.save(dest, "JPEG", quality=82, optimize=True)


def placeholder(name: str, region: str, dest: Path) -> None:
    c1, c2 = REGION_COLORS.get(region, ((71, 85, 105), (30, 41, 59)))
    w, h = MAX_W, 560
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / h
        for x in range(w):
            u = (x / w + t) / 2
            px[x, y] = tuple(round(c1[i] + (c2[i] - c1[i]) * u) for i in range(3))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 64)
    except Exception:
        font = ImageFont.load_default()
    tw = draw.textlength(name, font=font)
    draw.text(((w - tw) / 2, h / 2 - 40), name, fill=(255, 255, 255), font=font)
    img.save(dest, "JPEG", quality=82)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    stats = {"banner": 0, "summary": 0, "placeholder": 0}
    for c in COUNTRIES:
        dest = OUT / f"{c.slug}.jpg"
        source, attr = "placeholder", {}
        # 1) Wikivoyage banner
        fn = banner_filename(c.name)
        got = commons_image(fn) if fn else None
        if got:
            url, attr = got
            try:
                save_photo(_get(url), dest)
                source = "banner"
            except Exception:
                got = None
        # 2) Wikivoyage summary thumbnail
        if source == "placeholder":
            st = summary_thumb(c.name)
            if st:
                try:
                    save_photo(_get(st), dest)
                    source, attr = "summary", {"file": st}
                except Exception:
                    pass
        # 3) gradient placeholder
        if source == "placeholder":
            placeholder(c.name, c.region, dest)
        stats[source] += 1
        manifest.append({"slug": c.slug, "name": c.name, "region": c.region,
                         "source": source, **attr})
        print(f"  [{source:11}] {c.name}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDONE: {stats}  -> {OUT}")


if __name__ == "__main__":
    main()
