"""Continuous attended session. Stdlib unittest only -- no framework to install.

    python -m unittest discover -s tests -v

These pin the two things that make a session attended rather than scheduled: it
runs only for the length the user picked, and it can always be stopped with the
control that started it.
"""
from __future__ import annotations

import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from branch.models import Explanation, Item, Lead, ScanResult      # noqa: E402
from branch.profile import Profile                                 # noqa: E402
from branch.runner import ASKS_PER_CYCLE, RUN_FOR_SECONDS          # noqa: E402
from branch.session import (                                       # noqa: E402
    PASS_GAP_SECONDS, Session, duration_seconds, lead_key,
)

PROFILES = Profile.load_all(ROOT / "profiles")


def lead(text: str, url: str = "", score: float = 5.0) -> Lead:
    item = Item(id=url or text[:8], text=text, url=url, venue="facebook",
                posted_at=datetime.now(timezone.utc))
    return Lead(item=item, score=score, explanation=Explanation())


def result(*leads: Lead, scanned: int = 10) -> ScanResult:
    return ScanResult(leads=list(leads), scanned=scanned, venues=["facebook"])


class TestDuration(unittest.TestCase):
    def test_once_is_not_a_session(self):
        """The default must behave exactly as Go always has: one pass, stop."""
        self.assertEqual(duration_seconds("Once"), 0.0)
        self.assertIsNone(Session().start({"trade_slug": "plumbing"}, 0.0))

    def test_every_offered_duration_is_understood(self):
        for label in RUN_FOR_SECONDS:
            with self.subTest(label=label):
                self.assertIsInstance(duration_seconds(label), float)

    def test_an_unknown_duration_is_a_single_pass(self):
        """A stale settings file must not start an hour-long run by accident."""
        self.assertEqual(duration_seconds("forever"), 0.0)
        self.assertEqual(duration_seconds(""), 0.0)


class TestSessionEnds(unittest.TestCase):
    """A session that cannot end is a schedule, which is the thing we do not do."""

    @staticmethod
    def _expired_session() -> Session:
        """A session whose clock has run out, without waiting for one.

        Sleeping past a short deadline looks deterministic and is not: Windows'
        monotonic clock ticks about every 15.6ms, so a 60ms sleep can measure as
        under 50ms and the session is not expired yet. That failed the Windows
        release build and nothing else -- a real defect in the test, not in the
        program. Moving the deadline is exact on every platform.
        """
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        s._deadline = time.monotonic() - 1.0
        return s

    def test_it_stops_itself_when_the_clock_runs_out(self):
        s = self._expired_session()
        self.assertTrue(s.expired())
        self.assertFalse(s.finished_pass())
        self.assertFalse(s.running)

    def test_it_says_why_it_ended(self):
        s = self._expired_session()
        seen = []
        s.ended.connect(seen.append)
        s.finished_pass()
        self.assertEqual(seen, ["time is up"])

    def test_stop_means_stop_immediately(self):
        """It used to end only when a pass reported in. If the pass in flight
        never reported -- nothing to read, a skipped source, a browser that
        never came back -- the window sat on "Stop" with nothing running."""
        s = Session()
        ended = []
        s.ended.connect(ended.append)
        s.start({"trade_slug": "plumbing"}, 600.0)
        s.ask_stop()
        self.assertFalse(s.running, "the session outlived the Stop button")
        self.assertEqual(ended, ["stopped"])
        self.assertFalse(s.finished_pass(), "a stopped session started another pass")

    def test_a_stopped_session_does_not_restart_itself(self):
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        s.stop()
        self.assertFalse(s.finished_pass())
        self.assertFalse(s.running)

    def test_it_pauses_between_passes(self):
        """Back-to-back passes with no gap is the part that looks automated."""
        self.assertGreaterEqual(PASS_GAP_SECONDS, 10.0)


class TestAccumulation(unittest.TestCase):
    def test_leads_accumulate_across_passes(self):
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        s.absorb(result(lead("need a plumber", "https://x/1")))
        merged = s.absorb(result(lead("leaking pipe", "https://x/2")))
        self.assertEqual(len(merged.leads), 2)
        self.assertEqual(merged.scanned, 20)

    def test_the_same_lead_twice_is_shown_once(self):
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        s.absorb(result(lead("need a plumber", "https://x/1")))
        merged = s.absorb(result(lead("need a plumber", "https://x/1")))
        self.assertEqual(len(merged.leads), 1)

    def test_undated_facebook_results_dedupe_on_their_text(self):
        """Facebook search results share a URL that points at no post, so the
        URL cannot tell two people apart -- see the 2026-09-16 sweep."""
        a = lead("I need a plumber with RV experience",
                 "https://www.facebook.com/search/posts#?bfc")
        b = lead("Anyone have a good plumber in the area?",
                 "https://www.facebook.com/search/posts#?ihe")
        self.assertNotEqual(lead_key(a), lead_key(b))
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        s.absorb(result(a))
        merged = s.absorb(result(b))
        self.assertEqual(len(merged.leads), 2)

    def test_the_best_lead_stays_at_the_top(self):
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        s.absorb(result(lead("weak", "https://x/1", score=2.0)))
        merged = s.absorb(result(lead("strong", "https://x/2", score=9.0)))
        self.assertEqual(merged.leads[0].item.text, "strong")

    def test_status_reads_as_a_sentence_a_person_can_act_on(self):
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        s.absorb(result(lead("need a plumber", "https://x/1")))
        status = s.status()
        self.assertIn("pass 1", status)
        self.assertIn("1 lead", status)
        self.assertIn("left", status)


