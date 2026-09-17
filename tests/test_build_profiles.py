"""The profile generator. Stdlib unittest only.

    python -m unittest discover -s tests -v

A hundred trades cannot be hand-written and kept consistent, so they are built
from the research documents. These pin the parts that would silently produce a
hundred broken profiles.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from branch.profile import Profile                                # noqa: E402

try:
    import build_profiles as gen                                  # noqa: E402
    HAVE_RESEARCH = (ROOT.parent / "research" / "PROFESSIONS-100.md").exists()
except ModuleNotFoundError:                                       # pragma: no cover
    HAVE_RESEARCH = False

ROW = {"rank": 3, "slug": "roofer", "display_name": "Roofer", "category": "home-trade",
       "reach": "local", "frequency": "seasonal", "urgency": "emergency",
       "also_called": ["roofing contractor", "roof guy"]}
VOCAB = {"subject": ["roof", "shingle", "gutter", "flashing"],
         "problem": ["leaking", "missing shingles", "storm damage"]}


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.text = gen.render(ROW, VOCAB)
        self.profile = Profile.from_dict(__import__("yaml").safe_load(self.text))

    def test_a_generated_profile_loads(self):
        self.assertEqual(self.profile.trade, "roofer")
        self.assertEqual(self.profile.name, "Roofer")

    def test_it_knows_what_customers_call_the_trade(self):
        terms = {t for g in self.profile.subject for t in g.terms}
        self.assertIn("roof guy", terms,
                      "'roofing contractor' is what they call themselves; "
                      "'roof guy' is what the customer types")

    def test_every_trade_can_notice_a_request(self):
        kinds = {g.kind for g in self.profile.intent}
        self.assertIn("request", kinds)

    def test_problems_are_marked_as_problems_not_requests(self):
        problems = [g for g in self.profile.intent if g.kind == "problem"]
        self.assertTrue(problems)
        self.assertIn("storm damage", {t for g in problems for t in g.terms})

    def test_urgency_sets_how_fast_the_lead_goes_cold(self):
        """A roof leaking in a storm is not the same clock as a wedding."""
        self.assertEqual(self.profile.recency_half_life_hours,
                         gen.HALF_LIFE["emergency"])
        planned = Profile.from_dict(__import__("yaml").safe_load(
            gen.render({**ROW, "urgency": "planned"}, VOCAB)))
        self.assertGreater(planned.recency_half_life_hours,
                           self.profile.recency_half_life_hours)

    def test_a_trade_with_no_researched_vocabulary_still_loads(self):
        """Thin, but it must not be broken -- it still knows its own name."""
        profile = Profile.from_dict(__import__("yaml").safe_load(
            gen.render(ROW, {})))
        self.assertTrue(profile.subject)
        self.assertTrue([g for g in profile.intent if g.kind == "request"])

    def test_the_marker_is_present_so_hand_edits_can_be_kept(self):
        self.assertIn(gen.MARKER, self.text)


@unittest.skipUnless(HAVE_RESEARCH, "research documents not present")
class TestWriting(unittest.TestCase):
    """Writing needs the research documents, which live outside the published
    repository -- they are the working record, not part of the program. A clone
    has the profiles already built, so these skip there rather than fail."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_a_hand_edited_profile_is_never_overwritten(self):
        mine = self.dir / "roofer.yaml"
        mine.write_text("trade: roofer\nsubject: [roof]\nintent: [leak]\n")
        gen.main(["--out", str(self.dir)])
        self.assertNotIn(gen.MARKER, mine.read_text(),
                         "somebody's tuning was overwritten by the generator")

    def test_a_generated_profile_is_replaced_on_a_rerun(self):
        gen.main(["--out", str(self.dir)])
        written = list(self.dir.glob("*.yaml"))
        self.assertTrue(written)
        gen.main(["--out", str(self.dir)])
        self.assertEqual(len(list(self.dir.glob("*.yaml"))), len(written))

    def test_the_originals_are_not_duplicated_under_a_new_name(self):
        """The research calls it "plumber"; the tuned profile is "plumbing".
        Generating both would put two of the same trade in the dropdown."""
        for slug, existing in gen.ALIASES.items():
            with self.subTest(slug=slug):
                self.assertTrue((ROOT / "profiles" / f"{existing}.yaml").exists())


class TestAgainstTheRealResearch(unittest.TestCase):
    @unittest.skipUnless(HAVE_RESEARCH, "research documents not present")
    def test_the_professions_table_parses(self):
        rows = gen.professions(ROOT.parent / "research" / "PROFESSIONS-100.md")
        self.assertGreaterEqual(len(rows), 90)
        self.assertEqual(len({r["slug"] for r in rows}), len(rows), "duplicate slug")
        for row in rows:
            with self.subTest(slug=row["slug"]):
                self.assertTrue(row["display_name"])
                self.assertIn(row["urgency"], gen.HALF_LIFE)

    @unittest.skipUnless(HAVE_RESEARCH, "research documents not present")
    def test_every_researched_trade_renders_into_a_valid_profile(self):
        """Loaded the way the program loads it, which is the only way the shared
        exclusions in _defaults.yaml are part of the profile at all."""
        import shutil
        directory = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "profiles" / "_defaults.yaml", directory)
        vocab = gen.vocabulary(ROOT.parent / "research" / "TRADE-VOCABULARY.md")
        rows = gen.professions(ROOT.parent / "research" / "PROFESSIONS-100.md")
        for row in rows:
            (directory / f"{row['slug']}.yaml").write_text(
                gen.render(row, vocab.get(row["slug"], {})), encoding="utf-8")
        loaded = Profile.load_all(directory)
        self.assertEqual(len(loaded), len(rows))
        for slug, profile in loaded.items():
            with self.subTest(slug=slug):
                self.assertEqual(profile.validate(), [])
                self.assertTrue([g for g in profile.intent if g.kind == "request"])


class TestStartupCost(unittest.TestCase):
    def test_phrases_compile_on_first_use_rather_than_at_startup(self):
        """A hundred profiles compiled eagerly cost most of half a second before
        the window appeared, and the window only needs each trade's name."""
        profile = Profile.from_dict({
            "trade": "t", "subject": [{"terms": ["a"]}], "intent": [{"terms": ["b"]}]})
        group = profile.subject[0]
        self.assertEqual(group._patterns, [], "compiled before anyone scanned")
        self.assertTrue(group.patterns)
        self.assertTrue(group._patterns, "compiled twice")


if __name__ == "__main__":
    unittest.main()
