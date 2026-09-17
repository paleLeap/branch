"""Facebook: Marketplace and post search, through the user's own browser.

Interactive rather than fetched. Everything else in `sources/` answers `fetch()`
on a worker thread; this one cannot, because the only way in is a logged-in
browser session and that lives on the UI thread. So it declares `interactive`,
the runner skips it, and the window opens `ui/browser.py` instead.

WHAT AN ACCOUNT DOES AND DOES NOT CHANGE. Logged out, Marketplace returns HTTP
400 -- no content at all -- and robots.txt disallows everything. An account makes
the content visible. It does not make bulk automated collection permitted, and
the account carrying that risk is the user's own. Hence: attended, paced, capped,
and never running unwatched. See ui/browser.py.

Marketplace is the strongest geography Branch has access to anywhere: a real
radius, 1-500 miles, geocoded, filtered on seller location. Nothing else offers
that.
"""
from __future__ import annotations

import urllib.parse

from .base import Fetched, Query, Source

MILES_TO_KM = 1.609


def city_slug(location: str) -> str:
    """"Fort Worth, TX" -> "fortworth", which is what Marketplace's paths use."""
    city = location.split(",")[0].strip().lower()
    return "".join(ch for ch in city if ch.isalnum())


def marketplace_url(query: Query) -> str:
    terms = ([query.narrow] if query.narrow else []) + list(query.terms or [])
    term = terms[0] if terms else ""
    slug = city_slug(query.location) or "search"
    params = urllib.parse.urlencode({
        "query": term,
        "radius_km": int(round(query.radius_miles * MILES_TO_KM)),
        "sortBy": "creation_time_descend",
    })
    return f"https://www.facebook.com/marketplace/{slug}/search?{params}"


def posts_url(query: Query) -> str:
    """Facebook post search -- the best lead source Branch has found anywhere.

    A correction worth keeping: /search/ paths appear to 404 and I concluded they
    were dead. They are not. **Signed out, every Facebook path returns "Not
    Found"; signed in, search works normally.** The 404 was the missing session,
    not a missing endpoint.

    The query is how customers *ask* -- "need a plumber" -- plus the city, rather
    than the trade's vocabulary. Searching "water heater" finds people discussing
    water heaters; searching "need a plumber Dallas" finds people who want one.
    """
    return posts_urls(query)[0][0]


def posts_urls(query: Query) -> list[tuple[str, str]]:
    """(url, label) for every way this trade's customers ask.

    One search returns about four results and then stops growing, so depth comes
    from asking several questions rather than scrolling one answer harder.
    """
    city = query.location.split(",")[0].strip()
    asks = [a for a in (query.asks or [query.ask] or [""]) if a]
    out = []
    for ask in asks:
        phrase = f"{ask} {query.narrow}".strip() if query.narrow else ask
        params = urllib.parse.urlencode({"q": f"{phrase} {city}".strip()})
        out.append((f"https://www.facebook.com/search/posts?{params}", phrase))
    return out


class _Interactive(Source):
    """Base for sources that need the user and a browser, not a thread."""

    interactive = True
    login_service = "Facebook"
    # The plain login page rather than a deep link: it is the page the user
    # already knows, and it is Facebook's own form. Branch never sees what is
    # typed into it -- see ui/browser.py.
    login_url = "https://www.facebook.com/login"

    def available(self) -> str | None:
        return None

    def fetch(self, query: Query) -> Fetched:
        # The runner never calls this for interactive sources; if something does,
        # say why rather than returning a silent nothing.
        return self._unavailable(
            "opens in a browser window -- it cannot run on its own")


class Marketplace(_Interactive):
    key = "marketplace"
    label = "Marketplace"
    description = ("Facebook Marketplace listings within a real radius -- the only source "
                   "with true distance. Works without signing in.")
    geographic = True          # a real radius, unlike anything else wired
    # Alone among the Facebook surfaces, this one serves a logged-out visitor --
    # checked, and the source of a confusing symptom once: Marketplace kept
    # returning results while search and groups returned a bare "Not Found",
    # which read like a broken URL rather than a missing session. So it is not
    # marked as needing a sign-in, because it does not.
    login_service = ""
    login_url = ""

    def url(self, query: Query) -> str:
        return marketplace_url(query)


class FacebookPosts(_Interactive):
    key = "facebook"
    label = "Facebook"
    description = ("Public Facebook posts matching what your trade's customers ask, "
                   "searched by city. Needs a Facebook account.")
    geographic = False         # tagged-location only; most posts carry no tag

    def url(self, query: Query) -> str:
        return posts_url(query)

    def urls(self, query: Query) -> list[tuple[str, str]]:
        return posts_urls(query)


def group_discovery_urls(query: Query) -> list[str]:
    """Where to look for groups worth reading.

    Searching "<city> <trade>" alone finds **contractor** groups -- full of
    tradesmen advertising, which is the supply side, not the demand side. A live
    run returned five such groups and zero leads. The groups that actually carry
    requests are the neighbourhood and homeowner ones, so both are searched.
    """
    city = query.location.split(",")[0].strip()
    trade = query.trade.replace("-", " ")
    wanted = [f"{city} {trade}", f"{city} homeowners",
              f"{city} recommendations", f"{city} community"]
    return [f"https://www.facebook.com/search/groups?"
            + urllib.parse.urlencode({"q": q.strip()}) for q in wanted if q.strip()]


def group_discovery_url(query: Query) -> str:
    return group_discovery_urls(query)[0]


class FacebookGroups(_Interactive):
    """Local groups, found and then read.

    The best-shaped route into Facebook that Branch has, for three reasons
    checked live rather than assumed:

      * a public group's feed is readable **without joining**;
      * it carries real `/groups/<id>/posts/<id>/` permalinks, so leads from here
        can actually be opened -- unlike search results, which carry none at all;
      * both of the strongest leads found so far came from groups.

    It discovers the groups itself, so it does not depend on the user having
    joined anything.
    """

    key = "groups"
    label = "FB Groups"
    description = ("Local Facebook groups -- Branch finds them and reads them without "
                   "joining. The only Facebook route whose posts have real links.")
    geographic = True          # a DFW group is a place, in a way a search is not

    def url(self, query: Query) -> str:
        return group_discovery_url(query)

    def urls(self, query: Query) -> list[tuple]:
        # "discover" marks these as lists of groups rather than lists of posts:
        # the browser turns what it finds into the feeds to read next.
        return [(url, f"finding groups ({url.split('q=')[-1][:28]})", "discover")
                for url in group_discovery_urls(query)]
