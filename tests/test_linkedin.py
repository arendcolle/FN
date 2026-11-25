import contextlib
import hashlib
import io
import json
import logging
import os
import unittest
from datetime import UTC, date, datetime
from unittest import mock

import httpx
from pydantic import SecretStr

from fn import config, evidence, extract, geo, gold, net, orgs, parse, rank, score, websearch
from fn.contracts import Chip, Chips, GeoArea, LaneIn, LaneOut, Place, Question, record_source
from fn.lanes import linkedin
from fn.steps import StepContext, run_step
from fn.web import app
from fn.worker import Worker, new_id, now
from tests.helpers import (
    FIXTURES,
    StubLLM,
    cities_zip,
    make_db,
    make_seeded_db,
    make_settings,
)

RECORDED = FIXTURES / "http" / "linkedin"
TOKEN = "apify_api_test_0123456789"
PARALLEL = "px-parallel-0123456789"
CITIES = geo.index((FIXTURES / "geo" / "cities15000-extract.txt").read_text(encoding="utf-8"))
READ = datetime(2027, 1, 15, tzinfo=UTC)
GS02_QUESTION = "Flemish experts in telecom and 6G research in the New York and New Jersey area"
WIM, ANJA, KAREL = "https://www.linkedin.com/in/wim-doe-invented", "https://www.linkedin.com/in/anja-voorbeeld-invented", \
    "https://www.linkedin.com/in/karel-proef-invented"


