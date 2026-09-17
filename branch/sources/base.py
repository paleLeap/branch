"""The source adapter interface.

Every source declares its own auth, its own rate limit, its own cost per call and
its own legal standing, and any of them can be switched off per install. That is
deliberate: Reddit and X both changed their terms materially inside eighteen
months, and a design that assumed either would stay put would already be broken.

Two rules every adapter obeys:

  - **Never raise into the UI.** A source that cannot run returns `Unavailable`
    with a plain-language reason. A scan with a dead source still returns the
    leads from the live ones.
  - **Silent omission is a bug.** If a source did not run, it says so and why, and
    that reason is shown to the user. A scan that quietly searched nothing must
    not look like a scan that found nothing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import Item


@dataclass(frozen=True)
class Query:
    """What the window asked for, in terms an adapter can act on."""
    trade: str
    narrow: str = ""
    location: str = ""
    coordinates: tuple[float, float] | None = None
    radius_miles: float = 25.0
    since_hours: float = 24.0
    terms: list[str] = field(default_factory=list)   # profile vocabulary to search on
    forums: list[str] = field(default_factory=list)  # sites this trade cares about
    ask: str = ""                                    # how customers phrase the request
    asks: list[str] = field(default_factory=list)    # every phrasing, for paging


@dataclass
class Fetched:
    """What an adapter got, and what it could not."""
    items: list[Item] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class Source(ABC):
    """One place to look."""

    key: str = ""
    label: str = ""

    #: Roughly what one scan costs in money. 0.0 for free sources. Shown before
    #: a scan runs, because X is metered per call and a user must never be
    #: surprised by a bill.
    cost_per_scan: float = 0.0

    #: True when the source only covers a geography implicitly, or not at all.
    #: The UI says so rather than implying a radius was honoured.
    geographic: bool = True

    #: True when the source needs the user and a browser rather than a thread.
    #: The runner skips these; the window opens a browser for them instead.
    interactive: bool = False

    #: The service whose sign-in this source needs, if any -- "Facebook", "X".
    #: Branch's browser keeps its own session, so being signed in elsewhere on
    #: the machine does not count. The window says which, and offers the page.
    login_service: str = ""

    #: Where that sign-in happens. Opened in Branch's own browser, on the
    #: service's own form. Branch never sees the password.
    login_url: str = ""

    #: One sentence: what this source actually is. Shown when the user clicks a
    #: source marked "?" -- "not built yet" answers why it is off but not what
    #: they are missing, and the second question is the one worth answering.
    description: str = ""

    #: Two or three words for the label on a source that cannot run -- the full
    #: sentence from available() is longer than the window is wide. Sources that
    #: can always run never use it.
    short_reason: str = "unavailable"

    @abstractmethod
    def available(self) -> str | None:
        """Return None if ready, otherwise a plain-language reason it is not."""

    @abstractmethod
    def fetch(self, query: Query) -> Fetched:
        """Get posts. Must not raise; return Fetched with an `unavailable` entry."""

    def available_for(self, profile) -> str | None:
        """Why this source cannot run FOR THIS TRADE, if it cannot.

        Most sources are the same whatever the trade, so this is available()
        by default. Forums is not: it knows about forums because some profile
        names one, and a trade that names none can do nothing with it. Saying
        "ready" there is the window telling the user something untrue about the
        choice he just made.
        """
        return self.available()

    def state(self, connected: set[str] | None = None, profile=None) -> "SourceState":
        """What the window should show for this source, in one answer.

        `connected` is the set of services whose sign-in Branch has seen, lower
        case -- passed in rather than read here so this stays pure and the
        adapters stay free of config-file knowledge.

        Three outcomes, and the distinction between the last two matters to the
        user: **ready** can be ticked and will run; **login** can be ticked and
        will stop to ask for a sign-in it can offer a page for; **unavailable**
        cannot run at all and says why. Collapsing login into unavailable would
        hide the one state the user can actually fix.
        """
        reason = self.available_for(profile) if profile is not None else self.available()
        if reason is not None:
            return SourceState(self.key, self.label, "unavailable",
                               reason, self.short_reason,
                               description=self.description,
                               cost=self.cost_per_scan)
        if self.login_service and self.login_service.lower() not in (connected or set()):
            return SourceState(self.key, self.label, "login",
                               f"sign in to {self.login_service} in Branch's own "
                               "browser -- it keeps its own session, separate "
                               "from the one in your normal browser",
                               "sign in", self.login_service, self.login_url,
                               description=self.description,
                               cost=self.cost_per_scan)
        return SourceState(self.key, self.label, "ready", "", "",
                           description=self.description,
                           cost=self.cost_per_scan, note=self.ticked_note())

    def ticked_note(self) -> str:
        """One line to show the moment this source is ticked, or nothing.

        For a source that can work more than one way, this is where it says
        which way it is about to take -- the user is entitled to know that
        before Go, not afterwards from the results.
        """
        return ""

    def _unavailable(self, reason: str) -> Fetched:
        return Fetched(unavailable={self.key: reason})


@dataclass(frozen=True)
class SourceState:
    """What the window shows for one source, and why.

    `cost` and `note` ride along so a source can say what it is about to do
    *before* it runs -- what it will cost, or which of two routes it will take.
    cost_per_scan was declared in the contract and promised "shown before a scan
    runs", and no part of the window had ever read it. Nothing metered is wired
    today; this is kept so the next one cannot arrive silently.
    """

    key: str
    label: str
    state: str                 # "ready" | "login" | "unavailable"
    reason: str = ""           # the full sentence, on hover
    short: str = ""            # two or three words, on the face of it
    service: str = ""          # which sign-in, when state is "login"
    login_url: str = ""
    description: str = ""      # what this source is, in one sentence
    cost: float = 0.0          # rough dollars per scan; 0.0 for free sources
    note: str = ""             # one line shown when the user ticks it, if any

    @property
    def selectable(self) -> bool:
        """A login-gated source is still tickable: ticking it is how the user
        reaches the sign-in. Only a source that cannot run at all is off."""
        return self.state in ("ready", "login")
