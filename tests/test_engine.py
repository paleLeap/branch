"""Engine tests. Stdlib unittest only -- no test framework to install.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from branch.engine import scan                                    # noqa: E402
from branch.fixtures import load_items                            # noqa: E402
from branch.models import Item                                    # noqa: E402
from branch.profile import Profile                                # noqa: E402
from branch.text import compile_phrase, is_negated, normalize, tokenize  # noqa: E402

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
PROFILES = Profile.load_all(ROOT / "profiles")


def item(text: str, *, id: str = "x", venue: str = "test", age_hours: float = 1.0,
         author: str | None = None, title: str | None = None) -> Item:
    return Item(id=id, text=text, url=f"https://example.invalid/{id}", venue=venue,
                posted_at=NOW - timedelta(hours=age_hours), author=author, title=title)


class TestMatching(unittest.TestCase):
    def test_apostrophes_match_both_directions(self):
        for pattern in ("won't start", "wont start"):
            for text in ("my bike won't start", "my bike wont start", "my bike won’t start"):
                with self.subTest(pattern=pattern, text=text):
                    self.assertTrue(compile_phrase(pattern).search(normalize(text)))

    def test_word_boundaries_are_respected(self):
        self.assertFalse(compile_phrase("bike").search(normalize("biker gang")))
        self.assertFalse(compile_phrase("carb").search(normalize("carburetor rebuild")))
        self.assertFalse(compile_phrase("shop").search(normalize("shopping for parts")))

    def test_trailing_plural_is_implicit(self):
        self.assertTrue(compile_phrase("fork seal").search(normalize("leaking fork seals")))
        self.assertTrue(compile_phrase("bike").search(normalize("two bikes")))

    def test_star_is_open_ended(self):
        pat = compile_phrase("leak*")
        for t in ("leak", "leaks", "leaking", "leakage"):
            self.assertTrue(pat.search(normalize(f"it is {t} badly")), t)

    def test_flexible_whitespace(self):
        self.assertTrue(compile_phrase("fork seal").search(normalize("fork   seal")))

    def test_negation_window(self):
        text = normalize("I don't need a mechanic")
        m = compile_phrase("need a mechanic").search(text)
        self.assertTrue(is_negated(text, tokenize(text), m.start(),
                                   frozenset({"dont", "not"}), 4))

    def test_negation_respects_distance(self):
        text = normalize("not really sure about anything else but honestly I need a mechanic")
        m = compile_phrase("need a mechanic").search(text)
        self.assertFalse(is_negated(text, tokenize(text), m.start(),
                                    frozenset({"not"}), 3))


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.moto = PROFILES["motorcycle-repair"]

    def test_exclusion_beats_a_strong_match(self):
        """A for-sale listing is full of trade vocabulary and must still be dropped."""
        it = item("Bonneville doesn't run, needs carb work and fork seals. $400 obo", id="sale")
        res = scan([it], self.moto, now=NOW)
        self.assertEqual(res.leads, [])
        self.assertEqual(res.discarded[0].stage, "exclude")

    def test_subject_without_intent_is_not_a_lead(self):
        res = scan([item("Took the motorcycle out for a great ride, clutch feels lovely")],
                   self.moto, now=NOW)
        self.assertEqual(res.leads, [])
        self.assertEqual(res.discarded[0].stage, "intent")

    def test_intent_without_subject_is_not_a_lead(self):
        res = scan([item("They quoted me $600, is this worth fixing? Any recommendations?")],
                   self.moto, now=NOW)
        self.assertEqual(res.leads, [])
        self.assertEqual(res.discarded[0].stage, "subject")

    def test_negated_intent_is_not_demand(self):
        res = scan([item("My bike carb is fine, I don't need a mechanic")], self.moto, now=NOW)
        self.assertEqual(res.leads, [])

    def test_fresher_post_outranks_identical_older_one(self):
        a = item("My bike won't start, carb issue, anyone know a good shop?", id="new", age_hours=1)
        b = item("My motorcycle won't start, clutch issue, anyone know a good shop?", id="old", age_hours=96)
        res = scan([b, a], self.moto, now=NOW)
        self.assertEqual([l.item.id for l in res.leads], ["new", "old"])

    def test_recency_floor_prevents_total_erasure(self):
        res = scan([item("My bike won't start, carb, anyone know a good shop?", age_hours=10_000)],
                   self.moto, now=NOW)
        self.assertEqual(len(res.leads), 1)
        self.assertGreater(res.leads[0].score, 0.0)

    def test_near_duplicates_are_collapsed(self):
        a = item("My Sportster won't turn over at all, think the carb is gummed up, know a good shop?",
                 id="a", author="u/same", age_hours=3)
        b = item("My Sportster wont turn over at all, think the carb is gummed up, know a good shop?",
                 id="b", author="u/same", age_hours=4)
        res = scan([a, b], self.moto, now=NOW)
        self.assertEqual(len(res.leads), 1)
        self.assertEqual(res.discarded[-1].stage, "duplicate")

    def test_venue_weight_applies(self):
        it = item("My bike won't start, carb, anyone know a good shop?", venue="junk")
        base = scan([it], self.moto, now=NOW).leads[0].score
        down = scan([it], self.moto, now=NOW, venue_weights={"junk": 0.5}).leads[0].score
        self.assertAlmostEqual(down, base * 0.5, places=6)

    def test_every_lead_explains_itself(self):
        res = scan(load_items(ROOT / "fixtures" / "mixed_venue.json", now=NOW), self.moto, now=NOW)
        self.assertTrue(res.leads)
        for lead in res.leads:
            self.assertTrue(lead.explanation.subject_hits)
            self.assertTrue(lead.explanation.intent_hits)
            self.assertTrue(any("score" in line for line in lead.explanation.lines()))

    def test_every_discard_names_its_rule(self):
        res = scan(load_items(ROOT / "fixtures" / "mixed_venue.json", now=NOW), self.moto, now=NOW)
        for d in res.discarded:
            self.assertTrue(d.reason, f"{d.item.id} discarded with no reason")
            self.assertIn(d.stage, {"exclude", "subject", "intent", "score", "duplicate"})

    def test_unavailable_sources_are_carried_through(self):
        """Silent omission of a source is a bug."""
        res = scan([], self.moto, now=NOW,
                   unavailable={"facebook:groups": "not signed in"})
        self.assertEqual(res.unavailable["facebook:groups"], "not signed in")

    def test_determinism(self):
        items = load_items(ROOT / "fixtures" / "mixed_venue.json", now=NOW)
        a = scan(items, self.moto, now=NOW)
        b = scan(list(reversed(items)), self.moto, now=NOW)
        self.assertEqual([l.item.id for l in a.leads], [l.item.id for l in b.leads])


class TestNarrowing(unittest.TestCase):
    """The search box narrows an already trade-filtered set. It is NOT a
    description of who to look for -- that is the profile's job."""

    def setUp(self):
        self.moto = PROFILES["motorcycle-repair"]
        self.lead = item("My bike won't start, the carb is gummed up, know a good shop?")

    def test_empty_narrowing_changes_nothing(self):
        for value in (None, "", "   ", []):
            self.assertEqual(len(scan([self.lead], self.moto, now=NOW, narrow=value).leads), 1, value)

    def test_narrowing_keeps_a_matching_lead(self):
        self.assertEqual(len(scan([self.lead], self.moto, now=NOW, narrow="carb").leads), 1)

    def test_narrowing_drops_a_lead_that_does_not_mention_it(self):
        res = scan([self.lead], self.moto, now=NOW, narrow="clutch")
        self.assertEqual(res.leads, [])
        self.assertEqual(res.discarded[0].stage, "narrow")
        self.assertIn("clutch", res.discarded[0].reason)

    def test_several_words_are_alternatives_not_one_phrase(self):
        """Typing "carb clutch" means either."""
        self.assertEqual(len(scan([self.lead], self.moto, now=NOW, narrow="clutch carb").leads), 1)

    def test_a_list_is_kept_as_a_phrase(self):
        self.assertEqual(len(scan([self.lead], self.moto, now=NOW, narrow=["fork seal"]).leads), 0)

    def test_describing_the_customer_matches_nothing(self):
        """The trap this whole design exists to avoid: nobody posts the sentence
        "people who need motorcycle repairs", so typing it finds nothing."""
        res = scan([self.lead], self.moto, now=NOW, narrow=["people who need motorcycle repairs"])
        self.assertEqual(res.leads, [])

    def test_the_match_is_explained(self):
        lead = scan([self.lead], self.moto, now=NOW, narrow="carb").leads[0]
        self.assertTrue(lead.explanation.narrow_hits)
        self.assertIn("matched", " ".join(lead.explanation.lines()))


