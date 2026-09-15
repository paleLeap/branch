"""The results list: leads, discards, and the tuning loop.

Every card explains itself. That is only possible because matching is
deterministic -- the engine records which phrase matched, what it scored, and
which rule killed the posts that did not survive. A model-based classifier could
not offer any of this, and the tuning loop below would not exist.

Nothing about a person is written to disk here. A card holds an excerpt, a venue,
an age and a link, for as long as the scan is on screen.
"""
from __future__ import annotations

import html
import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .. import enrich, places
from ..models import Discarded, Lead, ScanResult
from ..text import fold
from .theme import Size, Theme, rgba

EXCERPT_CHARS = 260


def _excerpt(text: str, focus: int) -> tuple[str, int]:
    """A window of the post centred on the first match. Returns (text, offset)."""
    if len(text) <= EXCERPT_CHARS:
        return text, 0
    start = max(0, focus - EXCERPT_CHARS // 3)
    start = min(start, len(text) - EXCERPT_CHARS)
    chunk = text[start:start + EXCERPT_CHARS]
    return ("..." if start else "") + chunk + "...", start - (3 if start else 0)


def _highlighted(text: str, spans: list[tuple[int, int]], colour: str) -> str:
    """Escape the text and wrap the matched spans. Offsets are into `fold()`."""
    merged: list[tuple[int, int]] = []
    for lo, hi in sorted(spans):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    out, cursor = [], 0
    for lo, hi in merged:
        lo, hi = max(0, lo), min(len(text), hi)
        if lo >= hi:
            continue
        out.append(html.escape(text[cursor:lo]))
        out.append(f'<span style="color:{colour}">{html.escape(text[lo:hi])}</span>')
        cursor = hi
    out.append(html.escape(text[cursor:]))
    return "".join(out)


def _age(hours: float) -> str:
    if hours < 1:
        return f"{max(1, int(hours * 60))}m ago"
    if hours < 48:
        return f"{int(hours)}h ago"
    return f"{int(hours / 24)}d ago"


class PhraseChip(QPushButton):
    """A phrase that matched. Clicking it excludes that phrase from the trade."""

    def __init__(self, phrase: str, parent=None) -> None:
        super().__init__(phrase, parent)
        self.setObjectName("chip")
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setToolTip(f'Never match "{phrase}" for this trade again')


class LeadCard(QFrame):
    """One lead: what was said, where, when, and why it is here."""

    exclude_requested = Signal(str)
    open_requested = Signal(str)

    def __init__(self, lead: Lead, theme: Theme, parent=None,
                 near: tuple[float, float] | None = None) -> None:
        super().__init__(parent)
        self.lead = lead
        self.setObjectName("card")
        t = theme
        exp = lead.explanation
        item = lead.item

        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.s(9), t.s(7), t.s(9), t.s(7))
        outer.setSpacing(t.s(3))

        top = QHBoxLayout()
        top.setSpacing(t.s(6))
        title = QLabel(item.title or (item.text or "")[:80])
        title.setObjectName("cardTitle")
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title.setWordWrap(False)
        top.addWidget(title, 1)

        # What else the post itself says: a postcode, a nearby town it names,
        # whether it reads as urgent. Read from the text on screen, never looked
        # up -- and contact details are reported as present, never extracted.
        facts = [item.venue]
        if item.author:
            facts.append(item.author)
        facts.append(_age(exp.age_hours) if (item.extra or {}).get("time_known", True)
                     else "time unknown")
        facts.extend(enrich.describe(item.full_text, near, places.load_cities()))
        meta = QLabel("  ·  ".join(facts))
        meta.setObjectName("cardMeta")
        meta.setWordWrap(True)
        top.addWidget(meta, 0)

        # Say where the link goes. Facebook search results for group posts have
        # no post permalink, so "Open" would quietly land on the group -- which is
        # exactly what it did until he noticed.
        kind = (item.extra or {}).get("link", "post")
        open_btn = QPushButton({"post": "Open", "listing": "Open listing",
                                "story": "Open story", "group": "Open group",
                                "profile": "Open profile"}.get(kind, "Open page"))
        open_btn.setObjectName("cardOpen")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setFlat(True)
        open_btn.clicked.connect(lambda: self.open_requested.emit(item.url))
        if kind in ("group", "profile", "page"):
            open_btn.setToolTip(
                "Facebook does not put a link to the post itself on a search "
                "result, so this opens the " + kind + ". Browsing the group "
                "directly does give real post links.")
        top.addWidget(open_btn, 0)
        outer.addLayout(top)

        # The post, with every matched phrase picked out. The title is already the
        # heading above, so it is trimmed off the front of the excerpt rather than
        # printed twice -- and the match offsets shift with it.
        body = fold(item.full_text)
        trimmed = 0
        if item.title:
            prefix = fold(item.title)
            if body.startswith(prefix):
                trimmed = len(prefix) + 1
                body = body[trimmed:].lstrip()
                trimmed += len(fold(item.full_text)[trimmed:]) - len(body)

        hits = [h for h in exp.narrow_hits + exp.subject_hits + exp.intent_hits
                if h.start >= trimmed]
        focus = min((h.start - trimmed for h in hits), default=0)
        shown, offset = _excerpt(body, focus)
        spans = [(h.start - trimmed - offset, h.end - trimmed - offset) for h in hits]
        excerpt = QLabel(_highlighted(shown, spans, t.accent_hi))
        excerpt.setObjectName("cardBody")
        excerpt.setWordWrap(True)
        excerpt.setTextFormat(Qt.RichText)
        outer.addWidget(excerpt)

        # Why it is here, and the way to say "it shouldn't be".
        why = QHBoxLayout()
        why.setSpacing(t.s(4))
        # Chips list every match, including ones in the title.
        for hit in (exp.narrow_hits + exp.subject_hits + exp.intent_hits)[:6]:
            chip = PhraseChip(hit.phrase, self)
            chip.clicked.connect(lambda _c=False, p=hit.phrase: self.exclude_requested.emit(p))
            why.addWidget(chip, 0)
        score = QLabel(f"{lead.score:.1f}")
        score.setObjectName("cardScore")
        score.setToolTip("\n".join(exp.lines()))
        why.addStretch(1)
        why.addWidget(score, 0)
        outer.addLayout(why)


