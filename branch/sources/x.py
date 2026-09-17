"""X, through the user's own browser.

THE PRICE DOES NOT APPLY HERE. X charges about $0.005 per post read through its
**API**, which is a separate product. Reading the site in a browser is not the
API and never touches it, so there is nothing being bypassed -- the site is free
to read once you have an account, the way it is for anyone.

What does apply is the same trade as Facebook: X's terms forbid automated access,
and the cost of crossing that line is the user's own account rather than a bill.
X enforces more aggressively than Meta does. So this is attended, paced, capped
and never runs unwatched, exactly like ui/browser.py's other targets.

GEOGRAPHY: I WAS WRONG. I claimed `near:"Dallas" within:25mi` made this the only
free-text source with a real radius. **Tested signed in, those operators return
an explicit "No results" for every query** -- including ones that return results
without them. X has retired geo search, so the operators do not narrow a search,
they empty it. They are gone from the URL; leaving them in would have made every
X scan return nothing while looking like it worked.

So X is **not** geographic. Locality has to come from the words in the post, the
same as Facebook post search.
"""
from __future__ import annotations

import urllib.parse

from .base import Query
from .facebook import _Interactive


def search_urls(query: Query) -> list[tuple[str, str]]:
    """(url, label) per phrasing, each restricted to the search area.

    `f=live` sorts by newest rather than by engagement, which matters: the
    default ranking surfaces popular old posts, and a lead that is a month old
    has already hired someone.

    The city goes in as a plain word, not as `near:`/`within:` -- see the module
    docstring for why.
    """
    city = query.location.split(",")[0].strip()
    asks = [a for a in (query.asks or ([query.ask] if query.ask else [])) if a]
    urls = []
    for ask in asks:
        phrase = f'"{ask}"'
        if query.narrow:
            phrase = f"{phrase} {query.narrow}"
        params = urllib.parse.urlencode({"q": f"{phrase} {city}".strip(), "f": "live"})
        urls.append((f"https://x.com/search?{params}", ask))
    return urls


class X(_Interactive):
    key = "x"
    label = "X / Twitter"
    description = ("Public posts on X, searched by city. Needs an X account, and a "
                   "new one may have search restricted until it is established.")
    cost_per_scan = 0.0        # the browser is not the API; see the module docstring
    geographic = False         # geo operators are retired; see the docstring
    login_service = "X"        # not Facebook's, despite the shared base class
    login_url = "https://x.com/login"

    def url(self, query: Query) -> str:
        found = search_urls(query)
        return found[0][0] if found else "https://x.com/explore"

    def urls(self, query: Query) -> list[tuple[str, str]]:
        return search_urls(query)