class TestPrompts(unittest.TestCase):
    def test_every_profile_offers_prompts(self):
        for trade, prof in PROFILES.items():
            self.assertTrue(prof.prompts(), trade)

    def test_prompts_fall_back_to_the_profiles_own_phrases(self):
        prof = Profile.from_dict({
            "trade": "t",
            "subject": [{"terms": ["widget"], "weight": 3}],
            "intent": [{"terms": ["broken widget"], "weight": 4}],
        })
        self.assertEqual(prof.prompts(2)[0], "broken widget")

    def test_prompts_are_things_a_customer_would_actually_write(self):
        """A prompt must survive the matcher, or suggesting it is a lie."""
        from branch.text import compile_phrase, normalize
        for trade, prof in PROFILES.items():
            for prompt in prof.prompts():
                text = normalize(f"my {prompt} is giving me trouble")
                self.assertTrue(compile_phrase(prompt).search(text), f"{trade}: {prompt}")


class TestProfiles(unittest.TestCase):
    def test_all_profiles_load_without_warnings(self):
        self.assertGreaterEqual(len(PROFILES), 4)
        for trade, prof in PROFILES.items():
            self.assertEqual(prof.validate(), [], f"{trade} has warnings")

    def test_unreachable_threshold_is_flagged(self):
        prof = Profile.from_dict({
            "trade": "broken",
            "subject": [{"terms": ["x"], "weight": 1}],
            "intent": [{"terms": ["y"], "weight": 1}],
            "exclude": [["z"]],
            "thresholds": {"subject": 99},
        })
        self.assertTrue(any("can ever match" in w for w in prof.validate()),
                        prof.validate())

    def test_terse_and_verbose_group_forms_are_equivalent(self):
        a = Profile.from_dict({"trade": "t", "subject": [["alpha", "beta"]]})
        b = Profile.from_dict({"trade": "t", "subject": [{"terms": ["alpha", "beta"], "weight": 1}]})
        self.assertEqual(a.subject[0].terms, b.subject[0].terms)
        self.assertEqual(a.subject[0].weight, b.subject[0].weight)

    def test_missing_trade_key_is_rejected(self):
        with self.assertRaises(ValueError):
            Profile.from_dict({"subject": [["a"]]})


