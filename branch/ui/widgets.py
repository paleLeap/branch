"""Custom widgets: the frameless window's own controls."""
from __future__ import annotations

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QSize, QTimer, Qt, Signal,
)
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtCore import QStringListModel, Signal
from PySide6.QtWidgets import (
    QCompleter, QComboBox, QLineEdit, QListWidget, QPushButton, QWidget,
)

from .. import places
from .theme import Size, Theme, popup_stylesheet


class WindowButton(QWidget):
    """A minimise or close glyph. No box, no chrome -- just the mark.

    Hover is link's `.wbtn` treatment: a faint rounded wash behind the glyph and
    the glyph itself coming up from dim to full. Same shape, same softness, so
    this window's chrome behaves like the rest of the family's.
    """

    clicked = Signal()

    def __init__(self, kind: str, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind                      # "close" | "minimize"
        self._t = theme
        self._glow = 0.0
        side = theme.s(Size.wbtn)
        self.setFixedSize(QSize(side, side))
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip("Close" if kind == "close" else "Minimise")

        self._anim = QPropertyAnimation(self, b"glow", self)
        self._anim.setDuration(int(theme.motion_speed))
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def get_glow(self) -> float:
        return self._glow

    def set_glow(self, value: float) -> None:
        self._glow = value
        self.update()

    glow = Property(float, get_glow, set_glow)

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._glow)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event) -> None:
        self._animate_to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_to(0.0)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        t = self._t
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.rect()

        if self._glow > 0.01:
            wash = QColor(t.foreground)
            wash.setAlphaF(0.07 * self._glow)
            painter.setPen(Qt.NoPen)
            painter.setBrush(wash)
            painter.drawRoundedRect(r, t.s(8), t.s(8))

        colour = QColor(t.foreground_dim)
        colour.setAlphaF(0.75 + 0.25 * self._glow)
        if self._glow > 0.5:
            colour = QColor(t.foreground)
            colour.setAlphaF(0.55 + 0.45 * self._glow)
        painter.setPen(QPen(colour, max(1, t.s(1.4)), Qt.SolidLine, Qt.RoundCap))

        glyph = t.s(Size.wbtn_glyph)
        box = r.adjusted((r.width() - glyph) // 2, (r.height() - glyph) // 2,
                         -(r.width() - glyph) // 2, -(r.height() - glyph) // 2)
        if self._kind == "close":
            painter.drawLine(box.topLeft(), box.bottomRight())
            painter.drawLine(box.topRight(), box.bottomLeft())
        else:
            y = box.center().y()
            painter.drawLine(box.left(), y, box.right(), y)
        painter.end()


class SourceToggle(QPushButton):
    """One platform to search, with a mark saying whether it can be.

    The mark answers "why is nothing happening when I tick this?" before it is
    asked, and it answers it at a glance across the whole grid:

        tick  this works right now
        !     this needs an account before it can do anything
        ?     this cannot run; click to find out what it is and why

    Painted rather than added to the label. Put in the text it would shift each
    name off its own left edge by a different amount and the column would stop
    reading as a column -- the same reason the combo chevron is painted.
    """

    #: The three states a source can be in, as the window shows them.
    READY, NEEDS_ACCOUNT, UNAVAILABLE = "ready", "login", "unavailable"

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(label, parent)
        self.setObjectName("source")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._state = self.READY
        self._t: Theme | None = None

    def set_state(self, state: str, theme: "Theme | None" = None) -> None:
        if theme is not None:
            self._t = theme
        self._state = state
        self.update()

    @property
    def state(self) -> str:
        return self._state

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        theme, mark = self._t, self._mark()
        if theme is None or not mark:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colour = QColor(theme.accent_hi if self._state == self.READY
                        else theme.foreground_dim)
        # The tick is the quiet one: it says "nothing to do here". The other two
        # are asking for attention and sit at full strength.
        colour.setAlphaF(0.75 if self._state == self.READY else 1.0)
        painter.setPen(colour)
        font = painter.font()
        # The theme sizes fonts in PIXELS, so pointSizeF() is -1 here and
        # scaling it produces a negative size Qt refuses. Scale whichever one
        # this font actually uses.
        scale = 0.88 if mark == "\u2713" else 1.0
        if font.pixelSize() > 0:
            font.setPixelSize(max(6, round(font.pixelSize() * scale)))
        elif font.pointSizeF() > 0:
            font.setPointSizeF(max(6.0, font.pointSizeF() * scale))
        font.setBold(mark != "\u2713")
        painter.setFont(font)
        inset = theme.s(6)
        painter.drawText(self.rect().adjusted(0, 0, -inset, 0),
                         Qt.AlignRight | Qt.AlignVCenter, mark)
        painter.end()

    def _mark(self) -> str:
        return {self.READY: "\u2713",          # tick
                self.NEEDS_ACCOUNT: "!",
                self.UNAVAILABLE: "?"}.get(self._state, "")


class ActivityDot(QWidget):
    """Proof that the program is alive, next to what it is doing.

    A scan takes anywhere from a few seconds to two minutes -- measured on a
    clean install: 115 seconds, most of it Reddit rate-limit backoff. For all of
    that the button said "Searching..." and nothing else, and **a working scan
    looked exactly like a hung one**. He could not tell whether to wait or
    restart it, which is the complaint this answers.

    Static text cannot answer it, because a frozen app shows static text too.
    Only motion proves the program is still running -- and because the animation
    is driven by Qt's event loop, it stops the moment the UI thread blocks. That
    is the point: if the dot is moving, the window is alive. Scanning happens on
    a worker thread, so during a real scan it keeps moving.

    Three dots filling and fading in turn. No spinner, no progress bar: a bar
    would have to claim a percentage, and a scan cannot know one -- how many
    posts a source will return is not knowable until it has returned them.
    """

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self._t = theme
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._step)
        side = theme.s(Size.query_h)
        self.setFixedSize(QSize(theme.s(26), side))
        self.hide()

    def start(self) -> None:
        self._phase = 0.0
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def _step(self) -> None:
        self._phase = (self._phase + 0.18) % 3.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = max(1.0, self._t.s(2.0))
        gap = self._t.s(7)
        total = gap * 2
        x = (self.width() - total) / 2.0
        y = self.height() / 2.0
        for i in range(3):
            # Distance from the travelling phase, wrapped, so the pulse runs
            # round rather than bouncing.
            offset = abs(((self._phase - i + 1.5) % 3.0) - 1.5)
            strength = max(0.0, 1.0 - offset / 1.5)
            colour = QColor(self._t.accent_hi)
            colour.setAlphaF(0.22 + 0.78 * strength)
            painter.setBrush(QBrush(colour))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(x + i * gap, y), radius, radius)
        painter.end()


