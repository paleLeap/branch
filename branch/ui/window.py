"""The single window.

Frameless, movable, resizable, translucent. Layout follows the mockup:

    [ query .................. ] [ Go, go, go. ]            [ _ ] [ X ]
    +-- panel ------------------------------------------------------+
    |  [Location] [Trade ]      [src] [src]                         |
    |  [Radius  ] [Within]      [src] [src]                         |
    |                           [src] [src]                         |
    |                           [src] [src]                         |
    +---------------------------------------------------------------+

    Nothing is outlined. Every control is a tray -- a darker, slightly
    transparent slab the text sits on, going less transparent on hover.

How results are displayed is deliberately not decided yet -- this is the control
surface only.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import (
    QEasingCurve, QObject, QPoint, QPropertyAnimation, QTimer, Qt, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGraphicsOpacityEffect, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import locate
from .results import ResultsView
from .theme import Size, Theme, rgba, stylesheet
from .widgets import (
    HouseComboBox, LocationEdit, PromptList, QueryEdit, SearchableCombo, SourceToggle,
    WindowButton,
)

# The four refine controls, in reading order: where, what, how wide, how recent.
# Location leads because it is the one the user checks first, and it is a text
# field rather than a dropdown -- 20,000 towns will not fit in a list.
REFINE_FIELDS: list[tuple[str, str, list[str]]] = [
    ("location", "Location",      []),           # text + suggestions
    ("trade",    "Trade",         []),           # filled from profiles/ at runtime
    ("radius",   "Radius",        ["5 miles", "10 miles", "25 miles", "50 miles",
                                   "100 miles", "250 miles"]),
    ("since",    "Posted within", ["Last hour", "Last 6 hours", "Last 24 hours",
                                   "Last 3 days", "Last week", "Last month"]),
]

# The eight source toggles. Availability is a per-adapter question, not a UI one;
# the window only reflects what the adapter layer reports.
SOURCES: list[tuple[str, str]] = [
    ("reddit", "Reddit"),
    ("craigslist", "Craigslist"),
    ("marketplace", "Marketplace"),
    ("forums", "Forums"),
    ("facebook", "Facebook"),
    ("groups", "FB Groups"),
    ("x", "X / Twitter"),
    ("feeds", "My feeds"),
    ("reviews", "Reviews"),
]

class PositionProbe(QObject):
    """Finds roughly where we are, off the UI thread.

    The lookup can take a few seconds or hang on a blocked network, and the window
    must open instantly either way. It is fire-and-forget: if it never returns, the
    location field simply stays empty and the user types a city.
    """

    found = Signal(float, float)

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        fix = locate.detect()
        if fix is not None:
            self.found.emit(fix.lat, fix.lon)


class MainWindow(QWidget):
    scan_requested = Signal(dict)
    exclusion_requested = Signal(str)
    browser_harvested = Signal(list)
    #: (service, url) -- the user pressed "Sign in to Facebook". The app opens
    #: Branch's own browser on that page; Branch never sees what is typed there.
    login_requested = Signal(str, str)
    #: A sign-in state was learned, so the source sections need re-reading.
    login_finished = Signal()

    def __init__(self, trades: list[str] | None = None, theme: Theme | None = None,
                 trade_slugs: dict[str, str] | None = None,
                 trade_prompts: dict[str, list[str]] | None = None) -> None:
        super().__init__()
        self.theme = theme or Theme.load()
        # display label -> profile slug, so the engine gets the profile and the
        # user sees "Wedding Photography" rather than "wedding-photography".
        self._trade_slugs = dict(trade_slugs or {})
        # display label -> example narrowings, from each profile's `suggestions:`
        self._trade_prompts = {k: list(v) for k, v in (trade_prompts or {}).items()}
        self._drag_offset: QPoint | None = None
        self._resize_edges = Qt.Edges()
        self._combos: dict[str, QComboBox] = {}
        self._sources: dict[str, SourceToggle] = {}
        # key -> SourceState, so current_query() can refuse to send a source
        # that cannot run even if something ticked it programmatically.
        self._source_states: dict = {}

        t = self.theme
        self.setWindowTitle("Branch")
        # Frameless: "there shouldn't be a header or window bar if possible."
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setStyleSheet(stylesheet(t))

        self._build(trades or [])
        self._build_prompt_list()

        self.setMinimumSize(t.s(Size.window_w * 0.7), t.s(Size.window_h * 0.7))
        self._fit_window()
        self.resize(max(self.width(), t.s(Size.window_w)), self.height())
        self._position_controls()

        # Fill the location field with the nearest major city, if we can work out
        # where we are. Never overwrites what the user has typed.
        self._probe = PositionProbe(self)
        self._probe.found.connect(self.location.set_near)
        self._probe.start()

    # -- construction --------------------------------------------------------

    def _build(self, trades: list[str]) -> None:
        t = self.theme
        pad = t.s(Size.pad)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(t.s(Size.gap))

        outer.addLayout(self._build_top_row(), 0)
        outer.addWidget(self._build_panel(trades), 0)

        # Hidden until a scan returns; the window grows to fit it and shrinks back
        # when results are cleared. The controls stay put at the top so the query
        # can be adjusted and re-run while reading what came back.
        self.results = ResultsView(t, self)
        self.results.exclude_requested.connect(self._exclude_phrase)
        self.results.mode_changed.connect(lambda: QTimer.singleShot(0, self._fit_results))
        self.results.hide()
        outer.addWidget(self.results, 1)
        # Nothing stretches. The panel is exactly as tall as its controls, and the
        # window starts exactly as tall as the panel -- the previous version left a
        # band of empty slab under everything.
        outer.addStretch(0)

    def _build_top_row(self) -> QHBoxLayout:
        t = self.theme
        row = QHBoxLayout()
        row.setSpacing(t.s(Size.gap))

        self.query = QueryEdit(t)
        # No placeholder: the suggestion list answers "what do I type here?"
        # better than a greyed-out sentence, and it answers it per trade.
        self.query.returnPressed.connect(self._emit_scan)
        # Fixed width, not the whole top row. The empty space to its right is
        # deliberate: on a frameless window it is the drag handle.
        self.query.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.query.setFixedSize(t.s(Size.query_w), t.s(Size.query_h))
        row.addWidget(self.query, 0)

        # Just the text. No pill, no border, no fill.
        self.go = QPushButton("Go, go, go.")
        self.go.setObjectName("go")
        self.go.setCursor(Qt.PointingHandCursor)
        self.go.setFlat(True)
        self.go.setFixedHeight(t.s(Size.query_h))
        self.go.clicked.connect(self._emit_scan)
        row.addWidget(self.go, 0)          # directly to the right of the query
        row.addStretch(1)

        # The minimise and close glyphs are NOT in the layout. They belong in the
        # true top-right corner of the window, and a layout would inset them by
        # the window padding and centre them on the query row instead.
        self._build_window_controls()
        return row

    def _build_window_controls(self) -> QWidget:
        """Minimise and close, hidden until the window is hovered.

        A free-floating child pinned to the corner by _position_controls(), not a
        layout item.
        """
        t = self.theme
        holder = QWidget(self)
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(t.s(2))

        self.btn_min = WindowButton("minimize", t, holder)
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_close = WindowButton("close", t, holder)
        self.btn_close.clicked.connect(self.close)
        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_close)

        # Fade the pair in and out rather than hiding them, so the layout never shifts.
        self._controls_fx = QGraphicsOpacityEffect(holder)
        self._controls_fx.setOpacity(0.0)
        holder.setGraphicsEffect(self._controls_fx)
        self._controls_anim = QPropertyAnimation(self._controls_fx, b"opacity", self)
        self._controls_anim.setDuration(int(self.theme.motion_speed))
        self._controls_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Qt's enter/leave events are not reliable for this: the window gets a
        # leave when the pointer moves onto one of its own children, and on X11 a
        # leave can be missed entirely when the pointer jumps to another window --
        # which left the glyphs showing for as long as the window stayed active.
        # Polling the actual cursor position is the only version that is always
        # right, and at 120ms it costs nothing.
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(120)
        self._hover_timer.timeout.connect(self._sync_controls)
        self._controls_shown = False

        self._controls = holder
        holder.adjustSize()
        holder.raise_()
        return holder

    def _build_panel(self, trades: list[str]) -> QFrame:
        t = self.theme
        pad = t.s(Size.pad)
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMouseTracking(True)
        # Exactly as tall as its controls need, and never shorter. A QFrame
        # defaults to Preferred, which lets a parent squeeze it below its own
        # hint -- and a squeezed grid of fixed-height pills does not clip, it
        # draws them on top of each other. That is what shipped.
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay = QHBoxLayout(panel)
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(t.s(Size.column_gap))

        lay.addLayout(self._build_refine(trades), 1)

        # The sources go in a widget of their own, not a bare layout, so their
        # height can be pinned to what they actually need. A word-wrapped label
        # in that column makes Qt under-report the minimum height of everything
        # above it, and the shortfall lands on the grid of fixed-height pills --
        # which overlap rather than clip. Pinning the wrapper is what stops it.
        self._sources_panel = QWidget()
        self._sources_panel.setMouseTracking(True)
        self._sources_panel.setLayout(self._build_sources())
        self._sources_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay.addWidget(self._sources_panel, 1)
        return panel

    def _build_refine(self, trades: list[str]) -> QGridLayout:
        """The four refine controls, 2x2. Location is a text field, not a combo."""
        t = self.theme
        grid = QGridLayout()
        grid.setHorizontalSpacing(t.s(Size.gap))
        grid.setVerticalSpacing(t.s(Size.gap))

        for i, (key, label, options) in enumerate(REFINE_FIELDS):
            cell = QVBoxLayout()
            cell.setSpacing(t.s(2))
            cap = QLabel(label)
            cap.setObjectName("fieldLabel")

            if key == "location":
                field = LocationEdit(t)
                field.returnPressed.connect(self._emit_scan)
                self.location = field
            elif key == "trade":
                # Typeable as well as browsable, and blank until chosen.
                field = SearchableCombo(t)
                field.addItems(trades)
                field.setEnabled(bool(trades))
                field.currentTextChanged.connect(self._trade_changed)
                self._combos[key] = field
            else:
                field = HouseComboBox(t)
                field.addItems(options)
                field.setCurrentIndex(2)          # 25 miles / last 24 hours
                self._combos[key] = field
            field.setFixedHeight(t.s(Size.combo_h))

            cell.addWidget(cap)
            cell.addWidget(field)
            grid.addLayout(cell, i // 2, i % 2)

        # The source column is taller than this one now that it is grouped, and
        # without this the two rows drift apart to fill the height.
        grid.setRowStretch(len(REFINE_FIELDS) // 2, 1)
        return grid

    def _build_sources(self) -> QVBoxLayout:
        """The source column: one grid of pills and nothing else.

        It carried two lines of standing text -- the sign-in links and an
        "Unavailable:" line -- and they were wrong twice over. They took two rows
        of the window permanently to answer a question asked about twice, and
        they read as clutter next to the toggles they described.

        Every source is a pill, and every pill is clickable. One that cannot run
        says why **when you click it**, in a window that offers the link that
        fixes it and then goes away. See ui/notice.py.
        """
        t = self.theme
        box = QVBoxLayout()
        box.setSpacing(t.s(2))

        for key, label in SOURCES:
            btn = SourceToggle(label)
            btn.setFixedHeight(t.s(Size.pill_h))
            # Reddit and Craigslist need no account and no configuration, and
            # both are local by construction -- so they are the two that are on
            # before the user touches anything.
            btn.setChecked(key in ("reddit", "craigslist"))
            btn.clicked.connect(lambda _=False, k=key: self._source_clicked(k))
            self._sources[key] = btn

        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(t.s(Size.tight))
        self._grid.setVerticalSpacing(t.s(Size.tight))
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        box.addLayout(self._grid)
        box.addStretch(1)

        self._lay_out_sources([key for key, _ in SOURCES])
        return box

    def _lay_out_sources(self, keys: list[str]) -> None:
        """Fill the grid, two across, in the order SOURCES declares."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        for i, key in enumerate(keys):
            self._sources[key].setVisible(True)
            self._grid.addWidget(self._sources[key], i // 2, i % 2)
        self._pin_sources_height()

    def _pin_sources_height(self) -> None:
        """Make the column exactly as tall as its contents, measured not guessed.

        Without this the panel can be handed less height than the grid needs --
        `adjustSize()` clamps a window to two thirds of the screen -- and a grid
        of fixed-height pills does not clip when squeezed, it draws them on top
        of each other. That shipped once; the tests at five ui_scales are here
        because of it.
        """
        panel = getattr(self, "_sources_panel", None)
        # The first lay-out runs while the column is still being built, before
        # its layout is attached to the wrapper. Nothing to pin yet.
        if panel is None or panel.layout() is None:
            return
        panel.layout().invalidate()
        panel.layout().activate()
        panel.setFixedHeight(panel.layout().sizeHint().height())

    def _source_clicked(self, key: str) -> None:
        """A source that cannot run explains itself here, rather than in two
        lines of text that sit in the window forever."""
        state = self._source_states.get(key)
        btn = self._sources.get(key)
        if state is None or state.selectable and state.state == "ready":
            return                              # an ordinary toggle; let it be
        if btn is not None:
            btn.setChecked(False)               # it cannot be scanned yet
        self._show_source_notice(state)

    def _show_source_notice(self, state) -> None:
        from .notice import LOGIN_MESSAGE, SourceNotice, open_externally
        gated = state.state == "login"
        dialog = SourceNotice(
            self.theme,
            title=state.label,
            message=LOGIN_MESSAGE if gated else state.reason,
            link=state.login_url if gated else "",
            link_label=f"Open {state.service} sign-in" if gated else "",
            parent=self)
        if dialog.exec() != dialog.Accepted or not dialog.link:
            return
        if gated:
            # Branch's own browser, not the system one: the session a scan uses
            # is this window's, and signing in anywhere else does nothing here.
            self.login_requested.emit(state.service, dialog.link)
        else:
            open_externally(dialog.link)

    def _fit_window(self) -> None:
        """Size to the content, and make Qt refuse to go below it.

        `adjustSize()` alone is not enough, and neither is measuring once:

        - Qt clamps `adjustSize()` to two thirds of the screen. A window clamped
          below its minimum does not scroll or clip -- a grid of fixed-height
          pills simply draws them on top of each other, which is what shipped.
        - `minimumSizeHint()` read straight after re-filling a layout is stale;
          the layout has not recalculated yet, so it under-reports and the
          resize that follows is too small.

        So: activate the layout first, then set a real minimum height, which Qt
        then enforces against every later resize -- including the user dragging
        the window smaller.
        """
        layout = self.layout()
        if layout is not None:
            layout.activate()
        needed = self.minimumSizeHint()
        self.setMinimumHeight(needed.height())
        self.adjustSize()
        self.resize(max(self.width(), needed.width()),
                    max(self.height(), needed.height()))

    # -- query ---------------------------------------------------------------

    def _build_prompt_list(self) -> None:
        """The suggestion list, as a child widget drawn over the panel.

        Shown whenever the empty search box has focus and a trade is chosen, and
        hidden the moment the user types or clicks away -- which is what a popup
        would have done, without a popup's grab.
        """
        self._prompt_list = PromptList(self.theme, self)
        self._prompt_list.chosen.connect(self._prompt_chosen)
        self.query.focused.connect(self._maybe_show_prompts)
        self.query.blurred.connect(self._prompt_list.hide)
        self.query.textEdited.connect(lambda _t: self._prompt_list.hide())

    def _maybe_show_prompts(self) -> None:
        if self.query.text().strip():
            return
        t = self.theme
        below = self.height() - self.query.geometry().bottom() - t.s(Size.pad) * 2
        self._prompt_list.show_beneath(self.query, max(t.s(40), below))

    def _prompt_chosen(self, text: str) -> None:
        self.query.setText(text)
        self._prompt_list.hide()
        self.query.setFocus(Qt.OtherFocusReason)

    def _trade_changed(self, label: str) -> None:
        """Re-point the search box's suggestions at the chosen trade."""
        prompts = self._trade_prompts.get(label.strip(), [])
        self.query.set_prompts(prompts)
        self._prompt_list.set_prompts(prompts)
        if self.query.hasFocus():
            self._maybe_show_prompts()

    def current_query(self) -> dict:
        city = self.location.city()
        return {
            # The narrowing, not a description of who to look for -- see
            # engine.scan()'s docstring. Empty means "every lead for this trade".
            "narrow": self.query.text().strip(),
            "location": self.location.text().strip(),
            # None when the field is not a place we know -- the caller decides
            # whether to refuse the scan or widen it.
            "coordinates": (city.lat, city.lon) if city else None,
            **{k: c.currentText().strip() for k, c in self._combos.items()},
            "trade_slug": self._trade_slugs.get(self._combos["trade"].currentText().strip())
            if "trade" in self._combos else None,
            # A source that cannot run is never sent, even if something ticked
            # it before the adapters reported in. Scanning a dead source and
            # reporting nothing is exactly the silent failure this avoids.
            "sources": [k for k, b in self._sources.items()
                        if b.isChecked() and self._can_run(k)],
        }

    def _can_run(self, key: str) -> bool:
        state = self._source_states.get(key)
        return True if state is None else state.selectable

    def _emit_scan(self) -> None:
        self._prompt_list.hide()
        self.scan_requested.emit(self.current_query())

    def browse(self, targets: list[tuple[str, str, str]]) -> None:
        """Open the harvest browser for sources that need a logged-in session.

        Deferred import: QtWebEngine pulls in a large chunk of Chromium, and a
        user who never ticks Facebook should never pay for loading it.
        """
        if not targets:
            return
        self._browser_window()
        self._browser.resize(self.theme.s(1400), self.theme.s(1000))
        key, url, label = targets[0]
        self._pending_browse = targets[1:]
        # A source may offer several searches; one returns about four results and
        # then stops growing, so depth comes from asking more than one question.
        queue = list(getattr(self, "_browse_queue", {}).get(key) or [])
        if queue:
            self._browser.harvest_all(queue, key)
        else:
            self._browser.harvest(url, key, label)

    def open_login(self, service: str, url: str) -> None:
        """Open Branch's browser on a service's sign-in page and nothing else."""
        self._browser_window().open_login(service, url)

    def _browser_window(self):
        """The one harvest browser, made on first use.

        Deferred import for the same reason browse() defers it: QtWebEngine is a
        large chunk of Chromium, and a user who never touches Facebook should
        never pay to load it.
        """
        from .browser import HarvestBrowser
        if getattr(self, "_browser", None) is None:
            self._browser = HarvestBrowser(self.theme, self)
            self._browser.harvested.connect(self.browser_harvested)
            # The browser is hidden, so its progress has to show up here instead.
            self._browser.progress.connect(self._browsing_progress)
            self._browser.signed_in.connect(self._record_sign_in)
        return self._browser

    def _record_sign_in(self, service: str, connected: bool) -> None:
        """The browser learned whether a session is signed in. Remember the one
        bit, and re-read the source sections so the window agrees with it."""
        from .. import accounts
        if accounts.connected(service.lower()) == connected:
            return                     # nothing changed; no need to rebuild
        accounts.mark(service, connected)
        self.login_finished.emit()

    def set_browse_queue(self, queue: dict) -> None:
        self._browse_queue = dict(queue)

    def _browsing_progress(self, message: str) -> None:
        count = "".join(ch for ch in message.split(" ")[1:2][0] if ch.isdigit()) \
            if message.startswith("Read ") else ""
        self.go.setText(f"Searching... {count}" if count else "Searching...")

    def scan_started(self) -> None:
        """A scan is in flight. It runs on a worker thread, so the window stays
        live -- this only says so."""
        self.go.setText("Searching...")
        self.go.setEnabled(False)

    def show_result(self, result) -> None:
        """Display a finished scan, growing the window to make room."""
        self.go.setText("Go, go, go.")
        self.go.setEnabled(True)
        if not self.results.isVisible():
            self._collapsed_height = self.height()
            self.results.show()
        self.results.set_near(self.location.city() and
                              (self.location.city().lat, self.location.city().lon))
        self.results.show_result(result)
        # One turn later: freshly-created cards have not laid themselves out yet,
        # so measuring now reports a two-lead list as a few pixels tall.
        QTimer.singleShot(0, self._fit_results)

    def _fit_results(self) -> None:
        """Grow to fit what came back, capped so a hundred leads do not fill the
        screen. Two leads should not leave a band of empty slab under them."""
        if not self.results.isVisible():
            return
        wanted = self._collapsed_height + min(self.results.natural_height(),
                                              self.theme.s(Size.results_h))
        self.resize(self.width(), wanted)
        self._position_controls()

    def clear_results(self) -> None:
        if not self.results.isVisible():
            return
        self.results.hide()
        self._fit_window()
        self.resize(self.width(), max(getattr(self, "_collapsed_height", self.height()),
                                      self.minimumSizeHint().height()))
        self._position_controls()

    def _exclude_phrase(self, phrase: str) -> None:
        """The user pointed at the word that made a bad lead match."""
        self.exclusion_requested.emit(phrase)

    def set_source_states(self, states: dict) -> None:
        """The adapter layer reporting in: what each source can do right now.

        Every source stays in the grid and stays clickable. What changes is what
        a click does -- scan, or explain itself. Nothing is hidden, and nothing
        is dimmed into looking broken either: a source needing a sign-in is one
        click from being usable, and that is not the same as a dead one.
        """
        self._source_states = dict(states)
        for key, _label in SOURCES:
            state = states.get(key)
            btn = self._sources.get(key)
            if btn is None:
                continue
            if state is None:
                btn.setToolTip("")
                continue
            btn.setToolTip(state.reason)
            if state.state != "ready":
                btn.setChecked(False)
        self._pin_sources_height()
        if not self.results.isVisible():
            self._fit_window()
        self._position_controls()

    def set_source_available(self, key: str, available: bool, reason: str = "") -> None:
        """The older, coarser way to say the same thing: available or not.

        Kept because it is the smallest possible statement a caller can make, and
        because "unavailable" is still the right answer for a source that simply
        cannot be reached. Anything that knows *why* -- a missing sign-in in
        particular -- should call set_source_states() instead and say so.
        """
        btn = self._sources.get(key)
        if btn is None:
            return
        btn.setEnabled(available)
        if not available:
            btn.setChecked(False)
        btn.setToolTip(reason if reason else "")

    # -- frameless window behaviour -----------------------------------------

    def _edges_at(self, pos: QPoint) -> Qt.Edges:
        margin = self.theme.s(Size.resize_margin)
        edges = Qt.Edges()
        if pos.x() <= margin:
            edges |= Qt.LeftEdge
        if pos.x() >= self.width() - margin:
            edges |= Qt.RightEdge
        if pos.y() <= margin:
            edges |= Qt.TopEdge
        if pos.y() >= self.height() - margin:
            edges |= Qt.BottomEdge
        return edges

    @staticmethod
    def _cursor_for(edges: Qt.Edges) -> Qt.CursorShape:
        if (edges & Qt.LeftEdge and edges & Qt.TopEdge) or (edges & Qt.RightEdge and edges & Qt.BottomEdge):
            return Qt.SizeFDiagCursor
        if (edges & Qt.RightEdge and edges & Qt.TopEdge) or (edges & Qt.LeftEdge and edges & Qt.BottomEdge):
            return Qt.SizeBDiagCursor
        if edges & (Qt.LeftEdge | Qt.RightEdge):
            return Qt.SizeHorCursor
        if edges & (Qt.TopEdge | Qt.BottomEdge):
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        edges = self._edges_at(pos)
        if edges:
            # Qt's own system resize: correct on every platform and DPI, and it
            # avoids the jitter a hand-rolled resize loop produces on Wayland.
            handle = self.windowHandle()
            if handle is not None:
                self._resize_edges = edges
                handle.startSystemResize(edges)
                return
        # Anywhere else on the background drags the window. Child widgets consume
        # their own clicks, so reaching here means the background was hit.
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            return
        self.setCursor(self._cursor_for(self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        self._resize_edges = Qt.Edges()
        super().mouseReleaseEvent(event)

    # -- hover and focus -----------------------------------------------------

    def _fade_controls(self, target: float) -> None:
        self._controls_anim.stop()
        self._controls_anim.setStartValue(self._controls_fx.opacity())
        self._controls_anim.setEndValue(target)
        self._controls_anim.start()

    def _position_controls(self) -> None:
        inset = self.theme.s(Size.wbtn_inset)
        self._controls.adjustSize()
        self._controls.move(self.width() - self._controls.width() - inset, inset)
        self._controls.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_controls()

    def showEvent(self, event) -> None:
        # Qt defers resize events for a hidden widget, so a window resized before
        # it is shown would open with the glyphs at their old position.
        super().showEvent(event)
        self._position_controls()
        self._hover_timer.start()

    def hideEvent(self, event) -> None:
        self._hover_timer.stop()
        self._hide_popups()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._hover_timer.stop()
        self._hide_popups()
        super().closeEvent(event)

    def _pointer_inside(self) -> bool:
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _sync_controls(self) -> None:
        """Show the glyphs when the pointer is over the window, and only then.

        Being the active window is not enough -- that was the bug.
        """
        wanted = self._pointer_inside() and self.isVisible()
        if wanted == self._controls_shown:
            return
        self._controls_shown = wanted
        self._fade_controls(1.0 if wanted else 0.0)
        if not wanted:
            self.unsetCursor()

    def enterEvent(self, event) -> None:
        self._sync_controls()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._sync_controls()
        super().leaveEvent(event)

    def _hide_popups(self) -> None:
        """Close anything holding a pointer grab. A completer popup that outlives
        its window is what made the desktop unclickable."""
        self._prompt_list.hide()
        for widget in (self.query, self.location):
            widget.completer().popup().hide()
        for combo in self._combos.values():
            combo.hidePopup()
            if combo.completer() is not None:
                combo.completer().popup().hide()

    def changeEvent(self, event) -> None:
        """Slightly transparent when active, more transparent when not."""
        if event.type() == event.Type.ActivationChange:
            if not self.isActiveWindow():
                self._hide_popups()
                self._sync_controls()
            self.update()   # the slab alpha changes; see paintEvent
        super().changeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            if self._prompt_list.isVisible():
                self._prompt_list.hide()
                return
            if self.results.isVisible():
                self.clear_results()
                return
            self.close()
        super().keyPressEvent(event)

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        """The house glass: a tinted slab under a hairline edge and a top glow.

        link and plinth get this from picom blurring what shows through, so a low
        alpha reads as frosted rather than as a hole. Qt has no blur of its own,
        so the alpha here sits higher than link's .61 -- otherwise the window
        looks thin rather than frosted. Idle drops it, which is the
        "more transparent when not active" the brief asked for.
        """
        t = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        radius = t.s(t.corner_radius)
        rect = self.rect().adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        alpha = float(t.slab_alpha if self.isActiveWindow() else t.slab_alpha_idle)
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, QColor(rgba(t.slab_tint, alpha)))
        grad.setColorAt(0.55, QColor(rgba(t.slab_tint, alpha * 0.92)))
        grad.setColorAt(1.0, QColor(rgba(t.slab_bottom, alpha * 1.05)))
        painter.fillPath(path, QBrush(grad))

        # A hairline edge, kept faint: picom cuts the same radius, so anything
        # heavier draws right on the seam between our paint and its cut.
        painter.setPen(QPen(QColor(rgba(t.foreground, 0.06)), 1))
        painter.drawPath(path)

        # inset 0 1px 0 rgba(foreground, top_glow) -- the family's top highlight
        glow = QPainterPath()
        glow.addRoundedRect(rect.adjusted(radius * 0.4, 0.5, -radius * 0.4, 0), 0, 0)
        painter.setPen(QPen(QColor(rgba(t.foreground, float(t.top_glow))), 1))
        painter.drawLine(int(rect.left() + radius * 0.4), int(rect.top() + 1),
                         int(rect.right() - radius * 0.4), int(rect.top() + 1))
        painter.end()
