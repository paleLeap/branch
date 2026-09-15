"""The scan pipeline.

    normalise -> exclude -> subject -> intent -> score -> dedupe -> rank

Deterministic end to end. Given the same items and the same profile it returns the
same leads in the same order, forever, with no model and no network.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone

from .models import Discarded, Explanation, Item, Lead, PhraseHit, ScanResult
from .profile import Group, Profile
from .text import compile_phrase, excerpt_around, is_negated, normalize, tokenize

_FIRST_PERSON = re.compile(r"(?<![a-z0-9])(i|my|mine|i'?m|i'?ve|we|our|us)(?![a-z0-9])")


def _match_group(
    group: Group,
    kind: str,
    text: str,
    tokens: list[tuple[str, int, int]],
    profile: Profile,
    apply_negation: bool,
) -> tuple[list[PhraseHit], list[PhraseHit]]:
    """Return (live hits, negated hits) for one group."""
    live: list[PhraseHit] = []
    negated: list[PhraseHit] = []
    for term, pattern in zip(group.terms, group.patterns):
        m = pattern.search(text)
        if not m:
            continue
        neg = apply_negation and is_negated(
            text, tokens, m.start(), profile.negation_terms, profile.negation_window
        )
        hit = PhraseHit(
            phrase=term, group=kind, weight=group.weight,
            start=m.start(), end=m.end(),
            excerpt=excerpt_around(text, m.start(), m.end()),
            negated=neg,
        )
        (negated if neg else live).append(hit)
    return live, negated


def _score_stage(
    groups: list[Group],
    kind: str,
    text: str,
    tokens: list[tuple[str, int, int]],
    profile: Profile,
    apply_negation: bool,
) -> tuple[float, list[PhraseHit], list[PhraseHit]]:
    """Each group contributes its weight at most once, however many of its terms hit.

    Counting every term would let a profile author accidentally make one verbose
    group outweigh every other signal.
    """
    total = 0.0
    hits: list[PhraseHit] = []
    negated: list[PhraseHit] = []
    for group in groups:
        live, neg = _match_group(group, kind, text, tokens, profile, apply_negation)
        negated.extend(neg)
        if live:
            total += group.weight
            hits.extend(live)
    return total, hits, negated


def _recency_factor(age_hours: float, half_life: float, floor: float = 0.0) -> float:
    """Exponential decay, optionally floored.

    Without a floor, a short half-life drives anything older than a day or so to
    effectively zero, which buries genuinely strong older leads beneath weak fresh
    ones. The floor lets a profile say "freshness matters, but never erase a lead".
    """
    if half_life <= 0:
        return 1.0
    return max(floor, 0.5 ** (age_hours / half_life))


def _shingles(text: str, n: int = 5) -> frozenset[str]:
    # Apostrophe-stripped, so a post reworded "won't" -> "wont" still reads as the
    # same post. Reposts with trivial edits are common and waste the user's time.
    toks = [t.replace("'", "") for t, _s, _e in tokenize(text)]
    if len(toks) < n:
        return frozenset([" ".join(toks)]) if toks else frozenset()
    return frozenset(" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1))


def _same_thread(a: Item, b: Item) -> bool:
    """Same venue and same title means the same discussion."""
    if a.venue != b.venue or not a.title or not b.title:
        return False
    return normalize(a.title) == normalize(b.title)


def _near_duplicate(a: frozenset[str], b: frozenset[str], threshold: float = 0.8,
                    contained: float | None = None) -> bool:
    """Jaccard, optionally with a containment check.

    Jaccard alone misses the common real case: the same post shared to two groups
    arrives with a different group name stapled to the front, so each text holds
    a handful of shingles the other lacks and the score falls just under the bar.
    Measured on a live scan, one person's "I need a plumber, my kitchen sink is
    backing up" appeared as two separate leads at a Jaccard of about 0.8.

    Containment -- how much of the *smaller* text appears in the larger -- handles
    that, and is only applied within a single venue, where the chrome that differs
    is predictable and the risk of merging two genuinely different posts is low.
    """
    if not a or not b:
        return False
    inter = len(a & b)
    if inter / len(a | b) >= threshold:
        return True
    if contained is not None:
        return inter / min(len(a), len(b)) >= contained
    return False


def scan(
    items: list[Item],
    profile: Profile,
    *,
    now: datetime | None = None,
    venue_weights: dict[str, float] | None = None,
    min_score: float = 0.0,
    unavailable: dict[str, str] | None = None,
    narrow: str | Sequence[str] | None = None,
) -> ScanResult:
    """Run the pipeline over a batch of items.

    `items` come from source adapters; the engine neither knows nor cares which.
    `unavailable` is carried straight through to the result so the UI can always
    answer "what didn't you look at, and why?" -- silent omission is a bug.

    WHAT `narrow` IS, because it is the part that is easy to get wrong.

    The **profile** is what finds leads. It already encodes "people who need
    plumbing repairs" -- the intent language, the trade vocabulary, the exclusions.
    That is the entire job of a trade profile.

    `narrow` is an **optional filter applied on top of that**, not a description of
    who you are looking for. Empty means "every plumbing lead in the area". Given
    "water heater" it keeps only those leads that also mention a water heater.

    So "Pipe broken" is a narrowing and works; "People who need plumbing repairs"
    is the *profile's* job and typing it here would match almost nothing, because
    no customer writes that sentence. The UI has to make that distinction obvious,
    and it does it by suggesting real narrowings from the chosen profile.
    """
    now = now or datetime.now(timezone.utc)
    venue_weights = venue_weights or {}

    # Whitespace-separated words are treated as alternatives, not as one phrase:
    # someone typing "carb clutch" means either, and a quoted "fork seal" or a
    # list means the phrase.
    if isinstance(narrow, str):
        narrow_terms = [t for t in narrow.strip().split() if t] if narrow.strip() else []
    else:
        narrow_terms = [str(t) for t in (narrow or []) if str(t).strip()]
    narrow_patterns = [(t, compile_phrase(t)) for t in narrow_terms]
    result = ScanResult(
        scanned=len(items),
        venues=sorted({i.venue for i in items}),
        unavailable=dict(unavailable or {}),
    )

    # Candidates are scored first and deduped afterwards, in score order. Deduping
    # during the scan would make the output depend on input order, and would keep
    # whichever copy happened to arrive first rather than the strongest one.
    candidates: list[tuple[Lead, frozenset[str]]] = []

    for item in items:
        text = normalize(item.full_text)
        tokens = tokenize(text)
        exp = Explanation(age_hours=item.age_hours(now))

        # 1. Exclusions kill outright. Negation is NOT applied here: "not for sale"
        #    still means the post is about a sale, and we would rather drop a
        #    borderline item than show the user a junk lead.
        # An exclusion can be switched off for a venue -- see Group.except_venues.
        active_exclusions = [g for g in profile.exclude if g.applies_to(item.venue)]
        ex_score, ex_hits, _ = _score_stage(active_exclusions, "exclude", text, tokens, profile, False)
        if ex_hits:
            exp.exclude_hits = ex_hits
            result.discarded.append(Discarded(
                item=item, stage="exclude",
                reason=f'excluded by {", ".join(h.phrase for h in ex_hits)}',
                explanation=exp,
            ))
            continue

        # 2. The user's narrowing, if they typed one. Applied before the profile
        #    stages because it is the cheapest possible reject.
        if narrow_patterns:
            hits = []
            for term, pattern in narrow_patterns:
                m = pattern.search(text)
                if m is not None:
                    hits.append(PhraseHit(
                        phrase=term, group="narrow", weight=0.0,
                        start=m.start(), end=m.end(),
                        excerpt=excerpt_around(text, m.start(), m.end()),
                    ))
            if not hits:
                result.discarded.append(Discarded(
                    item=item, stage="narrow",
                    reason=f"does not mention {' or '.join(narrow_terms)}",
                    explanation=exp,
                ))
                continue
            exp.narrow_hits = hits

        # 3. Subject: is this even about the trade?
        s_score, s_hits, s_neg = _score_stage(profile.subject, "subject", text, tokens, profile, False)
        exp.subject_score, exp.subject_hits = s_score, s_hits
        if s_score < profile.subject_threshold:
            result.discarded.append(Discarded(
                item=item, stage="subject",
                reason=f"subject score {s_score:g} below threshold {profile.subject_threshold:g}",
                explanation=exp,
            ))
            continue

        # 4. Intent: does this person want it dealt with? Negation applies here --
        #    "I don't need a mechanic" must not read as demand.
        i_score, i_hits, i_neg = _score_stage(profile.intent, "intent", text, tokens, profile, True)
        exp.intent_score, exp.intent_hits = i_score, i_hits
        exp.negated_hits = s_neg + i_neg
        if i_score < profile.intent_threshold:
            result.discarded.append(Discarded(
                item=item, stage="intent",
                reason=f"intent score {i_score:g} below threshold {profile.intent_threshold:g}",
                explanation=exp,
            ))
            continue

        # 5. Boosts
        boost_total = 0.0
        if "question_mark" in profile.boosts and "?" in item.full_text:
            exp.boosts["asks a question"] = profile.boosts["question_mark"]
            boost_total += profile.boosts["question_mark"]
        if "first_person" in profile.boosts and _FIRST_PERSON.search(text):
            exp.boosts["first person"] = profile.boosts["first_person"]
            boost_total += profile.boosts["first_person"]
        exp.boost_score = boost_total

        # 6. Score
        exp.base_score = s_score + i_score + boost_total
        exp.recency_factor = _recency_factor(
            exp.age_hours, profile.recency_half_life_hours, profile.recency_floor
        )
        exp.venue_factor = venue_weights.get(item.venue, 1.0)
        score = exp.base_score * exp.recency_factor * exp.venue_factor

        if score < min_score:
            result.discarded.append(Discarded(
                item=item, stage="score",
                reason=f"score {score:.2f} below minimum {min_score:g}",
                explanation=exp,
            ))
            continue

        candidates.append((Lead(item=item, score=score, explanation=exp), _shingles(text)))

    # 7. Dedupe. Crossposts and lightly-reworded reposts are common and waste the
    #    user's time. Walking highest-score-first means the best copy is the one
    #    that survives, and sorting first makes the result independent of the order
    #    the adapters happened to hand us items in.
    candidates.sort(key=lambda pair: (-pair[0].score, pair[0].item.id))
    kept: list[tuple[Lead, frozenset[str]]] = []
    for lead, sh in candidates:
        dup_of = next(
            (k for k, ks in kept
             # Same thread: two comments under one post are one lead, however
             # differently they are worded. Without this, a busy thread floods
             # the list with what is really a single opportunity.
             if _same_thread(k.item, lead.item)
             or (k.item.author and k.item.author == lead.item.author
                 and _near_duplicate(ks, sh, 0.5))
             or _near_duplicate(
                 ks, sh,
                 contained=0.75 if k.item.venue == lead.item.venue else None)),
            None,
        )
        if dup_of is not None:
            result.discarded.append(Discarded(
                item=lead.item, stage="duplicate",
                reason=f"near-duplicate of {dup_of.item.id}, which scored higher",
                explanation=lead.explanation,
            ))
            continue
        kept.append((lead, sh))

    result.leads = [k for k, _ in kept]
    return result
