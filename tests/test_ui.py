"""Window smoke tests. Skipped entirely if PySide6 isn't installed, so the
engine test suite still runs on a machine with no GUI stack.

    QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from branch.ui.window import REFINE_FIELDS, SOURCES, MainWindow
    HAVE_QT = True
except ModuleNotFoundError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestWindow(unittest.TestCase):
    app: "QApplication"

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = MainWindow(trades=["motorcycle-repair", "plumbing"])

    def tearDown(self):
        self.w.deleteLater()

    def test_window_is_frameless_and_translucent(self):
        self.assertTrue(self.w.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(self.w.testAttribute(Qt.WA_TranslucentBackground))

    def test_idle_is_more_transparent_than_active(self):
        """Transparency lives in the slab gradient, not windowOpacity, so the
        rounded corners stay crisp instead of being faded along with the body."""
        t = self.w.theme
        self.assertLess(float(t.slab_alpha_idle), float(t.slab_alpha))

    def test_location_leads_the_refine_controls(self):
        self.assertEqual(len(REFINE_FIELDS), 4)
        self.assertEqual(REFINE_FIELDS[0][0], "location")

    def test_location_is_a_text_field_not_a_dropdown(self):
        """20,000 towns will not fit in a list."""
        from branch.ui.widgets import LocationEdit
        self.assertIsInstance(self.w.location, LocationEdit)
        self.assertNotIn("location", self.w._combos)
        self.assertEqual(len(self.w._combos), 3)

    def test_location_suggests_while_typing(self):
        self.w.location.set_near(32.749, -96.4629)
        self.w.location._on_edited("dal")
        self.assertEqual(self.w.location._model.stringList()[0], "Dallas, TX")

    def test_detected_position_fills_the_field(self):
        self.w.location.setText("")
        self.w.location._user_typed = False
        self.w.location.set_near(32.749, -96.4629)
        self.assertEqual(self.w.location.text(), "Dallas, TX")

    def test_detected_position_never_overwrites_typing(self):
        self.w.location.setText("Tulsa, OK")
        self.w.location._user_typed = True
        self.w.location.set_near(32.749, -96.4629)
        self.assertEqual(self.w.location.text(), "Tulsa, OK")

    def test_query_carries_resolved_coordinates(self):
        self.w.location.setText("Dallas, TX")
        q = self.w.current_query()
        self.assertEqual(q["location"], "Dallas, TX")
        self.assertAlmostEqual(q["coordinates"][0], 32.78, places=1)

    def test_unknown_location_yields_no_coordinates(self):
        self.w.location.setText("Nowhereville")
        self.assertIsNone(self.w.current_query()["coordinates"])

    def test_app_module_is_runnable(self):
        """`python -m branch.app` must actually start. A rewrite once dropped the
        __main__ guard and the app exited instantly with status 0 -- no error,
        no window, nothing to debug."""
        source = (ROOT / "branch" / "app.py").read_text(encoding="utf-8")
        self.assertIn('if __name__ == "__main__":', source)
        self.assertIn("main()", source)

    def test_every_source_in_the_registry_is_accounted_for_in_the_window(self):
        """Hacker News was wired as an adapter but had no toggle, so the only
        source that actually worked was unreachable from the window.

        The rule is not "everything is a toggle" -- a source that cannot run is
        no longer offered as one. The rule is that no source ever goes missing:
        it is either something the user can tick, or something the window names
        and gives a reason for.
        """
        from branch.sources.registry import build
        self.assertEqual(set(self.w._sources), set(build()))
        for btn in self.w._sources.values():
            self.assertTrue(btn.isCheckable())

    def test_trades_populate_the_trade_dropdown(self):
        combo = self.w._combos["trade"]
        self.assertEqual([combo.itemText(i) for i in range(combo.count())],
                         ["motorcycle-repair", "plumbing"])

    def test_trade_starts_blank(self):
        """An unmade choice should look unmade, not silently default to whichever
        trade happens to sort first."""
        self.assertEqual(self.w._combos["trade"].currentText(), "")
        self.assertEqual(self.w.current_query()["trade"], "")
        self.assertIsNone(self.w.current_query()["trade_slug"])

    def test_trade_is_typeable_as_well_as_browsable(self):
        from branch.ui.widgets import SearchableCombo
        combo = self.w._combos["trade"]
        self.assertIsInstance(combo, SearchableCombo)
        self.assertTrue(combo.isEditable())
        self.assertEqual(combo.completer().filterMode(), Qt.MatchContains)

    def test_trade_resolves_to_its_profile_slug(self):
        w = MainWindow(trades=["Wedding Photography"],
                       trade_slugs={"Wedding Photography": "wedding-photography"})
        w._combos["trade"].setCurrentText("Wedding Photography")
        self.assertEqual(w.current_query()["trade_slug"], "wedding-photography")
        w.deleteLater()

    def test_popups_are_styled_and_not_white(self):
        """A completer popup is a top-level window and does not inherit the main
        stylesheet -- unstyled it renders as a white list box over the page."""
        for popup in (self.w.location.completer().popup(),
                      self.w._combos["trade"].completer().popup(),
                      self.w._combos["trade"].view()):
            self.assertIn("QAbstractItemView", popup.styleSheet())
            self.assertNotIn("#ffffff", popup.styleSheet().lower())

    def test_popup_widens_to_fit_the_longest_suggestion(self):
        """'Fort Worth, TX' truncated to 'Fort Wor...' is not a suggestion."""
        self.w.location.set_near(32.749, -96.4629)
        self.w.location._on_edited("fort l")
        popup = self.w.location.completer().popup()
        longest = max(self.w.location._model.stringList(), key=len)
        self.assertGreaterEqual(popup.minimumWidth(),
                                popup.fontMetrics().horizontalAdvance(longest))

    def test_window_hugs_its_content(self):
        """No band of empty slab under the controls."""
        self.assertLessEqual(self.w.height(), self.w.sizeHint().height() + 1)

    def test_corner_radius_matches_the_compositor_exactly(self):
        """picom.conf sets corner-radius = 10. Ours must be the same number: it
        cuts the blur at its radius, so any difference leaves the blur showing
        outside our curve and the corner clips."""
        self.assertEqual(int(self.w.theme.corner_radius), 10)
        self.assertLessEqual(int(self.w.theme.control_radius), 6)

    def test_window_is_glass_not_a_slab(self):
        """picom blurs behind this and then applies its own 0.96/0.88, so our
        alpha is the third thing stacked and has to be low."""
        t = self.w.theme
        self.assertLess(float(t.slab_alpha), 0.22)
        self.assertLess(float(t.slab_alpha_idle), 0.12)

    def test_query_does_not_fill_the_top_row(self):
        self.assertLess(self.w.query.width(), self.w.width() // 3)

    def test_go_sits_directly_beside_the_query(self):
        gap = self.w.go.x() - (self.w.query.x() + self.w.query.width())
        self.assertLessEqual(gap, self.w.theme.s(10))
        self.assertGreaterEqual(gap, 0)

    def test_window_controls_are_pinned_to_the_corner(self):
        """Not a layout item -- a layout would inset them by the window padding
        and centre them on the query row."""
        c = self.w._controls
        inset = self.w.theme.s(6)
        self.assertLessEqual(self.w.width() - (c.x() + c.width()), inset)
        self.assertLessEqual(c.y(), inset)

    def test_controls_follow_a_resize(self):
        self.w.show()
        self.app.processEvents()
        self.w.resize(self.w.width() + 120, self.w.height())
        self.app.processEvents()
        c = self.w._controls
        self.assertLessEqual(self.w.width() - (c.x() + c.width()), self.w.theme.s(6))

    def test_palette_is_blue_not_green(self):
        """Moved off the family's green at his instruction; the structure stays."""
        def rgb(h):
            h = h.lstrip("#")
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        for key in ("ground", "panel", "accent", "accent_hi", "foreground", "slab_tint"):
            r, g, b = rgb(getattr(self.w.theme, key))
            self.assertGreaterEqual(b, g, f"{key} is not blue-leaning")

    def test_window_controls_stay_visible_over_a_child(self):
        """Qt sends the window a leave event when the pointer moves onto one of
        its own children; fading on that made the glyphs flicker over every
        control."""
        from PySide6.QtCore import QEvent
        self.w.show()                                  # _sync_controls ignores a hidden window
        self.w._fade_controls(1.0)
        self.w._controls_shown = True
        self.w._controls_anim.setCurrentTime(self.w._controls_anim.duration())
        self.w._pointer_inside = lambda: True          # pointer moved onto a combo
        self.w.leaveEvent(QEvent(QEvent.Leave))
        self.w._controls_anim.setCurrentTime(self.w._controls_anim.duration())
        self.assertAlmostEqual(self.w._controls_fx.opacity(), 1.0, places=3)

    def test_window_controls_fade_when_pointer_truly_leaves(self):
        from PySide6.QtCore import QEvent
        self.w._fade_controls(1.0)
        self.w._controls_shown = True
        self.w._controls_anim.setCurrentTime(self.w._controls_anim.duration())
        self.w._pointer_inside = lambda: False
        self.w.leaveEvent(QEvent(QEvent.Leave))
        self.w._controls_anim.setCurrentTime(self.w._controls_anim.duration())
        self.assertAlmostEqual(self.w._controls_fx.opacity(), 0.0, places=3)

    def test_no_trades_does_not_crash(self):
        w = MainWindow(trades=[])
        self.assertFalse(w._combos["trade"].isEnabled())
        w.deleteLater()

    def test_go_button_emits_the_current_query(self):
        seen = []
        self.w.scan_requested.connect(seen.append)
        self.w.query.setText("  bike won't start  ")
        self.w._sources["reddit"].setChecked(True)
        self.w.go.click()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["narrow"], "bike won't start")
        self.assertIn("reddit", seen[0]["sources"])
        self.assertIn("trade", seen[0])

    def test_return_in_query_also_scans(self):
        seen = []
        self.w.scan_requested.connect(seen.append)
        self.w.query.returnPressed.emit()
        self.assertEqual(len(seen), 1)

    def test_unavailable_source_is_disabled_with_a_reason(self):
        """Silent omission of a source is a bug."""
        self.w._sources["facebook"].setChecked(True)
        self.w.set_source_available("facebook", False, "not signed in")
        btn = self.w._sources["facebook"]
        self.assertFalse(btn.isEnabled())
        self.assertFalse(btn.isChecked())
        self.assertEqual(btn.toolTip(), "not signed in")

    def test_window_controls_start_hidden(self):
        self.assertAlmostEqual(self.w._controls_fx.opacity(), 0.0)

    def test_hover_reveals_window_controls(self):
        self.w._fade_controls(1.0)
        self.w._controls_anim.setCurrentTime(self.w._controls_anim.duration())
        self.assertAlmostEqual(self.w._controls_fx.opacity(), 1.0, places=3)

    def _settle(self):
        self.w._controls_anim.setCurrentTime(self.w._controls_anim.duration())

    def test_controls_hidden_when_active_but_not_hovered(self):
        """Being the active window is not hovering it. This was the bug."""
        self.w._pointer_inside = lambda: False
        self.w._controls_shown = True
        self.w._sync_controls()
        self._settle()
        self.assertAlmostEqual(self.w._controls_fx.opacity(), 0.0, places=3)

    def test_controls_appear_only_on_hover(self):
        self.w.show()
        self.w._pointer_inside = lambda: True
        self.w._controls_shown = False
        self.w._sync_controls()
        self._settle()
        self.assertAlmostEqual(self.w._controls_fx.opacity(), 1.0, places=3)

    def test_hover_is_polled_not_only_event_driven(self):
        """X11 can drop a leave event when the pointer jumps to another window."""
        self.w.show()
        self.app.processEvents()
        self.assertTrue(self.w._hover_timer.isActive())
        self.w.hide()
        self.assertFalse(self.w._hover_timer.isActive())

    def test_edge_detection_drives_resize_cursors(self):
        from PySide6.QtCore import QPoint
        self.w.resize(800, 400)
        self.assertTrue(self.w._edges_at(QPoint(1, 1)) & Qt.TopEdge)
        self.assertTrue(self.w._edges_at(QPoint(1, 1)) & Qt.LeftEdge)
        self.assertEqual(self.w._edges_at(QPoint(400, 200)), Qt.Edges())
        self.assertEqual(self.w._cursor_for(Qt.LeftEdge | Qt.TopEdge), Qt.SizeFDiagCursor)

    def test_ui_scale_resizes_everything(self):
        """One value in theme.json makes the whole window bigger or smaller."""
        from branch.ui.theme import DEFAULTS, Size, Theme
        one = Theme({**DEFAULTS, "ui_scale": 1.0})
        two = Theme({**DEFAULTS, "ui_scale": 2.0})
        self.assertEqual(two.s(Size.combo_h), 2 * one.s(Size.combo_h))
        self.assertEqual(two.s(Size.window_w), 2 * one.s(Size.window_w))

    def test_theme_falls_back_when_json_is_missing(self):
        from pathlib import Path
        from branch.ui.theme import Theme
        t = Theme.load(Path("/nonexistent/theme.json"))
        self.assertTrue(str(t.foreground).startswith("#"))

    def test_stylesheet_is_complete_and_has_no_forbidden_colour(self):
        """House rule: no red anywhere. No magenta or purple either."""
        from branch.ui.theme import Theme, stylesheet
        css = stylesheet(Theme.load()).lower()
        for selector in ("qpushbutton#go", "qpushbutton#source", "qlineedit#query", "qframe#panel"):
            self.assertIn(selector, css)
        # A Python None leaking into an f-string would render as "None".
        self.assertNotIn("None", stylesheet(Theme.load()))
        for banned in ("red", "magenta", "purple", "#ff00", "214, 68, 168"):
            self.assertNotIn(banned, css)

    def test_nothing_is_outlined(self):
        """Controls are trays, not boxes. A border anywhere is a regression."""
        from branch.ui.theme import Theme, stylesheet
        css = stylesheet(Theme.load())
        self.assertNotIn("1px solid", css)
        for line in css.splitlines():
            if "border:" in line:
                self.assertIn("none", line, line.strip())

    def test_hover_tray_is_less_transparent_than_rest(self):
        from branch.ui.theme import Theme
        t = Theme.load()
        self.assertGreater(float(t.tray_hover), float(t.tray))
        self.assertGreater(float(t.tray_active), float(t.tray_hover))

    def test_no_search_where_label(self):
        from PySide6.QtWidgets import QLabel
        labels = {lbl.text() for lbl in self.w.findChildren(QLabel)}
        self.assertNotIn("Search where", labels)

    def test_window_controls_are_small(self):
        from branch.ui.theme import Size
        self.assertLessEqual(self.w.btn_close.height(), self.w.theme.s(12))
        self.assertLess(self.w.btn_close.height(), self.w.query.height())

    def test_go_button_has_no_pill_or_fill(self):
        """Just the text."""
        from branch.ui.theme import Theme, stylesheet
        css = stylesheet(Theme.load())
        block = css.split("QPushButton#go {")[1].split("}")[0]
        self.assertIn("background: transparent", block)
        self.assertIn("border: none", block)

    def test_combos_paint_their_own_chevron(self):
        """Qt's ::down-arrow border-triangle renders as a white square here, so
        the chevron is painted by HouseComboBox. A plain QComboBox silently
        reintroduces the white blocks -- this caught exactly that."""
        from branch.ui.widgets import HouseComboBox
        for key, combo in self.w._combos.items():
            self.assertIsInstance(combo, HouseComboBox, key)

    def test_search_box_never_raises_a_grabbing_popup_itself(self):
        """A Qt completer popup takes a mouse and keyboard grab. Raising one from
        focus rather than from a keystroke left the grab held and the desktop
        could not be clicked until a suggestion was chosen. QueryEdit may emit a
        signal on focus; it may never call complete()."""
        import inspect
        from branch.ui.widgets import QueryEdit
        self.assertNotIn("complete()", inspect.getsource(QueryEdit))

    def test_prompt_list_cannot_grab_input(self):
        """The whole point of it being a child widget rather than a popup."""
        pl = self.w._prompt_list
        self.assertIs(pl.parentWidget(), self.w)
        self.assertFalse(pl.windowFlags() & Qt.Popup)
        self.assertFalse(pl.isWindow())
        self.assertEqual(pl.focusPolicy(), Qt.NoFocus)

    def test_prompts_show_on_focus_and_hide_on_typing(self):
        w = MainWindow(trades=["Plumbing"],
                       trade_prompts={"Plumbing": ["water heater", "burst pipe"]})
        w.show()
        self.app.processEvents()
        w._combos["trade"].setCurrentText("Plumbing")
        w.query.setFocus(Qt.OtherFocusReason)
        self.app.processEvents()
        self.assertTrue(w._prompt_list.isVisible())
        w.query.textEdited.emit("wa")
        self.assertFalse(w._prompt_list.isVisible())
        w.deleteLater()

    def test_prompts_do_not_show_without_a_trade(self):
        self.w.query.setFocus(Qt.OtherFocusReason)
        self.app.processEvents()
        self.assertFalse(self.w._prompt_list.isVisible())

    def test_choosing_a_prompt_fills_the_box(self):
        w = MainWindow(trades=["Plumbing"],
                       trade_prompts={"Plumbing": ["water heater", "burst pipe"]})
        w.show()
        w._combos["trade"].setCurrentText("Plumbing")
        w._maybe_show_prompts()
        w._prompt_list.itemClicked.emit(w._prompt_list.item(1))
        self.assertEqual(w.query.text(), "burst pipe")
        self.assertFalse(w._prompt_list.isVisible())
        w.deleteLater()

    def test_prompt_list_shows_whole_rows_only(self):
        """Capping the height alone left the row past the cut half-drawn."""
        w = MainWindow(trades=["T"], trade_prompts={"T": [f"prompt {i}" for i in range(6)]})
        w.show()
        w._combos["trade"].setCurrentText("T")
        w._maybe_show_prompts()
        self.app.processEvents()
        pl = w._prompt_list
        last = pl.visualItemRect(pl.item(pl.count() - 1))
        self.assertLessEqual(last.bottom(), pl.viewport().height())
        self.assertLessEqual(pl.geometry().bottom(), w.height())
        w.deleteLater()

    def test_placeholder_teaches_instead_of_the_popup(self):
        self.w.query.set_prompts(["water heater", "burst pipe"])
        self.assertEqual(self.w.query.placeholderText(), "e.g. water heater")
        self.w.query.set_prompts([])
        self.assertEqual(self.w.query.placeholderText(), "")

    def test_popups_close_when_the_window_deactivates(self):
        self.w.location.set_near(32.749, -96.4629)
        self.w.location._on_edited("dal")
        self.w._hide_popups()
        self.assertFalse(self.w.location.completer().popup().isVisible())
        self.assertFalse(self.w.query.completer().popup().isVisible())

    def test_search_box_has_no_clear_button(self):
        """Qt's clear glyph cannot be themed and is redundant next to select-all."""
        self.assertFalse(self.w.query.isClearButtonEnabled())

    def test_search_box_suggests_prompts_for_the_chosen_trade(self):
        w = MainWindow(trades=["Plumbing", "IT Support"],
                       trade_prompts={"Plumbing": ["water heater", "burst pipe"],
                                      "IT Support": ["ransomware"]})
        self.assertEqual(w.query.prompts(), [])
        w._combos["trade"].setCurrentText("Plumbing")
        self.assertEqual(w.query.prompts(), ["water heater", "burst pipe"])
        w._combos["trade"].setCurrentText("IT Support")
        self.assertEqual(w.query.prompts(), ["ransomware"])
        w.deleteLater()

    def test_query_placeholder_is_empty_without_a_trade(self):
        self.assertEqual(self.w.query.placeholderText(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestSourceGrid(unittest.TestCase):
    """Every source is a pill, every pill is clickable, and a pill that cannot
    run explains itself in a window rather than in standing text.

    The panel used to carry two permanent lines -- the sign-in links and an
    "Unavailable: ..." line. They were honest and they were clutter, and they
    cost two rows of the window forever to answer a question asked twice.
    """

    app: "QApplication"

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from branch.sources.registry import build
        self.w = MainWindow(trades=["plumbing"])
        self.states = {k: s.state(set()) for k, s in build().items()}
        self.w.set_source_states(self.states)

    def tearDown(self):
        self.w.deleteLater()

    def _grid_widgets(self):
        g = self.w._grid
        return [g.itemAt(i).widget() for i in range(g.count())
                if g.itemAt(i).widget() is not None]

    def test_every_source_is_in_the_grid_and_clickable(self):
        widgets = self._grid_widgets()
        self.assertEqual(len(widgets), len(SOURCES))
        for key, _ in SOURCES:
            with self.subTest(source=key):
                btn = self.w._sources[key]
                self.assertIn(btn, widgets)
                self.assertTrue(btn.isCheckable())
                self.assertTrue(btn.isEnabled(), "a pill must stay clickable to "
                                                 "be able to explain itself")

    def test_the_panel_carries_no_standing_explanatory_text(self):
        """The two lines he objected to, asserted gone by their words."""
        from PySide6.QtWidgets import QLabel
        texts = " ".join(lbl.text() for lbl in self.w.findChildren(QLabel))
        for banned in ("Sign in to", "Unavailable:", "Needs sign-in",
                       "no feeds set", "needs a key"):
            self.assertNotIn(banned, texts, f"{banned!r} is still in the panel")

    def test_the_reason_is_still_reachable_on_hover(self):
        self.assertIn("Google Places", self.w._sources["reviews"].toolTip())
        self.assertIn("sign in", self.w._sources["facebook"].toolTip().lower())

    def test_clicking_a_gated_source_unticks_it_and_explains(self):
        shown = []
        self.w._show_source_notice = shown.append
        self.w._sources["facebook"].setChecked(True)
        self.w._source_clicked("facebook")
        self.assertFalse(self.w._sources["facebook"].isChecked())
        self.assertEqual([s.key for s in shown], ["facebook"])

    def test_clicking_an_unavailable_source_explains_too(self):
        shown = []
        self.w._show_source_notice = shown.append
        self.w._source_clicked("reviews")
        self.assertEqual([s.key for s in shown], ["reviews"])

    def test_clicking_a_working_source_just_toggles_it(self):
        shown = []
        self.w._show_source_notice = shown.append
        self.w._sources["reddit"].setChecked(True)
        self.w._source_clicked("reddit")
        self.assertTrue(self.w._sources["reddit"].isChecked())
        self.assertEqual(shown, [], "a working source must not lecture the user")

    def test_a_gated_source_is_never_scanned(self):
        self.w._sources["facebook"].setChecked(True)
        self.w.set_source_states(self.states)
        self.assertNotIn("facebook", self.w.current_query()["sources"])

    def test_an_unavailable_source_is_never_scanned(self):
        self.w._sources["reviews"].setChecked(True)
        self.assertNotIn("reviews", self.w.current_query()["sources"])

    def test_signing_in_makes_the_source_an_ordinary_toggle(self):
        from branch.sources.registry import build
        self.w.set_source_states({k: s.state({"facebook"}) for k, s in build().items()})
        shown = []
        self.w._show_source_notice = shown.append
        self.w._sources["facebook"].setChecked(True)
        self.w._source_clicked("facebook")
        self.assertTrue(self.w._sources["facebook"].isChecked())
        self.assertEqual(shown, [])
        self.assertIn("facebook", self.w.current_query()["sources"])


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestSourceNotice(unittest.TestCase):
    """The window that explains a source, and the link it offers."""

    app: "QApplication"

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_login_message_says_what_to_do_and_offers_the_page(self):
        from branch.ui.notice import LOGIN_MESSAGE, SourceNotice
        from branch.ui.theme import Theme
        dialog = SourceNotice(Theme.load(), "Facebook", LOGIN_MESSAGE,
                              "https://www.facebook.com/login", "Open Facebook sign-in")
        try:
            self.assertIn("requires an account", LOGIN_MESSAGE)
            self.assertIn("burner", LOGIN_MESSAGE)
            self.assertEqual(dialog.link, "https://www.facebook.com/login")
        finally:
            dialog.deleteLater()

    def test_a_source_with_no_fix_offers_no_link(self):
        from branch.ui.notice import SourceNotice
        from branch.ui.theme import Theme
        dialog = SourceNotice(Theme.load(), "Reviews", "needs a Google Places API key")
        try:
            self.assertEqual(dialog.link, "")
        finally:
            dialog.deleteLater()

    def test_it_paints_its_own_ground(self):
        """It floats over whatever is behind the app, so a panel wash leaves it
        transparent -- which is exactly how the first version rendered."""
        from branch.ui.theme import Theme, stylesheet
        self.assertIn("QFrame#notice", stylesheet(Theme.load()))

    def test_signing_in_goes_through_branchs_own_browser(self):
        """Not the system browser: the session a scan uses is this window's, and
        signing in anywhere else does nothing for it."""
        source = (ROOT / "branch" / "ui" / "window.py").read_text(encoding="utf-8")
        body = source.split("def _show_source_notice")[1].split("\n    def ")[0]
        self.assertIn("login_requested.emit", body)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestSourceGridDoesNotOverlap(unittest.TestCase):
    """The bug he caught in a screenshot: four toggles drawn on top of each other.

    `adjustSize()` clamps a window to two thirds of the screen. Once the source
    column grew tall enough to hit that ceiling the panel was handed less height
    than it needed, and a grid of *fixed-height* pills does not clip when it is
    squeezed -- it overlaps. It looked fine at ui_scale 1.0 on an offscreen
    screen, which is exactly why it shipped.

    Checked at several scales because the failure is a function of how the
    window's height compares to the screen's.
    """

    app: "QApplication"

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, scale: float):
        from branch.profile import Profile
        from branch.runner import ScanRunner
        from branch.ui.theme import Theme
        theme = Theme.load()
        theme.values["ui_scale"] = scale
        window = MainWindow(trades=["plumbing"], theme=theme)
        runner = ScanRunner(ROOT, Profile.load_all(ROOT / "profiles"), parent=window)
        window.set_source_states(runner.source_states())
        window.show()
        self.app.processEvents()
        return window

    def test_no_two_toggles_ever_overlap(self):
        for scale in (1.0, 1.5, 2.0, 2.5, 3.0):
            with self.subTest(ui_scale=scale):
                window = self._window(scale)
                try:
                    boxes = [(key, b.geometry()) for key, b in window._sources.items()
                             if b.isVisible() and b.parent() is not None]
                    self.assertTrue(boxes, "no toggles are visible at all")
                    for i, (key_a, a) in enumerate(boxes):
                        for key_b, b in boxes[i + 1:]:
                            self.assertFalse(
                                a.intersects(b),
                                f"{key_a} overlaps {key_b} at ui_scale {scale}: {a} vs {b}")
                finally:
                    window.deleteLater()

    def test_the_column_is_tall_enough_for_what_is_in_it(self):
        """The check that would have caught it without a screenshot."""
        for scale in (1.0, 2.0, 3.0):
            with self.subTest(ui_scale=scale):
                window = self._window(scale)
                try:
                    panel = window._sources_panel
                    self.assertGreaterEqual(panel.height(),
                                            window._grid.minimumSize().height())
                finally:
                    window.deleteLater()

    def test_the_toggles_stay_inside_their_column(self):
        window = self._window(2.0)
        try:
            column = window._sources_panel.rect()
            for key, btn in window._sources.items():
                if btn.isVisible() and btn.parent() is window._sources_panel:
                    with self.subTest(source=key):
                        self.assertTrue(column.contains(btn.geometry()),
                                        f"{key} is drawn outside the source column")
        finally:
            window.deleteLater()
