"""Core data types for the Branch engine.

Deliberately plain: dataclasses, no framework, no I/O. The engine is pure logic so
it can be tested without a network, a browser or a platform account.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Item:
    """One post, listing, review or comment as fetched from a venue.

    Source adapters produce these. The engine never knows which platform it came from
    beyond `venue` -- that is what keeps sources swappable.
    """
    id: str
    text: str
    url: str
    venue: str                      # e.g. "reddit:r/FortWorth", "fb-marketplace:76107+25mi"
    posted_at: datetime
    author: str | None = None       # display handle only; never stored durably
    title: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return f"{self.title}\n{self.text}" if self.title else self.text

    def age_hours(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        posted = self.posted_at
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        return max(0.0, (now - posted).total_seconds() / 3600.0)


@dataclass(frozen=True)
class PhraseHit:
    """A single phrase that matched, with enough detail to explain itself."""
    phrase: str
    group: str                      # "subject" | "intent" | "exclude"
    weight: float
    start: int
    end: int
    excerpt: str
    negated: bool = False
    #: For an intent hit: "request" (somebody is asking for the work), "problem"
    #: (something is wrong) or "price" (shopping the job). The distinction is
    #: what separates a customer from a review of a competitor.
    group_kind: str = ""

    def __str__(self) -> str:
        flag = " (negated, suppressed)" if self.negated else ""
        return f'"{self.phrase}" +{self.weight:g}{flag}'


@dataclass
class Explanation:
    """Why an item scored what it scored. Shown in the UI, verbatim.

    This exists because a rules engine's whole advantage over a model is that the
    user can see the reasoning and change it.
    """
    subject_hits: list[PhraseHit] = field(default_factory=list)
    intent_hits: list[PhraseHit] = field(default_factory=list)
    exclude_hits: list[PhraseHit] = field(default_factory=list)
    narrow_hits: list[PhraseHit] = field(default_factory=list)
    negated_hits: list[PhraseHit] = field(default_factory=list)
    #: Who is asking, and for what. Kept apart from intent_hits so the card can
    #: say "asked for it" rather than only showing a score.
    request_hits: list[PhraseHit] = field(default_factory=list)
    owned_problem_hits: list[PhraseHit] = field(default_factory=list)
    boosts: dict[str, float] = field(default_factory=dict)
    subject_score: float = 0.0
    intent_score: float = 0.0
    boost_score: float = 0.0
    base_score: float = 0.0
    recency_factor: float = 1.0
    venue_factor: float = 1.0
    age_hours: float = 0.0

    def lines(self) -> list[str]:
        out: list[str] = []
        if self.narrow_hits:
            out.append("matched  " + ", ".join(h.phrase for h in self.narrow_hits))
        if self.subject_hits:
            out.append(f"subject {self.subject_score:g}  " + ", ".join(str(h) for h in self.subject_hits))
        if self.intent_hits:
            out.append(f"intent  {self.intent_score:g}  " + ", ".join(str(h) for h in self.intent_hits))
        for name, val in self.boosts.items():
            out.append(f"boost   {val:+g}  {name}")
        if self.negated_hits:
            out.append("negated " + ", ".join(h.phrase for h in self.negated_hits))
        out.append(
            f"score   {self.base_score:g} base x {self.recency_factor:.2f} recency "
            f"({self.age_hours:.0f}h old) x {self.venue_factor:.2f} venue"
        )
        return out


@dataclass
class Lead:
    """An item that survived the pipeline."""
    item: Item
    score: float
    explanation: Explanation

    @property
    def url(self) -> str:
        return self.item.url


@dataclass
class Discarded:
    """An item that did not survive, and the rule responsible.

    Kept for the current scan only, so the user can tune. Never persisted.
    """
    item: Item
    stage: str                      # "exclude" | "subject" | "intent" | "duplicate"
    reason: str
    explanation: Explanation | None = None


@dataclass
class ScanResult:
    leads: list[Lead] = field(default_factory=list)
    discarded: list[Discarded] = field(default_factory=list)
    scanned: int = 0
    venues: list[str] = field(default_factory=list)
    unavailable: dict[str, str] = field(default_factory=dict)
    # ^ venue -> plain-language reason. Silent omission of a source is a bug;
    #   the UI must always be able to answer "what didn't you look at, and why?"
