"""Trade profiles: the editable rules that define what a business is looking for.

A profile is a plain YAML file. It is content, not code -- users edit them, share
them, and PR them for their own trade. Nothing here is specific to any profession;
motorcycle repair is just the first one written.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .text import compile_phrase

DEFAULT_NEGATIONS = [
    "not", "no", "never", "dont", "doesnt", "didnt", "wont", "cant",
    "isnt", "arent", "wasnt", "havent", "hasnt", "nor", "without",
]


@dataclass
class Group:
    """A weighted set of phrases. Scores its weight once if any phrase matches."""
    terms: list[str]
    weight: float = 1.0
    label: str = ""
    #: Venues this group does NOT apply to. Only meaningful for exclusions, and
    #: it exists because "for sale" means opposite things in different places: on
    #: Reddit a sale post is noise, but on Marketplace a broken item listed cheap
    #: is the strongest signal a repair trade gets. Excluding sales there would
    #: throw away the entire reason to read Marketplace at all.
    except_venues: list[str] = field(default_factory=list)
    #: What kind of evidence this group is, for intent groups only:
    #:
    #:   "request" -- somebody is ASKING for the work: "anyone know a plumber",
    #:                "need someone to fix", "looking for a mechanic". This is
    #:                the thing Branch exists to find.
    #:   "problem"  -- something is wrong: "leaking", "won't start", "backed up".
    #:                A problem is only a lead when the person describing it is
    #:                the one who has it. "They did a great job fixing a leak"
    #:                is a five-star review, and it scored as demand until this
    #:                distinction existed.
    #:   "price"    -- shopping the job: "how much should", "quoted me".
    #:
    #: Defaults to "problem" because that is the safe reading: it requires
    #: corroboration before the item counts as a lead. See engine.scan().
    kind: str = "problem"
    #: Compiled lazily. With a hundred trade profiles, compiling every phrase in
    #: every profile at startup cost most of half a second before the window
    #: appeared -- and the window only needs each trade's NAME to start. A
    #: profile's patterns are built the first time it is actually scanned with.
    _patterns: list[re.Pattern[str]] = field(default_factory=list, repr=False)

    def applies_to(self, venue: str) -> bool:
        return not any(venue.startswith(v) for v in self.except_venues)

    def __post_init__(self) -> None:
        if not self.terms:
            raise ValueError(f"group {self.label or '?'} has no terms")

    @property
    def patterns(self) -> list[re.Pattern[str]]:
        if not self._patterns:
            self._patterns = [compile_phrase(t) for t in self.terms]
        return self._patterns


@dataclass
class Profile:
    trade: str
    display_name: str = ""
    subject: list[Group] = field(default_factory=list)
    intent: list[Group] = field(default_factory=list)
    exclude: list[Group] = field(default_factory=list)
    subject_threshold: float = 3.0
    intent_threshold: float = 3.0
    recency_half_life_hours: float = 48.0
    recency_floor: float = 0.05
    negation_window: int = 4
    negation_terms: frozenset[str] = frozenset(DEFAULT_NEGATIONS)
    boosts: dict[str, float] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)
    ask_terms: list[str] = field(default_factory=list)
    forums: list[str] = field(default_factory=list)
    notes: str = ""
    path: Path | None = None

    @property
    def name(self) -> str:
        return self.display_name or self.trade

    # -- loading -------------------------------------------------------------

    @staticmethod
    def _groups(raw: Any, kind: str) -> list[Group]:
        """Accept either the verbose form or a bare list of phrases.

        Verbose:  - terms: [a, b]
                    weight: 3
        Terse:    - [a, b]          (weight defaults to 1)
        Terse:    - "a single phrase"

        The terse forms exist because a user editing their own profile should not
        have to learn a schema to add one word.
        """
        if not raw:
            return []
        groups: list[Group] = []
        for i, entry in enumerate(raw):
            label = f"{kind}[{i}]"
            if isinstance(entry, str):
                groups.append(Group(terms=[entry], weight=1.0, label=label))
            elif isinstance(entry, list):
                groups.append(Group(terms=[str(t) for t in entry], weight=1.0, label=label))
            elif isinstance(entry, dict):
                terms = entry.get("terms") or entry.get("any") or []
                if isinstance(terms, str):
                    terms = [terms]
                groups.append(Group(
                    terms=[str(t) for t in terms],
                    weight=float(entry.get("weight", 1.0)),
                    label=str(entry.get("label", label)),
                    except_venues=[str(v) for v in (entry.get("except_venues") or [])],
                    kind=str(entry.get("kind", "problem")).strip().lower(),
                ))
            else:
                raise ValueError(f"{label}: expected string, list or mapping, got {type(entry).__name__}")
        return groups

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> "Profile":
        if "trade" not in data:
            raise ValueError("profile is missing required key 'trade'")
        thresholds = data.get("thresholds") or {}
        neg = data.get("negation") or {}
        terms = neg.get("terms", DEFAULT_NEGATIONS)
        return cls(
            trade=str(data["trade"]),
            display_name=str(data.get("display_name", "")),
            subject=cls._groups(data.get("subject"), "subject"),
            intent=cls._groups(data.get("intent"), "intent"),
            exclude=cls._groups(data.get("exclude"), "exclude"),
            subject_threshold=float(thresholds.get("subject", 3.0)),
            intent_threshold=float(thresholds.get("intent", 3.0)),
            recency_half_life_hours=float(data.get("recency_half_life_hours", 48.0)),
            recency_floor=float(data.get("recency_floor", 0.05)),
            negation_window=int(neg.get("window", 4)),
            # Stored apostrophe-free so a profile may write "don't" or "dont".
            negation_terms=frozenset(str(t).replace("'", "").lower() for t in terms),
            boosts={str(k): float(v) for k, v in (data.get("boost") or {}).items()},
            suggestions=[str(x) for x in (data.get("suggestions") or [])],
            ask_terms=[str(x) for x in (data.get("ask") or [])],
            forums=[str(x).rstrip("/") for x in (data.get("forums") or [])
                    if str(x).startswith("http")],
            notes=str(data.get("notes", "")),
            path=path,
        )

    @staticmethod
    def local_path_for(path: Path) -> Path:
        """Where this profile's user tuning lives: `plumbing.local.yaml`."""
        return path.with_suffix("").with_suffix(".local.yaml")

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: profile must be a YAML mapping")

        # Shared rules every trade needs. Two kinds:
        #
        #   exclude -- news, product announcements, listicles, the trade
        #              advertising itself. Kept in one file so a new profile
        #              inherits them rather than rediscovering them.
        #   intent  -- HOW PEOPLE ASK, which is almost entirely trade-agnostic.
        #              "anyone know a good ___", "please help", "need someone
        #              to ___" are the same sentence whoever is being asked for,
        #              and a real lead was nearly lost because one profile's own
        #              list happened not to contain "please help". A profile
        #              says what its trade is about; the shared file says what
        #              asking looks like.
        defaults = path.parent / "_defaults.yaml"
        if defaults.exists() and path.name != "_defaults.yaml":
            try:
                with defaults.open("r", encoding="utf-8") as fh:
                    shared = yaml.safe_load(fh) or {}
                for key in ("exclude", "intent"):
                    if shared.get(key):
                        data[key] = list(data.get(key) or []) + list(shared[key])
            except Exception as exc:
                print(f"warning: ignoring {defaults}: {exc}")

        # User tuning lives in a sidecar rather than being written back into the
        # shipped profile. That keeps the curated file and its comments pristine,
        # makes every change the user made visible in one place, and means undoing
        # their tuning is deleting one file.
        local = cls.local_path_for(path)
        if local.exists():
            try:
                with local.open("r", encoding="utf-8") as fh:
                    overlay = yaml.safe_load(fh) or {}
                for key in ("subject", "intent", "exclude"):
                    if overlay.get(key):
                        data[key] = list(data.get(key) or []) + list(overlay[key])
                for key in ("thresholds", "boost"):
                    if overlay.get(key):
                        data[key] = {**(data.get(key) or {}), **overlay[key]}
            except Exception as exc:
                print(f"warning: ignoring {local}: {exc}")

        try:
            return cls.from_dict(data, path=path)
        except ValueError as exc:
            # A user is going to hand-edit these. Say which file broke.
            raise ValueError(f"{path}: {exc}") from exc

    def add_exclusion(self, term: str) -> bool:
        """Add a phrase to this profile's exclusions, in its sidecar file.

        Called when the user looks at a bad lead and says "this word is why".
        Returns False if the profile has no path or the term is already excluded.
        """
        term = term.strip()
        if not term or self.path is None:
            return False
        if any(term.lower() == t.lower() for g in self.exclude for t in g.terms):
            return False

        local = self.local_path_for(self.path)
        data: dict = {}
        if local.exists():
            with local.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        data.setdefault("exclude", []).append({"terms": [term], "label": "tuned-by-hand"})
        header = (f"# Tuning for {self.trade}, added from the results list.\n"
                  f"# Delete this file to undo every change made here.\n")
        local.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                         encoding="utf-8")
        self.exclude.append(Group(terms=[term], weight=1.0, label="tuned-by-hand"))
        return True

    @classmethod
    def load_all(cls, directory: str | Path) -> dict[str, "Profile"]:
        directory = Path(directory)
        found: dict[str, Profile] = {}
        for p in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
            if p.name.startswith("_"):
                continue          # _defaults.yaml is shared rules, not a trade
            prof = cls.load(p)
            found[prof.trade] = prof
        return found

    def prompts(self, limit: int = 10) -> list[str]:
        """Example things to type in the search box, for this trade.

        The box narrows an already-trade-filtered result set, so the useful thing
        to type is a *symptom or a part* -- "water heater", "burst pipe" -- not a
        description of the customer. Curated `suggestions:` in the YAML come first;
        otherwise fall back to the profile's own highest-weighted phrases, which
        are by construction the language this trade's customers actually use.
        """
        if self.suggestions:
            return self.suggestions[:limit]
        out: list[str] = []
        seen: set[str] = set()
        for group in sorted(self.intent + self.subject, key=lambda g: -g.weight):
            for term in group.terms:
                clean = term.replace("*", "").strip()
                if len(clean) < 3 or clean in seen:
                    continue
                seen.add(clean)
                out.append(clean)
                if len(out) >= limit:
                    return out
        return out

    def ask_phrases(self, limit: int = 3, offset: int = 0) -> list[str]:
        """How this trade's customers phrase the request itself.

        Different from prompts(): a prompt narrows results already found
        ("water heater"), whereas this is what someone actually types when they
        want the work done ("need a plumber"). Facebook search needs the latter.

        `offset` rotates the list, which is what a continuous session uses to ask
        different questions on each pass rather than the same ones over and over.
        Rotation only buys coverage when a profile has **more** phrasings than one
        pass asks -- with ten phrasings and ten asked, it only changes the order.
        Adding phrasings to the YAML is what makes a long session find more.
        """
        if self.ask_terms:
            return self._rotate(self.ask_terms, limit, offset)
        # Falling back to the asking-for-help group is better than nothing, but
        # those phrases are deliberately trade-agnostic ("any recommendations") --
        # searching one finds recommendations for everything. A profile should
        # name its own.
        for group in sorted(self.intent, key=lambda g: -g.weight):
            if "ask" in group.label.lower():
                return self._rotate([t.replace("*", "") for t in group.terms],
                                    limit, offset)
        return self.prompts(limit)

    @staticmethod
    def _rotate(terms: list[str], limit: int, offset: int) -> list[str]:
        """`limit` phrases starting `offset` in, wrapping at the end.

        Never returns the same phrase twice in one pass, however large the
        offset: a pass that asked "need a plumber" twice would spend a Facebook
        search on a page it had already read.
        """
        if not terms or limit <= 0:
            return []
        start = offset % len(terms)
        ordered = terms[start:] + terms[:start]
        return ordered[:limit]

    def validate(self) -> list[str]:
        """Non-fatal warnings to surface in the profile editor."""
        warnings: list[str] = []
        if not self.subject:
            warnings.append("no subject groups: every item will fail the subject stage")
        if not self.intent:
            warnings.append("no intent groups: every item will fail the intent stage")
        max_subject = sum(g.weight for g in self.subject)
        max_intent = sum(g.weight for g in self.intent)
        if self.subject and max_subject < self.subject_threshold:
            warnings.append(
                f"subject threshold {self.subject_threshold:g} exceeds the maximum "
                f"achievable score {max_subject:g}: nothing can ever match"
            )
        if self.intent and max_intent < self.intent_threshold:
            warnings.append(
                f"intent threshold {self.intent_threshold:g} exceeds the maximum "
                f"achievable score {max_intent:g}: nothing can ever match"
            )
        if not self.exclude:
            warnings.append("no exclusions: for-sale and job posts will show up as leads")
        return warnings
