"""Lemmy -- the federated Reddit-alike.

Open API, no account, no key. Its communities are far smaller than Reddit's, so
volume is low, but it costs one request and it is one of the few places a
Reddit-shaped conversation happens outside Reddit.

Not geographic: Lemmy's local communities exist but are thin, so this searches by
term across an instance rather than pretending to honour a radius.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..models import Item
from .base import Fetched, Query, Source

INSTANCES = ["https://lemmy.world", "https://lemm.ee"]
USER_AGENT = "Branch/0.1 (local demand radar; single-user desktop app)"
TIMEOUT = 10.0


class Lemmy(Source):
    key = "lemmy"
    label = "Lemmy"
    cost_per_scan = 0.0
    geographic = False

    def available(self) -> str | None:
        return None

    def fetch(self, query: Query) -> Fetched:
        terms = ([query.narrow] if query.narrow else []) + list(query.terms or [])
        terms = [t for t in terms if t][:4]
        if not terms:
            return self._unavailable("nothing to search for -- choose a trade")

        cutoff = datetime.now(timezone.utc).timestamp() - query.since_hours * 3600
        items: dict[str, Item] = {}
        reached = False

        for instance in INSTANCES:
            for term in terms:
                params = urllib.parse.urlencode({
                    "q": term, "type_": "Posts", "sort": "New", "limit": 25})
                request = urllib.request.Request(
                    f"{instance}/api/v3/search?{params}",
                    headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                except Exception:
                    continue
                reached = True
                for entry in payload.get("posts", []):
                    post = entry.get("post", {})
                    published = _when(post.get("published"))
                    if published is None or published.timestamp() < cutoff:
                        continue
                    post_id = str(post.get("id", ""))
                    if not post_id:
                        continue
                    community = (entry.get("community") or {}).get("name", "lemmy")
                    items[post_id] = Item(
                        id=f"lemmy:{post_id}",
                        text=post.get("body") or "",
                        title=post.get("name") or None,
                        url=post.get("ap_id") or f"{instance}/post/{post_id}",
                        venue=f"lemmy:{community}",
                        posted_at=published,
                        author=(entry.get("creator") or {}).get("name"),
                    )
            if reached:
                break        # one instance federates most of the content anyway

        if not reached:
            return self._unavailable("could not reach any Lemmy instance")
        return Fetched(items=list(items.values()),
                       notes=["Lemmy is worldwide -- no radius applied"])


def _when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
