"""Hacker News, through the Algolia search API.

Free, unauthenticated, no account, generous limits -- the only source reachable
with no credentials at all, which is why it is the first one wired.

Its weakness is stated rather than papered over: **HN has no geography.** There is
no radius to honour, so a scan here is worldwide. That makes it useful for trades
whose customers are online anyway (IT support, dev services) and close to useless
for a plumber. `geographic = False` is how the UI knows to say so.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..models import Item
from .base import Fetched, Query, Source

ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
USER_AGENT = "Branch/0.1 (local demand radar; single-user desktop app)"
TIMEOUT = 8.0
PER_TERM = 25


class HackerNews(Source):
    key = "hackernews"
    label = "Hacker News"
    cost_per_scan = 0.0
    geographic = False

    def available(self) -> str | None:
        return None      # no credentials, nothing to check

    def fetch(self, query: Query) -> Fetched:
        terms = [t for t in (query.terms or []) if t][:6]
        if query.narrow:
            terms = [query.narrow] + terms
        if not terms:
            return self._unavailable("nothing to search for -- choose a trade")

        cutoff = int(datetime.now(timezone.utc).timestamp() - query.since_hours * 3600)
        items: dict[str, Item] = {}
        failures = 0

        for term in terms:
            params = urllib.parse.urlencode({
                "query": term,
                "tags": "(story,comment)",
                "numericFilters": f"created_at_i>{cutoff}",
                "hitsPerPage": PER_TERM,
            })
            try:
                request = urllib.request.Request(f"{ENDPOINT}?{params}",
                                                 headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception:
                failures += 1
                continue

            for hit in payload.get("hits", []):
                text = hit.get("comment_text") or hit.get("story_text") or ""
                title = hit.get("title") or hit.get("story_title") or ""
                object_id = str(hit.get("objectID", ""))
                if not object_id or (not text and not title):
                    continue
                created = hit.get("created_at_i")
                if created is None:
                    continue
                items[object_id] = Item(
                    id=f"hn:{object_id}",
                    text=_strip_html(text),
                    title=title or None,
                    url=f"https://news.ycombinator.com/item?id={object_id}",
                    venue="hackernews",
                    posted_at=datetime.fromtimestamp(int(created), tz=timezone.utc),
                    author=hit.get("author"),
                )

        result = Fetched(items=list(items.values()))
        if failures == len(terms):
            return self._unavailable("could not reach Hacker News")
        if failures:
            result.notes.append(f"{failures} of {len(terms)} searches failed")
        result.notes.append("Hacker News is worldwide -- no radius applied")
        return result


def _strip_html(text: str) -> str:
    """Algolia returns comment bodies as HTML fragments."""
    import html
    import re
    text = re.sub(r"<p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()
