import hashlib
import json
import logging
import unittest
from datetime import UTC, datetime

import httpx

from fn import geo, orgs
from fn.contracts import (
    Chip,
    Chips,
    Claim,
    ClaimDraft,
    Identifier,
    LaneIn,
    Org,
    Place,
    Source,
    normalize,
)
from fn.lanes import seeds
from fn.steps import StepContext
from fn.worker import Worker, new_id, now
from tests.helpers import StubHttp, StubLLM, cities_zip, make_db, make_seeded_db, make_settings

TEXTS = {
    "ehealth": "Builds e-health platforms",
    "cpp": "Writes C++ compilers",
    "6g": "Leads 6G networks research",
    "and": "Works on research and development",
    "dutch": "Onderzoek aan de Université de Liège, één project",
}


def topic(text: str) -> Chips:
    return Chips(topics=[Chip(text=text, origin="edited")])


class FtsQueryTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        text = normalize("\n".join(TEXTS.values()))
        source = Source(id="src", kind="page", url="https://example.org/experts", text=text,
                        content_hash=hashlib.sha256(text.encode()).hexdigest())
        self.people = {}
        for key, value in TEXTS.items():
            person = self.store.resolve_person([Identifier(scheme="seed", value=key)], key)
            start = text.index(value)
            self.store.upsert_claim(ClaimDraft(person_id=person.id, kind="topic", value=value, quote=value,
                                               quote_start=start, quote_end=start + len(value), source=source))
            self.people[person.id] = key

    def claim(self, key: str, value: str) -> ClaimDraft:
        """A topic claim for a new seed person, quoted from its own page source."""
        source = Source(id=f"src-{key}", kind="page", url=f"https://example.org/{key}", text=value,
                        content_hash=hashlib.sha256(value.encode()).hexdigest())
        person = self.store.resolve_person([Identifier(scheme="seed", value=key)], key)
        self.people[person.id] = key
        return ClaimDraft(person_id=person.id, kind="topic", value=value, quote=value, quote_start=0,
                          quote_end=len(value), source=source)

    def lane(self, chips: Chips):
        ctx = StepContext(search_id="s", store=self.store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        return seeds.run(ctx, LaneIn(search_id="s", chips=chips))

    def test_operators_quotes_and_punctuation_are_plain_text(self):
        """Hyphens, C++, quoted 6G, FTS operators and Dutch accents raise nothing and match their row."""
        for text, expected in (("e-health", "ehealth"), ("C++ compilers", "cpp"), ('"6G"', "6g"),
                               ("AND NEAR e-health", "ehealth"), ("Universite de Liege", "dutch"), ("Liège", "dutch")):
            with self.subTest(text=text):
                out = self.lane(topic(text))
                self.assertEqual(self.people[out.hits[0].person_id], expected)

    def test_empty_chips_give_no_query_and_say_why(self):
        """A chip with no letters, only a place, or every chip removed runs no query and records the reason."""
        for chips in (topic(" -- "), Chips(place=Place(text="Boston", origin="edited")), Chips()):
            with self.subTest(chips=chips):
                out = self.lane(chips)
                self.assertEqual((out.query, out.hits), ("", []))
                self.assertEqual([c.reason for c in out.considered], [seeds.NO_QUERY])

    def test_claims_from_lane_and_vendor_sources_are_no_seed_hit_and_page_claims_are(self):
        """The seed lane matches claims from seed and page sources only.

        Claims from record, vendor_record and vendor_page sources never become seed hits.
        """
        text = "Leads 6G networks research"
        for kind in ("record", "vendor_record", "vendor_page", "page"):
            source = Source(id=f"src-{kind}", kind=kind, url=f"https://example.org/{kind}", text=text,
                            content_hash=hashlib.sha256(text.encode()).hexdigest())
            person = self.store.resolve_person([Identifier(scheme="seed", value=kind)], kind)
            self.store.upsert_claim(ClaimDraft(person_id=person.id, kind="topic", value=text, quote=text, quote_start=0,
                                               quote_end=len(text), source=source))
            self.people[person.id] = kind
        out = self.lane(topic("6G"))
        self.assertCountEqual([self.people[h.person_id] for h in out.hits], ["6g", "page"])

    def test_an_imported_affiliation_is_a_seed_hit(self):
        """Claims that quote an import or staff source match, so imported people are found by organization and role."""
        text = "organization: Leads 6G networks research"
        source = Source(id="src-import", kind="import", url="fn:import/i1#row-2", text=text,
                        content_hash=hashlib.sha256(text.encode()).hexdigest(), date_method="sheet_date")
        person = self.store.resolve_person([Identifier(scheme="import", value="i1:2")], "Imported Example")
        self.store.upsert_claim(ClaimDraft(person_id=person.id, kind="affiliation", value="Leads 6G networks research",
                                           quote=text, quote_start=0, quote_end=len(text), source=source))
        self.people[person.id] = "import"
        out = self.lane(topic("6G"))
        self.assertIn("import", [self.people[h.person_id] for h in out.hits])

    def test_query_quotes_tokens_and_adds_institution_aliases_as_phrases(self):
        chips = Chips(topics=[Chip(text='say "hi" OR', origin="edited")], institutions=[Chip(text="MIT", origin="edited")])
        self.assertEqual(seeds.fts_query(chips, lambda text: orgs.names(orgs.org_id(text))),
                         '"say" OR "hi" OR "MIT" OR "M.I.T." OR "Massachusetts Institute of Technology"')

    def test_function_words_are_not_queried(self):
        """AI in health care queries ai, health and care. A row that holds only the word in is no hit."""
        chips = topic("AI in health care")
        self.assertEqual(seeds.fts_query(chips), '"ai" OR "health" OR "care"')
        self.store.upsert_claim(self.claim("in", "Lives in a house"))
        out = self.lane(chips)
        self.assertEqual([self.people[h.person_id] for h in out.hits], ["ehealth"])

    def test_generic_words_only_and_no_institution_give_no_query(self):
        """Belgian research and a lone function word hold no content word, so the lane runs no query."""
        for text in ("Belgian research", "the"):
            with self.subTest(text=text):
                out = self.lane(topic(text))
                self.assertEqual((out.query, out.hits), ("", []))
                self.assertEqual([c.reason for c in out.considered], [seeds.NO_QUERY])

    def test_institution_chip_alone_still_queries_its_tokens_and_aliases(self):
        chips = Chips(topics=[Chip(text="research", origin="edited")], institutions=[Chip(text="MIT", origin="edited")])
        self.assertEqual(seeds.fts_query(chips, lambda text: orgs.names(orgs.org_id(text))),
                         '"MIT" OR "M.I.T." OR "Massachusetts Institute of Technology"')

    def test_lane_keeps_the_first_300_of_301_matches(self):
        """With 301 matching rows the lane keeps 300 hits and records the last one as below the cap."""
        for i in range(301):
            self.store.upsert_claim(self.claim(f"bulk{i}", f"Studies zebrafish number {i}"))
        out = self.lane(topic("zebrafish"))
        self.assertEqual((len(out.hits), out.total_seen), (300, 301))
        self.assertFalse(out.considered[-1].kept)


class SeedLaneSearchTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_seeded_db(self, self.settings)
        self.worker = Worker(self.store, self.settings, llm=StubLLM(error=AssertionError("parse must not run")),
                             http=StubHttp())
        self.addCleanup(self.worker.shutdown)

    def search(self, chips: Chips):
        return self.worker.execute(self.worker.create_search("Which Belgian faculty at MIT?", chips, "edited").id)

    def seed_person(self, row_key: str) -> str:
        return self.store.conn.execute(
            "SELECT person_id FROM person_identifiers WHERE scheme = 'seed' AND value = ?", (row_key,)).fetchone()[0]

    def test_mit_chip_finds_the_mit_spelled_rows(self):
        """An MIT chip reaches the rows that spell it M.I.T. and Massachusetts Institute of Technology."""
        found = self.search(Chips(institutions=[Chip(text="MIT", origin="edited")]))
        (lane,) = [s for s in self.store.list_steps(found.id) if s.step == "lane:seeds"]
        hits = {h["person_id"]: h for h in json.loads(self.store.get_payload(lane.id)[1])["hits"]}
        self.assertEqual(hits[self.seed_person("baef|julien-de-wit|2012|")]["matched_on"], "M.I.T.")
        self.assertIn(self.seed_person("francqui|michel-goemans|1987|"), hits)

    def test_gs10_chips_return_goemans_de_wit_and_janjevic(self):
        """The GS-10 chips (institution MIT) give entries for the three seed picks, Goemans with both his records."""
        found = self.search(Chips(institutions=[Chip(text="MIT", origin="edited")],
                                  place=Place(text="Boston", origin="edited")))
        self.assertEqual(found.status, "done")
        candidates = self.store.list_candidates(found.id)
        names = {self.store.get_persons([c.person_id])[c.person_id].name_key: c for c in candidates}
        for name in ("michel goemans", "julien de wit", "milena janjevic"):
            self.assertIn(name, names)
            self.assertEqual(names[name].section, "new")
        goemans = names["michel goemans"]
        self.assertCountEqual(goemans.person_ids, [self.seed_person("francqui|michel-goemans|1987|"),
                                                   self.seed_person("baef|michel-goemans|1987|")])
        self.assertEqual(goemans.person_id, self.seed_person("francqui|michel-goemans|1987|"))
        flags = self.store.list_flags(found.id)
        self.assertIn((goemans.person_id, self.seed_person("baef|michel-goemans|1987|")),
                      [(f.person_id, f.other_person_id) for f in flags])
        self.assertEqual(sorted(c.rank for c in candidates), list(range(1, len(candidates) + 1)))

    def test_stored_chips_skip_parse_and_reach_the_lane(self):
        chips = Chips(topics=[Chip(text="exoplanetology", origin="edited")])
        found = self.search(chips)
        steps = self.store.list_steps(found.id)
        self.assertEqual([(s.step, s.status) for s in steps][:2], [("parse", "skipped"), ("lane:seeds", "ok")])
        self.assertEqual(Chips.model_validate(json.loads(self.store.get_payload(steps[1].id)[0])["chips"]), chips)
        self.assertEqual(len(self.store.list_candidates(found.id)), 1)

    def test_same_question_twice_makes_two_searches_and_no_people(self):
        before = self.store.conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
        chips = Chips(institutions=[Chip(text="MIT", origin="edited")])
        first, second = self.search(chips), self.search(chips)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(self.store.list_candidates(first.id)), len(self.store.list_candidates(second.id)))
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0], before)


