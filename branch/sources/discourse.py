"""Discourse forums -- any of them.

Discourse powers a great many community and trade forums and exposes an open
search endpoint at `/search.json?q=`. No key, no account.

Which forums to read is a per-trade question, so it is answered in the trade
profile:

    forums:
      - https://forum.example.com

plus anything in ~/.config/branch/forums.txt, one URL per line. A forum a plumber
cares about is not one a wedding photographer does, and the profile is already
where that kind of knowledge lives.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from pathlib import Path

from .. import resources
from ..locate import cache_path
from ..models import Item
from .base import Fetched, Query, Source

USER_AGENT = "Branch/0.1 (local demand radar; single-user desktop app)"
TIMEOUT = 10.0


def profile_sites(root: Path | None = None) -> list[str]:
    """Every forum any bundled trade profile names.

    Availability is asked before a trade is chosen, so it cannot ask "does *this*
    trade have forums?". It asks the weaker, answerable question instead: does
    this install know about any forums at all? A trade that turns out to name
    none says so for that scan, which is the honest place to say it.

    Without this the toggle reported "no forums set" while two profiles shipped
    with working forums in them -- the source was usable and the window said it
    was not.
    """
    try:
        from ..profile import Profile
        base = root or resources.profiles()
        return [site for profile in Profile.load_all(base).values()
                for site in (getattr(profile, "forums", None) or [])]
    except Exception:
        return []          # a broken profile must not make the source vanish


def configured_sites() -> list[str]:
    path = cache_path().parent / "forums.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip().rstrip("/") for line in lines
            if line.strip() and not line.strip().startswith("#")
            and line.strip().startswith("http")]


class Discourse(Source):
    key = "forums"
    label = "Forums"
    description = ("Discussion forums that run on Discourse, searched through their public"
                   " API. Which forums comes from the trade profile.")
    short_reason = "no forums set"
    cost_per_scan = 0.0
    geographic = False        # a city forum would be; we cannot know which

    def available(self) -> str | None:
        if not configured_sites() and not profile_sites():
            return ("no trade profile names a forum, and there is nothing in "
                    f"{cache_path().parent / 'forums.txt'} -- one URL per line")
        return None

    def available_for(self, profile) -> str | None:
        """This trade's forums, not any trade's.

        A user who picks Graphic Designer and sees Forums ticked has been told
        it will read something. It will not: no graphic design profile names a
        forum, and the toggle said "ready" because two unrelated trades do.
        """
        if configured_sites() or (getattr(profile, "forums", None) or []):
            return None
        return (f"{profile.name} names no forum, and there is nothing in "
                f"{cache_path().parent / 'forums.txt'} -- one URL per line")

    def fetch(self, query: Query) -> Fetched:
        sites = list(dict.fromkeys(list(query.forums or []) + configured_sites()))
        if not sites:
            return self._unavailable(self.available() or "no forums configured")

        terms = ([query.narrow] if query.narrow else []) + list(query.terms or [])
        terms = [t for t in terms if t][:3]
        if not terms:
            return self._unavailable("nothing to search for -- choose a trade")

        cutoff = datetime.now(timezone.utc).timestamp() - query.since_hours * 3600
        items: dict[str, Item] = {}
        result = Fetched()
        reached = 0

        for site in sites:
            host = site.split("//", 1)[-1].split("/", 1)[0]
            ok = False
            for term in terms:
                # Discourse ranks by relevance by default, which returns mostly
                # old threads -- almost all of them outside any useful time
                # window. "order:latest" is the documented in-query modifier.
                params = urllib.parse.urlencode({"q": f"{term} order:latest"})
                request = urllib.request.Request(
                    f"{site}/search.json?{params}",
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                try:
                    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                except Exception:
                    continue
                ok = True
                topics = {t["id"]: t for t in payload.get("topics", []) if "id" in t}
                for post in payload.get("posts", []):
                    published = _when(post.get("created_at"))
                    if published is None or published.timestamp() < cutoff:
                        continue
                    post_id = str(post.get("id", ""))
                    topic = topics.get(post.get("topic_id"), {})
                    if not post_id:
                        continue
                    items[f"{host}:{post_id}"] = Item(
                        id=f"forum:{host}:{post_id}",
                        text=post.get("blurb") or "",
                        title=topic.get("title") or None,
                        url=f"{site}/t/{post.get('topic_id')}/{post.get('post_number', 1)}",
                        venue=f"forum:{host}",
                        posted_at=published,
                        author=post.get("username"),
                    )
            if ok:
                reached += 1
            else:
                result.notes.append(f"{host}: not reachable, or not a Discourse forum")

        if reached == 0:
            return self._unavailable("none of the configured forums could be read")
        result.items = list(items.values())
        result.notes.insert(0, f"searched {reached} of {len(sites)} forums")
        return result


def _when(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
