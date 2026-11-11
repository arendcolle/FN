import unittest

import httpx

from fn import geo
from fn.contracts import Place
from tests.helpers import FIXTURES, cities_zip

CITIES = geo.index((FIXTURES / "geo" / "cities15000-extract.txt").read_text(encoding="utf-8"))


class GeoTest(unittest.TestCase):
    def test_place_resolves_to_its_largest_named_city_with_a_radius(self):
        """New York and New Jersey becomes New York City with the metro radius; a place naming no city gives None."""
        area = geo.locate("New York and New Jersey area", CITIES)
        self.assertEqual((area.city, area.radius_km), ("New York City, US", geo.METRO_RADIUS_KM))
        self.assertAlmostEqual(area.lat, 40.714, places=2)
        self.assertAlmostEqual(area.lon, -74.006, places=2)
        self.assertEqual(geo.locate("Menlo Park", CITIES).city, "Menlo Park, US")
        self.assertIsNone(geo.locate("anywhere in the US", CITIES))
        self.assertIsNone(geo.locate("", CITIES))
        self.assertAlmostEqual(geo.distance_km(area.lat, area.lon, 40.73566, -74.17237), 14.2, places=0)

    def test_cities_are_fetched_once_per_client(self):
        """The dump is fetched through the given client and unzipped once, then served from memory."""
        calls = []

        class Http:
            def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
                calls.append(url)
                return httpx.Response(200, content=cities_zip())

        http = Http()
        self.assertEqual(geo.cities(http), CITIES)
        geo.cities(http)
        self.assertEqual(calls, [geo.CITIES_URL])

    def test_area_locates_only_a_metro_place_and_fetches_the_dump_only_then(self):
        """A metro or unkinded place chip gives its metro area; no place, abroad, anywhere_us or unknown city is None.

        The cities dump is fetched once, and only for a metro or unkinded place.
        """
        calls = []

        class Http:
            def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
                calls.append(url)
                return httpx.Response(200, content=cities_zip())

        def place(text: str, kind: str | None) -> Place:
            return Place(text=text, origin="parsed", kind=kind)

        http = Http()
        self.assertIsNone(geo.area(http, None))
        self.assertIsNone(geo.area(http, place("Leuven region", "abroad")))
        self.assertIsNone(geo.area(http, place("anywhere in the US", "anywhere_us")))
        self.assertEqual(calls, [])
        self.assertEqual(geo.area(http, place("Menlo Park area", None)), geo.locate("Menlo Park area", CITIES))
        self.assertEqual(geo.area(http, place("New York", "metro")).city, "New York City, US")
        self.assertIsNone(geo.area(http, place("Gotham", "metro")))
        self.assertEqual(calls, [geo.CITIES_URL])

    def test_a_place_text_resolves_to_the_city_its_state_country_or_metro_names(self):
        """A metro alias wins, a known state or country qualifier must match, an unknown one is ignored.

        A bare name keeps the largest city; a text naming only a state or country is None.
        """
        cases = [
            ("Bay Area", "San Francisco, US", (37.77, -122.42)), ("San Francisco Bay Area", "San Francisco, US", None),
            ("Silicon Valley", "San Jose, US", (37.34, -121.89)), ("Greater Boston", "Boston, US", None),
            ("Boston area", "Boston, US", None), ("Cambridge, Massachusetts", "Cambridge, US", (42.37, -71.11)),
            ("Cambridge, MA", "Cambridge, US", None), ("Cambridge, Massachusetts, United States", "Cambridge, US", None),
            ("Cambridge", "Cambridge, GB", None), ("Cambridge, UK", "Cambridge, GB", None),
            ("Cambridge, Texas", None, None), ("Portland, Maine", "Portland, US", (43.66, -70.26)),
            ("Portland Maine", "Portland, US", (43.66, -70.26)), ("Portland", "Portland, US", (45.52, -122.68)),
            ("Paris, Texas", "Paris, US", (33.66, -95.56)), ("Paris", "Paris, FR", None),
            ("Springfield, Massachusetts", "Springfield, US", (42.10, -72.59)),
            ("Columbus, Georgia", "Columbus, US", (32.46, -84.99)), ("Atlanta, GA", "Atlanta, US", None),
            ("Washington, DC", "Washington, US", None), ("New York and New Jersey area", "New York City, US", None),
            ("Brussels, Brussels Region, Belgium", "Brussels, BE", None),
            ("Leuven, Flemish Region, Belgium", "Leuven, BE", None), ("London", "London, GB", None),
            ("Toronto, CA", "Toronto, CA", None), ("Toronto, Canada", "Toronto, CA", None),
            ("Georgia", None, None), ("anywhere in the US", None, None), ("", None, None),
        ]
        for text, city, near in cases:
            with self.subTest(text=text):
                found = geo.locate(text, CITIES)
                self.assertEqual(found and found.city, city)
                if near:
                    self.assertAlmostEqual(found.lat, near[0], places=1)
                    self.assertAlmostEqual(found.lon, near[1], places=1)

    def test_a_city_with_its_state_and_country_apart_resolves_by_the_same_rules(self):
        """State and country each take a name or a code; an unknown city, or a known state that misses, is None."""
        cases = [(("Cambridge", "MA", None), "Cambridge, US"), (("Cambridge", "Massachusetts", "USA"), "Cambridge, US"),
                 (("Cambridge", None, "United States"), "Cambridge, US"), (("Cambridge", None, "UK"), "Cambridge, GB"),
                 (("Cambridge", None, None), "Cambridge, GB"), (("Leuven", None, "Belgium"), "Leuven, BE"),
                 (("Nowhere", "MA", None), None), (("Cambridge", "TX", None), None),
                 (("Toronto", None, "CA"), "Toronto, CA"), (("Leuven", None, "Netherlands"), None)]
        for args, city in cases:
            with self.subTest(args=args):
                found = geo.locate_city(*args, CITIES)
                self.assertEqual(found and found.city, city)


if __name__ == "__main__":
    unittest.main()
