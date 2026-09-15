"""Cities: nearest-major lookup and type-ahead suggestions.

The dataset is bundled (src/data/cities.csv.gz, from GeoNames) rather than fetched
from a geocoding API. No key, no account, no network, no per-query cost -- the same
reasoning as the rest of the program.
"""
from __future__ import annotations

from . import resources
import csv
import gzip
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_PATH = resources.data("cities.csv.gz")

# A "major" city is the anchor of a metro, not merely the nearest large town.
# Someone in Forney TX should see "Dallas", not "Mesquite" -- so the rule is
# "biggest city within reach", not "nearest city over some population".
METRO_RADIUS_KM = 120.0
WIDE_RADIUS_KM = 300.0


@dataclass(frozen=True)
class City:
    name: str
    admin1: str
    country: str
    lat: float
    lon: float
    population: int

    @property
    def label(self) -> str:
        return f"{self.name}, {self.admin1}" if self.admin1 else self.name


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def load_cities(path: str | None = None) -> tuple[City, ...]:
    """Read the bundled dataset. Cached; roughly 20k rows."""
    target = Path(path) if path else DATA_PATH
    if not target.exists():
        return ()
    out: list[City] = []
    with gzip.open(target, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                out.append(City(
                    name=row["name"], admin1=row["admin1"], country=row["country"],
                    lat=float(row["lat"]), lon=float(row["lon"]),
                    population=int(row["population"] or 0),
                ))
            except (ValueError, KeyError):
                continue
    return tuple(out)


def nearest_major_city(lat: float, lon: float,
                       cities: tuple[City, ...] | None = None) -> City | None:
    """The metro anchor for a point: the largest city within reach.

    Not the nearest large one. From Forney TX the nearest city over 100k is
    Mesquite, but the answer a person expects is Dallas.
    """
    cities = cities if cities is not None else load_cities()
    if not cities:
        return None
    for radius in (METRO_RADIUS_KM, WIDE_RADIUS_KM):
        best: City | None = None
        for c in cities:
            if abs(c.lat - lat) > radius / 111.0:      # cheap reject before haversine
                continue
            if haversine_km(lat, lon, c.lat, c.lon) <= radius:
                if best is None or c.population > best.population:
                    best = c
        if best is not None:
            return best
    return min(cities, key=lambda c: haversine_km(lat, lon, c.lat, c.lon))


def nearby(lat: float, lon: float, radius_km: float, limit: int = 12,
           min_population: int = 15_000,
           cities: tuple[City, ...] | None = None) -> list[City]:
    """Towns within the radius, biggest first.

    This is what turns the radius control into something a source can act on: a
    local venue exists per town, so "25 miles" becomes a concrete list of places
    to read rather than a number nothing honours.
    """
    cities = cities if cities is not None else load_cities()
    degrees = radius_km / 111.0
    found: list[tuple[int, City]] = []
    for c in cities:
        if c.population < min_population or abs(c.lat - lat) > degrees:
            continue
        if haversine_km(lat, lon, c.lat, c.lon) <= radius_km:
            found.append((c.population, c))
    found.sort(key=lambda pair: -pair[0])
    return [c for _p, c in found[:limit]]


def suggest(prefix: str, near: tuple[float, float] | None = None, limit: int = 8,
            cities: tuple[City, ...] | None = None) -> list[City]:
    """Type-ahead matches, ranked for a person typing their own area.

    Nearby places outrank distant ones of the same size, so "Dal" from Forney
    offers Dallas TX before Dallas OR.
    """
    cities = cities if cities is not None else load_cities()
    text = prefix.strip().lower()
    if not text or not cities:
        return []

    # "dallas, tx" -- let the state narrow the match once it is typed.
    state = ""
    if "," in text:
        text, _, state = (p.strip() for p in text.partition(","))

    scored: list[tuple[float, City]] = []
    for c in cities:
        name = c.name.lower()
        if not name.startswith(text):
            continue
        if state and not c.admin1.lower().startswith(state):
            continue
        score = math.log10(max(c.population, 1) + 10)
        if name == text:
            score += 3.0
        if near is not None:
            km = haversine_km(near[0], near[1], c.lat, c.lon)
            # Local places win: full bonus in-metro, fading out by ~500km.
            score += 6.0 * math.exp(-km / 180.0)
        scored.append((score, c))

    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [c for _s, c in scored[:limit]]


def find(label: str, cities: tuple[City, ...] | None = None) -> City | None:
    """Resolve 'Dallas, TX' back to a city, for turning the field into coordinates."""
    cities = cities if cities is not None else load_cities()
    name, _, state = (p.strip().lower() for p in label.partition(","))
    best: City | None = None
    for c in cities:
        if c.name.lower() != name:
            continue
        if state and c.admin1.lower() != state:
            continue
        if best is None or c.population > best.population:
            best = c
    return best
