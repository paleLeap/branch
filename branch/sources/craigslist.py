"""Craigslist, through the attended browser.

WHY THIS IS BUILT, AFTER BEING EXCLUDED

The first pass excluded Craigslist on the grounds that "their terms forbid it and
robots.txt disallows it". **Half of that was wrong, and it was checked rather than
assumed the second time.** `robots.txt` disallows only `/reply`, `/fb/`,
`/suggest`, `/flag`, `/mf`, `/mailflag` and `/eaf` -- not `/search` -- and
craigslist publishes sitemaps of live postings.

What is true: their **Terms of Use** forbid automated access, which is a matter of
contract rather than criminal law, and they enforce it harder than anyone else in
this space. A plain `urllib` request to a search page comes back as a 403 "Your
request has been blocked" page on the *first* try -- measured, not guessed --
and `?format=rss` is blocked the same way.

So Craigslist is read the way Facebook is read: in the user's own browser, at the
user's own address, at reading pace, while they watch, and never on a schedule.
That is the posture this program already committed to for Facebook and X, and the
reasoning transfers exactly.

WHAT IT IS GOOD FOR, AND WHAT IT IS NOT

Rendered in a real browser a category page gives **~138 results with real
permalinks, dates, an excerpt, and the town in the URL slug** -- better shaped
than Facebook post search, which carries no permalink at all.

But `gigs` is mostly **employers hiring workers**, not people needing a service.
A live read of Dallas domestic gigs returned housekeeping vacancies, two medical
research studies and a paid-chores scheme -- and among them "I have a portable
carport that needs to be put together" and "Moving job", which are exactly right.
So: strong for moving, labour and handyman work; thin for plumbing or motorcycle
repair. The advertising exclusions in `profiles/_defaults.yaml` do most of the
filtering, and this source leans on them harder than any other.

GEOGRAPHY IS REAL HERE. Craigslist is organised into 468 North American areas and
a scan reads the one nearest the user, from a bundled table -- no geocoding call,
no key. See `data/build_craigslist_areas.py`.
"""
from __future__ import annotations

import csv
import gzip
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from .. import resources
from ..places import haversine_km
from .base import Query
from .facebook import _Interactive

AREAS_PATH = resources.data("craigslist_areas.csv.gz")

#: The categories where someone describes a job they want done. `ggg` is every
#: gig; the rest are the sub-categories worth naming separately because a trade
#: usually wants one of them rather than all.
#:
#: Deliberately absent: `bbb` (services OFFERED) and the job boards. Those are
#: the supply side -- the competition -- and reading them would fill the results
#: with the very advertising the profiles work to exclude.
CATEGORIES: dict[str, str] = {
    "ggg": "gigs",
    "lbg": "labor gigs",
    "dmg": "domestic gigs",
    "cpg": "computer gigs",
    "evg": "event gigs",
    "crg": "creative gigs",
}

#: Which categories a trade should read, by the keywords in its name. Anything
#: unrecognised reads every gig, which is the honest default: a trade we have no
#: opinion about should not be silently narrowed.
TRADE_CATEGORIES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("computer", "it", "tech", "网"), ("cpg", "ggg")),
    (("photo", "video", "wedding", "design"), ("crg", "evg", "ggg")),
    (("clean", "maid", "housekeep", "nanny", "care"), ("dmg", "ggg")),
    (("move", "moving", "haul", "labor", "labour", "handyman", "landscap"),
     ("lbg", "ggg")),
]


@dataclass(frozen=True)
class Area:
    slug: str
    label: str
    lat: float
    lon: float


def load_areas(path: Path | None = None) -> tuple[Area, ...]:
    target = path or AREAS_PATH
    try:
        with gzip.open(target, "rt", encoding="utf-8") as fh:
            return tuple(Area(r["slug"], r["label"], float(r["lat"]), float(r["lon"]))
                         for r in csv.DictReader(fh))
    except (OSError, KeyError, ValueError):
        return ()


def nearest_area(lat: float, lon: float,
                 areas: tuple[Area, ...] | None = None) -> Area | None:
    """The craigslist area covering these coordinates, or the closest one.

    Nearest by straight-line distance to the area's main town. Craigslist areas
    are large and irregular and their real boundaries are not published, so this
    is an approximation -- but "the nearest craigslist city" is also how a person
    picks one, so it approximates the right thing.
    """
    areas = areas if areas is not None else load_areas()
    if not areas:
        return None
    return min(areas, key=lambda a: haversine_km(lat, lon, a.lat, a.lon))


def categories_for(trade: str) -> tuple[str, ...]:
    trade = (trade or "").lower()
    for keywords, cats in TRADE_CATEGORIES:
        if any(word in trade for word in keywords):
            return cats
    return ("ggg",)


def search_urls(query: Query) -> list[tuple[str, str]]:
    """(url, label) per category, plus one keyword search if the box was used.

    The category pages are the substance: they are demand-side by construction
    and already scoped to the area. A typed narrowing becomes one extra search
    across all gigs rather than a filter on each, because craigslist's own search
    is weak and narrowing six pages to nothing is the more likely failure.
    """
    area = None
    if query.coordinates is not None:
        area = nearest_area(*query.coordinates)
    if area is None:
        return []

    base = f"https://www.craigslist.org/search/area/{area.slug}"
    out = [(f"{base}?cat={cat}", f"{CATEGORIES.get(cat, cat)} in {area.label}")
           for cat in categories_for(query.trade)]

    if query.narrow:
        params = urllib.parse.urlencode({"cat": "ggg", "query": query.narrow})
        out.append((f"{base}?{params}", f"{query.narrow} in {area.label}"))
    return out


class Craigslist(_Interactive):
    """Public postings, read in the user's own browser. No account needed."""

    key = "craigslist"
    label = "Craigslist"
    description = ("Craigslist gigs in your area -- people posting one-off jobs they need "
                   "doing. Read in Branch's browser; no account needed.")
    geographic = True          # a real area, picked from coordinates
    login_service = ""         # craigslist serves everyone; nothing to sign in to
    login_url = ""
    short_reason = "no location set"

    def available(self) -> str | None:
        if not load_areas():
            return "the craigslist area table is missing from data/"
        return None

    def url(self, query: Query) -> str:
        found = search_urls(query)
        return found[0][0] if found else "https://www.craigslist.org/"

    def urls(self, query: Query) -> list[tuple[str, str]]:
        return search_urls(query)
