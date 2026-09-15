"""Which sources exist, and what to say about the ones that do not.

Every toggle in the window appears here. A source that is not built yet reports
that plainly rather than being absent from the UI or silently returning nothing --
the user must always be able to answer "what didn't you look at, and why?".
"""
from __future__ import annotations

from .base import Source
from .craigslist import Craigslist
from .custom import CustomFeeds
from .discourse import Discourse
from .facebook import FacebookGroups, FacebookPosts, Marketplace
from .reddit import Reddit
from .x import X


class NotBuilt(Source):
    """A toggle with no adapter behind it yet."""

    def __init__(self, key: str, label: str, reason: str, short: str) -> None:
        self.key = key
        self.label = label
        self._reason = reason
        self.short_reason = short

    def available(self) -> str | None:
        return self._reason

    def fetch(self, query):
        return self._unavailable(self._reason)


def build() -> dict[str, Source]:
    """Every source key the window knows about."""
    sources: dict[str, Source] = {
        "reddit": Reddit(),
        "feeds": CustomFeeds(),
        "forums": Discourse(),
        "marketplace": Marketplace(),
        "facebook": FacebookPosts(),
        "x": X(),
        "groups": FacebookGroups(),
        "craigslist": Craigslist(),
    }
    # Reasons are specific because they are shown to the user, and because the
    # honest ones differ: some are unbuilt, some are closed to us entirely.
    # The short form is what fits on the face of the label; the sentence is
    # still there on hover. Both are shown -- a source the user cannot pick is
    # never left to look like one they simply forgot to tick.
    # Hacker News, Lemmy and Mastodon are gone. They cost nothing to run, which
    # is why they survived three reviews, but they produced **zero** real leads
    # across every test in the project's history: they are global populations
    # discussing topics, not local people who need work doing. A source that
    # cannot produce a lead is a row of the window spent on nothing, and the
    # window is the scarce thing here. The adapters remain in sources/ -- they
    # are correct, they are just not worth a toggle.
    #
    # YouTube was dropped rather than left unbuilt: people do not go to YouTube
    # to ask for a plumber, and a toggle that will never be worth building is
    # just a promise the window cannot keep.
    for key, label, reason, short in [
        ("reviews", "Reviews",
         "not built yet -- needs a Google Places API key", "needs a key"),
    ]:
        sources[key] = NotBuilt(key, label, reason, short)
    return sources