class HouseComboBox(QComboBox):
    """A combo that draws its own chevron.

    Qt's ``::down-arrow`` border-triangle trick renders as a plain white square
    on this platform, which is how the first draft of this window ended up with
    four bright blocks down the middle of the panel. Painting the mark directly
    also lets it match the 1.7-weight round-capped stroke the family's SVG icons
    use, instead of approximating it with CSS borders.
    """

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self._t = theme
        self.setCursor(Qt.PointingHandCursor)
        self.setMaxVisibleItems(8)
        # The popup is its own top-level window; the main stylesheet never
        # reaches it, so it has to be styled directly or it renders plain white.
        self.view().setStyleSheet(popup_stylesheet(theme))
        self.view().setFont(self.font())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        t = self._t
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        colour = QColor(t.foreground if self.underMouse() else t.foreground_dim)
        colour.setAlphaF(1.0 if self.isEnabled() else 0.4)
        painter.setPen(QPen(colour, max(1, t.s(1.4)), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

        w = t.s(7)
        h = t.s(3.5)
        cx = self.width() - t.s(11)
        cy = self.height() // 2
        painter.drawLine(cx - w // 2, cy - h // 2, cx, cy + h // 2)
        painter.drawLine(cx, cy + h // 2, cx + w // 2, cy - h // 2)
        painter.end()


class LocationEdit(QLineEdit):
    """The location field: a text box that suggests real places as you type.

    Not a dropdown -- the list of towns a person might serve is 20,000 long, so
    the only workable control is typing with suggestions. Matches are ranked by
    proximity to the detected position, so "Dal" from north Texas offers
    Dallas, TX before Dallas, OR.
    """

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("location")
        self._t = theme
        self._near: tuple[float, float] | None = None
        self._user_typed = False

        self._model = QStringListModel([], self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._completer.setMaxVisibleItems(8)
        popup = self._completer.popup()
        popup.setObjectName("completer")
        # Same reason as HouseComboBox: a popup is a top-level window and does not
        # inherit the main stylesheet. Without this it is a white list box.
        popup.setStyleSheet(popup_stylesheet(theme))
        popup.setFont(self.font())
        self.setCompleter(self._completer)

        self.textEdited.connect(self._on_edited)

    # -- detected position ---------------------------------------------------

    def set_near(self, lat: float, lon: float) -> None:
        """Called when the position probe returns. Never overwrites typing."""
        self._near = (lat, lon)
        if self._user_typed or self.text().strip():
            return
        city = places.nearest_major_city(lat, lon)
        if city is not None:
            self.setText(city.label)

    def city(self):
        """The field resolved back to a real place, or None if it is not one."""
        return places.find(self.text())

    def focusOutEvent(self, event) -> None:
        self._completer.popup().hide()
        super().focusOutEvent(event)

    # -- suggestions ---------------------------------------------------------

    def _on_edited(self, text: str) -> None:
        self._user_typed = True
        matches = places.suggest(text, near=self._near, limit=8)
        labels = [c.label for c in matches]
        self._model.setStringList(labels)
        if not labels or not text.strip():
            return

        # Qt sizes the popup to the field, which truncates "Fort Worth, TX" to
        # "Fort Wor...". Widen it to the longest entry -- a suggestion you cannot
        # read is not a suggestion.
        popup = self._completer.popup()
        metrics = popup.fontMetrics()
        widest = max(metrics.horizontalAdvance(label) for label in labels)
        popup.setMinimumWidth(max(self.width(), widest + self._t.s(24)))
        self._completer.complete()


class SearchableCombo(HouseComboBox):
    """A combo you can also type into.

    Trade is a list that grows every time someone drops a profile in `profiles/`,
    so it needs both affordances: open it to see what exists, or type "plumb" and
    have it complete. It starts blank -- an unmade choice should look unmade
    rather than silently defaulting to whichever trade sorts first.
    """

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(theme, parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.lineEdit().setPlaceholderText("")

        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)   # "photo" should find Wedding Photography
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.popup().setStyleSheet(popup_stylesheet(theme))
        completer.popup().setFont(self.font())
        self.setCompleter(completer)

    def addItems(self, texts) -> None:
        super().addItems(texts)
        self.setCurrentIndex(-1)      # blank until chosen
        self.setEditText("")

    def value(self) -> str:
        return self.currentText().strip()


class QueryEdit(QLineEdit):
    """The search box, with suggested prompts for the chosen trade.

    Emits `focused` / `blurred` so the window can show and hide its PromptList.

    The box is easy to misread, so the suggestions exist to teach it. It does not
    describe *who* you are looking for -- the Trade profile already does that, and
    it encodes far more than a sentence could. What goes here is a **narrowing**:
    a symptom or a part. Leave it empty and you get every lead for the trade.

    Suggestions appear as you type, and the placeholder names a real example for
    the chosen trade so the question is answered before a key is pressed.

    The popup is NEVER opened programmatically on focus. A Qt completer popup takes
    a mouse and keyboard grab; opening one in response to focus rather than to a
    keystroke left that grab held with nothing to dismiss it, and the desktop could
    not be clicked at all until a suggestion was chosen. A popup may only ever be
    raised by the user typing.
    """

    focused = Signal()
    blurred = Signal()

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("query")
        self._t = theme
        self._model = QStringListModel([], self)

        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._completer.setMaxVisibleItems(8)
        self._completer.popup().setStyleSheet(popup_stylesheet(theme))
        self._completer.popup().setFont(self.font())
        self.setCompleter(self._completer)

    def set_prompts(self, prompts: list[str]) -> None:
        """Called when the trade changes. Empty list disables the suggestions."""
        prompts = list(prompts)
        self._model.setStringList(prompts)
        # The placeholder does the teaching the focus-popup used to do, without
        # taking a grab: a real example, from the trade actually selected.
        self.setPlaceholderText(f"e.g. {prompts[0]}" if prompts else "")

    def prompts(self) -> list[str]:
        return self._model.stringList()

    def focusInEvent(self, event) -> None:
        # Emits only. Raising a popup from here is what locked the desktop; the
        # window answers this by showing PromptList, which takes no grab.
        super().focusInEvent(event)
        self.focused.emit()

    def focusOutEvent(self, event) -> None:
        # Belt and braces: never leave a popup holding a grab behind us.
        self._completer.popup().hide()
        super().focusOutEvent(event)
        self.blurred.emit()


class PromptList(QListWidget):
    """The suggested searches for the chosen trade.

    Deliberately NOT a QCompleter popup and not a Qt.Popup window. Both of those
    take a mouse and keyboard grab, and a grab raised by focus rather than by a
    keystroke is what made the desktop unclickable. This is an ordinary child
    widget of the main window, drawn over the panel: it can be shown whenever we
    like, because it cannot take input away from anything.

    It takes no focus either, so clicking an entry does not blur the search box
    out from under itself.
    """

    chosen = Signal(str)

    MAX_ROWS = 6

    def __init__(self, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self._t = theme
        self.setObjectName("prompts")
        self.setStyleSheet(popup_stylesheet(theme))
        self.setFocusPolicy(Qt.NoFocus)          # never steal focus from the box
        self.setCursor(Qt.PointingHandCursor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QListWidget.NoFrame)
        self._all: list[str] = []
        self.hide()
        self.itemClicked.connect(lambda item: self.chosen.emit(item.text()))

    def set_prompts(self, prompts: list[str]) -> None:
        self._all = list(prompts)[: self.MAX_ROWS]
        self.clear()
        self.addItems(self._all)

    def show_beneath(self, field: QWidget, limit_height: int) -> None:
        """Place under `field`, inside the window, and reveal."""
        if not self._all:
            return
        t = self._t
        metrics = self.fontMetrics()
        widest = max(metrics.horizontalAdvance(text) for text in self._all)

        # Whole rows only. Capping the *height* was not enough -- the row past the
        # cut still rendered, half-drawn, which reads as a rendering fault. So cap
        # the number of entries to what actually fits and rebuild the list.
        # The pitch is measured from a laid-out row rather than derived from
        # Size.popup_row, because the stylesheet's padding makes the real row
        # taller than the nominal one.
        padding = 2 * t.s(3) + 2 * self.frameWidth()
        pitch = max(1, self.visualItemRect(self.item(0)).height())
        fits = max(1, (limit_height - padding) // pitch)

        if len(self._all) > fits:
            self.clear()
            self.addItems(self._all[:fits])
        elif self.count() != len(self._all):
            self.clear()
            self.addItems(self._all)

        self.setFixedSize(max(field.width(), widest + t.s(28)),
                          self.count() * pitch + padding)

        parent = self.parentWidget()
        top_left = field.mapTo(parent, field.rect().bottomLeft())
        self.move(top_left.x(), top_left.y() + t.s(3))
        self.raise_()
        self.show()
