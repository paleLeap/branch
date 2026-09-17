"""A continuous attended session: keep asking, for as long as the user said.

WHY THIS EXISTS. A scan finished when it ran out of *questions* -- ten phrasings
for Facebook, four group searches -- not when the area ran out of leads. Nothing
in that logic ever knew whether new posts existed. So a user who wanted to sit
and watch for an hour had to press Go, wait twelve minutes, and press it again.

WHAT IT IS NOT. This is not a scheduler and not a background sweep. The rule it
respects is "never unwatched", not "never more than once": the user chooses a
duration **at the moment they press Go**, sees a countdown the whole time, and
can stop it with the same button. When the duration runs out the session stops
for good and does not restart itself. Nothing here runs unless a person asked it
to, in front of them, for a length of time they chose.

The browser's own safeguards are untouched and still do the real protecting: the
paced scrolling, the per-page caps, the "no new posts" stop. A pass inside a
session is exactly the pass Go always ran.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from .models import Lead, ScanResult
from .runner import RUN_FOR_SECONDS


#: Seconds between the end of one pass and the start of the next. The browser
#: already paces its scrolling and its searches for the same reason: a fresh
#: pass beginning the instant the last one ended is the part that would look
#: automated rather than attended.
PASS_GAP_SECONDS = 30.0


def duration_seconds(label: str) -> float:
    return RUN_FOR_SECONDS.get((label or "").strip(), 0.0)


def lead_key(lead: Lead) -> str:
    """What makes two leads the same lead across passes.

    The URL where there is one. Facebook search results carry no post permalink
    -- several share `/search/posts#?ihe` -- so those fall back to the text,
    which is what actually differs between two people asking for a plumber.
    """
    url = (getattr(lead.item, "url", "") or "").strip()
    if url and "/search/posts" not in url:
        return url
    text = " ".join((lead.item.text or "").split()).lower()
    return text[:200] or url


class Session(QObject):
    """Runs passes back to back until the clock the user set runs out."""

    #: One merged result: everything found so far this session, best first.
    result = Signal(object)
    #: What the session is doing, in words -- pass number and time left.
    progress = Signal(str)
    #: Emitted once when the session ends, with why it ended.
    ended = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._query: dict | None = None
        self._deadline = 0.0
        self._cycle = 0
        self._seen: set[str] = set()
        self._leads: list[Lead] = []
        self._scanned = 0
        self._discarded: list = []
        self._venues: list[str] = []
        self._unavailable: dict[str, str] = {}
        self._running = False
        self._stopping = False

    # -- state ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def cycle(self) -> int:
        return self._cycle

    def seconds_left(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    def expired(self) -> bool:
        return self.seconds_left() <= 0.0

    # -- driving -------------------------------------------------------------

    def start(self, query: dict, seconds: float) -> dict | None:
        """Begin a session. Returns the query for the first pass, or None.

        None means "this is a one-off" -- a duration of zero is the original
        behaviour and must stay the default, so nothing about pressing Go
        changes for a user who never touches the new control.
        """
        if seconds <= 0:
            return None
        self._query = dict(query)
        self._deadline = time.monotonic() + seconds
        self._cycle = 0
        self._seen.clear()
        self._leads = []
        self._scanned = 0
        self._discarded = []
        self._venues = []
        self._unavailable = {}
        self._running = True
        self._stopping = False
        return self.next_query()

    def next_query(self) -> dict:
        """The query for the pass about to run, numbered so phrasings rotate."""
        query = dict(self._query or {})
        query["cycle"] = self._cycle
        return query

    def absorb(self, result) -> object:
        """Fold one pass's result into the session's running total.

        Returns the merged result: every lead found this session, best first,
        with the counts summed. The list the user is watching grows rather than
        being replaced, which is the whole point of sitting there for an hour.
        """
        fresh = 0
        for lead in getattr(result, "leads", []) or []:
            key = lead_key(lead)
            if key in self._seen:
                continue
            self._seen.add(key)
            self._leads.append(lead)
            fresh += 1
        self._scanned += int(getattr(result, "scanned", 0) or 0)
        # The rejects come too. They are how the user tunes -- clicking a phrase
        # excludes it and re-runs -- and a session that dropped them showed
        # "Discarded 0" against 136 scanned posts, which is worse than useless:
        # it says nothing was thrown away when everything was.
        self._discarded = list(getattr(result, "discarded", []) or []) or self._discarded
        for venue in getattr(result, "venues", []) or []:
            if venue not in self._venues:
                self._venues.append(venue)
        self._unavailable.update(getattr(result, "unavailable", {}) or {})
        self._leads.sort(key=lambda l: -l.score)
        self._fresh = fresh
        return self.merged()

    def merged(self) -> ScanResult:
        return ScanResult(leads=list(self._leads), scanned=self._scanned,
                          discarded=list(self._discarded),
                          venues=list(self._venues),
                          unavailable=dict(self._unavailable))

    def finished_pass(self) -> bool:
        """One pass is done. True if another should start.

        False when the clock has run out or the user stopped it -- and in that
        case the session is over, not paused. It will not start again without
        somebody pressing Go.
        """
        if not self._running:
            return False
        if self._stopping or self.expired():
            self.stop("time is up" if self.expired() else "stopped")
            return False
        self._cycle += 1
        return True

    def stop(self, why: str = "stopped") -> None:
        if not self._running:
            return
        self._running = False
        self._stopping = True
        self.ended.emit(why)

    def ask_stop(self) -> None:
        """Stop after the pass in flight finishes reading what it has open."""
        self._stopping = True

    # -- what the user reads -------------------------------------------------

    def status(self) -> str:
        left = int(self.seconds_left())
        clock = f"{left // 60}:{left % 60:02d}" if left >= 60 else f"{left}s"
        found = len(self._leads)
        return (f"pass {self._cycle + 1}  ·  {found} lead{'' if found == 1 else 's'}"
                f"  ·  {clock} left")
