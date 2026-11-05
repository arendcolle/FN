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


if __name__ == "__main__":
    unittest.main()
