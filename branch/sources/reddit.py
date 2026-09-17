"""Reddit, through the official API with the user's own account.

ACCESS, because this is the part that keeps changing, and the earlier note here
was wrong. `/r/x/new.json` returns 403 to anonymous clients -- but **`/r/x/new.rss`
returns 200**. The public feed is still open; only the JSON API was closed. So
Branch works out of the box with no account at all, and gets better with one.

Two paths, in order:

  1. **Feed** (no credentials). Read `r/<City>/new.rss` -- the whole venue, up to
     100 posts -- and let the engine classify it. This is the container model
     exactly: locality comes from the subreddit, relevance from the profile. No
     search endpoint is involved, so nothing is lost by not having one.
     Anonymous feed reads are limited to roughly **one request per minute per
     address**, measured. One request per scan is within that; a 429 is reported,
     not hidden.
  2. **OAuth** (the user's own app). Adds search, so several terms can be queried
     across a longer window, with far better limits.

Under bring-your-own-account the OAuth client is the *user's*, registered against
their own account, which keeps a tool given to friends inside the free tier's
non-commercial terms.

Register one at https://www.reddit.com/prefs/apps (type: "script"), then either

    export BRANCH_REDDIT_CLIENT_ID=... BRANCH_REDDIT_CLIENT_SECRET=...

or write ~/.config/branch/reddit.json with {"client_id": "...", "client_secret": "..."}.

LOCALITY. Locality lives in the container, not the content: people post inside a
local subreddit and describe the problem without naming the city. So this adapter
searches r/<City>, not the whole site for city names.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .. import places
from ..locate import cache_path
from ..models import Item
from .base import Fetched, Query, Source
from .feeds import FeedCache, RateLimited, fetch as fetch_feed, parse as parse_feed

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
USER_AGENT = "python:branch:0.1 (local demand radar, single-user desktop app)"
TIMEOUT = 10.0
PER_TERM = 25


def credentials() -> tuple[str, str] | None:
    cid = os.environ.get("BRANCH_REDDIT_CLIENT_ID", "").strip()
    secret = os.environ.get("BRANCH_REDDIT_CLIENT_SECRET", "").strip()
    if cid and secret:
        return cid, secret
    config = cache_path().parent / "reddit.json"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
        cid, secret = str(data["client_id"]).strip(), str(data["client_secret"]).strip()
        return (cid, secret) if cid and secret else None
    except Exception:
        return None


def _subreddit_name(city: str) -> str:
    """r/FortWorth from "Fort Worth". Reddit corrects the casing itself."""
    return "".join(part for part in city.split() if part.isalnum() or part)


def subreddits_for(location: str) -> list[str]:
    """Local subreddit names for a "Dallas, TX" style label."""
    city = location.split(",")[0].strip()
    if not city:
        return []
    squashed = _subreddit_name(city)
    return [n for n in dict.fromkeys([squashed, squashed.lower()]) if n]


def subreddits_in_radius(query: Query, limit: int = 8) -> list[str]:
    """Every town inside the radius, as subreddit names.

    A multireddit -- r/Dallas+FortWorth+plano -- returns all of them in **one**
    request, which matters enormously: anonymous feed reads are limited to about
    one a minute, so asking per town would take a minute per town. This is what
    makes the radius control mean something on Reddit.
    """
    primary = subreddits_for(query.location)
    if query.coordinates is None:
        return primary[:1]

    towns = places.nearby(query.coordinates[0], query.coordinates[1],
                          query.radius_miles * 1.609, limit=limit)
    names: list[str] = list(primary[:1])
    for town in towns:
        name = _subreddit_name(town.name)
        if name and name.lower() not in {n.lower() for n in names}:
            names.append(name)
    return names[:limit]


def _venue_of(url: str, fallback: str) -> str:
    """Pull the real subreddit out of a permalink, since a multireddit mixes them."""
    match = re.search(r"/r/([^/]+)/", url or "")
    return f"reddit:r/{match.group(1) if match else fallback}"


class Reddit(Source):
    key = "reddit"
    label = "Reddit"
    description = ("Local subreddits inside your radius, read from Reddit's public feeds. "
                   "No account needed.")
    cost_per_scan = 0.0        # free tier, non-commercial, user's own client
    geographic = True

    #: Anonymous feed reads are ~1/minute per address. Holding the response for
    #: 90s means a re-run after tuning does not trip the limit. Memory only.
    FEED_LIMIT = 100
    #: Anonymous reads allow about one a minute; measured, not assumed.
    SPACING_SECONDS = 22

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires = 0.0
        self._cache = FeedCache(90.0)

    def available(self) -> str | None:
        return None      # the public feed needs nothing; OAuth is an upgrade

    def mode(self) -> str:
        return "search" if credentials() is not None else "feed"

    def _authenticate(self) -> str | None:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        creds = credentials()
        if creds is None:
            return None
        basic = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        request = urllib.request.Request(
            TOKEN_URL, data=body,
            headers={"Authorization": f"Basic {basic}", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        self._token = payload.get("access_token")
        self._token_expires = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    def fetch(self, query: Query) -> Fetched:
        subs = subreddits_in_radius(query)
        if not subs:
            return self._unavailable("set a location first")

        if credentials() is None:
            return self._fetch_feed(query, subs)

        token = self._authenticate()
        if token is None:
            return self._unavailable("Reddit rejected those credentials")
        return self._fetch_search(query, subs, token)

    # -- feed: no credentials, whole venue, classified locally ---------------

    def _fetch_feed(self, query: Query, subs: list[str]) -> Fetched:
        """Three streams, not one.

        The multireddit of new *posts* was all this read, and it caps at 100 items
        across every town -- a few hours of a busy metro. Two more are open:

          * the **comments** feed, `r/a+b+c/comments/.rss`, which is a hundred
            more items and is where "anyone know a good plumber?" usually lives,
            since it is a reply far more often than a post;
          * **search**, `search.rss`, which reaches beyond the newest hundred and
            beyond the local subreddits entirely.

        Anonymous reads are limited to roughly one a minute, measured, so these
        are spaced and any 429 is waited out rather than dropped.
        """
        cutoff = datetime.now(timezone.utc).timestamp() - query.since_hours * 3600
        multi = "+".join(subs)
        limit = self.FEED_LIMIT

        streams: list[tuple[str, str]] = [
            (f"https://www.reddit.com/r/{multi}/new.rss?limit={limit}", "new posts"),
            (f"https://www.reddit.com/r/{multi}/comments/.rss?limit={limit}", "comments"),
        ]
        city = query.location.split(",")[0].strip()
        # Only two here: each is a round trip at roughly one a minute. Facebook
        # is where extra phrasings are cheap, so that is where they are spent.
        for ask in (query.asks or ([query.ask] if query.ask else []))[:2]:
            phrase = urllib.parse.quote(f'"{ask}" {city}'.strip())
            streams.append((
                f"https://www.reddit.com/search.rss?q={phrase}&sort=new&t=month&limit=50",
                f'search "{ask}"'))

        items: dict[str, Item] = {}
        result = Fetched()
        reached = 0

        for index, (url, label) in enumerate(streams):
            if index:
                time.sleep(self.SPACING_SECONDS)
            body = self._fetch_patiently(url)
            if body is None:
                result.notes.append(f"{label}: rate-limited, skipped")
                continue
            entries = parse_feed(body)
            if not entries:
                continue
            reached += 1
            for e in entries:
                if e.published.timestamp() < cutoff:
                    continue
                items[e.id] = Item(
                    id=f"reddit:{e.id}", text=e.body, title=e.title or None,
                    url=e.url, venue=_venue_of(e.url, subs[0]),
                    posted_at=e.published, author=e.author)

        if reached == 0:
            return self._unavailable(
                "Reddit is rate-limiting anonymous reads -- wait a minute, or add "
                "a Reddit app for higher limits")

        covered = sorted({i.venue.split("r/")[-1] for i in items.values()})
        result.items = list(items.values())
        result.notes.append(
            f"read {reached} of {len(streams)} streams across {len(covered)} "
            f"subreddits ({len(result.items)} inside the time window)")
        return result

    def _fetch_patiently(self, url: str) -> str | None:
        """One retry after a rate limit, then give up and say so."""
        for attempt in range(2):
            try:
                return fetch_feed(url, self._cache)
            except RateLimited:
                if attempt == 0:
                    time.sleep(self.SPACING_SECONDS)
            except Exception:
                return None
        return None

    # -- search: with the user's own app -------------------------------------

    def _fetch_search(self, query: Query, subs: list[str], token: str) -> Fetched:
        terms = ([query.narrow] if query.narrow else []) + list(query.terms or [])
        terms = [t for t in terms if t][:4]
        if not terms:
            return self._unavailable("nothing to search for -- choose a trade")

        window = "day" if query.since_hours <= 24 else (
            "week" if query.since_hours <= 168 else "month")
        cutoff = datetime.now(timezone.utc).timestamp() - query.since_hours * 3600

        items: dict[str, Item] = {}
        reached: list[str] = []
        for sub in subs:
            for term in terms:
                hits, ok = self._search(token, sub, term, window)
                if ok and sub not in reached:
                    reached.append(sub)
                for raw in hits:
                    data = raw.get("data", {})
                    created = float(data.get("created_utc") or 0)
                    if created < cutoff:
                        continue
                    name = data.get("name") or data.get("id")
                    if not name:
                        continue
                    items[name] = Item(
                        id=f"reddit:{name}",
                        text=data.get("selftext") or "",
                        title=data.get("title") or None,
                        url="https://www.reddit.com" + data.get("permalink", ""),
                        venue=f"reddit:r/{data.get('subreddit', sub)}",
                        posted_at=datetime.fromtimestamp(created, tz=timezone.utc),
                        author=data.get("author"),
                    )
            if reached:
                break            # first spelling that exists is the right one

        if not reached:
            return self._unavailable(
                f"no subreddit found for {query.location.split(',')[0].strip()}")

        result = Fetched(items=list(items.values()))
        result.notes.append(f"searched r/{reached[0]} with your Reddit app")
        return result

    def _search(self, token: str, sub: str, term: str, window: str) -> tuple[list, bool]:
        params = urllib.parse.urlencode({
            "q": term, "restrict_sr": "1", "sort": "new",
            "t": window, "limit": PER_TERM, "type": "link",
        })
        request = urllib.request.Request(
            f"{API}/r/{sub}/search?{params}",
            headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return [], False
        return payload.get("data", {}).get("children", []), True
