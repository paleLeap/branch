"""What else a post tells you, read from the post itself.

Deterministic, like everything else: this reads the text that is already on
screen and nothing more. No lookups, no profile fetching, no cross-referencing
a person across sources.

The line on contact details is deliberate. If someone has written "call me on
..." in a public post, Branch says **that they left a number**, not what the
number is. The user can read it themselves in the post. Branch is not going to
lift personal details out of posts and put them in a list -- that is precisely
the dossier-building the whole design refuses.
"""
from __future__ import annotations

import re

from .places import City, haversine_km

_ZIP = re.compile(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\d)")
_DM = re.compile(r"\b(dm me|pm me|message me|inbox me|send me a message|dm for)\b", re.I)
_URGENT = re.compile(r"\b(urgent|asap|emergency|today|right now|immediately|tonight)\b", re.I)
_BUDGET = re.compile(r"\$\s?\d[\d,]*")


def find_zip(text: str) -> str | None:
    """A US postcode, if the post names one.

    Weeded against years and prices: "75217" is a postcode, "2015" is not, and a
    number right after a dollar sign is money.
    """
    for match in _ZIP.finditer(text or ""):
        code = match.group(1)
        if code.startswith("0") and not code.startswith("00"):
            pass
        before = text[max(0, match.start() - 2):match.start()]
        if "$" in before:
            continue
        if 1900 <= int(code[:4]) <= 2100 and len(code) == 4:
            continue
        return code
    return None


def find_town(text: str, near: tuple[float, float] | None,
              cities: tuple[City, ...], radius_km: float = 160.0) -> str | None:
    """A nearby town named in the post.

    Only towns already inside the search area are considered, which keeps
    "Austin" in a Dallas scan from being read as a location rather than a name.
    """
    if not text or near is None or not cities:
        return None
    # Separators matter: "Dallas/Mesquite/Garland" is three towns, and matching
    # on " name " alone found none of them.
    lowered = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    best: City | None = None
    for city in cities:
        if city.population < 5_000:
            continue
        if haversine_km(near[0], near[1], city.lat, city.lon) > radius_km:
            continue
        if f" {city.name.lower()} " in lowered:
            if best is None or city.population > best.population:
                best = city
    return best.name if best else None


def signals(text: str) -> list[str]:
    """Short, human-readable notes about the post.

    Contact details are reported as present, never extracted -- see the module
    docstring.
    """
    found: list[str] = []
    if _URGENT.search(text or ""):
        found.append("urgent")
    if _BUDGET.search(text or ""):
        found.append("mentions a budget")
    if _DM.search(text or ""):
        found.append("asks for DMs")
    if _PHONE.search(text or ""):
        found.append("left a number")
    return found


def describe(text: str, near: tuple[float, float] | None = None,
             cities: tuple[City, ...] = ()) -> list[str]:
    """Everything worth showing under a lead, in one line."""
    out: list[str] = []
    code = find_zip(text)
    town = find_town(text, near, cities)
    if code:
        out.append(code)
    if town and town.lower() not in (code or "").lower():
        out.append(town)
    out.extend(signals(text))
    return out
