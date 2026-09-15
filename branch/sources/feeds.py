"""Atom/RSS reading, shared by every feed-backed source.

Feeds are the workhorse here. They need no key, no account and no contract, and a
great many of the venues that matter -- local subreddits, Discourse forums, news
and classifieds sites -- publish one. Reading a public feed is what a feed reader
does; it is the least intrusive way to see what a place is posting.

Nothing is written to disk. Responses are held in memory for the life of the
process only, purely to avoid asking a server the same question twice in a minute.
"""
from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

USER_AGENT = "Branch/0.1 (local demand radar; single-user desktop app)"
TIMEOUT = 12.0

ATOM = "{http://www.w3.org/2005/Atom}"
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")


class RateLimited(Exception):
    """The server said slow down. Not an error to hide -- one to report."""


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    body: str
    url: str
    author: str | None
    published: datetime


class FeedCache:
    """In-memory only, and deliberately so.

    Reddit rate-limits anonymous feed reads to roughly one request a minute per
    address, so asking twice inside a scan is both rude and pointless. This never
    touches the filesystem: Branch does not keep what it reads.
    """

    def __init__(self, ttl_seconds: float = 90.0) -> None:
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, str]] = {}

    def get(self, url: str) -> str | None:
        hit = self._store.get(url)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        return None

    def put(self, url: str, body: str) -> None:
        self._store[url] = (time.monotonic(), body)


def fetch(url: str, cache: FeedCache | None = None) -> str:
    if cache is not None:
        cached = cache.get(url)
        if cached is not None:
            return cached
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimited(str(url)) from exc
        raise
    if cache is not None:
        cache.put(url, body)
    return body


def _text(raw: str | None) -> str:
    if not raw:
        return ""
    stripped = _TAGS.sub(" ", raw)
    return _WS.sub(" ", html.unescape(stripped)).strip()


def _when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    value = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                parsed = datetime.strptime(raw.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse(xml: str) -> list[Entry]:
    """Read either Atom or RSS 2.0. Malformed feeds yield nothing, never raise."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    entries: list[Entry] = []
    for node in root.iter(f"{ATOM}entry"):
        link = node.find(f"{ATOM}link")
        published = _when((node.findtext(f"{ATOM}published")
                           or node.findtext(f"{ATOM}updated")))
        if published is None:
            continue
        entries.append(Entry(
            id=node.findtext(f"{ATOM}id") or (link.get("href") if link is not None else ""),
            title=_text(node.findtext(f"{ATOM}title")),
            body=_text(node.findtext(f"{ATOM}content") or node.findtext(f"{ATOM}summary")),
            url=link.get("href", "") if link is not None else "",
            author=_text(node.findtext(f"{ATOM}author/{ATOM}name")) or None,
            published=published,
        ))

    for node in root.iter("item"):
        published = _when(node.findtext("pubDate") or node.findtext("date"))
        if published is None:
            continue
        entries.append(Entry(
            id=node.findtext("guid") or node.findtext("link") or "",
            title=_text(node.findtext("title")),
            body=_text(node.findtext("description")),
            url=(node.findtext("link") or "").strip(),
            author=_text(node.findtext("author")) or None,
            published=published,
        ))
    return entries
