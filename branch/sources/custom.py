"""Any feed you point it at.

The fixed adapters cover the venues Branch knows about. This one covers the rest:
a town's Discourse forum, a trade forum, another subreddit, a local news site, a
classifieds feed -- anything that publishes Atom or RSS.

It is the answer to "my customers hang out somewhere you have never heard of",
and it needs no key, no account and no code change. Put one URL per line in

    ~/.config/branch/feeds.txt

Lines starting with # are ignored. A `name = url` line labels the venue.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..locate import cache_path
from ..models import Item
from .base import Fetched, Query, Source
from .feeds import FeedCache, RateLimited, fetch as fetch_feed, parse as parse_feed


def config_path():
    return cache_path().parent / "feeds.txt"


def configured_feeds() -> list[tuple[str, str]]:
    """(label, url) pairs from the user's feed list."""
    try:
        raw = config_path().read_text(encoding="utf-8")
    except OSError:
        return []
    feeds: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and not line.split("=", 1)[1].strip().startswith("//"):
            label, _, url = line.partition("=")
            label, url = label.strip(), url.strip()
        else:
            label, url = "", line
        if url.startswith(("http://", "https://")):
            feeds.append((label or _label_from(url), url))
    return feeds


def _label_from(url: str) -> str:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    return host.replace("www.", "")


class CustomFeeds(Source):
    key = "feeds"
    label = "My feeds"
    short_reason = "no feeds set"
    cost_per_scan = 0.0
    geographic = False        # whatever the user pointed it at; we cannot know

    def __init__(self) -> None:
        self._cache = FeedCache(90.0)

    def available(self) -> str | None:
        if not configured_feeds():
            return f"add one feed URL per line to {config_path()}"
        return None

    def fetch(self, query: Query) -> Fetched:
        feeds = configured_feeds()
        if not feeds:
            return self._unavailable(self.available() or "no feeds configured")

        cutoff = datetime.now(timezone.utc).timestamp() - query.since_hours * 3600
        items: list[Item] = []
        result = Fetched()
        read = 0

        for label, url in feeds:
            try:
                body = fetch_feed(url, self._cache)
            except RateLimited:
                result.notes.append(f"{label}: rate-limited, skipped")
                continue
            except Exception:
                result.notes.append(f"{label}: could not be read")
                continue

            entries = parse_feed(body)
            if not entries:
                result.notes.append(f"{label}: no entries -- is it a feed?")
                continue
            read += 1
            items.extend(
                Item(id=f"feed:{label}:{e.id}", text=e.body, title=e.title or None,
                     url=e.url, venue=f"feed:{label}",
                     posted_at=e.published, author=e.author)
                for e in entries if e.published.timestamp() >= cutoff
            )

        if read == 0:
            return self._unavailable("none of your feeds could be read")
        result.items = items
        result.notes.insert(0, f"read {read} of {len(feeds)} feeds")
        return result
