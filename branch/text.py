"""Text normalisation and phrase matching.

Everything here is deterministic. No model, no network, no learned weights.
"""
from __future__ import annotations

import re
import unicodedata

# Curly quotes, non-breaking spaces and friends turn "won't" into something that
# silently fails to match "won't". Normalise before anything else touches the text.
_APOSTROPHES = dict.fromkeys(map(ord, "‘’ʼ´`"), "'")
_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def fold(text: str) -> str:
    """Everything normalize() does except lowercasing.

    This exists so the UI can show a lead in its original casing and still use the
    match offsets: fold() and normalize() differ only by str.lower(), which is
    character-for-character, so an offset into one is the same offset into the
    other. Highlighting against the lowercased text instead would mean showing
    every post shouting in lowercase.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_APOSTROPHES)
    text = text.replace("—", " - ").replace("–", " - ")
    return _WS.sub(" ", text).strip()


def normalize(text: str) -> str:
    """Lowercase, fold unicode punctuation, collapse whitespace.

    Offsets into the result are what PhraseHit records; fold() gives the same
    string with its original casing and the same offsets.
    """
    return fold(text).lower()


def tokenize(text: str) -> list[tuple[str, int, int]]:
    """Return (token, start, end) triples over already-normalised text."""
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def compile_phrase(phrase: str) -> re.Pattern[str]:
    """Build a word-boundary regex for a phrase.

    Two accommodations that matter in practice:
      - apostrophes are optional *in both directions*, so a rule written "won't"
        matches text "wont", and a rule written "wont" matches text "won't".
        Both spellings are everywhere in real posts and a rules engine that only
        handled one of them would silently miss half its hits.
      - internal whitespace is flexible, so "fork  seal" matches "fork seal"
      - the final word takes an optional plural, so "fork seal" matches "fork seals".
        Profile authors write the singular and get both; without this, half the rules
        in a hand-written profile quietly miss.
      - a trailing "*" means "any continuation", for authors who want it explicitly:
        "leak*" matches leak, leaks, leaking, leakage.
    """
    parts: list[str] = []
    words = [w for w in normalize(phrase).split(" ") if w.strip("'")]
    for i, word in enumerate(words):
        open_ended = word.endswith("*")
        bare = word.rstrip("*").replace("'", "")
        if not bare:
            continue
        # Allow an optional apostrophe between every pair of characters. Over-permissive
        # in theory ("w'o'n't"), harmless in practice, and it makes the direction problem
        # disappear instead of depending on how the rule author spelled it.
        piece = "'?".join(re.escape(ch) for ch in bare)
        if open_ended:
            piece += "[a-z0-9]*"
        elif i == len(words) - 1:
            piece += "(?:e?s)?"
        parts.append(piece)
    if not parts:
        raise ValueError(f"empty phrase: {phrase!r}")
    body = r"\s+".join(parts)
    # \b fails against a leading/trailing non-word char, so guard with lookarounds.
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def excerpt_around(text: str, start: int, end: int, width: int = 60) -> str:
    """A readable snippet centred on a match, for the explanation panel."""
    lo = max(0, start - width)
    hi = min(len(text), end + width)
    snippet = text[lo:hi].strip()
    return ("..." if lo > 0 else "") + snippet + ("..." if hi < len(text) else "")


def is_negated(
    text: str,
    tokens: list[tuple[str, int, int]],
    match_start: int,
    negation_terms: frozenset[str],   # already apostrophe-stripped by the profile loader
    window: int,
) -> bool:
    """True if a negation word sits within `window` tokens before the match.

    Crude by design. It catches "I don't need a mechanic" and "no longer looking",
    which are the common false positives, and it will miss subtler negation. That
    trade is recorded in docs/CLASSIFICATION.md.
    """
    if window <= 0 or not negation_terms:
        return False
    idx = next((i for i, (_, s, _e) in enumerate(tokens) if s >= match_start), len(tokens))
    for tok, _s, _e in tokens[max(0, idx - window):idx]:
        # Compare apostrophe-free so "dont" in a profile matches "don't" in a post.
        if tok.replace("'", "") in negation_terms:
            return True
    return False
