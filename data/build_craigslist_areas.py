"""Rebuild `craigslist_areas.csv.gz` from craigslist's own list of sites.

Run by hand when the site list changes -- it is not part of the program and is
not imported by it. Branch ships the CSV so that finding the right craigslist
area needs no network call and no key:

    cd src && .venv/bin/python data/build_craigslist_areas.py

WHY A TABLE AT ALL. Craigslist is organised into ~470 North American areas, and
a scan has to pick the right one for the user's coordinates. The area names are
not city names -- "sfbay", "inlandempire", "orangecounty" -- so the slugs are
matched to towns in the bundled GeoNames city database and stored with that
town's coordinates. Picking an area is then a nearest-point lookup, offline.

Sixty-odd areas are named after a region rather than a town and cannot be
matched by name at all. Those are listed in BY_HAND, each mapped to the
population centre a person in that area would say they were near.
"""
from __future__ import annotations

import csv
import gzip
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from branch import places                                          # noqa: E402

SITES_URL = "https://www.craigslist.org/about/sites"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")

US = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
      "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
      "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
      "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
      "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
      "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
      "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
      "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
      "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
      "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
      "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
      "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
      "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}
CA = {"Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB",
      "New Brunswick": "NB", "Newfoundland and Labrador": "NL", "Nova Scotia": "NS",
      "Ontario": "ON", "Prince Edward Island": "PE", "Quebec": "QC",
      "Saskatchewan": "SK", "Northwest Territories": "NT", "Nunavut": "NU",
      "Yukon Territory": "YT"}

#: Areas craigslist names after a region, a spelling the city database does not
#: share ("st louis" vs "St. Louis", "montreal" vs "Montréal"), or a county. Each
#: maps to the town a person in that area would name as the nearest city.
#: Note the city database writes "Saint", never "St." -- that mismatch ate
#: six of these on the first run -- except St. Louis and St. John's, which
#: the database does abbreviate. It is not consistent; check before guessing.
BY_HAND = {
    "inlandempire": "Riverside, CA", "mohave": "Kingman, AZ", "goldcountry": "Auburn, CA",
    "siskiyou": "Yreka, CA", "kpr": "Kennewick, WA", "cnj": "Edison, NJ",
    "southjersey": "Vineland, NJ", "newjersey": "Newark, NJ", "hudsonvalley": "Poughkeepsie, NY",
    "longisland": "Hempstead, NY", "catskills": "Monticello, NY", "westernmass": "Springfield, MA",
    "capecod": "Barnstable, MA", "southcoast": "New Bedford, MA", "nh": "Manchester, NH",
    "vermont": "Burlington, VT", "maine": "Portland, ME", "delaware": "Wilmington, DE",
    "easternshore": "Salisbury, MD", "westmd": "Cumberland, MD", "esh": "Onley, VA",
    "nwct": "Torrington, CT", "outerbanks": "Kitty Hawk, NC", "wv": "Charleston, WV",
    "easternky": "Pikeville, KY", "westky": "Paducah, KY", "eastnc": "Greenville, NC",
    "thumb": "Bad Axe, MI", "up": "Marquette, MI", "nmi": "Traverse City, MI",
    "northernwi": "Rhinelander, WI", "nd": "Fargo, ND", "smd": "Lexington Park, MD",
    "skagit": "Mount Vernon, WA", "olympic": "Port Angeles, WA", "bigbend": "Alpine, TX",
    "texoma": "Sherman, TX", "bigisland": "Hilo, HI", "kauai": "Lihue, HI",
    "maui": "Kahului, HI", "westslope": "Grand Junction, CO", "highrockies": "Vail, CO",
    "eastco": "Lamar, CO", "swmi": "Kalamazoo, MI", "nwks": "Hays, KS",
    "swks": "Garden City, KS", "semo": "Cape Girardeau, MO", "loz": "Osage Beach, MO",
    "stlouis": "St. Louis, MO", "stcloud": "Saint Cloud, MN", "stjoseph": "Saint Joseph, MO",
    "staugustine": "Saint Augustine, FL", "honolulu": "Honolulu, HI", "providence": "Providence, RI",
    "montreal": "Montréal, QC", "quebec": "Québec, QC", "troisrivieres": "Trois-Rivières, QC",
    "allentown": "Allentown, PA", "fortmyers": "Fort Myers, FL", "quadcities": "Davenport, IA",
    "miami": "Miami, FL", "keys": "Key West, FL", "cfl": "Sebring, FL",
    "spacecoast": "Melbourne, FL", "treasure": "Port Saint Lucie, FL",
    "okaloosa": "Fort Walton Beach, FL", "lakecity": "Lake City, FL",
    "jerseyshore": "Toms River, NJ", "fingerlakes": "Ithaca, NY", "chautauqua": "Jamestown, NY",
    "twintiers": "Elmira, NY", "tricities": "Johnson City, TN", "sd": "Sioux Falls, SD",
    "nesd": "Watertown, SD", "montana": "Helena, MT", "wyoming": "Cheyenne, WY",
    "rockies": "Estes Park, CO", "newlondon": "New London, CT", "juneau": "Juneau, AK",
    "humboldt": "Eureka, CA", "mendocino": "Ukiah, CA", "eastidaho": "Idaho Falls, ID",
    "carbondale": "Carbondale, IL", "quincy": "Quincy, IL", "ottumwa": "Ottumwa, IA",
    "seks": "Pittsburg, KS", "eastky": "Pikeville, KY", "centralmich": "Mount Pleasant, MI",
    "marshall": "Marshall, MN", "northmiss": "Oxford, MS", "natchez": "Natchez, MS",
    "nwga": "Dalton, GA", "enid": "Enid, OK", "eastoregon": "Pendleton, OR",
    "oregoncoast": "Newport, OR", "chambersburg": "Chambersburg, PA",
    "poconos": "Stroudsburg, PA", "nacogdoches": "Nacogdoches, TX", "stgeorge": "Saint George, UT",
    "blacksburg": "Blacksburg, VA", "swva": "Bristol, VA", "martinsburg": "Martinsburg, WV",
    "wheeling": "Wheeling, WV", "swv": "Beckley, WV", "ftmcmurray": "Fort McMurray, AB",
    "abbotsford": "Abbotsford, BC", "kootenays": "Nelson, BC", "skeena": "Terrace, BC",
    "sunshine": "Powell River, BC", "newbrunswick": "Moncton, NB",
    "newfoundland": "St. John's, NL", "territories": "Yellowknife, NT",
    "soo": "Sault Ste. Marie, ON", "sudbury": "Greater Sudbury, ON",
    "pei": "Charlottetown, PE", "porthuron": "Port Huron, MI", "wenatchee": "Wenatchee, WA",
    "brownsville": "Brownsville, TX", "fortsmith": "Fort Smith, AR",
    "kirksville": "Kirksville, MO", "eauclaire": "Eau Claire, WI", "boone": "Boone, NC",
    "susanville": "Susanville, CA", "imperial": "El Centro, CA", "monterey": "Monterey, CA",
    "orangecounty": "Santa Ana, CA", "sfbay": "San Francisco, CA", "kenai": "Kenai, AK",
}