class DiscardCard(QFrame):
    """A post that did not survive, and the rule responsible.

    This view is the only way to see a *recall* problem. Without it, tuning is
    blind to everything the profile threw away.
    """

    def __init__(self, discarded: Discarded, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        t = theme
        self.setObjectName("discard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.s(9), t.s(5), t.s(9), t.s(5))
        lay.setSpacing(t.s(2))

        head = QLabel(discarded.item.title or (discarded.item.text or "")[:80])
        head.setObjectName("discardTitle")
        lay.addWidget(head)

        reason = QLabel(f"{discarded.stage}  ·  {discarded.reason}")
        reason.setObjectName("discardReason")
        reason.setWordWrap(True)
        lay.addWidget(reason)


class ResultsView(QWidget):
    """Leads and discards, with the counts, and what was not searched."""

    exclude_requested = Signal(str)

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self._t = theme
        self._result: ScanResult | None = None
        self._near: tuple[float, float] | None = None
        self._mode = "leads"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(theme.s(5))

        tabs = QHBoxLayout()
        tabs.setSpacing(theme.s(6))
        self.tab_leads = QPushButton("Leads")
        self.tab_discards = QPushButton("Discarded")
        for btn, mode in ((self.tab_leads, "leads"), (self.tab_discards, "discards")):
            btn.setObjectName("tab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFlat(True)
            btn.clicked.connect(lambda _c=False, m=mode: self.set_mode(m))
            tabs.addWidget(btn, 0)
        self.tab_leads.setChecked(True)
        tabs.addStretch(1)
        self.note = QLabel("")
        self.note.setObjectName("note")
        tabs.addWidget(self.note, 0)
        outer.addLayout(tabs)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("scroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, theme.s(4), 0)
        self._body_layout.setSpacing(theme.s(5))
        self._body_layout.addStretch(1)
        self.scroll.setWidget(self._body)
        outer.addWidget(self.scroll, 1)

    # -- content -------------------------------------------------------------

    def _clear(self) -> None:
        # deleteLater() is asynchronous: taking a card out of the layout leaves it
        # parented and painting until the event loop gets round to it, so switching
        # tabs drew the discards on top of the leads. Unparent immediately, then
        # let Qt free it.
        while self._body_layout.count() > 1:
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def natural_height(self) -> int:
        """How tall this wants to be, before the window caps it.

        Measured from the *layout*, not the widget: a widget's sizeHint is not
        settled in the same turn the cards are added to it, and asking too early
        reported a two-lead list as 30px tall.
        """
        self._body_layout.activate()
        return (self._body_layout.sizeHint().height()
                + self.tab_leads.sizeHint().height()
                + self._t.s(14))

    def set_near(self, near: tuple[float, float] | None) -> None:
        self._near = near

    def show_result(self, result: ScanResult) -> None:
        self._result = result
        self.tab_leads.setText(f"Leads  {len(result.leads)}")
        self.tab_discards.setText(f"Discarded  {len(result.discarded)}")
        # Silent omission of a source is a bug: say what was not searched.
        self.note.setText(
            "  ·  ".join(f"{v}: {why}" for v, why in result.unavailable.items())
            or f"{result.scanned} scanned"
        )
        self._render()

    mode_changed = Signal()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.tab_leads.setChecked(mode == "leads")
        self.tab_discards.setChecked(mode == "discards")
        self._render()
        self.mode_changed.emit()

    def _render(self) -> None:
        self._clear()
        if self._result is None:
            return
        if self._mode == "leads":
            for lead in self._result.leads:
                card = LeadCard(lead, self._t, self._body, near=self._near)
                card.exclude_requested.connect(self.exclude_requested)
                card.open_requested.connect(self._open)
                self._body_layout.insertWidget(self._body_layout.count() - 1, card)
            if not self._result.leads:
                self._empty("Nothing matched. Try a wider radius, a longer window, "
                            "or check Discarded to see what was thrown away.")
        else:
            for discarded in self._result.discarded:
                self._body_layout.insertWidget(
                    self._body_layout.count() - 1,
                    DiscardCard(discarded, self._t, self._body))
            if not self._result.discarded:
                self._empty("Nothing was discarded.")

    def _empty(self, message: str) -> None:
        label = QLabel(message)
        label.setObjectName("empty")
        label.setWordWrap(True)
        self._body_layout.insertWidget(self._body_layout.count() - 1, label)

    @staticmethod
    def _open(url: str) -> None:
        """Open the post in the user's own browser. Branch never contacts anyone."""
        if url:
            webbrowser.open(url)
