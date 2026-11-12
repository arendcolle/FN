import json
import re
import time
import unittest
from html import escape

import httpx

from fn import net, resolve
from fn.contracts import Chip, Chips, LaneOut, Place
from fn.lanes import openalex
from fn.web.debug import cards, lane_matches, trace_rows
from fn.worker import Worker
from tests.helpers import (
    FIXTURES,
    StubLLM,
    cities_zip,
    make_db,
    make_seeded_db,
    make_settings,
    save_recorded_orgs,
)

RECORDED = FIXTURES / "http" / "openalex"
BAEYENS, JANJEVIC, KLEIN, VANDEWIELE = "A5063711273", "A5022179613", "A5112227257", "A5067687780"
MIT = {"id": "https://openalex.org/I63966007", "ror": "https://ror.org/042nb2s44",
       "display_name": "Massachusetts Institute of Technology", "country_code": "US"}
LEUVEN = {"id": "https://openalex.org/I99464096", "display_name": "KU Leuven", "country_code": "BE"}


def recorded(name: str) -> dict:
    return json.loads((RECORDED / f"{name}.json").read_text())


def only(body: dict, ids: set[str]) -> dict:
    results = [r for r in body["results"] if openalex.short(r["id"]) in ids]
    return {"meta": {"count": len(results)}, "results": results}


def author(author_id: str, display_name: str, last_known: dict, years: dict[str, list[int]]) -> dict:
    """A minimal OpenAlex author record with one affiliation per institution in years."""
    institutions = {i["display_name"]: i for i in (MIT, LEUVEN)}
    return {"id": f"https://openalex.org/{author_id}", "display_name": display_name, "orcid": None,
            "last_known_institutions": [last_known], "updated_date": "2026-10-01",
            "affiliations": [{"institution": institutions[n], "years": y} for n, y in years.items()]}


def route(request: httpx.Request) -> httpx.Response:
    """Serve task 0's recorded OpenAlex responses, filtering the batch files to the ids asked for."""
    if request.url.host == "download.geonames.org":
        return httpx.Response(200, content=cities_zip())
    params, path = request.url.params, request.url.path
    where = params.get("filter", "")
    ids = set(where.split(":", 1)[1].split("|")) if ":" in where else set()
    if path == "/works":
        return httpx.Response(200, json=recorded("works_topic_" + re.sub(r"[^a-z0-9]+", "_", params["search"].lower())))
    if path == "/authors" and where.startswith("last_known_institutions.ror:https://ror.org/042nb2s44,"):
        return httpx.Response(200, json=recorded(f"authors_institution_mit_p{params['page']}"))
    if path == "/authors" and where.startswith("ids.openalex:"):
        return httpx.Response(200, json=only(recorded("authors_batch_picks"), ids))
    if path == "/institutions":
        return httpx.Response(200, json=only(recorded("institutions_batch_picks"), ids))
    return httpx.Response(404, json={"error": f"no fixture for {request.url}"})


class OpenAlexLaneTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live"})
        self.store = make_db(self, self.settings)
        save_recorded_orgs(self.store, self.settings)

    def search(self, chips: Chips, handler=route) -> LaneOut:
        http = net.Client(self.settings, httpx.MockTransport(handler))
        worker = Worker(self.store, self.settings, llm=StubLLM(error=AssertionError("parse must not run")), http=http)
        self.addCleanup(worker.shutdown)
        self.found = worker.execute(worker.create_search("question", chips, "edited").id)
        self.assertEqual(self.found.status, "done", self.found.error)
        (lane,) = [s for s in self.store.list_steps(self.found.id) if s.step == "lane:openalex"]
        return LaneOut.model_validate_json(self.store.get_payload(lane.id)[1])

    def person(self, author_id: str) -> str:
        rows = self.store.conn.execute(
            "SELECT person_id FROM person_identifiers WHERE scheme = 'openalex' AND value = ?", (author_id,)).fetchall()
        self.assertEqual(len(rows), 1)
        return rows[0][0]

    def claims(self, person_id: str) -> dict:
        """The person's claims by kind and value, each checked against the stored source text at its offsets."""
        found = {}
        claims = self.store.claims_of([person_id])
        sources = self.store.get_sources([c.source_id for c in claims])
        for claim in claims:
            self.assertEqual(sources[claim.source_id].text[claim.quote_start:claim.quote_end], claim.quote)
            found[(claim.kind, claim.value)] = claim
        return found

    def considered(self, out: LaneOut, author_id: str):
        (row,) = [c for c in out.considered if c.person_key == author_id]
        return row

    def test_baeyens_without_last_known_institution_is_one_person_with_imec_and_place_unknown(self):
        """An author with no last known institution is kept, with an IMEC claim at its offsets and no location."""
        out = self.search(Chips(topics=[Chip(text="telecommunications", origin="edited")],
                                place=Place(text="New York and New Jersey area", origin="edited", kind="metro")))
        person_id = self.person(BAEYENS)
        claims = self.claims(person_id)
        imec = claims[("affiliation", "IMEC")]
        self.assertEqual((imec.org_id, imec.valid_from, imec.valid_to, imec.date_method), ("ror:02kcbn207", "1996", "2002", "record_field"))
        self.assertIn("affiliations.4.institution.display_name: IMEC", imec.quote)
        self.assertNotIn("location", {kind for kind, _ in claims})
        row = self.considered(out, BAEYENS)
        self.assertTrue(row.kept)
        self.assertIn("place unknown", row.reason)
        self.assertIn("IMEC 1996-2002", row.reason)
        self.assertIn(person_id, [h.person_id for h in out.hits])
        self.assertIn("place 'New York and New Jersey area' is New York City, US", out.considered[0].reason)

    def test_janjevic_gets_a_ulb_affiliation_and_a_cambridge_location_claim(self):
        """Both MIT pages are read; the ULB and Cambridge claims quote their records, and seed FTS never sees them."""
        out = self.search(Chips(institutions=[Chip(text="MIT", origin="edited")],
                                place=Place(text="Boston", origin="edited", kind="metro")))
        person_id = self.person(JANJEVIC)
        claims = self.claims(person_id)
        ulb = claims[("affiliation", "Université Libre de Bruxelles")]
        self.assertEqual((ulb.org_id, ulb.claim_date, ulb.valid_from), ("ror:01r9htc13", "2018", "2013"))
        where = claims[("location", "Cambridge, Massachusetts, United States")]
        self.assertEqual((where.lat, where.lon, where.date_method), (42.3751, -71.10561, "read_date"))
        self.assertTrue(where.quote.startswith("geo.city: Cambridge\n"))
        (hit,) = [h for h in out.hits if h.person_id == person_id]
        self.assertCountEqual(hit.claim_ids, [ulb.id, where.id])
        self.assertIn("km from Boston, US (inside the radius)", self.considered(out, JANJEVIC).reason)
        self.assertEqual(out.total_seen, 362)
        self.assertIn("ror:https://ror.org/042nb2s44", out.query)
        self.assertEqual(self.considered(out, "A5107900815").reason, "no author record returned")
        self.assertNotEqual(self.store.match_claims('"Bruxelles"', exclude=("seed_page",)), [])
        self.assertEqual(self.store.match_claims('"Bruxelles"', exclude=("record",)), [])

    def test_an_affiliation_claim_carries_the_years_its_record_lists(self):
        """Janjevic's ULB claim keeps the five years OpenAlex lists, sorted, and still runs from 2013 to 2018."""
        self.search(Chips(institutions=[Chip(text="MIT", origin="edited")]))
        ulb = self.claims(self.person(JANJEVIC))[("affiliation", "Université Libre de Bruxelles")]
        self.assertEqual((ulb.years, ulb.valid_from, ulb.valid_to), ([2013, 2014, 2016, 2017, 2018], "2013", "2018"))

    def test_author_without_a_belgian_affiliation_is_kept_as_a_hit(self):
        """An author whose record has no BE affiliation is a kept hit, stored as one person with every dated affiliation."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/works":
                author = {"id": f"https://openalex.org/{KLEIN}", "display_name": "Thierry E. Klein"}
                work = {"id": "https://openalex.org/W1", "display_name": "w", "publication_year": 2020,
                        "authorships": [{"author": author, "institutions": []}]}
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [work]})
            return route(request)

        out = self.search(Chips(topics=[Chip(text="6G", origin="edited")]), handler)
        row = self.considered(out, KLEIN)
        self.assertEqual((row.name, row.stage, row.kept), ("Thierry E. Klein", "rank", True))
        self.assertIn("Belgian affiliations none", row.reason)
        (hit,) = out.hits
        topic = self.claims(hit.person_id)[("topic", "w")]
        self.assertEqual((hit.person_id, hit.claim_ids), (self.person(KLEIN), [topic.id]))
        self.assertEqual(len(self.claims(hit.person_id)), 6)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0], 1)

    def test_affiliation_institutions_are_saved_as_orgs_without_replacing_fn_orgs_rows(self):
        """An institution without a ROR id is stored under its OpenAlex id and country; a ROR one keeps its fn-orgs row."""
        record = author("A1", "Some Author", MIT, {"KU Leuven": [2020], MIT["display_name"]: [2021]})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/works":
                work = {"id": "https://openalex.org/W1", "display_name": "w", "publication_year": 2020,
                        "authorships": [{"author": {"id": record["id"], "display_name": record["display_name"]}}]}
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [work]})
            if request.url.path == "/authors":
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [record]})
            return route(request)

        mit_before = self.store.get_orgs(["ror:042nb2s44"])["ror:042nb2s44"]
        self.search(Chips(topics=[Chip(text="wind", origin="edited")]), handler)
        claims = self.claims(self.person("A1"))
        self.assertEqual(claims[("affiliation", "KU Leuven")].org_id, "openalex:I99464096")
        leuven = self.store.get_orgs(["openalex:I99464096"])["openalex:I99464096"]
        self.assertEqual((leuven.name, leuven.country_code, leuven.region), ("KU Leuven", "BE", None))
        self.assertEqual(leuven.source_id, claims[("affiliation", "KU Leuven")].source_id)
        self.assertEqual(self.store.get_orgs(["ror:042nb2s44"])["ror:042nb2s44"], mit_before)

    def test_an_affiliation_institution_is_saved_with_the_city_and_coordinates_of_its_fetched_record(self):
        """The last known institution is fetched with its geo, so its org row gets the city; an institution never fetched gets none."""
        record = author("A1", "Some Author", LEUVEN, {"KU Leuven": [2020], MIT["display_name"]: [2021]})
        leuven = LEUVEN | {"geo": {"city": "Leuven", "latitude": 50.88, "longitude": 4.7}}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/works":
                work = {"id": "https://openalex.org/W1", "display_name": "w", "publication_year": 2020,
                        "authorships": [{"author": {"id": record["id"], "display_name": record["display_name"]}}]}
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [work]})
            if request.url.path == "/authors":
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [record]})
            if request.url.path == "/institutions":
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [leuven]})
            return route(request)

        self.search(Chips(topics=[Chip(text="wind", origin="edited")]), handler)
        found = self.store.get_orgs(["openalex:I99464096"])["openalex:I99464096"]
        self.assertEqual((found.city, found.lat, found.lon), ("Leuven", 50.88, 4.7))

    def test_every_kept_author_is_a_hit_in_the_order_seen(self):
        """Without a place chip all 150 Belgian authors are hits, ranked in the order the works list them.

        The last author is on a second work too, and still ranks last: being seen more often orders nothing.
        """
        records = {f"A{i}": author(f"A{i}", f"Author {i}", MIT, {"KU Leuven": [2020]}) for i in range(150)}
        teams = [list(records.values()), [records["A149"]]]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/works":
                works = [{"id": f"https://openalex.org/W{i}", "display_name": "w", "publication_year": 2020,
                          "authorships": [{"author": {"id": a["id"], "display_name": a["display_name"]}} for a in team]}
                         for i, team in enumerate(teams)]
                return httpx.Response(200, json={"meta": {"count": 2}, "results": works})
            if request.url.path == "/authors":
                ids = request.url.params["filter"].split(":", 1)[1].split("|")
                return httpx.Response(200, json={"meta": {"count": len(ids)}, "results": [records[i] for i in ids]})
            return route(request)

        out = self.search(Chips(topics=[Chip(text="wind", origin="edited")]), handler)
        self.assertEqual([(h.rank, h.name_key) for h in out.hits], [(i + 1, f"author {i}") for i in range(150)])
        ranked = [c for c in out.considered if c.stage == "rank"]
        self.assertEqual(len(ranked), 150)
        self.assertTrue(all(c.kept for c in ranked))
        self.assertTrue(self.considered(out, "A149").reason.startswith("rank 150, seen #150; "))

    def test_a_higher_belgian_share_does_not_move_an_author_up(self):
        """In one place group an author seen first with one Belgian year of six ranks above one seen later with only Belgian years."""
        early = author("A1", "Early Author", MIT, {MIT["display_name"]: [2015, 2016, 2017, 2018, 2019], "KU Leuven": [2020]})
        later = author("A2", "Later Author", LEUVEN, {"KU Leuven": [2020]})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/works":
                work = {"id": "https://openalex.org/W1", "display_name": "w", "publication_year": 2020,
                        "authorships": [{"author": {"id": a["id"], "display_name": a["display_name"]}} for a in (early, later)]}
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [work]})
            if request.url.path == "/authors":
                return httpx.Response(200, json={"meta": {"count": 2}, "results": [early, later]})
            return route(request)

        out = self.search(Chips(topics=[Chip(text="wind", origin="edited")]), handler)
        self.assertEqual([(h.rank, h.name_key) for h in out.hits], [(1, "early author"), (2, "later author")])

    def test_every_fetched_author_is_a_hit_and_the_ranker_puts_the_belgian_one_first(self):
        """The lane keeps authors with no Belgian claim and ranks all three in the order seen.

        The ranker puts the Belgian author seen second first, because only it has a belgian_years part.
        """
        mit_only = author("A1", "Mit Author", MIT, {MIT["display_name"]: [2020]})
        leuven = author("A2", "Leuven Author", MIT, {"KU Leuven": [2020]})
        yearless = {**author("A3", "Yearless Author", LEUVEN, {"KU Leuven": []}), "last_known_institutions": []}
        records = [mit_only, leuven, yearless]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/works":
                work = {"id": "https://openalex.org/W1", "display_name": "w", "publication_year": 2020,
                        "authorships": [{"author": {"id": a["id"], "display_name": a["display_name"]}} for a in records]}
                return httpx.Response(200, json={"meta": {"count": 1}, "results": [work]})
            if request.url.path == "/authors":
                return httpx.Response(200, json={"meta": {"count": 3}, "results": records})
            return route(request)

        out = self.search(Chips(topics=[Chip(text="wind", origin="edited")]), handler)
        self.assertEqual([(h.rank, h.name_key) for h in out.hits],
                         [(1, "mit author"), (2, "leuven author"), (3, "yearless author")])
        self.assertEqual(out.hits[2].claim_ids, [self.claims(out.hits[2].person_id)[("topic", "w")].id])
        self.assertIn("Belgian affiliations none; place unknown", self.considered(out, "A3").reason)
        ids = {a: self.person(a) for a in ("A1", "A2", "A3")}
        found = {c.person_id: c for c in self.store.list_candidates(self.found.id)}
        self.assertEqual(found[ids["A2"]].rank, 1)
        self.assertEqual({a: [p.feature for p in found[p].score_parts] for a, p in ids.items()},
                         {"A1": ["openalex"], "A2": ["openalex", "belgian_years"], "A3": ["openalex"]})

    def works_handler(self, works: list[dict], records: dict[str, dict], delay: float = 0.0):
        """A handler serving the given works for every topic page and the given author records for every batch."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/works":
                return httpx.Response(200, json={"meta": {"count": len(works)}, "results": works})
            if request.url.path == "/authors":
                time.sleep(delay)
                ids = request.url.params["filter"].split(":", 1)[1].split("|")
                return httpx.Response(200, json={"meta": {"count": len(ids)}, "results": [records[i] for i in ids]})
            return route(request)
        return handler

    def topic_work(self, number: int, title: str | None, year: int | None, authors: list[dict]) -> dict:
        return {"id": f"https://openalex.org/W{number}", "display_name": title, "publication_year": year,
                "authorships": [{"author": {"id": a["id"], "display_name": a["display_name"]}} for a in authors]}

    def test_an_author_on_a_topic_work_gets_a_topic_claim_that_is_one_of_the_hit_reasons(self):
        """The claim holds the title, is dated by the year and quotes the work's record source at its offsets."""
        one = author("A1", "Ada Example", LEUVEN, {"KU Leuven": [2020]})
        work = self.topic_work(7, "Quantum routing for sample networks", 2021, [one])
        out = self.search(Chips(topics=[Chip(text="quantum", origin="edited")]), self.works_handler([work], {"A1": one}))
        (hit,) = out.hits
        topic = self.claims(hit.person_id)[("topic", "Quantum routing for sample networks")]
        self.assertEqual((topic.claim_date, topic.date_precision, topic.date_method), ("2021", "year", "record_field"))
        self.assertEqual(topic.quote, "display_name: Quantum routing for sample networks")
        self.assertEqual(hit.claim_ids[-1], topic.id)
        self.assertEqual(len(hit.claim_ids), 3)
        source = self.store.get_sources([topic.source_id])[topic.source_id]
        self.assertEqual(source.title, "OpenAlex work Quantum routing for sample networks")

    def test_a_work_without_a_year_gives_an_undated_claim_and_one_without_a_title_gives_none(self):
        """A missing title stores no claim; a missing year stores the claim without a date."""
        one = author("A1", "Ada Example", LEUVEN, {"KU Leuven": [2020]})
        works = [self.topic_work(1, "Sample work without a year", None, [one]), self.topic_work(2, None, 2020, [one])]
        out = self.search(Chips(topics=[Chip(text="quantum", origin="edited")]), self.works_handler(works, {"A1": one}))
        topics = [c for k, c in self.claims(out.hits[0].person_id).items() if k[0] == "topic"]
        self.assertEqual([(c.value, c.claim_date) for c in topics], [("Sample work without a year", None)])

    def test_five_works_give_three_claims(self):
        """Only the first 3 works seen give a topic claim."""
        one = author("A1", "Ada Example", LEUVEN, {"KU Leuven": [2020]})
        works = [self.topic_work(i, f"Sample work {i}", 2020, [one]) for i in range(5)]
        out = self.search(Chips(topics=[Chip(text="quantum", origin="edited")]), self.works_handler(works, {"A1": one}))
        topics = sorted(value for kind, value in self.claims(out.hits[0].person_id) if kind == "topic")
        self.assertEqual(topics, ["Sample work 0", "Sample work 1", "Sample work 2"])

    def test_a_work_returned_for_two_chips_gives_one_claim_and_one_reason(self):
        """The same work under two chips takes one slot: one topic claim, its id once in the hit's reasons."""
        one = author("A1", "Ada Example", LEUVEN, {"KU Leuven": [2020]})
        work = self.topic_work(7, "Quantum routing for sample networks", 2021, [one])
        chips = Chips(topics=[Chip(text="quantum", origin="edited"), Chip(text="photonics", origin="edited")])
        (hit,) = self.search(chips, self.works_handler([work], {"A1": one})).hits
        topic = self.claims(hit.person_id)[("topic", "Quantum routing for sample networks")]
        self.assertEqual(hit.claim_ids.count(topic.id), 1)
        self.assertEqual(len(set(hit.claim_ids)), len(hit.claim_ids))

    def test_an_author_found_only_through_an_institution_list_gets_no_topic_claim(self):
        """The MIT list has no works behind it, so its authors keep the affiliation and location claims only."""
        out = self.search(Chips(institutions=[Chip(text="MIT", origin="edited")]))
        self.assertTrue(out.hits)
        kinds = {kind for hit in out.hits for kind, _ in self.claims(hit.person_id)}
        self.assertNotIn("topic", kinds)

    def test_running_the_lane_twice_writes_no_new_claim(self):
        """A second search with the same chips finds every claim it needs already stored."""
        one = author("A1", "Ada Example", LEUVEN, {"KU Leuven": [2020]})
        work = self.topic_work(7, "Quantum routing for sample networks", 2021, [one])
        chips, handler = Chips(topics=[Chip(text="quantum", origin="edited")]), self.works_handler([work], {"A1": one})
        first, = self.search(chips, handler).hits
        self.assertIn(("topic", "Quantum routing for sample networks"), self.claims(first.person_id))
        count = lambda: self.store.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        before = count()
        self.search(chips, handler)
        self.assertEqual(count(), before)

    def test_six_batches_run_on_three_workers_and_keep_batch_order_in_the_records_and_the_log(self):
        """600 authors need 6 batches of 0.2 s; three workers finish in about a third of the serial 1.2 s."""
        records = {f"A{i}": author(f"A{i}", f"Author {i}", LEUVEN, {"KU Leuven": [2020]}) for i in range(600)}
        work = self.topic_work(1, "Sample work", 2020, list(records.values()))
        started = time.monotonic()
        out = self.search(Chips(topics=[Chip(text="wind", origin="edited")]), self.works_handler([work], records, 0.2))
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual([h.name_key for h in out.hits], [f"author {i}" for i in range(600)])
        (lane,) = [s for s in self.store.list_steps(self.found.id) if s.step == "lane:openalex"]
        batches = [c.request for c in self.store.list_calls(lane.id) if "ids.openalex" in c.request]
        firsts = [re.search(r"ids\.openalex(?::|%3A)(A\d+)", b).group(1) for b in batches]
        self.assertEqual(firsts, [f"A{i}" for i in range(0, 600, 100)])

    def test_place_only_chips_make_no_call(self):
        """Chips that are only a place produce no hits, no calls and say so in considered."""
        out = self.search(Chips(place=Place(text="Boston", origin="edited")), lambda r: self.fail(f"called {r.url}"))
        self.assertEqual([c.reason for c in out.considered], [openalex.NO_QUERY])

    def search_with_seed_twin(self) -> tuple[str, str]:
        """Run an MIT search where OpenAlex's 'Nick M. Vandewiele' and the seed 'Nick Vandewiele' share a card.

        Returns the seed person's id and the OpenAlex person's id.
        """
        self.settings = make_settings(self).model_copy(update={"http_mode": "live"})
        self.store = make_seeded_db(self, self.settings)
        record = author(VANDEWIELE, "Nick M. Vandewiele", MIT, {"KU Leuven": [2010, 2014], MIT["display_name"]: [2015]})

        def handler(request: httpx.Request) -> httpx.Response:
            response = route(request)
            if VANDEWIELE in request.url.params.get("filter", "") and request.url.path == "/authors":
                body = response.json()
                return httpx.Response(200, json={**body, "results": [*body["results"], record]})
            return response

        self.search(Chips(institutions=[Chip(text="MIT", origin="edited")]), handler)
        seed = self.store.conn.execute("SELECT person_id FROM person_identifiers WHERE value = ?",
                                       ("baef|nick-vandewiele|2014|",)).fetchone()[0]
        return seed, self.person(VANDEWIELE)

    def test_a_middle_initial_shares_one_flagged_card_with_the_seed_record_and_traces_by_seed_name(self):
        """OpenAlex 'Nick M. Vandewiele' and the seed 'Nick Vandewiele' stay two persons in one entry with both lanes' ranks.

        The flag names the middle initials, and a trace by the seed name or the OpenAlex id finds the OpenAlex verdict.
        """
        seed, oa = self.search_with_seed_twin()
        (card,) = [c for c in self.store.list_candidates(self.found.id) if oa in c.person_ids]
        self.assertCountEqual(card.person_ids, [seed, oa])
        self.assertEqual(set(card.lane_ranks), {"seeds", "openalex"})
        flags = {(f.person_id, f.other_person_id): f.reason for f in self.store.list_flags(self.found.id)}
        self.assertEqual(flags[(card.person_ids[0], card.person_ids[1])], resolve.SAME_BUT_INITIALS)
        for term in ("Nick Vandewiele", VANDEWIELE):
            with self.subTest(term=term):
                rows = trace_rows(self.store, self.found, term)
                (lane,) = [r for r in rows if r[1] == "lane:openalex"]
                self.assertEqual(lane[2:4], ["rank", "kept"])
                self.assertTrue([r for r in rows if r[1] == "rank" and r[2] == "rank"])

    def test_a_trace_by_person_id_finds_the_considered_row_that_comes_before_its_hit(self):
        """A key learned from a hit (the person id) also finds the lane's considered row, which is listed before the hits."""
        _, oa = self.search_with_seed_twin()
        rows = [r for r in trace_rows(self.store, self.found, oa) if r[1] == "lane:openalex"]
        self.assertEqual([r[2:4] for r in rows], [["rank", "kept"]])
        self.assertIn("found by institution", rows[0][4])

    def test_the_card_names_each_lane_that_found_a_record_with_how_it_matched(self):
        """lane_matches maps each person to its (lane, matched_on) pairs and the merged card prints one 'Found by' line each."""
        seed, oa = self.search_with_seed_twin()
        matches = lane_matches(self.store, self.found.id)
        self.assertEqual([lane for lane, _ in matches[seed]], ["seeds"])
        self.assertEqual([lane for lane, _ in matches[oa]], ["openalex"])
        html = cards(self.store, self.found)
        for person_id in (seed, oa):
            lane, how = matches[person_id][0]
            self.assertIn(f"Found by {lane}: {escape(how)}", html)

    def test_an_author_outside_the_radius_ranks_below_one_inside_and_the_hit_names_the_distance(self):
        """Place orders first: a Leuven author seen first and on two works ranks below a Cambridge author on one, for Boston."""
        far = author("A1", "Far Author", LEUVEN, {"KU Leuven": [2020]})
        near = author("A2", "Near Author", MIT, {"KU Leuven": [2010], MIT["display_name"]: [2020]})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/works":
                works = [{"id": f"https://openalex.org/W{i}", "display_name": "w", "publication_year": 2020,
                          "authorships": [{"author": {"id": a["id"], "display_name": a["display_name"]}} for a in team]}
                         for i, team in enumerate([[far], [far, near]])]
                return httpx.Response(200, json={"meta": {"count": 2}, "results": works})
            if request.url.path == "/authors":
                return httpx.Response(200, json={"meta": {"count": 2}, "results": [far, near]})
            return route(request)

        out = self.search(Chips(topics=[Chip(text="wind", origin="edited")],
                                place=Place(text="Boston", origin="edited", kind="metro")), handler)
        self.assertEqual([h.score for h in out.hits], [1, 2])
        self.assertEqual([self.considered(out, a).reason.split(",")[0] for a in ("A2", "A1")], ["rank 1", "rank 2"])
        self.assertIn("km from Boston, US (inside the radius)", out.hits[0].matched_on)
        self.assertIn("last known KU Leuven, Leuven", out.hits[1].matched_on)
        self.assertIn("(outside the radius)", out.hits[1].matched_on)


if __name__ == "__main__":
    unittest.main()
