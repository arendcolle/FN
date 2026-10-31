import hashlib
import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from fn.contracts import Candidate, ClaimDraft, Identifier, Search, Source, TieLabel
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

STATIC = Path(create_app.__code__.co_filename).parent / "static"


class VendoredMapTest(unittest.TestCase):
    def test_vendored_files_match_the_sha256_recorded_when_the_npm_tarball_was_verified(self):
        """Editing a vendored file, or pointing the style at another host, fails this test."""
        manifest = json.loads((STATIC / "vendor.json").read_text())
        self.assertRegex(manifest["version"], r"^5\.\d+\.\d+$")
        self.assertTrue(manifest["integrity"].startswith("sha512-"))
        self.assertEqual(set(manifest["sha256"]), {"maplibre-gl.js", "maplibre-gl.css", "maplibre-gl.LICENSE.txt", "positron.json"})
        for name, digest in manifest["sha256"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((STATIC / name).read_bytes()).hexdigest(), digest)
        style = json.loads((STATIC / "positron.json").read_text())
        urls = [style["sprite"], style["glyphs"], *(s["url"] for s in style["sources"].values() if "url" in s),
                *(t for s in style["sources"].values() for t in s.get("tiles", []))]
        self.assertEqual({urlsplit(u).netloc for u in urls}, {"tiles.openfreemap.org"})


class GeoTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def person(self, name: str, seed: str, *places: tuple[str, str | None, float, float]) -> str:
        """A person with one location claim per (place, date, lat, lon); a date of None leaves the claim undated."""
        person = self.store.resolve_person([Identifier(scheme="seed", value=seed)], name)
        for place, date, lat, lon in places:
            text = f"geo.city: {place}\ngeo.latitude: {lat}\n"
            source = Source(id=f"src-{seed}-{place}", kind="record", url="https://example.org/" + place.lower(),
                            title=place, text=text, content_hash=place)
            self.store.upsert_claim(ClaimDraft(
                person_id=person.id, kind="location", value=place, quote=f"geo.city: {place}", quote_start=0,
                quote_end=len(f"geo.city: {place}"), source=source, claim_date=date,
                date_precision="day" if date else None, date_method="read_date" if date else None, lat=lat, lon=lon))
        return person.id

    def test_geo_has_one_point_per_person_with_a_dated_location_claim_and_its_quote(self):
        """Persons without a location or without a dated one are left out, and the newest claim wins."""
        ann = self.person("Ann Near", "ann-1", ("Leuven", "2020-01-01", 50.88, 4.7), ("Cambridge", "2024-05-01", 42.37, -71.1))
        ann_twin = self.person("Ann Near", "ann-2", ("Delft", "2023-02-02", 52.0, 4.36))
        bob = self.person("Bob Nowhere", "bob")
        cy = self.person("Cy Undated", "cy", ("Gent", None, 51.05, 3.72))
        search = Search(id="s1", question="q", status="done", created_at=now(), code_sha=None, dirty=False,
                        llm_mode="replay", settings_json="{}", boot_id="b")
        self.store.create_search(search)
        tie = TieLabel(tie="none_found", rules_version="t")
        self.store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=ann, person_ids=[ann, ann_twin], section="new", rank=1, score=1.0,
                      lane_ranks={"openalex": 1}, tie=tie),
            Candidate(search_id="s1", person_id=bob, person_ids=[bob], section="new", rank=2, score=0.5,
                      lane_ranks={"seeds": 1}, tie=tie),
            Candidate(search_id="s1", person_id=cy, person_ids=[cy], section="new", rank=3, score=0.4,
                      lane_ranks={"seeds": 2}, tie=tie),
        ], [])
        response = self.client.get("/api/searches/s1/geo")
        self.assertEqual(response.status_code, 200)
        first, second = response.json()["features"]
        self.assertEqual(len(response.json()["features"]), 2)
        self.assertEqual(first["geometry"]["coordinates"], [-71.1, 42.37])
        self.assertEqual(first["properties"]["quote"], "geo.city: Cambridge")
        self.assertEqual((first["properties"]["name"], first["properties"]["claim_date"]), ("Ann Near", "2024-05-01"))
        self.assertTrue(first["properties"]["source_page"].startswith("/sources/src-ann-1-Cambridge?claim="))
        self.assertEqual((second["properties"]["place"], second["properties"]["quote"]), ("Delft", "geo.city: Delft"))
        self.assertEqual(self.client.get("/api/searches/nope/geo").status_code, 404)

    def test_map_page_loads_vendored_scripts_with_no_inline_script_and_the_search_page_links_to_it(self):
        """The CSP allows scripts from this site only, so the page names its scripts and the geo URL in attributes; the question stays text."""
        search = Search(id="s2", question='"><script>alert(1)</script>', status="done", created_at=now(), code_sha=None, dirty=False,
                        llm_mode="replay", settings_json="{}", boot_id="b")
        self.store.create_search(search)
        html = self.client.get("/searches/s2/map").text
        self.assertEqual(html.count("<script"), 2)
        self.assertIn("&lt;script&gt;alert(1)", html)
        for needle in ('src="/static/maplibre-gl.js"', 'src="/static/map.js"', 'href="/static/maplibre-gl.css"',
                       'data-geo="/api/searches/s2/geo"'):
            self.assertIn(needle, html)
        self.assertIn('href="/searches/s2/map"', self.client.get("/searches/s2").text)
        self.assertEqual(self.client.get("/searches/nope/map").status_code, 404)


if __name__ == "__main__":
    unittest.main()
