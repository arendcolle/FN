import re
import unittest
from datetime import timedelta

from fastapi.testclient import TestClient

from fn import network
from fn.contracts import Candidate, ClaimDraft, Identifier, Search, Source
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

START = now() - timedelta(days=30)


class NetworkPageTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def claim(self, person_id: str, kind: str, value: str, at=None, **fields) -> None:
        text = f"{value} of {person_id}"
        source = Source(id=f"src-{person_id}-{kind}-{value}", kind="page", url=f"https://example.org/{person_id}/{kind}",
                        title="Example page", text=text, content_hash=f"h-{person_id}-{kind}-{value}")
        self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, value=value, quote=text, quote_start=0,
                                           quote_end=len(text), source=source, **fields), at)

    def person(self, name: str, hours: int | None = 0, place: tuple[str, float, float] | None = None,
               employer: str | None = None, import_id: str | None = None) -> str:
        """A made-up person with an optional place and employer, added to the network hours after START unless None."""
        person_id = self.store.resolve_person([Identifier(scheme="seed", value=name)], name).id
        if place:
            self.claim(person_id, "location", place[0], START, lat=place[1], lon=place[2])
        if employer:
            self.claim(person_id, "affiliation", employer, START, relation="works_at")
        if hours is not None:
            network.add(self.store, [person_id], via="import" if import_id else "search", import_id=import_id,
                        now=START + timedelta(hours=hours))
        return person_id

    def names(self, html: str) -> list[str]:
        return re.findall(r'<h3 class="fn-row__name text-name"><a href="/people/[^"]+">([^<]+)</a>', html)

    def count_line(self, html: str) -> str:
        return re.search(r'<p class="fn-count text-meta"><span>([^<]*)</span>', html).group(1)

    def test_people_lists_the_network_newest_added_first_and_never_a_candidate(self):
        """Rows are network people only, ordered by their latest add, each a link to the Person page."""
        self.person("Ada Older", 1)
        newer = self.person("Bo Newer", 5, ("Gent", 51.05, 3.72), "Example Labs")
        self.person("Cy Candidate", None)
        html = self.client.get("/people").text
        self.assertEqual(self.names(html), ["Bo Newer", "Ada Older"])
        self.assertIn(f'class="fn-row" id="person-1" data-person="{newer}" data-place>', html)
        self.assertIn("Example Labs · Gent", html)
        self.assertIn("location not found", html)
        self.assertEqual(self.count_line(html), "2 people · 1 not on the map")

    def test_the_filter_matches_name_organization_and_place_in_any_case_with_plain_wildcards(self):
        """Text matches part of a name, organization or place ignoring case; % and _ match themselves; spaces are no filter."""
        self.person("Ada Vermeer", 1, ("Antwerpen", 51.2, 4.4), "Harbour Works")
        self.person("Bo 100% Smit", 2, ("Gent", 51.05, 3.72), "Tide_Lab")
        for text, expected in (("verm", ["Ada Vermeer"]), ("HARBOUR", ["Ada Vermeer"]), ("gEnT", ["Bo 100% Smit"]),
                               ("100%", ["Bo 100% Smit"]), ("e_l", ["Bo 100% Smit"]), ("Smi_", []), ("Ad%r", []),
                               ("'", []),
                               ("   ", ["Bo 100% Smit", "Ada Vermeer"])):
            with self.subTest(text=text):
                html = self.client.get("/people", params={"q": text}).text
                self.assertEqual(self.names(html), expected)
        self.assertIn("Clear all", self.client.get("/people", params={"q": "gent"}).text)
        self.assertNotIn("Clear all", self.client.get("/people", params={"q": "  "}).text)

    def test_import_and_new_facts_tokens_narrow_the_list(self):
        """import=<id> keeps the people that import added; new=1 keeps people with a fact first seen after seen_at."""
        self.store.conn.execute("INSERT INTO imports (id, filename, uploaded_at, status, text) "
                                "VALUES ('imp1', 'contacts.csv', ?, 'confirmed', '')", (START.isoformat(),))
        imported = self.person("Ada Imported", 1, import_id="imp1")
        self.person("Bo Searched", 2)
        fresh = self.person("Cy Fresh", 3)
        self.claim(fresh, "topic", "Tidal energy", START + timedelta(days=1))
        html = self.client.get("/people", params={"import": "imp1"}).text
        self.assertEqual(self.names(html), ["Ada Imported"])
        self.assertIn('<li class="fn-token text-meta"><span>From import contacts.csv</span>'
                      '<a href="/people" aria-label="Clear From import contacts.csv">Clear</a></li>', html)
        self.assertIn('<input type="hidden" name="import" value="imp1">', html)
        html = self.client.get("/people", params={"new": "1"}).text
        self.assertEqual(self.names(html), ["Cy Fresh"])
        self.assertIn('<span class="fn-new text-meta-strong">1 new fact</span>', html)
        self.assertIn("New facts only", html)
        self.assertNotIn(imported, self.client.get("/people", params={"new": "1", "import": "imp1"}).text)

    def test_limit_shows_steps_of_200_and_anything_else_falls_back_to_200(self):
        """The list shows 200 rows, limit=400 shows more, and a limit that is not a positive step of 200 is 200."""
        for n in range(230):
            self.person(f"Person {n:03}", n)
        first = self.client.get("/people").text
        self.assertEqual(len(self.names(first)), 200)
        self.assertEqual(self.count_line(first), "230 people · 230 not on the map")
        self.assertIn('<div class="fn-more text-meta"><span>200 of 230 shown</span>'
                      '<a class="fn-btn fn-btn--quiet text-control" href="/people?limit=400#person-201">Show 30 more</a>',
                      first)
        more = self.client.get("/people", params={"limit": "400"}).text
        self.assertEqual(len(self.names(more)), 230)
        self.assertNotIn("fn-more", more)
        for raw in ("abc", "-5", "999999999", "0", "250"):
            with self.subTest(limit=raw):
                self.assertEqual(len(self.names(self.client.get("/people", params={"limit": raw}).text)), 200)

    def test_an_empty_network_and_a_filter_without_match_show_a_notice_and_no_map(self):
        """No network people shows 'Your network is empty'; a filter matching nobody shows '0 people' and 'Nobody matches'."""
        self.person("Cy Candidate", None)
        for url in ("/people", "/"):
            with self.subTest(url=url):
                html = self.client.get(url).text
                self.assertIn("Your network is empty", html)
                self.assertIn("fn-results--no-map", html)
                self.assertNotIn("fn-row", html)
        self.person("Ada Vermeer", 1, ("Gent", 51.05, 3.72))
        html = self.client.get("/people", params={"q": "zzz"}).text
        self.assertIn('<p class="fn-count text-meta"><span>0 people</span><a href="/people">Clear all</a></p>', html)
        self.assertIn("Nobody matches", html)
        self.assertIn("Nobody in your network has “zzz” in their name, place or organization. Check the spelling, "
                      "or use Clear all to see all 1 person.", html)
        self.assertIn("fn-results--no-map", html)
        self.assertNotIn("fn-results--no-map", self.client.get("/people").text)

    def test_geo_has_one_point_per_placed_person_matching_the_count_line(self):
        """The network geo covers the whole filtered set, without the limit: total minus 'not on the map' points."""
        for n in range(205):
            self.person(f"Placed {n:03}", n, ("Gent", 51.05, 3.72) if n % 2 else None)
        for params in ({}, {"q": "placed 00"}, {"limit": "200"}):
            with self.subTest(params=params):
                total, _, missing = re.match(r"([\d,]+) people(?: · ([\d,]+) not on the map)?",
                                             self.count_line(self.client.get("/people", params=params).text)).group(1, 0, 2)
                features = self.client.get("/api/people/geo", params=params).json()["features"]
                self.assertEqual(len(features), int(total.replace(",", "")) - int((missing or "0").replace(",", "")))
        feature = self.client.get("/api/people/geo").json()["features"][0]
        self.assertEqual(feature["properties"]["href"], f"/people/{feature['properties']['id']}")

    def test_home_shows_three_searches_all_searches_past_three_and_the_network(self):
        """Home caps recent searches at three and links All searches only when there are more; /searches lists all."""
        self.person("Ada Vermeer", 1, ("Gent", 51.05, 3.72))
        for n in range(3):
            self.store.create_search(Search(id=f"s{n}", question=f"Question {n}", status="done",
                                            created_at=START + timedelta(hours=n), code_sha=None, dirty=False,
                                            llm_mode="replay", settings_json="{}", boot_id="b"))
        home = self.client.get("/").text
        self.assertEqual(home.count('<li><a href="/searches/'), 3)
        self.assertNotIn('href="/searches">All searches', home)
        self.assertEqual(self.names(home), ["Ada Vermeer"])
        self.assertIn('class="fn-results fn-results--page"', home)
        self.assertIn('action="/people"', home)
        self.store.create_search(Search(id="s3", question="Question 3", status="done", created_at=START + timedelta(hours=9),
                                        code_sha=None, dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        home = self.client.get("/").text
        self.assertEqual(home.count('<li><a href="/searches/'), 3)
        self.assertNotIn("Question 0", home)
        self.assertIn('<p class="fn-recent__all text-meta"><a href="/searches">All searches</a></p>', home)
        every = self.client.get("/searches").text
        self.assertIn('<h1 class="fn-section text-label">All searches <span>4</span></h1>', every)
        self.assertEqual(re.findall(r">Question (\d)</a>", every), ["3", "2", "1", "0"])

    def test_the_header_links_search_and_network_and_marks_the_current_one(self):
        """Every staff page has Search and Network in the header, with aria-current on the page's own link."""
        for url, current in (("/", "Search"), ("/searches", "Search"), ("/people", "Network")):
            with self.subTest(url=url):
                nav = re.search(r'<nav class="fn-nav text-body" aria-label="Main">(.*?)</nav>', self.client.get(url).text).group(1)
                self.assertEqual(re.findall(r'<a href="([^"]+)"', nav.replace(' aria-current="page"', "")), ["/", "/people"])
                self.assertEqual(re.findall(r'aria-current="page">(\w+)<', nav), [current])

    def test_the_results_geo_has_the_same_properties_as_the_network_geo(self):
        """Both maps read one shape: id, name, role, employer, place, new_facts and href."""
        person_id = self.person("Ada Vermeer", 1, ("Gent", 51.05, 3.72))
        self.store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None, dirty=False,
                                        llm_mode="replay", settings_json="{}", boot_id="b"))
        self.store.save_candidates("s1", [Candidate(search_id="s1", person_id=person_id, person_ids=[person_id],
                                                    hit_person_ids=[person_id], section="network", rank=1, score=1.0,
                                                    lane_ranks={"seeds": 1})], [])
        (found,) = self.client.get("/api/searches/s1/geo").json()["features"]
        (listed,) = self.client.get("/api/people/geo").json()["features"]
        self.assertEqual(set(found["properties"]), {"id", "name", "role", "employer", "place", "new_facts", "href"})
        self.assertEqual(found["properties"], listed["properties"])


if __name__ == "__main__":
    unittest.main()
