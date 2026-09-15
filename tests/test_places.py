"""City lookup and position detection. No network: the dataset is bundled, and
the one test that touches geolocation stubs the HTTP call.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from branch import locate, places                                   # noqa: E402

FORNEY = (32.749, -96.4629)      # what the geoip service returns for this machine


class TestCities(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cities = places.load_cities()

    def test_dataset_is_bundled_and_loads(self):
        self.assertGreater(len(self.cities), 15_000)

    def test_nearest_major_picks_the_metro_anchor(self):
        """From Forney the nearest city over 100k is Mesquite, but the answer a
        person expects is Dallas. 'Biggest within reach', not 'nearest large'."""
        city = places.nearest_major_city(*FORNEY, cities=self.cities)
        self.assertEqual(city.label, "Dallas, TX")

    def test_nearest_major_works_far_from_any_metro(self):
        city = places.nearest_major_city(48.0, -100.0, cities=self.cities)   # rural ND
        self.assertIsNotNone(city)
        self.assertTrue(city.admin1)

    def test_suggestions_prefer_nearby_over_distant_namesakes(self):
        got = places.suggest("dal", near=FORNEY, limit=5, cities=self.cities)
        self.assertEqual(got[0].label, "Dallas, TX")
        labels = [c.label for c in got]
        self.assertNotIn("Dallas, OR", labels[:1])

    def test_suggestions_include_small_towns(self):
        """A plumber serves towns, not just metros."""
        got = places.suggest("forn", near=FORNEY, limit=5, cities=self.cities)
        self.assertEqual(got[0].label, "Forney, TX")

    def test_state_narrows_the_match(self):
        got = places.suggest("dallas, or", near=FORNEY, limit=5, cities=self.cities)
        self.assertTrue(got)
        self.assertEqual(got[0].admin1, "OR")

    def test_empty_prefix_suggests_nothing(self):
        self.assertEqual(places.suggest("   ", near=FORNEY, cities=self.cities), [])

    def test_find_resolves_a_label_to_coordinates(self):
        city = places.find("Dallas, TX", cities=self.cities)
        self.assertIsNotNone(city)
        self.assertAlmostEqual(city.lat, 32.78, places=1)

    def test_find_rejects_nonsense(self):
        self.assertIsNone(places.find("Nowhereville, ZZ", cities=self.cities))

    def test_haversine_is_sane(self):
        km = places.haversine_km(32.7831, -96.8067, 29.7604, -95.3698)   # Dallas->Houston
        self.assertTrue(340 < km < 380, km)


class TestLocate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "location.json"

    def test_cache_round_trip(self):
        locate.write_cache(locate.Fix(32.7, -96.8, "geoip"), self.tmp)
        got = locate.read_cache(self.tmp)
        self.assertAlmostEqual(got.lat, 32.7)
        self.assertEqual(got.source, "cache")

    def test_detect_without_network_returns_nothing(self):
        self.assertIsNone(locate.detect(use_network=False, path=self.tmp))

    def test_detect_prefers_cache_and_does_not_call_out(self):
        locate.write_cache(locate.Fix(1.0, 2.0, "geoip"), self.tmp)
        called = []
        original = locate.lookup_geoip
        locate.lookup_geoip = lambda *a, **k: called.append(1)
        try:
            fix = locate.detect(path=self.tmp)
        finally:
            locate.lookup_geoip = original
        self.assertEqual(called, [])
        self.assertEqual((fix.lat, fix.lon), (1.0, 2.0))

    def test_lookup_failure_is_silent(self):
        self.assertIsNone(locate.lookup_geoip("http://127.0.0.1:9/nope", timeout=0.2))

    def test_unreadable_cache_is_not_fatal(self):
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text("{ not json", encoding="utf-8")
        self.assertIsNone(locate.read_cache(self.tmp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