STRIP = re.compile(r"\s+(county|area|peninsula|region|valley|coast|bay|islands?)$", re.I)


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


def rows_from(html: str) -> list[tuple[str, str, str]]:
    """(admin code, slug, display name) for every US and Canadian area."""
    tokens = re.findall(
        r'<h[234][^>]*>([^<]+)</h[234]>'
        r'|href="(?:https?:)?//www\.craigslist\.org/(area/[^"]+)">([^<]+)</a>', html)
    out, region = [], None
    for heading, slug, name in tokens:
        if heading:
            region = heading.strip()
        elif region in US or region in CA:
            out.append(((US.get(region) or CA[region]), slug.split("/", 1)[1], name.strip()))
    return out


def resolve(admin: str, slug: str, name: str, cities):
    if slug in BY_HAND:
        return places.find(BY_HAND[slug], cities)
    # "florence / muscle shoals" names two towns; try each, and try dropping a
    # trailing "county" or "bay area" before giving up on it.
    for part in re.split(r"\s*/\s*|\s+-\s+|-", name):
        part = part.strip()
        while part:
            city = places.find(f"{part}, {admin}", cities)
            if city is not None:
                return city
            shorter = STRIP.sub("", part).strip()
            part = shorter if shorter != part else " ".join(part.split()[:-1])
    return None


def main() -> int:
    cities = places.load_cities()
    resolved, missed, seen = [], [], set()
    for admin, slug, name in rows_from(fetch(SITES_URL)):
        if slug in seen:
            continue
        city = resolve(admin, slug, name, cities)
        if city is None:
            missed.append((slug, name))
            continue
        seen.add(slug)
        resolved.append((slug, f"{city.name}, {admin}", round(city.lat, 4), round(city.lon, 4)))

    dest = Path(__file__).resolve().parent / "craigslist_areas.csv.gz"
    with gzip.open(dest, "wt", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["slug", "label", "lat", "lon"])
        writer.writerows(sorted(resolved))

    print(f"{len(resolved)} areas -> {dest} ({dest.stat().st_size} bytes)")
    if missed:
        print(f"{len(missed)} unmatched, add to BY_HAND if they matter:")
        for slug, name in missed:
            print(f"  {slug:16} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
