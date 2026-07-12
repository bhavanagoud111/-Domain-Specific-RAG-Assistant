"""The 50 WanderRAG countries as structured data.

Each country has a canonical ``name``, a ``region``, and *slug variants* used to
build source URLs. Slugs default to a lowercase, hyphenated form of the name
(``United Kingdom`` -> ``united-kingdom``), but some sites use non-obvious slugs
(e.g. State Dept uses ``czechia`` for the Czech Republic). Where we already know
an override, it is set explicitly; everything else falls back to the default and
is corrected based on the 404s logged by the scrapers.

The country list is FINAL per the project spec - do not add/remove entries.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def default_slug(name: str) -> str:
    """``"South Korea"`` -> ``"south-korea"``."""
    return name.strip().lower().replace(" ", "-")


@dataclass(frozen=True)
class Country:
    name: str
    region: str
    # Per-source slug overrides. When None we fall back to ``default_slug(name)``.
    state_dept_slug: str | None = None
    cdc_slug: str | None = None

    @property
    def slug(self) -> str:
        return default_slug(self.name)

    @property
    def state_dept_url(self) -> str:
        slug = self.state_dept_slug or self.slug
        return (
            "https://travel.state.gov/content/travel/en/traveladvisories/"
            f"traveladvisories/{slug}-travel-advisory.html"
        )

    @property
    def cdc_url(self) -> str:
        slug = self.cdc_slug or self.slug
        return f"https://wwwnc.cdc.gov/travel/destinations/traveler/none/{slug}"


# ---------------------------------------------------------------------------
# The 50 countries, grouped by region (FINAL list).
# Overrides below are best-effort; the scrapers log 404s so unknown slugs can
# be corrected here without touching any other code.
# ---------------------------------------------------------------------------

_EUROPE = [
    Country("France", "Europe"),
    Country("Spain", "Europe"),
    Country("Italy", "Europe"),
    Country("United Kingdom", "Europe"),
    Country("Germany", "Europe"),
    Country("Turkey", "Europe", state_dept_slug="turkey", cdc_slug="turkey"),
    Country("Greece", "Europe"),
    Country("Portugal", "Europe"),
    Country("Netherlands", "Europe"),
    Country("Austria", "Europe"),
    Country("Switzerland", "Europe"),
    Country("Croatia", "Europe"),
    # State Dept and CDC both use "czechia" rather than "czech-republic".
    Country("Czech Republic", "Europe", state_dept_slug="czechia", cdc_slug="czechia"),
    Country("Poland", "Europe"),
    Country("Ireland", "Europe"),
    Country("Iceland", "Europe"),
    Country("Sweden", "Europe"),
    Country("Norway", "Europe"),
]

_ASIA_PACIFIC = [
    Country("China", "Asia-Pacific", cdc_slug="china"),
    Country("Japan", "Asia-Pacific"),
    Country("Thailand", "Asia-Pacific"),
    Country("Vietnam", "Asia-Pacific"),
    Country("Indonesia", "Asia-Pacific"),
    Country("Malaysia", "Asia-Pacific"),
    Country("Singapore", "Asia-Pacific"),
    Country("South Korea", "Asia-Pacific"),
    Country("India", "Asia-Pacific"),
    Country("Philippines", "Asia-Pacific"),
    Country("Australia", "Asia-Pacific"),
    Country("New Zealand", "Asia-Pacific"),
    Country("Cambodia", "Asia-Pacific"),
    Country("Sri Lanka", "Asia-Pacific"),
    Country("Nepal", "Asia-Pacific"),
]

_AMERICAS = [
    # The US issues the advisories, so there is no State Dept page for itself;
    # the scraper will log a 404 for it, which is expected.
    Country("United States", "Americas"),
    Country("Mexico", "Americas"),
    Country("Canada", "Americas"),
    Country("Brazil", "Americas"),
    Country("Argentina", "Americas"),
    Country("Peru", "Americas"),
    Country("Costa Rica", "Americas"),
    Country("Colombia", "Americas"),
    Country("Dominican Republic", "Americas"),
    Country("Chile", "Americas"),
]

_MIDDLE_EAST_AFRICA = [
    Country("United Arab Emirates", "Middle East & Africa"),
    Country("Egypt", "Middle East & Africa"),
    Country("Morocco", "Middle East & Africa"),
    Country("South Africa", "Middle East & Africa"),
    Country("Saudi Arabia", "Middle East & Africa"),
    Country("Jordan", "Middle East & Africa"),
    Country("Israel", "Middle East & Africa", state_dept_slug="israel-west-bank-and-gaza"),
]

COUNTRIES: list[Country] = _EUROPE + _ASIA_PACIFIC + _AMERICAS + _MIDDLE_EAST_AFRICA

assert len(COUNTRIES) == 50, f"Expected 50 countries, got {len(COUNTRIES)}"


def by_name(name: str) -> Country:
    """Look up a country by (case-insensitive) name. Raises KeyError if absent."""
    target = name.strip().lower()
    for c in COUNTRIES:
        if c.name.lower() == target:
            return c
    raise KeyError(f"Unknown country: {name!r}")


def names() -> list[str]:
    return [c.name for c in COUNTRIES]
