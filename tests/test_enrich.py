"""What a post tells you about itself. Deterministic, and deliberately limited."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from branch import enrich                                       # noqa: E402
from branch.places import load_cities                           # noqa: E402

DALLAS = (32.7831, -96.8067)


class TestEnrich(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cities = load_cities()

    def test_finds_a_postcode(self):
        self.assertEqual(enrich.find_zip("rental property located in 75217, help"), "75217")

    def test_a_price_is_not_a_postcode(self):
        self.assertIsNone(enrich.find_zip("selling for $12500 today"))

    def test_finds_a_town_named_in_the_post(self):
        town = enrich.find_town("mobile mechanic in Dallas/Mesquite/Garland area",
                                DALLAS, self.cities)
        self.assertIn(town, {"Dallas", "Mesquite", "Garland"})

    def test_separators_do_not_hide_towns(self):
        """"Dallas/Mesquite/Garland" is three towns; matching on " name " alone
        found none of them."""
        self.assertIsNotNone(enrich.find_town("serving Plano/Frisco", DALLAS, self.cities))

    def test_distant_towns_are_not_treated_as_locations(self):
        self.assertIsNone(enrich.find_town("my friend Austin needs help", DALLAS,
                                           self.cities, radius_km=80))

    def test_urgency_and_budget(self):
        self.assertIn("urgent", enrich.signals("need someone ASAP please"))
        self.assertIn("mentions a budget", enrich.signals("budget is $400"))

    def test_contact_details_are_reported_not_extracted(self):
        """Branch says a number is there. It does not lift it into a list --
        that is the dossier-building the whole design refuses."""
        found = enrich.signals("call me on 214-555-0182")
        self.assertIn("left a number", found)
        for note in found:
            self.assertNotIn("214", note)
            self.assertNotIn("555", note)

    def test_describe_combines_them(self):
        out = enrich.describe("need someone in 75217 today ASAP, budget $400, dm me",
                              DALLAS, self.cities)
        self.assertIn("75217", out)
        self.assertIn("urgent", out)
        self.assertIn("asks for DMs", out)

    def test_nothing_to_say_is_an_empty_list(self):
        self.assertEqual(enrich.describe("hello there", DALLAS, self.cities), [])
