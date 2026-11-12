import hashlib
import json
import logging
import unittest

from fn import orgs
from fn.contracts import (
    Chip,
    Chips,
    ClaimDraft,
    Identifier,
    LaneIn,
    Place,
    Source,
    normalize,
)
from fn.lanes import seeds
from fn.steps import StepContext
from fn.worker import Worker, new_id, now
from tests.helpers import StubHttp, StubLLM, make_db, make_seeded_db, make_settings

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

    def lane(self, chips: Chips):
        ctx = StepContext(search_id="s", store=self.store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        return seeds.run(ctx, LaneIn(search_id="s", chips=chips))

    def test_operators_quotes_and_punctuation_are_plain_text(self):
        """Hyphens, C++, quoted 6G, FTS operators and Dutch accents raise nothing and match their row."""
        for text, expected in (("e-health", "ehealth"), ("C++", "cpp"), ('"6G"', "6g"), ("AND OR NOT", "and"),
                               ("Universite de Liege", "dutch"), ("een", "dutch")):
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
                         '"say" OR """hi""" OR "OR" OR "MIT" OR "M.I.T." OR "Massachusetts Institute of Technology"')


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


if __name__ == "__main__":
    unittest.main()