def gs02_chips() -> Chips:
    """The chips of the tracked GS-02 parse fixture."""
    for path in sorted((FIXTURES / "llm").glob("parse-*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if GS02_QUESTION in fixture["prompt"]:
            return Chips.model_validate(fixture["result"]["value"])
    raise AssertionError("no parse fixture for GS-02")


def chips(topics: list[str] = (), institutions: list[str] = (), place: Place | None = None) -> Chips:
    return Chips(topics=[Chip(text=t, origin="edited") for t in topics],
                 institutions=[Chip(text=i, origin="edited") for i in institutions], place=place)


def asked(roles: list[str], topics: list[str] = (), place: Place | None = None, version: int = 2,
          research: bool | None = False) -> Chips:
    """Chips of a version-2 question with role chips, as the parser makes them."""
    return Chips(roles=[Chip(text=r, origin="edited", research=research) for r in roles],
                 topics=[Chip(text=t, origin="edited") for t in topics], place=place, version=version)


def place(text: str, kind: str | None = "metro") -> Place:
    return Place(text=text, origin="edited", kind=kind)


def profiles() -> list[dict]:
    return json.loads((RECORDED / "profiles.json").read_text(encoding="utf-8"))


class ActorInputTest(unittest.TestCase):
    def test_the_gs02_chips_give_the_new_york_and_new_jersey_locations_and_quote_multi_word_topics(self):
        """The GS-02 parse fixture's chips give the whole actor input: ORed topics, the Belgian schools, both locations."""
        given = gs02_chips()
        area = geo.locate(given.place.text, CITIES)
        self.assertEqual(linkedin.actor_input(given, area), {
            "searchQuery": 'telecom OR "6G research"', "schools": linkedin.SCHOOLS,
            "locations": ["New York City Metropolitan Area", "New Jersey"],
            "profileScraperMode": "Full", "takePages": 1, "maxItems": 25})
        self.assertEqual(linkedin.SCHOOLS, [
            "KU Leuven", "Ghent University", "University of Antwerp", "Vrije Universiteit Brussel", "Hasselt University",
            "Université libre de Bruxelles", "UCLouvain", "University of Liège", "Vlerick Business School"])

    def test_locations_follow_the_place_chip_and_the_city_table(self):
        """No place and anywhere_us send the United States; a city outside the table sends its city name, not the
        place text; an unknown place and a place abroad send their own text; a city in the table sends LinkedIn's names.
        """
        topic = ["6G"]
        sf = GeoArea(place="San Francisco", city="San Francisco, US", lat=37.77, lon=-122.42, radius_km=100.0)
        for given, area, expected in (
            (chips(topic), None, ["United States"]),
            (chips(topic, place=place("anywhere in the US", "anywhere_us")), None, ["United States"]),
            (chips(topic, place=place("Menlo Park area", None)), geo.locate("Menlo Park area", CITIES), ["Menlo Park"]),
            (chips(topic, place=place("Gotham")), geo.locate("Gotham", CITIES), ["Gotham"]),
            (chips(topic, place=place("Leuven region", "abroad")), geo.locate("Leuven", CITIES), ["Leuven region"]),
            (chips(topic, place=place("San Francisco")), sf, ["San Francisco Bay Area"]),
            (chips(topic, place=place("New York")), geo.locate("New York", CITIES),
             ["New York City Metropolitan Area", "New Jersey"]),
        ):
            with self.subTest(place=given.place and given.place.text):
                self.assertEqual(linkedin.actor_input(given, area)["locations"], expected)
        self.assertEqual(sorted(linkedin.LOCATIONS), [
            f"{city}, US" for city in ("Atlanta", "Boston", "Chicago", "Houston", "Los Angeles", "New York City",
                                       "San Francisco", "Seattle", "Washington")])

    def test_the_search_query_drops_double_quotes_and_falls_back_to_the_institution_chips(self):
        """Topics win over institutions; with no topic the institutions are ORed the same way; quotes inside a chip go."""
        for given, expected in (
            (chips(['say "hello"  world', "x"]), '"say hello world" OR x'),
            (chips(institutions=["KU Leuven", "imec"]), '"KU Leuven" OR imec'),
            (chips(["6G"], ["imec"]), "6G"),
            (chips(['"']), ""),
            (chips(place=place("New York")), ""),
        ):
            with self.subTest(query=expected):
                self.assertEqual(linkedin.search_query(given), expected)


class JobTitleTest(unittest.TestCase):
    def test_role_chips_become_singular_lower_case_job_titles(self):
        """Roles give singular lower-case titles with no quotes, a closing "people" dropped and no repeat; a title
        search sends no query and the version-2 size, and chips of version 3 use that size as well.
        """
        la = GeoArea(place="Los Angeles", city="Los Angeles, US", lat=34.05, lon=-118.24, radius_km=100.0)
        body = linkedin.actor_input(asked(["architects", "designers"], place=place("Los Angeles")), la)
        self.assertEqual((body["currentJobTitles"], body["locations"], body["maxItems"]),
                         (["architect", "designer"], ["Los Angeles Metropolitan Area"], 10))
        self.assertNotIn("searchQuery", body)
        self.assertEqual(linkedin.actor_input(asked(["architects"], version=3), None)["maxItems"], 10)
        for text, expected in (("business development people", "business development"), ("Economists", "economist"),
                               ("secretaries", "secretary"), ("business", "business"), ('"Editors"', "editor"),
                               ("people", ""), ("Persons", "")):
            self.assertEqual(linkedin.title(text), expected, text)
        self.assertEqual(linkedin.job_titles(asked(["Architects", "architect people", "people", "Editors"])),
                         (["architect", "editor"], []))
        many = linkedin.job_titles(asked([f"title {n}" for n in range(1, 14)]))
        self.assertEqual((len(many[0]), many[1]), (12, ["title 13"]))

    def test_chicago_and_houston_send_linkedins_own_names(self):
        """The location table names LinkedIn's areas for Chicago and Houston."""
        for city, expected in (("Chicago, US", ["Greater Chicago Area"]), ("Houston, US", ["Greater Houston"])):
            area = GeoArea(place=city, city=city, lat=0.0, lon=0.0, radius_km=100.0)
            self.assertEqual(linkedin.actor_input(asked(["architects"], place=place(city)), area)["locations"], expected)


class CanonicalTest(unittest.TestCase):
    def test_canonical_gives_one_spelling_for_a_profile_url(self):
        """https, www.linkedin.com for the bare and country hosts, no query, fragment or trailing slash."""
        for spelling in ("linkedin.com/in/x/", "https://www.linkedin.com/in/x", "http://linkedin.com/in/x?trk=a#top",
                         " https://www.linkedin.com/in/x/ ", "https://be.linkedin.com/in/x"):
            with self.subTest(spelling=spelling):
                self.assertEqual(linkedin.canonical(spelling), "https://www.linkedin.com/in/x")


class RecordSourceTest(unittest.TestCase):
    def test_a_record_without_a_kind_keeps_its_id_and_a_vendor_record_has_its_own(self):
        """The id hashes the kind, so today's record ids stay and the same record as vendor_record is another source."""
        read = datetime(2026, 11, 3, tzinfo=UTC)
        digest = hashlib.sha256(b"a: b").hexdigest()
        url = "https://example.org/1"
        plain, _ = record_source(url, "t", [("a", "b")], {}, read)
        vendor, _ = record_source(url, "t", [("a", "b")], {}, read, kind="vendor_record")
        self.assertEqual((plain.kind, plain.id), ("record", hashlib.sha1(f"record\0{url}\0{digest}".encode()).hexdigest()))
        self.assertEqual((vendor.kind, vendor.id),
                         ("vendor_record", hashlib.sha1(f"vendor_record\0{url}\0{digest}".encode()).hexdigest()))


class AliasTest(unittest.TestCase):
    def test_the_new_belgian_school_spellings_map_to_their_orgs_and_the_rest_are_listed_unmapped(self):
        """KU Leuven's extra spellings, Vlerick and HOGENT map to ROR ids; EHSAL and a secondary school stay out."""
        for spelling, org in (
            ("University of Leuven", "ror:05f950310"), ("Katholieke University Leuven", "ror:05f950310"),
            ("Vlerick Business School", "ror:056t38c37"), ("Vlerick Leuven-Gent Management School", "ror:056t38c37"),
            ("University College Ghent", "ror:00rs45z86"),
        ):
            self.assertEqual(orgs.org_id(spelling), org, spelling)
        for spelling in ("EHSAL Management School", "Aangenomen College Sint-Truiden"):
            self.assertIsNone(orgs.org_id(spelling), spelling)
            self.assertIn(orgs.fold(spelling), orgs.unmapped(), spelling)
        for school in linkedin.SCHOOLS:
            self.assertRegex(orgs.org_id(school) or "", r"ror:", school)

    def test_the_seeded_database_holds_the_recorded_facts_of_the_new_orgs_as_belgian(self):
        """fn-orgs over the alias file stores Vlerick and HOGENT from their recorded ROR records, both in Belgium."""
        store = make_seeded_db(self)
        found = store.get_orgs(["ror:056t38c37", "ror:00rs45z86"])
        self.assertEqual({o.id: (o.name, o.country_code) for o in found.values()}, {
            "ror:056t38c37": ("Vlerick Business School", "BE"),
            "ror:00rs45z86": ("HOGENT University of Applied Sciences and Arts", "BE")})


NEW_YORK = place("New York")
JOURNALISTS = asked(["journalists", "editors"], place=NEW_YORK)
FREE_ACCOUNT = {"data": {"plan": {"tier": "FREE"}}}
SEATTLE = GeoArea(place="Seattle", city="Seattle, US", lat=47.6, lon=-122.3, radius_km=100.0)


def site(roles: str, where: str, named: str) -> str:
    return f"site:www.linkedin.com/in ({roles}) ({where}) ({named})"


class GoogleQueryTest(unittest.TestCase):
    ny = '"New York City Metropolitan Area" OR "New York, New York"'

    def queries(self, given: Chips, area: GeoArea | None = None) -> tuple[list[str], list[str]]:
        return linkedin.google_queries(given, area or geo.locate("New York", CITIES))

    def test_google_queries_name_three_titles_the_area_phrases_and_three_schools(self):
        """One query per group of three schools in SCHOOLS order; the first is the brief's; roles come from the job
        titles of a version-2 question, else from query_terms, which has quoted a multi-word term once already.
        """
        found, left = self.queries(asked(["journalists", "editors"], place=NEW_YORK))
        self.assertEqual(found, [
            site("journalist OR editor", self.ny, '"KU Leuven" OR "Ghent University" OR "University of Antwerp"'),
            site("journalist OR editor", self.ny,
                 '"Vrije Universiteit Brussel" OR "Hasselt University" OR "Université libre de Bruxelles"'),
            site("journalist OR editor", self.ny, '"UCLouvain" OR "University of Liège" OR "Vlerick Business School"')])
        self.assertEqual(left, [])
        leuven = asked(["journalists"], place=NEW_YORK).model_copy(update={"institutions": [Chip(text="KU Leuven", origin="edited")]})
        self.assertEqual(self.queries(leuven)[0], [site("journalist", self.ny, '"KU Leuven"')])
        for given, roles in (
            (chips(["6G", "wireless networks"], place=NEW_YORK), '6G OR "wireless networks"'),
            (asked([], ["6G research"], NEW_YORK), '"6G research"'),
            (asked(["business development people"], place=NEW_YORK), '"business development"'),
            (asked(["Editors"], ["6G"], NEW_YORK, version=1), "6G"),
        ):
            with self.subTest(roles=roles):
                self.assertEqual({q.split(") (")[0] for q in self.queries(given)[0]}, {f"site:www.linkedin.com/in ({roles}"})
        other = asked(["journalists"], place=NEW_YORK).model_copy(update={"institutions": [Chip(text="Acme Networks", origin="edited")]})
        self.assertEqual(self.queries(other), self.queries(asked(["journalists"], place=NEW_YORK)))
        only_school = asked([], place=NEW_YORK).model_copy(update={"institutions": [Chip(text="KU Leuven", origin="edited")]})
        self.assertEqual(self.queries(only_school)[0], [site('"KU Leuven"', self.ny, '"KU Leuven"')])

    def test_roles_past_the_third_are_returned_and_no_role_makes_no_query(self):
        """Four roles send the first three and name the fourth; no role, topic or institution gives no query."""
        found, left = self.queries(asked(["architects", "designers", "planners", "painters"], place=NEW_YORK))
        self.assertEqual({q.split(") (")[0] for q in found}, {"site:www.linkedin.com/in (architect OR designer OR planner"})
        self.assertEqual(left, ["painter"])
        self.assertEqual(self.queries(asked([], place=NEW_YORK)), ([], []))

    def test_the_place_phrases_follow_the_area_and_the_kind_of_place(self):
        """A table city sends its two phrases; no place and anywhere in the US send United States; a place abroad or
        one FN cannot locate sends its own text with inner quote marks dropped; another located city sends its name.
        """
        roles = asked(["architects"])
        for given, area, where in (
            (roles, None, '"United States"'),
            (roles.model_copy(update={"place": place("the US", "anywhere_us")}), SEATTLE, '"United States"'),
            (roles.model_copy(update={"place": place("Seattle")}), SEATTLE, '"Greater Seattle Area" OR "Seattle, Washington"'),
            (roles.model_copy(update={"place": place('Antwerp "area"', "abroad")}), None, '"Antwerp area"'),
            (roles.model_copy(update={"place": place("Gotham", None)}), None, '"Gotham"'),
            (roles.model_copy(update={"place": place("Menlo Park area")}), geo.locate("Menlo Park area", CITIES),
             '"Menlo Park"'),
        ):
            with self.subTest(where=where):
                self.assertEqual(linkedin.google_queries(given, area)[0][0].split(") (")[1], where)
        self.assertEqual(sorted(linkedin.PLACES), sorted(linkedin.LOCATIONS))
        self.assertTrue(all(len(v) == 2 for v in linkedin.PLACES.values()))


class GoogleAddressTest(unittest.TestCase):
    def test_a_profile_address_is_on_a_linkedin_host_under_in_and_is_made_canonical(self):
        """www.linkedin.com and linkedin.com give the one address; a country host, a company page, a bare /in and
        any other site give none; segments after the id and a query string are dropped.
        """
        want = "https://www.linkedin.com/in/ada-tester-invented"
        for url in ("https://www.linkedin.com/in/ada-tester-invented", "https://linkedin.com/in/ada-tester-invented/",
                    "http://www.linkedin.com/in/ada-tester-invented/en?trk=x#top", " https://linkedin.com/in/ada-tester-invented/details/"):
            self.assertEqual(linkedin.profile_address(url), want, url)
        for url in ("https://be.linkedin.com/in/ada", "https://www.linkedin.com/company/acme", "https://www.linkedin.com/in/",
                    "https://www.linkedin.com/in", "https://example.org/in/ada", "https://www.youtube.com/watch?v=x", "", "not a url"):
            self.assertIsNone(linkedin.profile_address(url), url)

    def test_addresses_alternate_queries_drop_repeats_and_non_profiles_and_stop_at_20(self):
        """The first result of each answer in turn, then the second; a repeat in another spelling and a result that is
        no profile address are left out and the latter counted; 20 distinct addresses are the most.
        """
        def result(slug: str) -> dict:
            return {"url": f"https://www.linkedin.com/in/{slug}"}

        answers = [[result("a1"), result("a2"), {"url": "https://www.youtube.com/watch?v=x"}],
                   [result("b1"), {"url": "https://linkedin.com/in/a1/?trk=x"}, {"position": 3}], [], [result("c1")]]
        self.assertEqual(linkedin.addresses(answers), ([f"https://www.linkedin.com/in/{s}" for s in ("a1", "b1", "c1", "a2")], 2))
        many = [[result(f"{q}{n}") for n in range(10)] for q in "abc"]
        found, others = linkedin.addresses(many)
        self.assertEqual((len(found), others, found[:4]), (20, 0, [f"https://www.linkedin.com/in/{s}" for s in ("a0", "b0", "c0", "a1")]))
        self.assertEqual(found[-2:], [f"https://www.linkedin.com/in/{s}" for s in ("a6", "b6")])
        self.assertEqual(linkedin.addresses([]), ([], 0))


class LinkedInLaneTest(unittest.TestCase):
    def setUp(self):
        self.live = make_settings(self).model_copy(
            update={"http_mode": "live", "apify_token": SecretStr(TOKEN), "linkedin_live": True})
        self.off = self.live.model_copy(update={"linkedin_live": False})
        self.store = make_db(self, self.live)
        self.answer: object = profiles()
        self.account: object = {"data": {"plan": {"tier": "STARTER"}, "email": "made.up@example.org"}}
        self.limits: object = {"data": {"limits": {"maxMonthlyUsageUsd": 39}, "current": {"monthlyUsageUsd": 5.5}}}
        self.google: list = json.loads((RECORDED / "google.json").read_text(encoding="utf-8"))
        self.extract: object = json.loads((RECORDED / "extract.json").read_text(encoding="utf-8"))
        self.sent: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        if str(request.url).split("?")[0] == linkedin.GOOGLE_URL:
            answer = self.google[sum(str(r.url).startswith(linkedin.GOOGLE_URL) for r in self.sent) - 1]
            return httpx.Response(200, content=answer) if isinstance(answer, bytes) else httpx.Response(200, json=answer)
        if str(request.url) == websearch.EXTRACT_URL:
            return httpx.Response(200, json=self.extract)
        if request.url.host == "download.geonames.org":
            return httpx.Response(200, content=cities_zip())
        if str(request.url) == linkedin.ACCOUNT_URL:
            return httpx.Response(200, json=self.account)
        if str(request.url) == linkedin.LIMITS_URL:
            return httpx.Response(200, json=self.limits)
        return httpx.Response(200, json=self.answer)

    def posts(self) -> list[httpx.Request]:
        return [r for r in self.sent if r.method == "POST"]

    def run_lane(self, given: Chips | None = None, settings=None) -> LaneOut:
        """Run lane:linkedin as a step of a new search over a mock transport; the default chips are the GS-02 ones.

        The step's clock reads READ, a year after the fixture's scrapedAt, so a scrape year cannot pass for the read year.
        """
        return self.in_step(given or gs02_chips(), settings or self.live, linkedin.run)

    def in_step(self, given: Chips, settings, work) -> LaneOut:
        """Run work(ctx, inp) as the lane:linkedin step of a new search over a mock transport."""
        http = net.Client(settings, httpx.MockTransport(self.handle))
        worker = Worker(self.store, settings, llm=StubLLM(error=AssertionError("the LLM must not be called")), http=http)
        self.addCleanup(worker.shutdown)
        self.search_id = worker.create_search("question", given, "edited").id
        ctx = StepContext(search_id=self.search_id, store=self.store, llm=None, http=http, now=lambda: READ, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        return run_step(ctx, "lane:linkedin", work, LaneIn(search_id=self.search_id, chips=given))

    def calls(self) -> list:
        """The POST calls of the last lane step."""
        return [c for c in self.store.list_calls(self.store.list_steps(self.search_id)[-1].id) if "POST " in c.request]

    def claims(self) -> set[tuple]:
        """Every stored claim as (person, source kind, source URL, kind, relation, org id, value, offsets, dates, method)."""
        rows = self.store.conn.execute(
            "SELECT p.display_name, s.kind, s.url, c.kind, c.relation, c.org_id, c.value, c.quote_start, c.quote_end, "
            "c.valid_from, c.valid_to, c.claim_date, c.date_precision, c.date_method FROM claims c "
            "JOIN persons p ON p.id = c.person_id JOIN sources s ON s.id = c.source_id")
        return {tuple(r) for r in rows}

    def claim(self, person: str, value: str):
        """The one stored claim of the person with that value."""
        rows = self.store.conn.execute(
            "SELECT c.id FROM claims c JOIN persons p ON p.id = c.person_id WHERE p.display_name = ? AND c.value = ?",
            (person, value)).fetchall()
        (found,) = [self.store.get_claim(r[0]) for r in rows]
        return found

    def count(self, table: str) -> int:
        return self.store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_every_profile_is_a_hit_with_the_exact_education_and_job_claims_it_lists(self):
        """Each education entry and job is one affiliation claim at its entry's lines; the repeats are not read.

        currentPosition and profileTopEducation hold copies of entries, so any claim from them would show here.
        """
        out = self.run_lane()
        vendor = "vendor_record"
        self.assertEqual(self.claims(), {
            ("Wim Doe", vendor, WIM, "affiliation", "studied_at", "ror:05f950310", "KU Leuven", 138, 308, "1990", "1994",
             "1994", "year", "record_field"),
            ("Wim Doe", vendor, WIM, "affiliation", "studied_at", "ror:00cv9y106", "Ghent University", 309, 414, None,
             None, None, None, None),
            ("Wim Doe", vendor, WIM, "affiliation", "studied_at", None, "Fantasie Instituut voor Kunsten", 415, 566,
             "1985", "1986", "1986", "year", "record_field"),
            ("Wim Doe", vendor, WIM, "affiliation", "works_at", None, "Acme Networks", 567, 782, "2015", "2026", "2026",
             "year", "record_field"),
            ("Wim Doe", vendor, WIM, "affiliation", "worked_at", None, "Example Labs", 783, 984, "2005", "2014", "2014",
             "year", "record_field"),
            ("Anja Voorbeeld", vendor, ANJA, "affiliation", "studied_at", "ror:006e5kg04", "Vrije Universiteit Brussel",
             118, 299, "2001", "2005", "2005", "year", "record_field"),
            ("Anja Voorbeeld", vendor, ANJA, "affiliation", "studied_at", "ror:056t38c37",
             "Vlerick Leuven-Gent Management School", 300, 461, None, "2008", "2008", "year", "record_field"),
            ("Anja Voorbeeld", vendor, ANJA, "affiliation", "worked_at", "ror:02kcbn207", "imec", 462, 655, "2006",
             "2012", "2012", "year", "record_field"),
            ("Anja Voorbeeld", vendor, ANJA, "affiliation", "works_at", None, "Example Labs", 656, 856, "2012", "2026",
             "2026", "year", "record_field"),
            ("Karel Proef", vendor, KAREL, "affiliation", "studied_at", "ror:00rs45z86", "University College Ghent", 90,
             267, "1998", "2001", "2001", "year", "record_field"),
            ("Wim Doe", vendor, WIM, "location", "lives_in", None, "New York, New York, United States", 81, 137, None,
             None, "2026-11-02", "day", "record_field"),
            ("Wim Doe", vendor, WIM, "role", None, None, "Chief Technology Officer", 567, 782, "2015", "2026", "2026",
             "year", "record_field"),
            ("Anja Voorbeeld", vendor, ANJA, "location", "lives_in", None, "United States", 81, 117, None, None,
             "2026-11-02", "day", "record_field"),
            ("Anja Voorbeeld", vendor, ANJA, "role", None, None, "Principal Engineer", 656, 856, "2012", "2026", "2026",
             "year", "record_field"),
            ("Karel Proef", vendor, KAREL, "location", "lives_in", None, "Newark, New Jersey, United States", 33, 89,
             None, None, "2026-11-02", "day", "record_field"),
        })
        persons = self.store.get_persons([h.person_id for h in out.hits])
        self.assertEqual([(h.rank, persons[h.person_id].display_name, h.lane) for h in out.hits],
                         [(1, "Wim Doe", "linkedin"), (2, "Anja Voorbeeld", "linkedin"), (3, "Karel Proef", "linkedin")])
        self.assertEqual(out.total_seen, 3)
        self.assertEqual([h.matched_on for h in out.hits], [
            f"result 1, Chief Technology Officer at Acme Networks, {WIM}",
            f"result 2, Principal Engineer at Example Labs, {ANJA}", f"result 3, {KAREL}"])
        for hit in out.hits:
            self.assertCountEqual(hit.claim_ids, [c.id for c in self.store.claims_of([hit.person_id])])
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM claims").fetchone()[0], 15)

    def test_the_profile_is_stored_as_a_dated_vendor_record_with_the_whole_answer_as_raw(self):
        """The source holds the lines the lane reads, the scrape day as its date, a title with the name and the raw."""
        self.run_lane()
        row = self.store.conn.execute("SELECT * FROM sources WHERE url = ?", (WIM,)).fetchone()
        self.assertEqual((row["kind"], row["title"], row["source_date"], row["date_method"]),
                         ("vendor_record", "LinkedIn profile Wim Doe", "2026-11-02", "record_field"))
        self.assertTrue(row["text"].startswith("firstName: Wim\nlastName: Doe\nheadline: Chief Technology Officer"))
        self.assertEqual(json.loads(row["raw_json"]), profiles()[0])
        self.assertEqual((row["text"].count("companyName: Acme Networks"), row["text"].count("schoolName: KU Leuven")),
                         (1, 1))
        self.assertEqual(self.count("sources"), 3)
        identifiers = self.store.conn.execute("SELECT scheme, value FROM person_identifiers").fetchall()
        named = ((WIM, "wim doe"), (ANJA, "anja voorbeeld"), (KAREL, "karel proef"))
        self.assertEqual({tuple(r) for r in identifiers},
                         {("profile_url", url) for url, _ in named}
                         | {("mention", f"{page}#{who}") for url, who in named for page in (url, url.replace("www.", ""))})

    def test_an_education_entry_dated_1990_to_1994_runs_from_1990_to_1994(self):
        """valid_from and valid_to are the start and end years, claim_date is the end year, and each year counts."""
        self.run_lane()
        ku = self.claim("Wim Doe", "KU Leuven")
        self.assertEqual((ku.valid_from, ku.valid_to, ku.claim_date, ku.date_precision, ku.date_method),
                         ("1990", "1994", "1994", "year", "record_field"))
        self.assertEqual(rank.units(ku), frozenset(str(y) for y in range(1990, 1995)))

    def test_a_job_from_2015_to_present_scraped_in_2026_is_works_at_with_the_units_2015_to_2026(self):
        """A current job runs to the scrape year, which is the year of _meta.scrapedAt; an ended job keeps its end year."""
        self.run_lane()
        acme, labs = self.claim("Wim Doe", "Acme Networks"), self.claim("Wim Doe", "Example Labs")
        self.assertEqual((acme.relation, acme.valid_from, acme.valid_to, acme.claim_date),
                         ("works_at", "2015", "2026", "2026"))
        self.assertEqual(rank.units(acme), frozenset(str(y) for y in range(2015, 2027)))
        self.assertEqual((labs.relation, labs.valid_to), ("worked_at", "2014"))

    def test_a_current_job_without_a_scrape_date_runs_to_the_year_of_the_read(self):
        """With no _meta.scrapedAt the source has no date, and the current job runs to the year the lane read it (2027)."""
        answer = profiles()[:1]
        del answer[0]["_meta"]
        self.answer = answer
        self.run_lane()
        acme = self.claim("Wim Doe", "Acme Networks")
        self.assertEqual((acme.valid_to, acme.claim_date), ("2027", "2027"))
        self.assertIsNone(self.store.conn.execute("SELECT source_date FROM sources").fetchone()[0])

    def test_an_entry_without_a_year_has_no_date_and_counts_as_one_undated_unit(self):
        """Ghent University has no dates: no claim_date, no validity, and the ranker counts one undated unit."""
        self.run_lane()
        ghent = self.claim("Wim Doe", "Ghent University")
        self.assertEqual((ghent.claim_date, ghent.date_precision, ghent.date_method, ghent.valid_from, ghent.valid_to),
                         (None, None, None, None, None))
        self.assertEqual(rank.units(ghent), frozenset({"undated"}))

    def test_an_entry_with_only_a_start_year_is_dated_by_it(self):
        """With no end year and no Present, the start year is the only year known: valid_from and claim_date, no valid_to."""
        answer = profiles()[:1]
        answer[0]["education"][2]["endDate"] = None
        self.answer = answer
        self.run_lane()
        art = self.claim("Wim Doe", "Fantasie Instituut voor Kunsten")
        self.assertEqual((art.valid_from, art.valid_to, art.claim_date), ("1985", None, "1985"))
        self.assertEqual(rank.units(art), frozenset({"1985"}))

    def test_titles_and_credentials_are_stripped_from_the_name_of_a_profile(self):
        """firstName and lastName go through clean_name, so Prof. Dr. and PhD do not reach the person or the group key."""
        answer = profiles()[1:2]
        answer[0].update(firstName="Prof. Dr. Anja", lastName="Voorbeeld, PhD")
        self.answer = answer
        out = self.run_lane(chips(["6G"]))
        (person,) = self.store.get_persons([out.hits[0].person_id]).values()
        self.assertEqual((person.display_name, person.name_key), ("Anja Voorbeeld", "anja voorbeeld"))
        self.assertEqual([c.name for c in out.considered if c.stage == "profile"], ["Anja Voorbeeld"])

    def test_a_school_with_no_org_id_is_noted_once_and_a_mapped_one_is_not(self):
        """Only the school spelling the alias file lacks gets a note, once for the two profiles that list it.

        Every profile and the size of the match get a row too.
        """
        answer = profiles()
        answer[2]["education"].append(answer[0]["education"][2])
        self.answer = answer
        out = self.run_lane()
        self.assertEqual([(c.stage, c.person_key, c.reason) for c in out.considered if c.stage == "school"], [
            ("school", "Fantasie Instituut voor Kunsten",
             "school 'Fantasie Instituut voor Kunsten' maps to no org id in data/org_aliases.csv")])
        self.assertEqual([c.reason for c in out.considered if c.stage == "read"], ["read 3 of 41 profiles"])
        self.assertEqual([(c.person_key, c.name, c.kept, c.reason) for c in out.considered if c.stage == "profile"], [
            (WIM, "Wim Doe", True, "result 1: 3 education and 2 job claims"),
            (ANJA, "Anja Voorbeeld", True, "result 2: 2 education and 2 job claims"),
            (KAREL, "Karel Proef", True, "result 3: 2 education and 0 job claims")])

    def test_the_call_goes_to_the_actor_with_the_token_the_caps_and_the_actor_input(self):
        """One POST to the sync endpoint: Bearer token, timeout and maxTotalChargeUsd as query parameters, the 290 s read
        timeout, and the body the pure actor_input gives.
        """
        out = self.run_lane()
        (post,) = self.posts()
        self.assertEqual(str(post.url.copy_with(query=None)), linkedin.ACTOR_URL)
        self.assertEqual(dict(post.url.params), {"timeout": "240", "maxTotalChargeUsd": "0.25"})
        self.assertEqual(post.headers["authorization"], f"Bearer {TOKEN}")
        self.assertEqual(post.extensions["timeout"]["read"], 290)
        self.assertEqual(json.loads(post.content), linkedin.actor_input(gs02_chips(), geo.locate(
            gs02_chips().place.text, CITIES)))
        self.assertEqual(out.query, 'telecom OR "6G research"; locations New York City Metropolitan Area, New Jersey')

    def test_a_place_abroad_or_anywhere_in_the_us_fetches_the_city_list_only_after_the_post(self):
        """Only a metro place needs GeoNames before the call; the other kinds send the one Apify call (after the
        account check) and fetch the city list afterwards, for the profiles' places.
        """
        for kind, text, expected in (("abroad", "Antwerp area", "Antwerp area"), ("anywhere_us", "the US", "United States")):
            with self.subTest(kind=kind):
                self.sent.clear()
                self.run_lane(chips(["6G"], place=place(text, kind)))
                self.assertEqual([r.url.host for r in self.sent],
                                 ["api.apify.com", "api.apify.com", "api.apify.com", "download.geonames.org"])
                self.assertEqual(json.loads(self.posts()[0].content)["locations"], [expected])

    def test_a_live_run_records_its_estimated_cost_and_a_cache_served_one_records_zero(self):
        """The estimate is $0.10 for the search page plus $0.004 a profile; the second, cached call costs nothing."""
        given = chips(["6G"])
        self.run_lane(given)
        (call,) = self.calls()
        self.assertAlmostEqual(call.cost_usd, 0.112)
        self.run_lane(given)
        (call,) = self.calls()
        self.assertEqual(call.cost_usd, 0.0)
        self.assertTrue(call.request.startswith("cache POST https://api.apify.com/"))

    def test_the_same_input_twice_makes_one_transport_call_and_adds_nothing(self):
        """With the lane on, the second search serves the first one's recorded run: no second POST, no new row."""
        given = chips(["6G"])
        first = self.run_lane(given)
        tables = ("persons", "person_identifiers", "sources", "claims")
        before = [self.count(t) for t in tables]
        second = self.run_lane(given)
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual([self.count(t) for t in tables], before)
        self.assertEqual([(h.person_id, h.claim_ids) for h in second.hits], [(h.person_id, h.claim_ids) for h in first.hits])

    def test_the_lane_off_with_no_recorded_run_notes_it_and_makes_no_transport_call(self):
        """Without FN_LINKEDIN=1 and without a cache file nothing is sent, and the note names the switch and the cost."""
        out = self.run_lane(chips(["6G"]), self.off)
        self.assertEqual(self.sent, [])
        self.assertEqual(out.hits, [])
        self.assertEqual([c.reason for c in out.considered], [linkedin.OFF])
        self.assertIn("FN_LINKEDIN=1", linkedin.OFF)
        self.assertEqual(self.store.list_steps(self.search_id)[-1].status, "ok")
        actor, google = self.calls()
        self.assertEqual((actor.error, google.error), ("not in the response cache", "not in the response cache"))
        self.assertEqual((linkedin.ACTOR_URL in actor.request, linkedin.GOOGLE_URL in google.request), (True, True))

    def test_the_lane_off_serves_a_recorded_run_without_a_transport_call(self):
        """A run made with the lane on is served to a search with it off: same hits, the transport called once in all."""
        given = chips(["6G"])
        first = self.run_lane(given)
        out = self.run_lane(given, self.off)
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual([h.person_id for h in out.hits], [h.person_id for h in first.hits])
        self.assertEqual(len(out.hits), 3)

    def test_a_recorded_run_for_other_chips_is_not_served(self):
        """The cache key holds the actor input, so other chips with the lane off find nothing."""
        self.run_lane(chips(["6G"]))
        out = self.run_lane(chips(["quantum"]), self.off)
        self.assertEqual((len(self.posts()), out.hits), (1, []))
        self.assertEqual([c.reason for c in out.considered], [linkedin.OFF])

    def test_replay_without_a_recorded_run_says_so_even_with_the_lane_on(self):
        """FN_HTTP=replay never calls out, so FN_LINKEDIN=1 cannot help and the note says the replay has no run."""
        out = self.run_lane(chips(["6G"]), self.live.model_copy(update={"http_mode": "replay"}))
        self.assertEqual(self.sent, [])
        self.assertEqual([c.reason for c in out.considered], ["FN_HTTP=replay has no recorded LinkedIn run for this input"])

    def test_the_lane_on_without_a_token_notes_the_missing_key_and_logs_a_warning(self):
        """MissingKey is raised before anything is sent; the lane returns a note and the search goes on."""
        with self.assertLogs("fn.step", "WARNING"):
            out = self.run_lane(chips(["6G"]), self.live.model_copy(update={"apify_token": None}))
        self.assertEqual(self.sent, [])
        self.assertEqual([c.reason for c in out.considered],
                         ["LinkedIn lane skipped: no key for api.apify.com; set APIFY_TOKEN or store it in the Keychain"])
        self.assertEqual(self.store.list_steps(self.search_id)[-1].status, "ok")

    def test_an_answer_with_no_profile_is_noted_and_never_cached(self):
        """An empty list, an error object and profiles without a URL leave no cache file, so the next search calls again."""
        for answer in ([], {"error": "run failed"}, [{"firstName": "No", "lastName": "Url"}]):
            with self.subTest(answer=answer):
                self.answer = answer
                before = len(self.posts())
                out = self.run_lane(chips(["6G"]))
                self.assertIn("Apify returned no profiles; not cached", [c.reason for c in out.considered])
                (call,) = self.calls()
                self.assertIsNone(call.response_path)
                self.run_lane(chips(["6G"]))
                self.assertEqual(len(self.posts()), before + 2)
                self.assertEqual(out.hits, [])

    def test_an_answer_where_one_profile_lacks_its_url_is_cached_and_that_profile_is_skipped(self):
        """One profile with a linkedinUrl is enough to cache; the profile without one is skipped with a row."""
        answer = profiles()
        del answer[1]["linkedinUrl"]
        self.answer = answer
        out = self.run_lane(chips(["6G"]))
        (call,) = self.calls()
        self.assertIsNotNone(call.response_path)
        self.run_lane(chips(["6G"]), self.off)
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual([c.reason for c in out.considered if c.stage == "profile" and not c.kept],
                         ["result 2: no linkedinUrl; skipped"])
        self.assertEqual([h.rank for h in out.hits], [1, 2])
        self.assertEqual(self.count("persons"), 2)
        self.assertNotIn("Apify returned no profiles; not cached", [c.reason for c in out.considered])

    def test_a_profile_whose_cleaned_name_has_fewer_than_two_words_is_skipped_with_a_row(self):
        """An empty name and a one-word name (Dr. Doe cleans to Doe) store nothing and get a considered row each."""
        wim, anja = profiles()[:2]
        nameless, doe = "https://www.linkedin.com/in/nameless-invented", "https://www.linkedin.com/in/doe-invented"
        empty = {**wim, "firstName": "", "lastName": None, "linkedinUrl": nameless}
        single = {**anja, "firstName": "Dr.", "lastName": "Doe", "linkedinUrl": doe}
        self.answer = [empty, wim, single]
        out = self.run_lane(chips(["6G"]))
        self.assertEqual([(c.person_key, c.name, c.kept, c.reason) for c in out.considered
                          if c.stage == "profile" and not c.kept], [
            (nameless, "", False, "name has fewer than two words: ''"),
            (doe, "Doe", False, "name has fewer than two words: 'Doe'")])
        self.assertEqual([(h.rank, self.store.get_persons([h.person_id])[h.person_id].display_name) for h in out.hits],
                         [(1, "Wim Doe")])
        self.assertEqual((self.count("persons"), self.count("sources"), out.total_seen), (1, 1, 3))

    def test_one_profile_url_in_two_spellings_is_one_person_one_hit_and_one_set_of_claims(self):
        """linkedin.com/in/x/ and https://www.linkedin.com/in/x are the same canonical URL, so the same person."""
        answer = profiles()[:1]
        self.answer = [answer[0], {**answer[0], "linkedinUrl": "linkedin.com/in/wim-doe-invented/"}]
        out = self.run_lane(chips(["6G"]))
        self.assertEqual((len(out.hits), self.count("persons"), self.count("sources"), self.count("claims")), (1, 1, 1, 7))
        self.assertEqual(out.total_seen, 2)

    def test_a_person_listed_twice_is_one_hit_holding_the_claims_of_both_entries(self):
        """A second entry for the same URL with a changed text is a new source; the one hit lists both sets of claims."""
        first = profiles()[0]
        second = {**first, "experience": [*first["experience"], first["experience"][1] | {"companyName": "Other Labs"}]}
        self.answer = [first, second]
        out = self.run_lane(chips(["6G"]))
        (hit,) = out.hits
        self.assertEqual((self.count("persons"), self.count("sources"), self.count("claims")), (1, 2, 15))
        self.assertCountEqual(hit.claim_ids, [c.id for c in self.store.claims_of([hit.person_id])])
        self.assertEqual(len(hit.claim_ids), 15)

    def test_chips_with_only_a_place_or_only_quote_marks_note_it_and_make_no_call(self):
        """Without a topic or institution chip with text the lane sends nothing, not even the GeoNames request."""
        for given in (chips(place=place("New York")), chips(['"'])):
            with self.subTest(chips=given):
                out = self.run_lane(given)
                self.assertEqual(self.sent, [])
                self.assertEqual([c.reason for c in out.considered], [linkedin.NO_QUERY])

    def test_a_query_over_300_characters_keeps_whole_chips_in_order_and_names_the_ones_left_out(self):
        """The actor refuses a searchQuery over 300 characters, so chips are kept while the ORed query fits.

        The first chip that does not fit and the ones after it are named in a note, which stays beside the note
        for a lane that is off or has no key. A first chip over 300 sends nothing.
        """
        two_words = "b" * 35 + " " + "b" * 34
        out = self.run_lane(chips(["a" * 72, two_words, "c" * 72, "d" * 72, "e"]))
        (post,) = self.posts()
        query = json.loads(post.content)["searchQuery"]
        self.assertEqual(query, f'{"a" * 72} OR "{two_words}" OR {"c" * 72} OR {"d" * 72}')
        self.assertEqual(len(query), 300)
        self.assertTrue(out.query.startswith(query + ";"))
        self.assertEqual([c.reason for c in out.considered if c.stage == "query"],
                         ["query over 300 characters; chips left out: e"])
        self.sent.clear()
        out = self.run_lane(chips(["f" * 301, "g"]))
        self.assertEqual(self.sent, [])
        self.assertEqual([c.reason for c in out.considered],
                         [f"query over 300 characters; chips left out: {'f' * 301}, g"])
        long, left_out = chips(["a" * 200, "b" * 200]), f"query over 300 characters; chips left out: {'b' * 200}"
        out = self.run_lane(long, self.off)
        self.assertEqual(self.sent, [])
        self.assertEqual([c.reason for c in out.considered], [left_out, linkedin.OFF])
        with self.assertLogs("fn.step", "WARNING"):
            out = self.run_lane(long, self.live.model_copy(update={"apify_token": None}))
        self.assertEqual([c.reason for c in out.considered], [
            left_out, "LinkedIn lane skipped: no key for api.apify.com; set APIFY_TOKEN or store it in the Keychain"])

    def test_a_refusal_from_apify_fails_the_step_with_its_message(self):
        """A 402 from the actor call is not a note: the step fails and the error carries the response body."""
        def refuse(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json=self.account if str(request.url) == linkedin.ACCOUNT_URL else self.limits)
            return httpx.Response(402, json={"error": {"message": "Free plan run limit reached"}})

        http = net.Client(self.live, httpx.MockTransport(refuse))
        worker = Worker(self.store, self.live, llm=StubLLM(), http=http)
        self.addCleanup(worker.shutdown)
        search = worker.create_search("question", chips(["6G"]), "edited").id
        ctx = StepContext(search_id=search, store=self.store, llm=None, http=http, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.live)
        with self.assertRaisesRegex(net.HttpError, "Free plan run limit reached"):
            run_step(ctx, "lane:linkedin", linkedin.run, LaneIn(search_id=search, chips=chips(["6G"])))
        self.assertEqual(self.store.list_steps(search)[-1].status, "error")

    def auto(self, **update):
        """Settings of the staff server: the lane on by itself, no FN_LINKEDIN=1."""
        return self.live.model_copy(update={"linkedin_live": False, "linkedin_auto": True} | update)

    def test_titles_win_over_topics_and_version_1_sends_todays_input(self):
        """A version-2 question with roles searches by title only, with the version-2 timeouts and size; the same
        chips as version 1 send the topics' query and round three's timeouts and size. More than 12 titles leave
        the rest out with a note.
        """
        ny = place("New York")
        out = self.run_lane(asked(["architects", "designers"], ["6G"], ny))
        (post,) = self.posts()
        sent = json.loads(post.content)
        self.assertEqual((sent["currentJobTitles"], sent["maxItems"], "searchQuery" in sent),
                         (["architect", "designer"], 10, False))
        self.assertEqual((dict(post.url.params), post.extensions["timeout"]["read"]),
                         ({"timeout": "270", "maxTotalChargeUsd": "0.25"}, 295))
        self.assertEqual(out.query, "job titles architect, designer; locations New York City Metropolitan Area, New Jersey")
        self.sent.clear()
        out = self.run_lane(asked(["architects"], ["6G"], ny, version=1))
        (post,) = self.posts()
        sent = json.loads(post.content)
        self.assertEqual((sent["searchQuery"], sent["maxItems"], "currentJobTitles" in sent), ("6G", 25, False))
        self.assertEqual((dict(post.url.params), post.extensions["timeout"]["read"]),
                         ({"timeout": "240", "maxTotalChargeUsd": "0.25"}, 290))
        self.sent.clear()
        out = self.run_lane(asked([f"title {n}" for n in range(1, 14)]))
        self.assertEqual(len(json.loads(self.posts()[0].content)["currentJobTitles"]), 12)
        self.assertEqual([c.reason for c in out.considered if c.stage == "query"],
                         ["more than 12 job titles; left out: title 13"])
        self.sent.clear()
        out = self.run_lane(asked(["people"]))
        self.assertEqual(([c.reason for c in out.considered], self.sent), ([linkedin.NO_QUERY], []))

    def test_a_question_for_researchers_only_gets_the_note_and_no_call(self):
        """Roles that all ask for researchers make no call, not even for the city list; a null or mixed answer runs."""
        self.assertEqual([parse.researchers_only(asked(["x"], research=r)) for r in (True, None, False)],
                         [True, False, False])
        self.assertFalse(parse.researchers_only(asked([])))
        out = self.run_lane(asked(["physicists", "chemists"], place=place("New York"), research=True))
        self.assertEqual(([c.reason for c in out.considered], self.sent), ([linkedin.RESEARCHERS], []))
        mixed = asked(["physicists", "architects"], research=True)
        mixed = mixed.model_copy(update={"roles": [mixed.roles[0], mixed.roles[1].model_copy(update={"research": False})]})
        for given in (asked(["architects"], research=None), mixed):
            self.sent.clear()
            self.run_lane(given)
            self.assertEqual(len(self.posts()), 1)

    def test_only_the_staff_server_runs_version_2_chips_without_fn_linkedin(self):
        """serve sets linkedin_auto unless FN_LINKEDIN=0; a version-2 question with a token then runs, while version 1
        or no token serve only a recorded run, with no warning.
        """
        seen = []
        for env, expected in (({}, True), ({"FN_LINKEDIN": "0"}, False), ({"FN_LINKEDIN": "1"}, True)):
            var = make_settings(self).var_dir
            with self.subTest(env=env), mock.patch.dict(os.environ, {"FN_VAR": str(var)} | env, clear=True), \
                    mock.patch("fn.config.keychain", return_value=None), mock.patch.object(app.uvicorn, "run"), \
                    mock.patch.object(app, "create_app", side_effect=lambda settings, *_: seen.append(settings)), \
                    mock.patch.object(app, "from_settings"), mock.patch.object(app, "setup_logging"), \
                    mock.patch.object(app.net, "Client"):
                app.serve()
                self.assertEqual(seen[-1].linkedin_auto, expected)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("fn.config.keychain", return_value=None):
            self.assertFalse(config.from_env().linkedin_auto)
        self.run_lane(asked(["architects"]), self.auto())
        self.assertEqual(len(self.posts()), 1)
        for given, settings in ((asked(["architects"], ["6G"], version=1), self.auto()),
                                (asked(["designers"]), self.auto(apify_token=None))):
            self.sent.clear()
            with self.assertNoLogs("fn.step", "WARNING"):
                out = self.run_lane(given, settings)
            self.assertEqual(([c.reason for c in out.considered], self.sent), ([linkedin.OFF], []))

    def test_the_account_decides_a_paid_run_and_its_answer_is_kept_nowhere(self):
        """Each account answer that cannot back a run gives its note and no POST; a paid plan with room for the
        $0.25 cap calls the account, the limits and then the actor, and the account's email is stored nowhere.
        """
        def limits(cap, used):
            return httpx.Response(200, json={"data": {"limits": {"maxMonthlyUsageUsd": cap},
                                                      "current": {"monthlyUsageUsd": used}}})

        def tier(value):
            return httpx.Response(200, json={"data": {"plan": {"tier": value}}})

        paid, base = tier("STARTER"), self.handle
        cases = {
            "free": (tier("FREE"), None, linkedin.FREE_PLAN),
            "no tier": (httpx.Response(200, json={"data": {"plan": {}}}), None, linkedin.NO_ACCOUNT),
            "empty tier": (tier(""), None, linkedin.NO_ACCOUNT),
            "not json": (httpx.Response(200, content=b"<html>"), None, linkedin.NO_ACCOUNT),
            "account 500": (httpx.Response(500, text="down"), None, linkedin.NO_ACCOUNT),
            "limits 500": (paid, httpx.Response(500, text="down"), linkedin.NO_ACCOUNT),
            "limits not json": (paid, httpx.Response(200, content=b"nope"), linkedin.NO_ACCOUNT),
            "no cap": (paid, httpx.Response(200, json={"data": {"current": {"monthlyUsageUsd": 1}}}), linkedin.NO_ACCOUNT),
            "bool cap": (paid, limits(True, 0), linkedin.NO_ACCOUNT),
            "text used": (paid, limits(39, "5"), linkedin.NO_ACCOUNT),
            "a cent short": (paid, limits(5.24, 5.0), linkedin.NO_ROOM.format(used=5.0, cap=5.24)),
        }
        for label, (account, limit, note) in cases.items():
            def handle(request, account=account, limit=limit):
                if str(request.url) in (linkedin.ACCOUNT_URL, linkedin.LIMITS_URL):
                    self.sent.append(request)
                    return account if str(request.url) == linkedin.ACCOUNT_URL else limit
                return base(request)

            with self.subTest(label), mock.patch.object(self, "handle", handle):
                self.sent.clear()
                out = self.run_lane(asked(["architects"]), self.auto())
                self.assertEqual(([c.reason for c in out.considered], self.posts(), out.hits),
                                 ([note, linkedin.NO_PARALLEL], [], []))
        self.assertEqual(linkedin.NO_ROOM.format(used=5.0, cap=5.24),
                         "the month's Apify budget has no room for a run ($5.00 of $5.24 used)")
        replayed = self.auto(http_mode="replay")
        self.sent.clear()
        out = self.run_lane(asked(["architects"]), replayed)
        self.assertEqual(([c.reason for c in out.considered], self.sent),
                         (["FN_HTTP=replay has no recorded LinkedIn run for this input"], []))
        for role, cap, used in (("architects", 5.25, 5.0), ("designers", 10.3, 10.05)):
            with self.subTest(cap=cap), mock.patch.object(self, "handle", lambda r: base(r)):
                self.limits = {"data": {"limits": {"maxMonthlyUsageUsd": cap}, "current": {"monthlyUsageUsd": used}}}
                self.sent.clear()
                with self.assertLogs(level="DEBUG") as logs:
                    out = self.run_lane(asked([role]), self.auto())
                self.assertEqual([(r.method, str(r.url).split("?")[0]) for r in self.sent],
                                 [("GET", linkedin.ACCOUNT_URL), ("GET", linkedin.LIMITS_URL), ("POST", linkedin.ACTOR_URL),
                                  ("GET", geo.CITIES_URL)])
                self.assertEqual(len(out.hits), 3)
        email = b"made.up@example.org"
        self.assertNotIn(email.decode(), "\n".join(logs.output))
        stored = [path.read_bytes() for path in self.live.var_dir.rglob("*") if path.is_file()]
        stored.append("\n".join(self.store.conn.iterdump()).encode())
        self.assertTrue(stored)
        self.assertFalse([b for b in stored if email in b])

    def stored(self, kind: str) -> list[tuple]:
        """(person, relation, value, quote, has a point) of the stored claims of that kind."""
        rows = self.store.conn.execute(
            "SELECT p.display_name, c.relation, c.value, c.quote, c.lat IS NOT NULL FROM claims c "
            "JOIN persons p ON p.id = c.person_id WHERE c.kind = ?", (kind,))
        return sorted(tuple(r) for r in rows)

    def test_a_profile_gives_a_located_place_and_a_role_per_current_job(self):
        """A profile with a place gets a lives_in claim of its parsed text, else its location text, quoting the
        location line; each current job with a position and a company gets a role claim.
        """
        wim = profiles()[0]
        base = {k: wim[k] for k in ("headline", "_meta", "education")}
        job = {"companyName": "Foo Studio", "position": "Lead Architect", "startDate": {"text": "Jan 2020", "year": 2020},
               "endDate": {"text": "Present"}}

        def person(first: str, slug: str, location, *experience):
            return base | {"firstName": first, "lastName": "Tester", "linkedinUrl": f"https://www.linkedin.com/in/{slug}",
                           "location": location, "experience": list(experience)}

        here = {"linkedinText": "Newark, NJ", "parsed": {"text": "Newark, New Jersey, United States"}}
        self.answer = [
            person("Ida", "ida", here, job, job | {"companyName": "Bar Group", "position": "Advisor"}),
            person("Bo", "bo", None, job | {"companyName": None}, job | {"position": None, "companyName": "Baz"},
                   job | {"endDate": {"text": "Dec 2021", "year": 2021}}),
            person("Cy", "cy", {"linkedinText": "Gotham, Nowhere"}),
            person("Di", "di", {"parsed": {"text": "Newark, New Jersey, United States"}}),
        ]
        self.run_lane(chips(["6G"]))
        line = "location.linkedinText: "
        self.assertEqual(self.stored("location"), [
            ("Cy Tester", "lives_in", "Gotham, Nowhere", line + "Gotham, Nowhere", 0),
            ("Ida Tester", "lives_in", "Newark, New Jersey, United States", line + "Newark, NJ", 1)])
        self.assertEqual([(p, v) for p, _, v, _, _ in self.stored("role")],
                         [("Ida Tester", "Advisor"), ("Ida Tester", "Lead Architect")])
        works = self.store.conn.execute("SELECT count(*) FROM claims WHERE person_id = (SELECT id FROM persons "
                                        "WHERE display_name = 'Bo Tester') AND relation = 'works_at'").fetchone()[0]
        self.assertEqual(works, 1)
        self.answer = [person("Bo", "bo", {"linkedinText": "Newark, NJ"}, job)]
        self.run_lane(chips(["quantum"]))
        self.assertEqual(self.count("persons"), 4)
        self.assertIn(("Bo Tester", "lives_in", "Newark, NJ", line + "Newark, NJ", 1), self.stored("location"))

    def test_a_linkedin_person_has_a_known_job_and_a_place_that_fits_the_area(self):
        """With its role and employer claims a profile's person has a known job, and its stored place is inside
        the New York area and outside the Los Angeles one.
        """
        out = self.run_lane()
        person = out.hits[0].person_id
        claims = self.store.claims_of([person])
        ny = geo.locate("New York", CITIES)
        la = GeoArea(place="Los Angeles", city="Los Angeles, US", lat=34.05, lon=-118.24, radius_km=100.0)
        card = {person: frozenset({"profile_url"})}
        fits = []
        for area in (ny, la):
            ask = Question(chips=Chips(version=2, place=place(area.place)), area=area, country="US")
            found = evidence.of(card, claims, {}, ask, date(2027, 1, 15))
            fits.append((found.job, rank.place_fit(found, ask)))
        self.assertEqual(fits, [("known", "inside"), ("known", "outside")])

    def keyed(self, **update):
        """Settings of the lane on, with a Parallel key unless update changes it."""
        return self.live.model_copy(update={"parallel_api_key": SecretStr(PARALLEL)} | update)

    def accounts(self, account: httpx.Response, limit: httpx.Response):
        """Patch handle so the account and the limits calls answer with these responses."""
        base = self.handle

        def handle(request: httpx.Request) -> httpx.Response:
            if str(request.url) not in (linkedin.ACCOUNT_URL, linkedin.LIMITS_URL):
                return base(request)
            self.sent.append(request)
            return account if str(request.url) == linkedin.ACCOUNT_URL else limit

        return mock.patch.object(self, "handle", handle)

    def sent_to(self, url: str) -> list[httpx.Request]:
        return [r for r in self.sent if str(r.url).split("?")[0] == url]

    def searched(self, settings, queries: list[str], live: bool) -> list[list[dict]]:
        """The results search_google gives for each query, called inside a step so the client records its calls."""
        found = []

        def work(ctx: StepContext, inp: LaneIn) -> LaneOut:
            found.extend(linkedin.search_google(ctx, q, live) for q in queries)
            return LaneOut(lane="linkedin", query="", total_seen=0)

        self.in_step(chips(["6G"]), settings, work)
        return found

    def test_without_a_paid_run_google_runs_and_with_one_only_the_scraper(self):
        """A free plan, no room in the month and an unreadable account send no actor call and three Google calls with
        the caps, a 150 s timeout and $0.001 each, then one read. A paid plan with room sends the actor call only, and
        a recorded strict answer is served alone.
        """
        free = httpx.Response(200, json=FREE_ACCOUNT)
        paid = httpx.Response(200, json=self.account)
        room = httpx.Response(200, json={"data": {"limits": {"maxMonthlyUsageUsd": 5.1}, "current": {"monthlyUsageUsd": 5.0}}})
        down = httpx.Response(500, text="down")
        for role, account, limit in (("architects", free, down), ("economists", paid, room), ("traders", down, down)):
            with self.subTest(role=role), self.accounts(account, limit):
                self.sent.clear()
                given = asked([role], place=NEW_YORK)
                self.run_lane(given, self.keyed())
                self.assertEqual(self.sent_to(linkedin.ACTOR_URL), [])
                posts = self.sent_to(linkedin.GOOGLE_URL)
                queries, _ = linkedin.google_queries(given, geo.locate("New York", CITIES))
                for post, query in zip(posts, queries, strict=True):
                    self.assertEqual(dict(post.url.params), {"maxTotalChargeUsd": "0.05", "timeout": "120"})
                    self.assertEqual(post.headers["authorization"], f"Bearer {TOKEN}")
                    self.assertEqual(post.extensions["timeout"]["read"], 150)
                    self.assertEqual(json.loads(post.content), {"keyword": query, "limit": "10", "country": "US", "hl": "en"})
                self.assertEqual([c.cost_usd for c in self.calls() if linkedin.GOOGLE_URL in c.request], [0.001] * 3)
                self.assertEqual(len(self.sent_to(websearch.EXTRACT_URL)), 1)
        self.sent.clear()
        given = asked(["designers"], place=NEW_YORK)
        self.run_lane(given, self.keyed())
        self.assertEqual((len(self.sent_to(linkedin.ACTOR_URL)), self.sent_to(linkedin.GOOGLE_URL)), (1, []))
        self.sent.clear()
        out = self.run_lane(given, self.keyed(linkedin_live=False))
        (served,) = self.calls()
        self.assertEqual((self.posts(), len(out.hits), served.request.startswith("cache POST " + linkedin.ACTOR_URL)),
                         ([], 3, True))

    def test_a_kept_profile_is_one_person_with_dated_education_job_role_and_place(self):
        """Wim Doe's profile gives a studied_at claim per school with its years, a works_at and a worked_at claim,
        a role claim and a lives_in claim, all in one vendor_record source dated by Parallel's copy; his job is known
        and his place is inside the New York area.
        """
        self.account = FREE_ACCOUNT
        out = self.run_lane(JOURNALISTS, self.keyed())
        person = next(h.person_id for h in out.hits if self.store.get_persons([h.person_id])[h.person_id].display_name == "Wim Doe")
        rows = self.store.conn.execute(
            "SELECT s.kind, s.url, s.source_date, c.kind, c.relation, c.org_id, c.value, c.valid_from, c.valid_to, c.claim_date, "
            "c.lat IS NOT NULL FROM claims c JOIN sources s ON s.id = c.source_id WHERE c.person_id = ?", (person,))
        vendor = ("vendor_record", WIM, "2026-11-02")
        self.assertEqual({tuple(r) for r in rows}, {
            (*vendor, "affiliation", "studied_at", "ror:05f950310", "KU Leuven", "1990", "1994", "1994", 0),
            (*vendor, "affiliation", "studied_at", "ror:00cv9y106", "Ghent University", None, None, None, 0),
            (*vendor, "affiliation", "studied_at", None, "Fantasie Instituut voor Kunsten", "1985", "1986", "1986", 0),
            (*vendor, "affiliation", "works_at", None, "Acme Networks", "2015", "2026", "2026", 0),
            (*vendor, "affiliation", "worked_at", None, "Example Labs", "2005", "2014", "2014", 0),
            (*vendor, "role", None, None, "Chief Technology Officer", "2015", "2026", "2026", 0),
            (*vendor, "location", "lives_in", None, "New York City Metropolitan Area", None, None, "2026-11-02", 1)})
        ny = geo.locate("New York", CITIES)
        ask = Question(chips=Chips(version=2, place=place(ny.place)), area=ny, country="US")
        found = evidence.of({person: frozenset({"profile_url"})}, self.store.claims_of([person]), {}, ask, date(2027, 1, 15))
        self.assertEqual((found.job, rank.place_fit(found, ask)), ("known", "inside"))
        self.assertEqual([(h.rank, h.lane) for h in out.hits], [(1, "linkedin"), (2, "linkedin")])
        self.assertEqual([h.matched_on for h in out.hits], [
            f"result 1, Chief Technology Officer at Acme Networks, {WIM}",
            f"result 4, Principal Engineer at Example Labs, {ANJA}"])

    def test_a_profile_without_a_belgian_school_stores_nothing_and_names_nobody(self):
        """A school counts by its name or by the Belgian country of its org: a Dutch spelling, a French one and a
        school inside a Leuven name count; two other schools do not. Such a profile leaves a row with its result
        number and no person, source, claim or name anywhere.
        """
        other = make_settings(self)
        self.store = make_seeded_db(self, other)
        facts = self.store.get_orgs([i for i in map(orgs.org_id, ("Universiteit Gent", "Université libre de Bruxelles")) if i])
        for school, expected in (("Universiteit Gent", True), ("Université libre de Bruxelles", True),
                                 ("Rega School, KU Leuven", True), ("Université Libre de Bruxelles ", True),
                                 ("Columbia University", False), ("Estate School of Media", False), ("", False)):
            self.assertEqual(linkedin.belgian_school(school, facts), expected, school)
        self.assertEqual(facts[orgs.org_id("Universiteit Gent")].country_code, "BE")
        self.account = FREE_ACCOUNT
        out = self.run_lane(JOURNALISTS, self.keyed(var_dir=other.var_dir))
        dropped = [(c.person_key, c.name, c.stage, c.kept, c.reason) for c in out.considered if "not kept" in c.reason]
        self.assertEqual(dropped, [
            ("result 2", "", "profile", False, "result 2: no Belgian school among 0 schools; not kept"),
            ("result 3", "", "profile", False, "result 3: no Belgian school among 2 schools; not kept")])
        self.assertEqual(sorted(p.display_name for p in self.store.get_persons([h.person_id for h in out.hits]).values()),
                         ["Anja Voorbeeld", "Wim Doe"])
        gone = self.store.conn.execute(
            "SELECT (SELECT count(*) FROM persons WHERE display_name IN ('Pat Nobel', 'Karel Proef')), "
            "(SELECT count(*) FROM sources WHERE url LIKE '%pat-nobel%' OR url LIKE '%karel-proef%'), "
            "(SELECT count(*) FROM claims WHERE value LIKE '%Estate School%' OR quote LIKE '%Studio Invented%'), "
            "(SELECT count(*) FROM person_identifiers WHERE value LIKE '%pat-nobel%' OR value LIKE '%karel-proef%')").fetchone()
        self.assertEqual(tuple(gone), (0, 0, 0, 0))
        self.assertNotRegex(repr(out.considered), "Nobel|nobel|Karel|karel")

    def test_only_the_header_experience_and_education_are_read(self):
        """Summary, skills, collaborators and recommendations reach neither the stored source nor its raw record. An
        education without a school, a school block without a name, a job without a company, a header alone and an
        empty block are read as far as they go; a one-word name is no profile; a cut text loses its last line.
        """
        self.account = FREE_ACCOUNT
        self.run_lane(JOURNALISTS, self.keyed())
        rows = self.store.conn.execute("SELECT text || raw_json FROM sources").fetchall()
        self.assertTrue(rows)
        for (stored,) in rows:
            for absent in ("invented summary", "skill alpha", "Someone Else", "recommendation"):
                self.assertNotIn(absent, stored)
        page = {r["url"]: r for r in self.extract["results"]}
        anja = linkedin.read_profile(page["https://linkedin.com/in/anja-voorbeeld-invented/"]["full_content"], ANJA, "")
        self.assertEqual(anja["education"][1], {"degree": "Certificate", "endDate": {"year": 2009}})
        self.assertNotIn("companyName", anja["experience"][1])
        self.assertEqual((anja["headline"], anja["_meta"]), ("Principal Engineer at Example Labs", {"scrapedAt": ""}))
        karel = linkedin.read_profile(page["https://linkedin.com/in/karel-proef-invented"]["full_content"], KAREL, "x")
        self.assertEqual((karel["experience"], karel["education"], karel["location"]),
                         ([], [], {"linkedinText": "Newark, New Jersey, United States"}))
        unnamed = " * first name: Cher\n * Locality: Newark\n"
        nameless = "# Education\n   - Degree: MA\n\n## School\n   - Name: \n"
        self.assertIsNone(linkedin.read_profile(unnamed, KAREL, ""))
        self.assertIsNone(linkedin.read_profile(nameless, KAREL, ""))
        named = " * first name: Ada\n * last name: Tester\n"
        self.assertEqual(linkedin.read_profile(named + nameless, KAREL, "")["education"], [{"degree": "MA"}])
        bare = named + " * headline\n * Summary\n   - invented summary of Ada\n"
        self.assertNotIn("headline", linkedin.read_profile(bare, KAREL, ""))
        head, tail = named + " * Summary\n   - ", "\n# Education\n   - Degree: Master of Sci"
        filler = linkedin.PROFILE_CHARS - len(head) - len(tail)
        cut, whole = (linkedin.read_profile(head + "x" * (filler - drop) + tail, KAREL, "") for drop in (0, 1))
        self.assertEqual((cut["education"], whole["education"]), ([], [{"degree": "Master of Sci"}]))
        self.extract["results"] = [dict(r, full_content=" * first name: Solo\n") for r in self.extract["results"]]
        self.sent.clear()
        out = self.run_lane(JOURNALISTS, self.keyed())
        self.assertEqual((out.hits, [c.reason for c in out.considered if c.stage == "profile"]), ([], [
            "result 1: no first and last name; not read", "result 2: no first and last name; not read",
            "result 3: no first and last name; not read", "result 4: no first and last name; not read",
            "result 5: not read (fetch_failed)"]))
        self.assertIn(linkedin.NONE_PARSED, [c.reason for c in out.considered])

    def test_a_profile_the_web_lane_read_is_the_same_person_in_either_order(self):
        """A person the web lane stored from a profile page, under the page address without www and the name, is the
        record the LinkedIn lane writes to; and a person the LinkedIn lane stored first is the one the web lane finds.
        """
        self.account = FREE_ACCOUNT
        page = extract.identifier("https://linkedin.com/in/wim-doe-invented", "Wim Doe")
        first = self.store.resolve_person([page], "Wim Doe")
        out = self.run_lane(JOURNALISTS, self.keyed())
        self.assertIn(first.id, [h.person_id for h in out.hits])
        self.assertEqual(self.count("persons"), len(out.hits))
        later = extract.identifier("https://linkedin.com/in/anja-voorbeeld-invented", "Anja Voorbeeld")
        anja = self.store.resolve_person([later], "Anja Voorbeeld")
        self.assertIn(anja.id, [h.person_id for h in out.hits])
        self.assertEqual(self.count("persons"), len(out.hits))

    def test_an_answer_that_lost_the_site_limit_is_asked_once_more_with_the_limit_at_the_end(self):
        """When under half of a query's results are profile addresses, the query goes out once more with the site
        limit at the end and the answer with more profile addresses is used. Two such answers make no third call,
        and an empty answer is not asked again.
        """
        self.account = FREE_ACCOUNT
        kept, second, third = self.google
        lost = [{"page_number": 1, "results": [{"position": n, "url": f"https://example.org/page-{n}"} for n in (1, 2, 3)]}]
        weak = [{"page_number": 1, "results": [*lost[0]["results"][:2], kept[0]["results"][0]]}]
        empty = [{"page_number": 1, "results": []}]
        queries, _ = linkedin.google_queries(JOURNALISTS, geo.locate("New York", CITIES))
        moved = queries[0].removeprefix("site:www.linkedin.com/in ") + " site:www.linkedin.com/in"
        for served, used, asked_again in (([lost, kept, second, third], [kept, second, third], True),
                                          ([lost, weak, second, third], [weak, second, third], True),
                                          ([empty, second, third], [second, third], False)):
            with self.subTest(served=len(served), asked_again=asked_again):
                self.google, self.sent = served, []
                out = self.run_lane(JOURNALISTS, self.keyed())
                sent = [json.loads(r.content)["keyword"] for r in self.sent_to(linkedin.GOOGLE_URL)]
                self.assertEqual(sent, [queries[0], moved, *queries[1:]] if asked_again else queries)
                self.assertEqual(linkedin.ASKED_AGAIN.format(n=1) in [c.reason for c in out.considered], asked_again)
                self.assertEqual(out.total_seen, len(linkedin.addresses([a[0]["results"] for a in used])[0]))

    def test_a_parallel_error_or_missing_result_leaves_a_row(self):
        """An address Parallel reports as failed, one it leaves out and one it returns without content each get a row
        with the result number and the reason, and no person.
        """
        self.account = FREE_ACCOUNT
        out = self.run_lane(JOURNALISTS, self.keyed())
        rows = {c.person_key: c for c in out.considered if c.stage == "profile" and not c.kept}
        self.assertEqual((rows["result 5"].reason, rows["result 5"].name, rows["result 5"].kept),
                         ("result 5: not read (fetch_failed)", "", False))
        self.extract["errors"] = []
        self.extract["results"][0]["full_content"] = None
        del self.extract["results"][1]
        self.sent.clear()
        out = self.run_lane(JOURNALISTS, self.keyed())
        self.assertEqual([c.reason for c in out.considered if "not read" in c.reason],
                         ["result 1: not read (missing)", "result 4: not read (missing)", "result 5: not read (missing)"])
        self.assertEqual([h.matched_on.split(",")[0] for h in out.hits], [])

    def test_off_without_a_recorded_first_query_is_ok_and_a_later_miss_fails(self):
        """Off, the actor and the first Google query miss and the step is ok and not degraded. With the first query
        recorded, the second missing fails the step; with all three recorded, a missing read fails it too.
        """
        out = self.run_lane(JOURNALISTS, self.off)
        self.assertEqual(([c.reason for c in out.considered], self.posts(), self.store.list_steps(self.search_id)[-1].status),
                         ([linkedin.OFF], [], "ok"))
        self.assertFalse(score.degraded(self.store, self.search_id, set()))
        queries, _ = linkedin.google_queries(JOURNALISTS, geo.locate("New York", CITIES))
        for recorded in (1, 3):
            self.sent.clear()
            self.searched(self.live, queries[:recorded], True)
            self.sent.clear()
            with self.subTest(recorded=recorded), self.assertRaises(net.CacheMiss):
                self.run_lane(JOURNALISTS, self.off)
            self.assertEqual(self.store.list_steps(self.search_id)[-1].status, "error")
            self.assertTrue(score.degraded(self.store, self.search_id, set()))

    def test_an_answer_without_a_results_list_is_not_cached_and_an_empty_one_is(self):
        """A refused run, an empty list, an item without results and text that is no JSON leave no cache file; a
        results list that is empty is cached, so a replay serves it.
        """
        for answer in ({"error": "run failed"}, [], [{"page_number": 1}], [{"results": "none"}], [3], b"<html>"):
            with self.subTest(answer=answer):
                self.google, self.sent = [answer], []
                self.assertEqual(self.searched(self.live, ["query"], True), [[]])
                with self.assertRaises(net.CacheMiss):
                    self.searched(self.live, ["query"], False)
        self.google, self.sent = [[{"page_number": 1, "results": []}]], []
        self.assertEqual(self.searched(self.live, ["other"], True), [[]])
        self.assertEqual(self.searched(self.live, ["other"], False), [[]])
        self.assertEqual(len(self.sent_to(linkedin.GOOGLE_URL)), 1)

    def test_the_strict_routes_person_is_the_same_record_through_google(self):
        """A person the actor stored is the person Google finds under the same address: one record and one
        profile_url identifier each.
        """
        strict = self.run_lane(asked(["architects"], place=NEW_YORK), self.keyed())
        known = {p.display_name: p.id for p in self.store.get_persons([h.person_id for h in strict.hits]).values()}
        self.account = FREE_ACCOUNT
        found = self.run_lane(JOURNALISTS, self.keyed())
        again = {p.display_name: p.id for p in self.store.get_persons([h.person_id for h in found.hits]).values()}
        self.assertEqual(again, {k: known[k] for k in ("Wim Doe", "Anja Voorbeeld")})
        identifiers = self.store.conn.execute("SELECT count(*) FROM person_identifiers WHERE scheme = 'profile_url'")
        self.assertEqual((self.count("persons"), identifiers.fetchone()[0]), (3, 3))

    def test_researchers_only_no_token_and_no_parallel_key_note_and_call_nothing(self):
        """A question for researchers only, a missing Apify token and a missing Parallel key each give a note and
        send no Apify or Parallel call; the key note is logged as a warning.
        """
        out = self.run_lane(asked(["physicists"], place=NEW_YORK, research=True), self.keyed())
        self.assertEqual(([c.reason for c in out.considered], self.sent), ([linkedin.RESEARCHERS], []))
        self.account = FREE_ACCOUNT
        with self.assertLogs("fn.step", "WARNING"):
            out = self.run_lane(JOURNALISTS, self.keyed(apify_token=None))
        self.assertEqual([c.reason for c in out.considered],
                         ["LinkedIn lane skipped: no key for api.apify.com; set APIFY_TOKEN or store it in the Keychain"])
        self.assertEqual({r.url.host for r in self.sent} - {"download.geonames.org"}, set())
        self.sent.clear()
        with self.assertLogs("fn.step", "WARNING") as logged:
            out = self.run_lane(JOURNALISTS, self.live)
        self.assertEqual([c.reason for c in out.considered], [linkedin.FREE_PLAN, linkedin.NO_PARALLEL])
        self.assertEqual((self.posts(), out.hits, logged.records[0].getMessage()), ([], [], linkedin.NO_PARALLEL))


class GoldGuardTest(unittest.TestCase):
    class Spent(Exception):
        pass

    def main(self, ids: list[str], linkedin_live: bool) -> tuple[int | None, str, dict[str, mock.Mock]]:
        """gold.main with the env of a replay run in a temp var dir and run_case patched to raise Spent.

        Returns the exit code (None when run_case was reached), what main printed to stderr and the mocks
        of run_case, Store and Worker.
        """
        var = make_settings(self).var_dir
        env = {"FN_VAR": str(var), "FN_HTTP": "replay", "FN_LLM": "replay"} | ({"FN_LINKEDIN": "1"} if linkedin_live else {})
        errors, code = io.StringIO(), None
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("fn.config.keychain", return_value=None), \
                mock.patch.object(gold, "run_case", side_effect=self.Spent) as run_case, \
                mock.patch.object(gold, "Store") as store, mock.patch.object(gold, "Worker") as worker, \
                contextlib.redirect_stderr(errors), contextlib.suppress(self.Spent):
            code = gold.main(ids)
        return code, errors.getvalue(), {"run_case": run_case, "Store": store, "Worker": worker}

    def test_fn_linkedin_with_more_than_one_case_exits_before_any_search(self):
        """Two cases, and all 28, are refused when FN_LINKEDIN=1; run_case, the Store and the Worker are never reached."""
        for ids in (["GS-02", "GS-10"], []):
            with self.subTest(cases=ids or "all"):
                code, errors, mocks = self.main(ids, True)
                self.assertEqual(code, 2)
                self.assertIn("FN_LINKEDIN=1", errors)
                for name, called in mocks.items():
                    with self.subTest(mock=name):
                        called.assert_not_called()

    def test_fn_linkedin_with_exactly_one_case_and_many_cases_without_it_pass_the_guard(self):
        """The guard refuses only many cases with the switch: one case with it, and two cases without it, reach run_case."""
        for ids, switch in ((["GS-02"], True), (["GS-02", "GS-10"], False)):
            with self.subTest(cases=ids, linkedin=switch):
                code, errors, mocks = self.main(ids, switch)
                self.assertEqual((code, errors), (None, ""))
                self.assertEqual(mocks["run_case"].call_count, 1)


if __name__ == "__main__":
    unittest.main()