class TestRotation(unittest.TestCase):
    """Later passes must ask questions the earlier ones did not."""

    def test_passes_ask_different_phrasings(self):
        profile = PROFILES["plumbing"]
        first = profile.ask_phrases(ASKS_PER_CYCLE, offset=0)
        second = profile.ask_phrases(ASKS_PER_CYCLE, offset=ASKS_PER_CYCLE)
        self.assertNotEqual(first, second)
        self.assertTrue(set(second) - set(first),
                        "a second pass that asks nothing new is a wasted pass")

    def test_a_pass_never_asks_the_same_thing_twice(self):
        profile = PROFILES["plumbing"]
        for offset in range(0, 40, 3):
            with self.subTest(offset=offset):
                asks = profile.ask_phrases(ASKS_PER_CYCLE, offset=offset)
                self.assertEqual(len(asks), len(set(asks)))

    def test_rotation_wraps_rather_than_running_out(self):
        """Pass twenty must still have questions to ask."""
        profile = PROFILES["plumbing"]
        self.assertEqual(len(profile.ask_phrases(ASKS_PER_CYCLE, offset=200)),
                         ASKS_PER_CYCLE)

    def test_a_single_scan_still_asks_everything(self):
        """Cycle 0 is a one-off scan and must not lose coverage to rotation."""
        from branch.runner import ScanRunner
        runner = ScanRunner(ROOT, PROFILES)
        query = {"trade_slug": "plumbing", "location": "Dallas, TX",
                 "radius": "25 miles", "since": "Last 24 hours"}
        once = runner._request(query, PROFILES["plumbing"])
        self.assertEqual(len(once.asks), 10)
        in_session = runner._request({**query, "cycle": 1}, PROFILES["plumbing"])
        self.assertEqual(len(in_session.asks), ASKS_PER_CYCLE)




class TestWiring(unittest.TestCase):
    """The chaining lives in app.py, which has no window to test against here.

    Read as text, in the style test_sources.py already uses for the browser's
    safeguards: these are the connections that make the button honest.
    """

    def setUp(self):
        self.source = (ROOT / "branch" / "app.py").read_text(encoding="utf-8")

    def test_the_go_button_can_stop_a_session(self):
        self.assertIn("window.stop_requested.connect", self.source)

    def test_the_window_learns_when_the_session_ends(self):
        self.assertIn("session.ended.connect(window.session_ended)", self.source)

    def test_the_next_pass_waits_for_the_browser(self):
        """Starting pass two while pass one is still reading Facebook would put
        two passes in flight against one account."""
        self.assertIn("_pass_is_over", self.source)
        self.assertIn('pass_state["browsed"]', self.source)

    def test_a_pass_only_follows_a_pass_the_session_allowed(self):
        self.assertIn("session.finished_pass()", self.source)


if __name__ == "__main__":
    unittest.main()


class TestTuningSurvivesASession(unittest.TestCase):
    """The rejects are how a user tunes. A session that drops them shows
    "Discarded 0" against a hundred scanned posts -- seen live, roofer in
    Baton Rouge, 136 posts read and nothing listed as thrown away."""

    def test_discards_reach_the_window(self):
        from branch.models import Discarded, Item
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        thrown = Discarded(
            item=Item(id="x", text="for sale", url="u", venue="facebook",
                      posted_at=datetime.now(timezone.utc)),
            stage="exclude", reason="excluded by for sale")
        merged = s.absorb(ScanResult(leads=[], discarded=[thrown], scanned=136))
        self.assertEqual(len(merged.discarded), 1)
        self.assertEqual(merged.scanned, 136)

    def test_a_later_pass_with_nothing_to_show_keeps_the_last_reasons(self):
        from branch.models import Discarded, Item
        s = Session()
        s.start({"trade_slug": "plumbing"}, 600.0)
        thrown = Discarded(
            item=Item(id="x", text="for sale", url="u", venue="facebook",
                      posted_at=datetime.now(timezone.utc)),
            stage="exclude", reason="excluded by for sale")
        s.absorb(ScanResult(leads=[], discarded=[thrown], scanned=10))
        merged = s.absorb(ScanResult(leads=[], discarded=[], scanned=0))
        self.assertEqual(len(merged.discarded), 1, "the tuning list went blank")


class TestASessionNeedsSomethingToDo(unittest.TestCase):
    """Reported live: a scan running with one source showed Stop and kept
    running. A session whose sources cannot run reads nothing, finishes, and
    starts another pass thirty seconds later -- forever."""

    def setUp(self):
        self.source = (ROOT / "branch" / "app.py").read_text(encoding="utf-8")

    def test_go_refuses_a_query_with_nothing_runnable(self):
        self.assertIn("Nothing to search", self.source)

    def test_it_says_what_to_do_about_it(self):
        self.assertIn("Click one to see what it needs", self.source)
