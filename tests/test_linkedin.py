import contextlib
import hashlib
import io
import json
import logging
import os
import unittest
from datetime import UTC, datetime
from unittest import mock

import httpx
from pydantic import SecretStr

from fn import geo, gold, net, orgs, rank
from fn.contracts import Chip, Chips, GeoArea, LaneIn, LaneOut, Place, record_source
from fn.lanes import linkedin
from fn.steps import StepContext, run_step
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


class LinkedInLaneTest(unittest.TestCase):
    def setUp(self):
        self.live = make_settings(self).model_copy(
            update={"http_mode": "live", "apify_token": SecretStr(TOKEN), "linkedin_live": True})
        self.off = self.live.model_copy(update={"linkedin_live": False})
        self.store = make_db(self, self.live)
        self.answer: object = profiles()
        self.sent: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        if request.url.host == "download.geonames.org":
            return httpx.Response(200, content=cities_zip())
        return httpx.Response(200, json=self.answer)

    def posts(self) -> list[httpx.Request]:
        return [r for r in self.sent if r.url.host == "api.apify.com"]

    def run_lane(self, given: Chips | None = None, settings=None) -> LaneOut:
        """Run lane:linkedin as a step of a new search over a mock transport; the default chips are the GS-02 ones.

        The step's clock reads READ, a year after the fixture's scrapedAt, so a scrape year cannot pass for the read year.
        """
        settings, given = settings or self.live, given or gs02_chips()
        http = net.Client(settings, httpx.MockTransport(self.handle))
        worker = Worker(self.store, settings, llm=StubLLM(error=AssertionError("the LLM must not be called")), http=http)
        self.addCleanup(worker.shutdown)
        self.search_id = worker.create_search("question", given, "edited").id
        ctx = StepContext(search_id=self.search_id, store=self.store, llm=None, http=http, now=lambda: READ, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        return run_step(ctx, "lane:linkedin", linkedin.run, LaneIn(search_id=self.search_id, chips=given))

    def calls(self) -> list:
        """The calls of the last lane step."""
        return self.store.list_calls(self.store.list_steps(self.search_id)[-1].id)

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
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM claims").fetchone()[0], 10)

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
        self.assertEqual({tuple(r) for r in identifiers},
                         {("profile_url", WIM), ("profile_url", ANJA), ("profile_url", KAREL)})

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

    def test_a_place_abroad_or_anywhere_in_the_us_sends_its_text_without_fetching_the_city_list(self):
        """Only a metro place needs GeoNames; the other kinds make the one Apify call and nothing else."""
        for kind, text, expected in (("abroad", "Antwerp area", "Antwerp area"), ("anywhere_us", "the US", "United States")):
            with self.subTest(kind=kind):
                self.sent.clear()
                self.run_lane(chips(["6G"], place=place(text, kind)))
                self.assertEqual([r.url.host for r in self.sent], ["api.apify.com"])
                self.assertEqual(json.loads(self.sent[0].content)["locations"], [expected])

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
        (call,) = self.calls()
        self.assertEqual(call.error, "not in the response cache")

    def test_the_lane_off_serves_a_recorded_run_without_a_transport_call(self):
        """A run made with the lane on is served to a search with it off: same hits, the transport called once in all."""
        given = chips(["6G"])
        first = self.run_lane(given)
        out = self.run_lane(given, self.off)
        self.assertEqual(len(self.sent), 1)
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
        self.assertEqual((len(out.hits), self.count("persons"), self.count("sources"), self.count("claims")), (1, 1, 1, 5))
        self.assertEqual(out.total_seen, 2)

    def test_a_person_listed_twice_is_one_hit_holding_the_claims_of_both_entries(self):
        """A second entry for the same URL with a changed text is a new source; the one hit lists both sets of claims."""
        first = profiles()[0]
        second = {**first, "experience": [*first["experience"], first["experience"][1] | {"companyName": "Other Labs"}]}
        self.answer = [first, second]
        out = self.run_lane(chips(["6G"]))
        (hit,) = out.hits
        self.assertEqual((self.count("persons"), self.count("sources"), self.count("claims")), (1, 2, 11))
        self.assertCountEqual(hit.claim_ids, [c.id for c in self.store.claims_of([hit.person_id])])
        self.assertEqual(len(hit.claim_ids), 11)

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