class CitiesHttp:
    """Answers the GeoNames dump with the test extract, outside any step."""

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        assert url == geo.CITIES_URL, url
        return httpx.Response(200, content=cities_zip())


BOSTON = Place(text="Boston", origin="edited")
TODAY = datetime(2026, 11, 12, tzinfo=UTC)


class SeedPlaceTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.store.upsert_source(Source(id="org-src", kind="record", url="https://example.org/orgs", text="orgs",
                                        content_hash="h-orgs"))
        for org_id, city, lat, lon in (("ror:00abcd111", "Cambridge", 42.3751, -71.10561),
                                       ("ror:00abcd222", "Chicago", 41.85003, -87.65005)):
            self.store.upsert_org(Org(id=org_id, name=f"{city} Example Lab", country_code="US", city=city, lat=lat,
                                      lon=lon, source_id="org-src", fetched_at=TODAY), True)
        self.people = {}

    def claim(self, key: str, value: str, **fields) -> Claim:
        """A claim of the seed person key, quoted from its own seed list source."""
        source = Source(id=f"src-{key}-{len(value)}-{fields.get('kind', '')}", kind="seed_page",
                        url=f"https://example.org/{key}", text=value, content_hash=hashlib.sha256(value.encode()).hexdigest())
        person = self.store.resolve_person([Identifier(scheme="seed", value=key)], key)
        self.people[person.id] = key
        return self.store.upsert_claim(ClaimDraft(**{"kind": "topic", **fields}, person_id=person.id, value=value,
                                                  quote=value, quote_start=0, quote_end=len(value), source=source))

    def lives(self, key: str, city: str, lat: float, lon: float) -> Claim:
        return self.claim(key, city, kind="location", relation="lives_in", lat=lat, lon=lon)

    def works(self, key: str, org_id: str, year: str) -> Claim:
        return self.claim(key, f"Researcher at lab {org_id}", kind="affiliation", relation="works_at", org_id=org_id,
                          claim_date=year)

    def lane(self, chips: Chips):
        ctx = StepContext(search_id="s", store=self.store, llm=None, http=CitiesHttp(), now=lambda: TODAY,
                          new_id=new_id, log=logging.getLogger("fn.step"), settings=self.settings)
        return seeds.run(ctx, LaneIn(search_id="s", chips=chips))

    def keys(self, out) -> list[str]:
        return [self.people[h.person_id] for h in out.hits]

    def test_a_consul_in_the_city_is_a_place_hit_for_a_question_with_only_a_place(self):
        """A seed person with a stated place inside the area is a hit based in that place, citing the place claim."""
        place = self.lives("consul", "Boston", 42.36, -71.06)
        out = self.lane(Chips(place=BOSTON))
        self.assertEqual((out.query, self.keys(out)), ("", ["consul"]))
        self.assertEqual((out.hits[0].matched_on, out.hits[0].claim_ids), ("based in Boston", [place.id]))

    def test_a_far_place_and_an_old_employer_are_no_hit_and_a_recent_employer_is(self):
        """A place 300 km away and an employer fact older than five years give no hit.

        A recent employer in the area does, and a stated place inside counts whatever the employer.
        """
        self.lives("far", "New York City", 40.71427, -74.00597)
        self.works("old", "ror:00abcd111", "2015")
        recent = self.works("recent", "ror:00abcd111", "2025")
        self.lives("both", "Boston", 42.40, -71.06)
        self.works("both", "ror:00abcd222", "2025")
        out = self.lane(Chips(place=BOSTON))
        self.assertCountEqual(self.keys(out), ["recent", "both"])
        (hit,) = [h for h in out.hits if self.people[h.person_id] == "recent"]
        self.assertEqual((hit.matched_on, hit.claim_ids), ("based in Cambridge", [recent.id]))

    def test_25_people_in_the_area_give_the_nearest_20(self):
        for i in (7, 3, 24, 0, 18, 11, 22, 5, 14, 1, 20, 9, 16, 2, 23, 12, 6, 19, 4, 15, 10, 21, 8, 17, 13):
            self.lives(f"near{i:02d}", "Boston", 42.35843 + i * 0.01, -71.05977)
        out = self.lane(Chips(place=BOSTON))
        self.assertEqual(self.keys(out), [f"near{i:02d}" for i in range(20)])
        self.assertEqual([h.rank for h in out.hits], list(range(1, 21)))

    def test_a_country_anywhere_us_or_unknown_place_runs_no_place_search(self):
        """Only a place geo.area locates as a city gets a place search; the others leave the lane with no query."""
        self.lives("consul", "Boston", 42.36, -71.06)
        for place in (Place(text="Belgium", origin="edited"), Place(text="anywhere", origin="edited", kind="anywhere_us"),
                      Place(text="Atlantis", origin="edited")):
            with self.subTest(place=place.text):
                out = self.lane(Chips(place=place))
                self.assertEqual((out.query, out.hits), ("", []))
                self.assertEqual([c.reason for c in out.considered], [seeds.NO_QUERY])

    def test_a_topic_word_or_an_institution_beside_the_city_runs_no_place_search(self):
        """A question with a topic word or an institution chip and a city gets only its text hits.

        The person who is only based in the city is no hit and is not considered.
        """
        self.claim("topic1", "Studies zebrafish")
        self.claim("inst1", "Fellow at Example Hospital")
        self.lives("consul", "Boston", 42.36, -71.06)
        for chips, expected in ((Chips(topics=[Chip(text="zebrafish", origin="edited")], place=BOSTON), ["topic1"]),
                                (Chips(institutions=[Chip(text="Example Hospital", origin="edited")], place=BOSTON),
                                 ["inst1"])):
            with self.subTest(chips=chips):
                out = self.lane(chips)
                self.assertEqual(self.keys(out), expected)
                self.assertNotIn("place", {c.stage for c in out.considered})


if __name__ == "__main__":
    unittest.main()
