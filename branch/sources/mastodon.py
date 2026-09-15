"""Mastodon -- public hashtag timelines.

No account, no key: an instance's public tag timeline is open to anyone. Branch
reads tags derived from the trade's own vocabulary, which is why a profile's
`suggestions:` list doubles as its tag list.

Not geographic. Some instances are city- or region-based and those would be
genuinely local, which is what `~/.config/branch/mastodon.txt` is for -- one
instance URL per line, replacing the defaults.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ..locate import cache_path
from ..models import Item
from .base import Fetched, Query, Source
from .feeds import _text as strip_tags

DEFAULT_INSTANCES = ["https://mastodon.social"]
USER_AGENT = "Branch/0.1 (local demand radar; single-user desktop app)"
TIMEOUT = 10.0


def instances() -> list[str]:
    path = cache_path().parent / "mastodon.txt"
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return DEFAULT_INSTANCES
    chosen = [line for line in lines
              if line and not line.startswith("#") and line.startswith("http")]
    return chosen or DEFAULT_INSTANCES


def _tag(term: str) -> str:
    """"water heater" -> "waterheater". Tags carry no spaces or punctuation."""
    return re.sub(r"[^a-z0-9]", "", term.lower())


class Mastodon(Source):
    key = "mastodon"
    label = "Mastodon"
    cost_per_scan = 0.0
    geographic = False

    def available(self) -> str | None:
        return None

    def fetch(self, query: Query) -> Fetched:
        terms = ([query.narrow] if query.narrow else []) + list(query.terms or [])
        tags = [t for t in dict.fromkeys(_tag(x) for x in terms) if len(t) > 3][:5]
        if not tags:
            return self._unavailable("nothing to search for -- choose a trade")

        cutoff = datetime.now(timezone.utc).timestamp() - query.since_hours * 3600
        items: dict[str, Item] = {}
        reached = False

        for instance in instances():
            for tag in tags:
                params = urllib.parse.urlencode({"limit": 25})
                request = urllib.request.Request(
                    f"{instance}/api/v1/timelines/tag/{urllib.parse.quote(tag)}?{params}",
                    headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                except Exception:
                    continue
                reached = True
                for status in payload if isinstance(payload, list) else []:
                    published = _when(status.get("created_at"))
                    if published is None or published.timestamp() < cutoff:
                        continue
                    status_id = str(status.get("id", ""))
                    body = strip_tags(status.get("content") or "")
                    if not status_id or not body:
                        continue
                    account = status.get("account") or {}
                    items[status_id] = Item(
                        id=f"mastodon:{status_id}", text=body, title=None,
                        url=status.get("url") or "",
                        venue=f"mastodon:#{tag}", posted_at=published,
                        author=account.get("acct"),
                    )

        if not reached:
            return self._unavailable("could not reach any Mastodon instance")
        return Fetched(items=list(items.values()),
                       notes=[f"read #{', #'.join(tags)}"])


def _when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
