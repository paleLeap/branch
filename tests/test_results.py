"""The results list and the tuning loop."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from branch.engine import scan                                    # noqa: E402
from branch.models import Item                                    # noqa: E402
from branch.profile import Profile                                # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    from branch.ui.results import LeadCard, ResultsView, _excerpt, _highlighted
    from branch.ui.theme import Theme
    HAVE_QT = True
except ModuleNotFoundError:
    HAVE_QT = False

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


class TestProfileTuning(unittest.TestCase):
    """Exclusions land in a sidecar, never in the shipped profile."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "profiles" / "plumbing.yaml", self.dir / "plumbing.yaml")
        self.original = (self.dir / "plumbing.yaml").read_text(encoding="utf-8")
        self.profile = Profile.load(self.dir / "plumbing.yaml")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_exclusion_goes_to_a_sidecar_file(self):
        self.assertTrue(self.profile.add_exclusion("hot tub"))
        self.assertTrue((self.dir / "plumbing.local.yaml").exists())

    def test_shipped_profile_is_never_rewritten(self):
        """Its comments and curation have to survive the user's tuning."""
        self.profile.add_exclusion("hot tub")
        self.assertEqual((self.dir / "plumbing.yaml").read_text(encoding="utf-8"),
                         self.original)

    def test_exclusion_survives_a_reload(self):
        self.profile.add_exclusion("hot tub")
        reloaded = Profile.load(self.dir / "plumbing.yaml")
        self.assertTrue(any("hot tub" in g.terms for g in reloaded.exclude))

    def test_deleting_the_sidecar_undoes_everything(self):
        before = len(self.profile.exclude)
        self.profile.add_exclusion("hot tub")
        self.profile.add_exclusion("pool")
        (self.dir / "plumbing.local.yaml").unlink()
        self.assertEqual(len(Profile.load(self.dir / "plumbing.yaml").exclude), before)

    def test_duplicate_exclusion_is_refused(self):
        self.assertTrue(self.profile.add_exclusion("hot tub"))
        self.assertFalse(self.profile.add_exclusion("Hot Tub"))

    def test_exclusion_actually_changes_the_scan(self):
        post = Item(id="a", text="My hot tub is leaking, need a plumber, any recommendations?",
                    url="", venue="v", posted_at=NOW - timedelta(hours=1))
        self.assertEqual(len(scan([post], self.profile, now=NOW).leads), 1)
        self.profile.add_exclusion("hot tub")
        self.assertEqual(scan([post], self.profile, now=NOW).leads, [])

    def test_a_broken_sidecar_is_ignored_not_fatal(self):
        (self.dir / "plumbing.local.yaml").write_text("{ not: [valid", encoding="utf-8")
        self.assertIsNotNone(Profile.load(self.dir / "plumbing.yaml"))


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.theme = Theme.load()

    def test_highlight_escapes_html(self):
        out = _highlighted("<script> carb", [(9, 13)], "#fff")
        self.assertIn("&lt;script&gt;", out)
        self.assertIn(">carb<", out)

    def test_highlight_merges_overlapping_spans(self):
        out = _highlighted("abcdef", [(0, 3), (2, 5)], "#fff")
        self.assertEqual(out.count("<span"), 1)

    def test_excerpt_centres_on_the_match(self):
        text = "x" * 400 + "MATCH" + "y" * 400
        shown, offset = _excerpt(text, 400)
        self.assertIn("MATCH", shown)
        self.assertLess(len(shown), len(text))

    def test_short_text_is_not_excerpted(self):
        shown, offset = _excerpt("short post", 0)
        self.assertEqual((shown, offset), ("short post", 0))

    def test_card_does_not_repeat_the_title_in_the_excerpt(self):
        profile = Profile.load(ROOT / "profiles" / "plumbing.yaml")
        post = Item(id="a", title="Water heater flooding the garage",
                    text="Woke up to water everywhere. Need a plumber, can anyone help?",
                    url="https://example.invalid/a", venue="v",
                    posted_at=NOW - timedelta(hours=1))
        lead = scan([post], profile, now=NOW).leads[0]
        from PySide6.QtWidgets import QLabel
        card = LeadCard(lead, self.theme)
        texts = [w.text() for w in card.findChildren(QLabel)]
        excerpt = next(t for t in texts if "Woke up" in t)
        self.assertNotIn("Water heater flooding the garage", excerpt)
        card.deleteLater()

    def test_switching_tabs_removes_the_previous_cards(self):
        """deleteLater() is async; without unparenting, discards drew over leads."""
        profile = Profile.load(ROOT / "profiles" / "plumbing.yaml")
        posts = [Item(id=str(i), text="toilet backing up, need a plumber, recommendations?",
                      url="", venue="v", posted_at=NOW - timedelta(hours=i + 1))
                 for i in range(3)]
        view = ResultsView(self.theme)
        view.show_result(scan(posts, profile, now=NOW))
        leads_widgets = view._body_layout.count()
        view.set_mode("discards")
        self.app.processEvents()
        for i in range(view._body_layout.count() - 1):
            widget = view._body_layout.itemAt(i).widget()
            self.assertIsNotNone(widget)
            self.assertEqual(type(widget).__name__, "DiscardCard")
        self.assertGreater(leads_widgets, 0)
        view.deleteLater()

    def test_unavailable_sources_are_shown_not_hidden(self):
        from branch.models import ScanResult
        view = ResultsView(self.theme)
        view.show_result(ScanResult(unavailable={"reddit": "not signed in"}))
        self.assertIn("not signed in", view.note.text())
        view.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