class TestFixtureAccuracy(unittest.TestCase):
    """The end-to-end check: each profile must find its own leads and nobody else's."""

    def test_each_profile_matches_only_its_own(self):
        items = load_items(ROOT / "fixtures" / "mixed_venue.json", now=NOW)
        failures: list[str] = []
        for trade, prof in sorted(PROFILES.items()):
            got = {l.item.id for l in scan(items, prof, now=NOW).leads}
            # `expect` may name more than one trade: "our photographer fell
            # through, looking for someone" is a real lead for the wedding
            # specialist and for a photographer, and calling either one a false
            # positive would be teaching the engine something untrue.
            def expects(item) -> bool:
                wanted = item.extra.get("expect")
                return trade in (wanted if isinstance(wanted, list) else [wanted])

            want = {i.id for i in items if expects(i)}
            for missed in sorted(want - got):
                failures.append(f"{trade}: MISSED {missed}")
            for wrong in sorted(got - want):
                why = next((i.extra.get("why", "") for i in items if i.id == wrong), "")
                failures.append(f"{trade}: FALSE POSITIVE {wrong} ({why})")
        self.assertEqual(failures, [], "\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestSharedExclusions(unittest.TestCase):
    """profiles/_defaults.yaml is merged into every trade."""

    def test_defaults_are_not_loaded_as_a_trade(self):
        self.assertNotIn("_defaults", PROFILES)

    def test_every_trade_inherits_them(self):
        for trade, prof in PROFILES.items():
            labels = {g.label for g in prof.exclude}
            self.assertIn("news-and-product-announcements", labels, trade)

    def test_a_product_announcement_is_not_a_lead(self):
        """"Hitachi launches CO2 heat pump water heaters" was matching plumbing
        on "water heater" + "leak" -- the exact false positive these exist for."""
        post = item("Hitachi launches CO2 heat pump water heaters with no leak risk",
                    id="news")
        self.assertEqual(scan([post], PROFILES["plumbing"], now=NOW).leads, [])

    def test_a_real_lead_still_gets_through(self):
        post = item("My water heater is leaking everywhere, need a plumber, "
                    "any recommendations?", id="real")
        self.assertEqual(len(scan([post], PROFILES["plumbing"], now=NOW).leads), 1)


class TestThreadDedupe(unittest.TestCase):
    def test_two_comments_on_one_thread_are_one_lead(self):
        """A busy thread was flooding the list with what is really one opportunity."""
        profile = PROFILES["plumbing"]
        posts = [
            item("my water heater is leaking, need a plumber, recommendations?",
                 id="a", title="Water heater trouble", venue="hn", age_hours=2),
            item("same thing happened to me, the heater leaks and I need a plumber too",
                 id="b", title="Water heater trouble", venue="hn", age_hours=3),
        ]
        result = scan(posts, profile, now=NOW)
        self.assertEqual(len(result.leads), 1)
        self.assertEqual(result.discarded[-1].stage, "duplicate")

    def test_same_title_in_different_venues_is_not_a_duplicate(self):
        profile = PROFILES["plumbing"]
        posts = [
            item("water heater leaking, need a plumber, recommendations?",
                 id="a", title="Help", venue="reddit:r/Dallas", age_hours=2),
            item("water heater leaking, need a plumber, recommendations?",
                 id="b", title="Help", venue="reddit:r/Plano", age_hours=3),
        ]
        # Same text in two places is still a near-duplicate; different titles
        # in different venues are not. Check the venue rule in isolation.
        self.assertFalse(
            __import__("branch.engine", fromlist=["x"])._same_thread(posts[0], posts[1]))


class TestCrossPostDedupe(unittest.TestCase):
    """The same post shared to two groups is one lead."""

    def setUp(self):
        self.profile = PROFILES["plumbing"]
        self.body = ("Bindu Pyakurel Hey everyone, I need a plumber to help me out. "
                     "My kitchen sink is backing up and leaking underneath")

    def test_same_post_under_two_group_names_is_one_lead(self):
        posts = [
            item(f"Homeowners find Contractors - DFW {self.body}", id="a",
                 venue="facebook", age_hours=2),
            item(f"DFW - Contractors For Hire {self.body}", id="b",
                 venue="facebook", age_hours=3),
        ]
        self.assertEqual(len(scan(posts, self.profile, now=NOW).leads), 1)

    def test_containment_does_not_apply_across_venues(self):
        """Two people with the same problem in different places are two leads."""
        posts = [
            item(f"Homeowners find Contractors - DFW {self.body}", id="a",
                 venue="facebook", age_hours=2),
            item(f"DFW - Contractors For Hire {self.body}", id="b",
                 venue="reddit:r/Dallas", age_hours=3),
        ]
        self.assertEqual(len(scan(posts, self.profile, now=NOW).leads), 2)

    def test_genuinely_different_posts_survive(self):
        posts = [
            item(f"Homeowners find Contractors - DFW {self.body}", id="a",
                 venue="facebook", age_hours=2),
            item("My water heater is leaking and I need a plumber in Plano urgently",
                 id="b", venue="facebook", age_hours=3),
        ]
        self.assertEqual(len(scan(posts, self.profile, now=NOW).leads), 2)


class TestAdvertisingExclusions(unittest.TestCase):
    """The trade advertising itself is the largest false positive on Facebook.

    Search "need a plumber Dallas" and half the results are plumbing companies,
    whose adverts naturally contain every word a customer would use. A live scan
    returned four competitors in nine leads before these existed.
    """

    def setUp(self):
        self.profile = PROFILES["plumbing"]

    def _leads(self, text):
        return scan([item(text, id="x")], self.profile, now=NOW).leads

    def test_a_company_advert_is_not_a_lead(self):
        for advert in [
            "NO HOT WATER? LEAKING WATER HEATER? WE FIX IT FAST! Call us today, free estimate",
            "Burst Pipe? Call Dallas' Emergency Plumbing Experts! 24/7 service",
            "Should you repair or replace your water heater? Our team can help, licensed and insured",
        ]:
            with self.subTest(advert=advert[:40]):
                self.assertEqual(self._leads(advert), [])

    def test_praising_a_plumber_is_not_a_lead(self):
        self.assertEqual(self._leads("HIGHLY RECOMMENDED PLUMBER - DFW! so thankful"), [])

    def test_asking_for_recommendations_still_is(self):
        """The near-miss these have to avoid: "any recommendations?" is a real
        request, so the praise phrases are statements rather than questions."""
        self.assertEqual(
            len(self._leads("any recommendations for a plumber? my water heater is leaking")), 1)

    def test_real_requests_survive_all_of_it(self):
        for request in [
            "Hey everyone, I need a plumber to help me out. My kitchen sink is backed up in 75038",
            "Who Does Good Plumbing Work In Dallas? My Grandmother's House Has Some Leaks And I Need someone",
            "House at Dallas 75287, the water heater at attic is leaking, needs to fix now, please help",
        ]:
            with self.subTest(request=request[:40]):
                self.assertEqual(len(self._leads(request)), 1)


class TestSomebodyHasToBeAsking(unittest.TestCase):
    """The rule the whole program turns on: a lead is a REQUEST, not a mention.

    Every case here is real text from a live scan or a direct variation of one.
    """

    def setUp(self):
        self.profile = PROFILES["plumbing"]

    def _scan(self, text: str):
        got = scan([item(text, venue="facebook")], self.profile, now=NOW)
        return got.leads, got.discarded

    def test_an_explicit_request_is_a_lead(self):
        leads, _ = self._scan("Anyone know a good plumber? Leak under my kitchen sink.")
        self.assertEqual(len(leads), 1)

    def test_your_own_problem_is_a_lead_without_asking(self):
        """Nobody writes "I need a plumber" when the garage is filling up."""
        leads, _ = self._scan("My water heater is leaking all over the garage floor.")
        self.assertEqual(len(leads), 1)

    def test_a_five_star_review_is_not_a_lead(self):
        """Live Dallas scan, 2026-09-16: this was returned as a lead. It matched
        "leak*" and it says "my home", so neither the trade words nor a
        first-person test anywhere in the post can tell it from a customer."""
        leads, discarded = self._scan(
            "Best plumber around! Excellent service, they did a wonderful job "
            "fixing a leak outside of my home. Would highly recommend them.")
        self.assertEqual(leads, [])
        self.assertEqual(discarded[0].stage, "request")

    def test_a_plumber_advertising_is_not_a_lead(self):
        """Also live: a plumbing company's own post scored 9.9 on trade words."""
        leads, _ = self._scan(
            "Ever wonder what is actually behind your shower handle? Most "
            "homeowners only see the trim. We see the pipe, the valve and the "
            "leak behind it.")
        self.assertEqual(leads, [])

    def test_a_solved_problem_is_not_a_lead(self):
        leads, _ = self._scan("I do not need a plumber anymore, got the leak fixed.")
        self.assertEqual(leads, [])

    def test_an_impersonal_request_is_still_a_lead(self):
        """Live Dallas scan: a real customer, written with no "I" anywhere. The
        request gate must not require first person -- asking is enough."""
        leads, _ = self._scan("House at Dallas 75287, the water heater at attic "
                              "is leaking, needs to fix now, please help")
        self.assertEqual(len(leads), 1)

    def test_ownership_is_read_close_to_the_problem_not_anywhere(self):
        from branch.engine import OWNERSHIP_AFTER, OWNERSHIP_BEFORE
        self.assertGreater(OWNERSHIP_BEFORE, OWNERSHIP_AFTER,
                           "'fixing a leak at my home' is a review; "
                           "'flooded my basement' is a customer")

    def test_the_explanation_says_who_asked(self):
        leads, _ = self._scan("Anyone know a good plumber? My sink is backed up.")
        self.assertTrue(leads[0].explanation.request_hits,
                        "a lead must be able to show the words that asked")

    def test_asking_language_is_shared_by_every_trade(self):
        """A profile says what its trade is; _defaults says what asking is."""
        for slug, profile in PROFILES.items():
            with self.subTest(trade=slug):
                requests = [g for g in profile.intent if g.kind == "request"]
                self.assertTrue(requests, f"{slug} has no way to notice a request")
                terms = {t for g in requests for t in g.terms}
                self.assertIn("please help", terms)
