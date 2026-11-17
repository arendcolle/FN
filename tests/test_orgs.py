import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

import httpx

from fn import db, net, orgjob, orgs, search, seedload
from fn.contracts import (
    REGISTRY_ID,
    Chip,
    Chips,
    ClaimDraft,
    Identifier,
    LaneHit,
    LaneOut,
    OrgFacts,
    OrgMatchIn,
    OrgMatchOut,
    Place,
    PlacesOut,
    RankOut,
    Search,
    Source,
    page_source,
    record_source,
)
from fn.steps import StepContext, run_step
from fn.store import Store
from fn.web.debug import debug_search_page
from fn.worker import Worker, new_id, now
from tests.helpers import (
    FIXTURES,
    StubHttp,
    StubLLM,
    make_db,
    make_settings,
    recorded_orgs,
    save_recorded_orgs,
)

ROWS = [json.loads(line) for path in sorted(seedload.SEEDS.glob("*.jsonl")) for line in path.read_text().splitlines()]
VUB, ULB, KU_LEUVEN, KVAB = "ror:006e5kg04", "ror:01r9htc13", "ror:05f950310", "wikidata:Q1301699"


class AliasTest(unittest.TestCase):
    def test_every_alias_resolves_to_an_id_in_the_files_form(self):
        """Each alias, and each seed list's organization, resolves to a ror:<id> or wikidata:<Q> id."""
        rows = list(csv.DictReader(orgs.ALIASES.read_text(encoding="utf-8").splitlines()))
        self.assertGreater(len(rows), 100)
        for row in rows:
            with self.subTest(alias=row["alias"]):
                self.assertRegex(orgs.org_id(row["alias"]), REGISTRY_ID)
                self.assertEqual(orgs.org_id(row["alias"]), row["org_id"])
        for name, (_, org_name) in seedload.LISTS.items():
            with self.subTest(seed_list=name):
                self.assertRegex(orgs.org_id(org_name) or "", REGISTRY_ID)
        self.assertEqual(len(orgs.ids()), len(set(orgs.ids())))

    def test_names_and_ref_come_from_the_alias_file(self):
        """names lists every spelling of an org in file order; ref is the org id for a ROR org and None otherwise."""
        self.assertEqual(orgs.names(orgs.org_id("mit")), ["MIT", "M.I.T.", "Massachusetts Institute of Technology"])
        self.assertEqual(orgs.ref("M.I.T."), "ror:042nb2s44")
        self.assertEqual((orgs.names(None), orgs.ref("Nowhere"), orgs.org_id("Nowhere")), ([], None, None))
        self.assertEqual((orgs.org_id("KVAB"), orgs.ref("KVAB")), (KVAB, None))

    def test_every_frequent_seed_institution_is_mapped_or_listed_unmapped(self):
        """Each institution string on 5 or more seed rows is in the alias file or on the unmapped list, never both."""
        counts = Counter(inst["name"] for row in ROWS for inst in row["institutions"])
        frequent = [name for name, n in counts.items() if n >= 5]
        self.assertGreater(len(frequent), 80)
        for name in frequent:
            with self.subTest(name=name):
                self.assertNotEqual(orgs.org_id(name) is not None, orgs.fold(name) in orgs.unmapped())


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = Store(self.settings.db_path)
        self.addCleanup(self.store.close)

    def migrate_to(self, version: int) -> None:
        """Apply the migrations up to version, from a copy of those files."""
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        for path in db.MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"):
            if int(path.name[:3]) <= version:
                shutil.copy(path, directory)
        with mock.patch.object(db, "MIGRATIONS", directory):
            self.store.migrate()

    def test_002_rewrites_old_org_ids_and_empties_unknown_ones(self):
        """Old internal ids become their ROR or Wikidata ids, an unknown old id becomes empty, others stay as they are."""
        self.migrate_to(1)
        conn = self.store.conn
        conn.execute("INSERT INTO persons VALUES ('p1', 'An Example', 'an example', 'candidate', NULL)")
        conn.execute("INSERT INTO sources (id, kind, url, text, content_hash, normalize_version)"
                     " VALUES ('s1', 'seed_page', 'https://example.org', 'text', 'h', 1)")
        given = {"vub": "ror:006e5kg04", "kvab": "wikidata:Q1301699", "belgium": "wikidata:Q31", "acme": None,
                 None: None, "ror:042nb2s44": "ror:042nb2s44"}
        for i, org in enumerate(given):
            conn.execute("INSERT INTO claims (id, person_id, kind, org_id, value, quote, quote_start, quote_end, source_id)"
                         " VALUES (?, 'p1', 'affiliation', ?, ?, 'text', 0, 4, 's1')", (f"c{i}", org, f"v{i}"))
        self.migrate_to(2)
        found = dict(conn.execute("SELECT id, org_id FROM claims").fetchall())
        self.assertEqual({org: found[f"c{i}"] for i, org in enumerate(given)}, given)

    def test_005_gives_stored_claims_no_years_until_a_rerun_stores_them(self):
        """A claim row from before 005 reads back with years [], and upserting the same claim again fills its years."""
        self.migrate_to(4)
        text = "ULB 2012, 2023"
        source = Source(id="s1", kind="record", url="https://example.org", text=text, content_hash="h")
        conn = self.store.conn
        conn.execute("INSERT INTO persons VALUES ('p1', 'An Example', 'an example', 'candidate', NULL)")
        conn.execute("INSERT INTO sources (id, kind, url, text, content_hash, normalize_version)"
                     " VALUES ('s1', 'record', 'https://example.org', ?, 'h', 1)", (text,))
        claim_id = hashlib.sha1("\0".join(["p1", "affiliation", "ULB", "s1", "0"]).encode()).hexdigest()
        conn.execute("INSERT INTO claims (id, person_id, kind, value, quote, quote_start, quote_end, source_id)"
                     " VALUES (?, 'p1', 'affiliation', 'ULB', ?, 0, ?, 's1')", (claim_id, text, len(text)))
        self.store.migrate()
        self.assertEqual([(c.id, c.years) for c in self.store.claims_of(["p1"])], [(claim_id, [])])
        self.store.upsert_claim(ClaimDraft(person_id="p1", kind="affiliation", value="ULB", quote=text, quote_start=0,
                                           quote_end=len(text), source=source, years=[2012, 2023]))
        self.assertEqual([(c.id, c.years) for c in self.store.claims_of(["p1"])], [(claim_id, [2012, 2023])])

    def test_003_rewrites_full_url_chip_refs_to_ror_ids(self):
        """A search stored with a ror:https://ror.org/<id> chip ref reads back as ror:<id>; other refs are kept."""
        self.migrate_to(2)
        chips = Chips(institutions=[Chip(text="MIT", origin="parsed", ref="ror:https://ror.org/042nb2s44"),
                                    Chip(text="Acme", origin="edited", ref="ror:2")])
        self.store.create_search(Search(id="s1", question="q", chips=chips, status="done", created_at=datetime.now(UTC),
                                        code_sha=None, dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        self.store.migrate()
        self.assertEqual([c.ref for c in self.store.get_search("s1").chips.institutions], ["ror:042nb2s44", "ror:2"])


class WikidataTest(unittest.TestCase):
    def test_ranked_values_put_preferred_first_and_skip_deprecated_and_empty_statements(self):
        """A preferred statement comes before a normal one; deprecated and no-value statements are left out."""
        def statement(rank: str, value: str | None) -> dict:
            snak = {"datavalue": {"value": {"id": value}}} if value else {"snaktype": "somevalue"}
            return {"rank": rank, "mainsnak": snak}

        body = {"claims": {"P17": [statement("normal", "Q1"), statement("deprecated", "Q2"), statement("preferred", "Q3"),
                                   statement("preferred", None)]}}
        self.assertEqual([v["id"] for v in orgs.ranked_values(body, "P17")], ["Q3", "Q1"])


class FnOrgsTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)

    def test_recorded_responses_give_vub_ulb_kvab_facts_each_with_its_source(self):
        """VUB is BE/BRU/nl and ULB BE/BRU/fr from ROR, KVAB is BE from Wikidata; every alias-file id gets a row."""
        job = save_recorded_orgs(self.store, self.settings)
        self.assertEqual((job.kind, job.question, job.status), ("job", "fn-orgs", "done"))
        found = self.store.get_orgs(orgs.ids())
        self.assertEqual(set(found), set(orgs.ids()))
        facts = {o: (found[o].country_code, found[o].region, found[o].name_lang) for o in (VUB, ULB, KU_LEUVEN, KVAB)}
        self.assertEqual(facts, {VUB: ("BE", "BRU", "nl"), ULB: ("BE", "BRU", "fr"), KU_LEUVEN: ("BE", "VLG", "nl"),
                                 KVAB: ("BE", None, None)})
        sources = self.store.get_sources([found[VUB].source_id, found[KVAB].source_id])
        vub, kvab = sources[found[VUB].source_id], sources[found[KVAB].source_id]
        self.assertEqual((vub.kind, vub.url), ("record", "https://ror.org/006e5kg04"))
        self.assertIn("locations.0.geonames_details.country_subdivision_code: BRU", vub.text)
        self.assertEqual(kvab.url, "https://www.wikidata.org/wiki/Q1301699")
        self.assertIn("claims.P17: Q31\nclaims.P17.P297: BE", kvab.text)

    def test_calls_are_recorded_under_the_job_which_stays_off_the_searches_list(self):
        """The job has one orgs step holding every ROR and Wikidata call; its debug page lists them; / does not list it."""
        job = save_recorded_orgs(self.store, self.settings)
        (step,) = self.store.list_steps(job.id)
        calls = self.store.list_calls(step.id)
        wikidata = [o for o in orgs.ids() if o.startswith("wikidata:")]
        self.assertEqual((step.step, step.status, len(calls)), ("orgs", "ok", len(orgs.ids()) + 2 * len(wikidata)))
        self.assertEqual({c.status for c in calls}, {200})
        self.assertIn(f"GET {orgs.ROR_API}/006e5kg04", [c.request for c in calls])
        self.assertIn(f"{len(calls)} calls", debug_search_page(self.store, job))
        self.assertEqual(self.store.list_searches(10), [])

    def test_an_id_ror_or_wikidata_does_not_know_stops_the_job_and_names_it(self):
        """A 404 from ROR or a missing Wikidata item fails the orgs step with the org id; orgs before it stay saved."""
        def ror_404(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404) if request.url.path.endswith("/006e5kg04") else recorded_orgs(request)

        def kvab_missing(request: httpx.Request) -> httpx.Response:
            if request.url.params.get("ids") == "Q1301699":
                return httpx.Response(200, json={"entities": {"Q1301699": {"id": "Q1301699", "missing": ""}}})
            return recorded_orgs(request)

        def vub_not_json(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>") if request.url.path.endswith("/006e5kg04") else recorded_orgs(request)

        for handler, org, expected in ((ror_404, VUB, "returned 404"), (kvab_missing, KVAB, "no such item"),
                                       (vub_not_json, VUB, "unexpected answer, JSONDecodeError")):
            with self.subTest(org=org), self.assertLogs("fn.worker", "ERROR"):
                job = save_recorded_orgs(self.store, self.settings, handler)
                (step,) = self.store.list_steps(job.id)
                self.assertEqual((job.status, step.status, step.error_type), ("failed", "error", "OrgError"))
                self.assertTrue(step.error_message.startswith(f"{org}: "), step.error_message)
                self.assertIn(expected, step.error_message)
        self.assertIn(KU_LEUVEN, self.store.get_orgs([KU_LEUVEN]))

    def test_a_record_of_another_org_stops_the_job_and_names_both_ids(self):
        """ROR answering ULB's id with VUB's record fails the orgs step, naming the id asked for and the one received."""
        def wrong_record(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/01r9htc13"):
                return httpx.Response(200, content=(FIXTURES / "http" / "ror" / "006e5kg04.json").read_bytes())
            return recorded_orgs(request)

        with self.assertLogs("fn.worker", "ERROR"):
            job = save_recorded_orgs(self.store, self.settings, wrong_record)
        (step,) = self.store.list_steps(job.id)
        self.assertEqual((job.status, step.error_type), ("failed", "OrgError"))
        self.assertEqual(step.error_message, f"{ULB}: the record fetched is {VUB}")

    def test_a_lane_save_keeps_a_stored_row_and_an_fn_orgs_save_replaces_it(self):
        """save with replace=False leaves a stored org as it is; replace=True overwrites it with the new source."""
        at = datetime(2026, 11, 2, tzinfo=UTC)
        first, _ = record_source("https://ror.org/006e5kg04", "first", [("id", "a")], {}, at)
        second, _ = record_source("https://openalex.org/I1", "second", [("id", "b")], {}, at)
        orgs.save(self.store, [OrgFacts(id=VUB, name="VUB", country_code="BE", region="BRU")], first, replace=True)
        orgs.save(self.store, [OrgFacts(id=VUB, name="Vrije", country_code="BE")], second, replace=False)
        self.assertEqual((self.store.get_orgs([VUB])[VUB].region, self.store.get_orgs([VUB])[VUB].source_id),
                         ("BRU", first.id))
        orgs.save(self.store, [OrgFacts(id=VUB, name="Vrije", country_code="BE")], second, replace=True)
        stored = self.store.get_orgs([VUB])[VUB]
        self.assertEqual((stored.name, stored.region, stored.source_id), ("Vrije", None, second.id))


NOW = datetime(2026, 11, 2, tzinfo=UTC)


def institution_source(inst: dict) -> Source:
    """The record Source the OpenAlex lane stores for an institution record."""
    geo = inst.get("geo") or {}
    fields = [("id", inst["id"]), ("display_name", inst["display_name"]), ("ror", inst.get("ror")),
              *((f"geo.{p}", geo.get(p)) for p in ("city", "region", "country", "latitude", "longitude"))]
    return record_source(inst["id"], f"OpenAlex institution {inst['display_name']}", fields, inst, NOW)[0]


class OrgPlacesTest(unittest.TestCase):
    def setUp(self):
        self.store = make_db(self)

    def put(self, org: str, **place) -> None:
        source, _ = record_source(f"https://example.org/{org}", "org", [("id", org)], {}, NOW)
        orgs.save(self.store, [OrgFacts(id=org, name="Example Institute", **place)], source, replace=False)

    def test_a_ror_record_gives_the_city_and_coordinates_of_its_first_location_and_lists_them_in_its_source(self):
        record = json.loads((FIXTURES / "http" / "ror" / "006e5kg04.json").read_text())
        facts, source = orgs.ror_record(record, NOW)
        self.assertEqual((facts.city, facts.lat, facts.lon), ("Brussels", 50.85045, 4.34878))
        self.assertIn("locations.0.geonames_details.name: Brussels", source.text)
        self.assertIn("locations.0.geonames_details.lat: 50.85045", source.text)
        self.assertIn("locations.0.geonames_details.lng: 4.34878", source.text)
        bare = {k: v for k, v in record.items() if k != "locations"}
        self.assertEqual(
            [getattr(orgs.ror_record(bare, NOW)[0], f) for f in ("city", "lat", "lon")], [None, None, None])

    def test_a_lane_save_fills_an_empty_city_and_never_overwrites_a_set_one(self):
        """upsert_org(replace=False) gives a row without a city the new one; a stored city stays."""
        self.put("ror:0aaaaaa11")
        self.put("ror:0aaaaaa11", city="Ghent", lat=51.05, lon=3.72)
        self.put("ror:0aaaaaa11", city="Leuven", lat=50.88, lon=4.7)
        stored = self.store.get_orgs(["ror:0aaaaaa11"])["ror:0aaaaaa11"]
        self.assertEqual((stored.city, stored.lat, stored.lon), ("Ghent", 51.05, 3.72))

    def test_backfill_fills_orgs_from_stored_institution_records_skips_the_rest_and_a_second_run_fills_none(self):
        """A ROR-keyed and an OpenAlex-keyed institution fill their orgs; an org with a city or not stored is skipped."""
        ghent = {"id": "https://openalex.org/I1", "display_name": "Example One", "ror": "https://ror.org/0aaaaaa11",
                 "geo": {"city": "Ghent", "latitude": 51.05, "longitude": 3.72}}
        leuven = {"id": "https://openalex.org/I2", "display_name": "Example Two",
                  "geo": {"city": "Leuven", "latitude": 50.88, "longitude": 4.7}}
        kept = {"id": "https://openalex.org/I3", "display_name": "Example Three", "ror": "https://ror.org/0cccccc11",
                "geo": {"city": "Mons", "latitude": 50.45, "longitude": 3.95}}
        unstored = {"id": "https://openalex.org/I4", "display_name": "Example Four", "ror": "https://ror.org/0dddddd11",
                    "geo": {"city": "Namur", "latitude": 50.47, "longitude": 4.87}}
        nogeo = {"id": "https://openalex.org/I5", "display_name": "Example Five", "ror": "https://ror.org/0eeeeee11"}
        for org in ("ror:0aaaaaa11", "openalex:I2", "ror:0eeeeee11"):
            self.put(org)
        self.put("ror:0cccccc11", city="Liege", lat=50.63, lon=5.57)
        for inst in (ghent, leuven, kept, unstored, nogeo):
            self.store.upsert_source(institution_source(inst))
        self.assertEqual(orgs.backfill_places(self.store), 2)
        found = self.store.get_orgs(["ror:0aaaaaa11", "openalex:I2", "ror:0cccccc11", "ror:0dddddd11", "ror:0eeeeee11"])
        self.assertEqual({k: (o.city, o.lat, o.lon) for k, o in found.items()},
                         {"ror:0aaaaaa11": ("Ghent", 51.05, 3.72), "openalex:I2": ("Leuven", 50.88, 4.7),
                          "ror:0cccccc11": ("Liege", 50.63, 5.57), "ror:0eeeeee11": (None, None, None)})
        self.assertEqual(orgs.backfill_places(self.store), 0)

    def test_the_places_job_fills_cities_and_locates_stored_place_claims_in_one_recorded_step(self):
        """fn-orgs --places is a job with a places step whose output counts the orgs and the claims it filled."""
        settings = make_settings(self)
        self.store = make_db(self, settings)
        self.put("openalex:I2")
        self.store.upsert_source(institution_source({"id": "https://openalex.org/I2", "display_name": "Example Two",
                                                     "geo": {"city": "Leuven", "latitude": 50.88, "longitude": 4.7}}))
        page = page_source("https://example.org/p", "Page", "Wim Doe lives in Cambridge, Massachusetts.", {}, NOW, None)
        person = self.store.resolve_person([Identifier(scheme="mention", value="m1")], "Wim Doe")
        claim = self.store.upsert_claim(ClaimDraft(person_id=person.id, kind="location", relation="lives_in",
                                                   value="Cambridge, Massachusetts", quote="Cambridge, Massachusetts",
                                                   quote_start=17, quote_end=41, source=page))
        job = orgjob.fill_places(self.store, settings, StubHttp())
        (step,) = self.store.list_steps(job.id)
        self.assertEqual((job.status, step.step, step.status), ("done", "places", "ok"))
        self.assertEqual(PlacesOut.model_validate_json(self.store.get_payload(step.id)[1]), PlacesOut(orgs=1, claims=1))
        self.assertAlmostEqual(self.store.get_claim(claim.id).lat, 42.38, places=1)


class OrgPlacesMigrationTest(MigrationTest):
    def test_008_reads_an_old_org_row_back_with_empty_places(self):
        """A database at schema version 7 with an org keeps it, and the row reads back without city, lat and lon."""
        self.migrate_to(7)
        conn = self.store.conn
        conn.execute("INSERT INTO sources (id, kind, url, text, content_hash, normalize_version)"
                     " VALUES ('s1', 'record', 'https://example.org', 'text', 'h', 1)")
        conn.execute("INSERT INTO orgs (id, name, country_code, source_id, fetched_at)"
                     " VALUES ('ror:0aaaaaa11', 'Example Institute', 'BE', 's1', '2026-11-02T00:00:00+00:00')")
        self.assertEqual(self.store.migrate(), [8, 9, 10, 11, 12, 13, 14])
        old = self.store.get_orgs(["ror:0aaaaaa11"])["ror:0aaaaaa11"]
        self.assertEqual((old.name, old.country_code, old.city, old.lat, old.lon), ("Example Institute", "BE", None, None, None))


INBO = "Research Institute for Nature and Forest"
AGRICULTURE = "Research Institute for Agriculture"
ROR_ANSWERS = FIXTURES / "http" / "ror-affiliation"


class NamedTest(unittest.TestCase):
    def test_named_is_false_for_an_empty_name_and_for_a_record_without_names(self):
        """Nothing stands in an empty or punctuation-only employer text, and a record with no names names nothing."""
        record = {"names": [{"types": ["ror_display"], "value": "Example University"}]}
        self.assertEqual((orgs.named(record, ""), orgs.named(record, "-- . --"), orgs.named({}, "Example University"),
                          orgs.named({"names": []}, "Example University")), (False,) * 4)
        self.assertTrue(orgs.named(record, "Example U"))

    def test_a_one_word_employer_text_must_hold_a_whole_name(self):
        """One generic word such as "University" stands inside many names, so it names no organization on its own."""
        record = {"names": [{"types": ["ror_display"], "value": "Example University"},
                            {"types": ["alias"], "value": "Exuni"}]}
        self.assertEqual((orgs.named(record, "University"), orgs.named(record, "Exuni")), (False, True))


class Routed:
    """An HTTP client that sends ROR calls to a mock transport and every other call to StubHttp."""

    def __init__(self, ror: net.Client):
        self.ror, self.other = ror, StubHttp()

    def get(self, url, params=None, **options):
        return (self.ror if url == orgs.ROR_API else self.other).get(url, params, **options)

    def __getattr__(self, name):
        return getattr(self.other, name)


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.person = self.store.resolve_person([Identifier(scheme="mention", value="m1")], "Wim Doe")
        self.asked: list[str] = []
        self.answers = {INBO: (200, (ROR_ANSWERS / "inbo.json").read_bytes()),
                        AGRICULTURE: (200, (ROR_ANSWERS / "agriculture.json").read_bytes())}

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.params["affiliation"]
        self.assertEqual(request.url.params["single_search"], "")
        self.asked.append(name)
        known = {orgs.fold(k): v for k, v in self.answers.items()}
        status, content = known.get(orgs.fold(name), (200, b'{"items": []}'))
        return httpx.Response(status, content=content, headers={"Retry-After": "300"} if status == 429 else {})

    def claim(self, value: str, relation: str = "works_at", date: str | None = "2025"):
        text = f"Wim Doe works at {value.strip()}."
        page = page_source(f"https://example.org/{hashlib.sha1((value + relation).encode()).hexdigest()}", "Page", text,
                           {}, NOW, None)
        quote = value.strip()
        start = text.index(quote)
        return self.store.upsert_claim(ClaimDraft(person_id=self.person.id, kind="affiliation", relation=relation,
                                                  value=value, quote=quote, quote_start=start, quote_end=start + len(quote),
                                                  source=page, claim_date=date))

    def run_match(self) -> tuple[Search, OrgMatchOut | None]:
        client = net.Client(self.settings.model_copy(update={"http_mode": "live"}), httpx.MockTransport(self.handler))
        worker = Worker(self.store, self.settings, llm=None, http=client)
        self.addCleanup(worker.shutdown)
        job = worker.execute(worker.create_search(orgjob.MATCH_JOB, kind="job").id,
                             lambda ctx, _: run_step(ctx, "match", orgs.match, OrgMatchIn(pace_s=0)))
        step = self.store.list_steps(job.id)[-1]
        return job, (OrgMatchOut.model_validate_json(self.store.get_payload(step.id)[1]) if step.status == "ok" else None)

    def org_of(self, *claims) -> list[str | None]:
        return [self.store.get_claim(c.id).org_id for c in claims]

    def test_one_call_stores_the_org_with_its_place_and_links_the_claims_of_all_spellings(self):
        """A name in three spellings is asked once; its claims get the chosen org, stored with city and coordinates."""
        claims = [self.claim(INBO), self.claim(INBO.upper()), self.claim(f"  {INBO.lower()}  ", "worked_at")]
        job, out = self.run_match()
        self.assertEqual((job.status, [orgs.fold(n) for n in self.asked]), ("done", [orgs.fold(INBO)]))
        self.assertEqual(out, OrgMatchOut(asked=1, chosen=1, linked=3, failed=0))
        self.assertEqual(self.org_of(*claims), ["ror:00j54wy13"] * 3)
        org = self.store.get_orgs(["ror:00j54wy13"])["ror:00j54wy13"]
        self.assertEqual((org.country_code, org.city, org.lat, org.lon), ("BE", "Brussels", 50.85045, 4.34878))

    def test_no_chosen_item_stores_a_null_answer_and_a_second_run_makes_no_call(self):
        """The agriculture answer has a first item at 0.95 that is not chosen: nothing links, and the name is not asked again."""
        claim = self.claim(AGRICULTURE)
        _, out = self.run_match()
        self.assertEqual((out, self.org_of(claim)), (OrgMatchOut(asked=1, chosen=0, linked=0, failed=0), [None]))
        self.assertEqual(self.store.org_answers(), {orgs.fold(AGRICULTURE): None})
        self.assertEqual(self.run_match()[1], OrgMatchOut(asked=0, chosen=0, linked=0, failed=0))
        self.assertEqual(self.asked, [AGRICULTURE])

    def test_a_new_claim_of_a_remembered_name_is_linked_by_a_rerun_without_a_call(self):
        """The stored answer links a claim added after the first run, and a rejected claim of the name too."""
        self.claim(INBO)
        self.run_match()
        later = self.claim(INBO, "affiliated_with")
        rejected = self.claim(INBO, "studied_at")
        self.store.conn.execute("UPDATE claims SET rejected_at = '2026-11-03' WHERE id = ?", (rejected.id,))
        _, out = self.run_match()
        self.assertEqual((out.asked, out.linked, self.asked), (0, 2, [INBO]))
        self.assertEqual(self.org_of(later, rejected), ["ror:00j54wy13"] * 2)

    def test_an_unmapped_a_one_letter_and_a_long_name_make_no_call(self):
        """A name in the unmapped file, one with under three letters and one over 200 characters are not asked or stored."""
        for value in (next(iter(orgs.unmapped())), "X", "-- 7 --", "Lab " * 75):
            self.claim(value)
        job, out = self.run_match()
        self.assertEqual((job.status, out, self.asked, self.store.org_answers()),
                         ("done", OrgMatchOut(asked=0, chosen=0, linked=0, failed=0), [], {}))

    def test_two_chosen_items_link_nothing_and_a_record_without_locations_links_and_gives_no_place(self):
        """Two chosen items are no match; one chosen record without locations links its claims to an org with no city."""
        item = json.loads((ROR_ANSWERS / "inbo.json").read_text())["items"][0]
        bare = {**item, "organization": {k: v for k, v in item["organization"].items() if k != "locations"}}
        other = {**item, "organization": {**item["organization"], "id": "https://ror.org/0aaaaaa11"}}
        self.answers = {"Two Place": (200, json.dumps({"items": [item, other]}).encode()),
                        INBO: (200, json.dumps({"items": [bare]}).encode())}
        both, nowhere = self.claim("Two Place"), self.claim(INBO)
        _, out = self.run_match()
        self.assertEqual((out.chosen, out.linked), (1, 1))
        self.assertEqual(self.org_of(both, nowhere), [None, "ror:00j54wy13"])
        org = self.store.get_orgs(["ror:00j54wy13"])["ror:00j54wy13"]
        self.assertEqual((org.city, org.lat, org.lon), (None, None, None))

    def answer_with(self, employer: str, *names: tuple[str, str]) -> None:
        """Make the answer for the employer text one chosen organization that goes by the given (type, value) names."""
        item = json.loads((ROR_ANSWERS / "inbo.json").read_text())["items"][0]
        record = {**item["organization"], "names": [{"lang": None, "types": [t], "value": v} for t, v in names]}
        self.answers = {employer: (200, json.dumps({"items": [{**item, "organization": record}]}).encode())}

    def test_a_chosen_organization_none_of_whose_names_stands_in_the_employer_is_not_linked(self):
        """The name is stored as asked with no organization, so a second run makes no call."""
        self.answer_with("Sample Medical School", ("ror_display", "Example Technology Institute"))
        claim = self.claim("Sample Medical School")
        _, out = self.run_match()
        self.assertEqual((out.chosen, self.org_of(claim)), (0, [None]))
        self.assertEqual(self.store.org_answers(), {orgs.fold("Sample Medical School"): None})
        self.assertEqual(self.run_match()[1].asked, 0)

    def test_a_chosen_organization_is_linked_when_a_name_stands_in_the_employer_or_the_other_way_round(self):
        """A display name inside a longer text, an alias equal to the text, the text inside the name, "U." for University."""
        cases = [("Example University Department of Physics", [("ror_display", "Example University")]),
                 ("CalExample", [("ror_display", "Example Institute of Technology"), ("alias", "CalExample")]),
                 ("Example Institute", [("ror_display", "Example Institute of Technology")]),
                 ("Example U. Graduate School", [("ror_display", "Example University")])]
        for employer, names in cases:
            with self.subTest(employer=employer):
                self.answer_with(employer, *names)
                claim = self.claim(employer)
                self.assertEqual(self.run_match()[1].linked, 1)
                self.assertEqual(self.org_of(claim), ["ror:00j54wy13"])

    def test_a_two_letter_acronym_alone_is_no_match_and_a_four_letter_acronym_is(self):
        """The acronym "EX" in the employer text does not link the organization; "EXAM" does."""
        self.answer_with("EX Group", ("ror_display", "Sample Foundation"), ("acronym", "EX"))
        short = self.claim("EX Group")
        self.assertEqual((self.run_match()[1].chosen, self.org_of(short)), (0, [None]))
        self.answer_with("EXAM Group", ("ror_display", "Sample Foundation"), ("acronym", "EXAM"))
        long = self.claim("EXAM Group")
        self.assertEqual((self.run_match()[1].chosen, self.org_of(long)), (1, ["ror:00j54wy13"]))

    def test_a_stored_org_keeps_its_city(self):
        """When the org is stored with a city, a match of the name leaves that city alone."""
        source, _ = record_source("https://example.org/inbo", "org", [("id", "x")], {}, NOW)
        orgs.save(self.store, [OrgFacts(id="ror:00j54wy13", name="Research Institute", city="Leuven", lat=50.88, lon=4.7)],
                  source, replace=False)
        self.claim(INBO)
        self.run_match()
        org = self.store.get_orgs(["ror:00j54wy13"])["ror:00j54wy13"]
        self.assertEqual((org.city, org.lat, org.lon), ("Leuven", 50.88, 4.7))

    def test_a_429_over_30_seconds_fails_the_step_naming_the_name_and_a_rerun_asks_only_the_rest(self):
        """Names are asked in key order; the 429 stops the run at its name, earlier answers stay, the rerun skips them."""
        first, limited, last = self.claim(AGRICULTURE), self.claim("Zed Limited Lab"), self.claim("Zzz Lab")
        self.answers["Zed Limited Lab"] = (429, b"slow down")
        with self.assertLogs("fn.worker", "ERROR"):
            job, out = self.run_match()
        step = self.store.list_steps(job.id)[-1]
        self.assertEqual((job.status, step.status, out), ("failed", "error", None))
        self.assertIn("'Zed Limited Lab'", step.error_message)
        self.assertEqual(self.asked, [AGRICULTURE, "Zed Limited Lab"])
        self.assertEqual(self.store.org_answers(), {orgs.fold(AGRICULTURE): None})
        self.answers["Zed Limited Lab"] = (200, b'{"items": []}')
        self.asked.clear()
        self.run_match()
        self.assertEqual(self.asked, ["Zed Limited Lab", "Zzz Lab"])
        self.assertEqual(self.org_of(first, limited, last), [None, None, None])

    def test_a_400_adds_to_failed_is_not_stored_and_the_next_name_is_asked(self):
        """A 400 and an answer that is not JSON each count as failed and store nothing; the run goes on to INBO."""
        bad, text, good = self.claim("Aa Bad Lab"), self.claim("Ab Text Lab"), self.claim(INBO)
        self.answers["Aa Bad Lab"] = (400, b'{"errors": ["bad"]}')
        self.answers["Ab Text Lab"] = (200, b"<html>")
        job, out = self.run_match()
        self.assertEqual((job.status, out), ("done", OrgMatchOut(asked=3, chosen=1, linked=1, failed=2)))
        self.assertEqual(self.org_of(bad, text, good), [None, None, "ror:00j54wy13"])
        self.assertEqual(list(self.store.org_answers()), [orgs.fold(INBO)])

    def test_a_seed_load_after_a_match_keeps_the_link_and_a_second_load_writes_nothing(self):
        """A claim linked by a match keeps its org when the seed rows load again, and that load changes no row."""
        seedload.load(self.store)
        (claim_id, _), *_ = self.store.unlinked_affiliations(orgs.MATCH_RELATIONS)
        self.assertEqual(self.store.link_claims([claim_id], "ror:00j54wy13"), 1)
        before = self.store.conn.total_changes
        seedload.load(self.store)
        self.assertEqual(self.store.conn.total_changes - before, 0)
        self.assertEqual(self.store.get_claim(claim_id).org_id, "ror:00j54wy13")

    def test_a_match_moves_a_person_with_an_employer_in_belgium_from_unknown_to_abroad_in_a_us_search(self):
        """The saved fit's place is unknown while the employer has no org, and abroad after the match and a rerank."""
        self.claim(INBO)
        person = self.person

        def run(ctx, inp):
            hit = LaneHit(person_id=person.id, name_key=person.name_key, lane="seeds", rank=1, score=1.0, matched_on="wind")
            return LaneOut(lane="seeds", query="wind", total_seen=1, hits=[hit])

        chips = Chips(topics=[Chip(text="wind", origin="edited")],
                      place=Place(text="the US", origin="edited", kind="anywhere_us"), version=2)
        worker = Worker(self.store, self.settings, llm=StubLLM(), http=StubHttp())
        self.addCleanup(worker.shutdown)
        search_id = worker.create_search("Who knows wind?", chips, "edited").id
        with mock.patch("fn.search.LANES", [SimpleNamespace(name="seeds", run=run)]):
            worker.execute(search_id)
        (before,) = self.store.list_candidates(search_id)
        self.run_match()
        ctx = StepContext(search_id=search_id, store=self.store, llm=None, http=None, now=now, new_id=new_id,
                          log=mock.Mock(), settings=self.settings)
        search.refinish(ctx, self.store.get_search(search_id))
        (after,) = self.store.list_candidates(search_id)
        self.assertEqual((before.fit.place, after.fit.place), ("unknown", "abroad"))

    def person_named(self, name: str):
        return self.store.resolve_person([Identifier(scheme="mention", value=name)], name)

    def claim_of(self, person, value: str, relation: str = "works_at", date: str | None = "2025"):
        text = f"{person.display_name} works at {value}."
        page = page_source(f"https://example.org/{hashlib.sha1((person.id + value + relation).encode()).hexdigest()}",
                           "Page", text, {}, NOW, None)
        start = text.index(value)
        return self.store.upsert_claim(ClaimDraft(person_id=person.id, kind="affiliation", relation=relation, value=value,
                                                  quote=value, quote_start=start, quote_end=start + len(value),
                                                  source=page, claim_date=date))

    def match_for(self, **fields) -> OrgMatchOut:
        client = net.Client(self.settings.model_copy(update={"http_mode": "live"}), httpx.MockTransport(self.handler))
        worker = Worker(self.store, self.settings, llm=None, http=client)
        self.addCleanup(worker.shutdown)
        job = worker.execute(worker.create_search(orgjob.MATCH_JOB, kind="job").id,
                             lambda ctx, _: run_step(ctx, "match", orgs.match, OrgMatchIn(pace_s=0, **fields)))
        return OrgMatchOut.model_validate_json(self.store.get_payload(self.store.list_steps(job.id)[-1].id)[1])

    def routed(self) -> Routed:
        client = net.Client(self.settings.model_copy(update={"http_mode": "live"}), httpx.MockTransport(self.handler))
        return Routed(client)

    def search_with(self, lanes: dict[str, tuple[object, int]], http, version: int = 2) -> str:
        """Run a search whose fake lanes each hit one person at a rank; returns the search id."""
        def lane(name, person, rank):
            def run(ctx, inp):
                hit = LaneHit(person_id=person.id, name_key=person.name_key, lane=name, rank=rank, score=1.0, matched_on="x")
                return LaneOut(lane=name, query="x", total_seen=1, hits=[hit])
            return SimpleNamespace(name=name, run=run)

        place = Place(text="the US", origin="edited", kind="anywhere_us")
        chips = Chips(topics=[Chip(text="wind", origin="edited")], place=place, version=version)
        worker = Worker(self.store, self.settings, llm=StubLLM(), http=http)
        self.addCleanup(worker.shutdown)
        search_id = worker.create_search("Who knows wind?", chips, "edited").id
        with mock.patch("fn.search.LANES", [lane(n, p, r) for n, (p, r) in lanes.items()]):
            worker.execute(search_id)
        return search_id

    def steps_of(self, search_id: str, name: str):
        return [s for s in self.store.list_steps(search_id) if s.step == name]

    def first_place(self, search_id: str, person) -> str:
        (rank,) = self.steps_of(search_id, "rank")[:1]
        out = RankOut.model_validate_json(self.store.get_payload(rank.id)[1])
        return next(c.fit.place for c in out.candidates if c.person_id == person.id)

    def test_a_scoped_match_links_only_the_claims_of_the_given_persons_and_an_empty_list_asks_nothing(self):
        """person_ids limits the claims read to those persons; an empty list reads none and makes no call."""
        ada, bo = self.person_named("Ada Moss"), self.person_named("Bo Rink")
        mine, theirs = self.claim_of(ada, INBO), self.claim_of(bo, INBO)
        self.assertEqual(self.match_for(person_ids=[]), OrgMatchOut(asked=0, chosen=0, linked=0, failed=0))
        self.assertEqual(self.match_for(person_ids=[ada.id]), OrgMatchOut(asked=1, chosen=1, linked=1, failed=0))
        self.assertEqual(self.org_of(mine, theirs), ["ror:00j54wy13", None])
        self.assertEqual(list(self.store.org_answers()), [orgs.fold(INBO)])

    def test_most_stops_asking_after_the_limit_in_the_order_of_the_persons_and_counts_the_names_left(self):
        """Names are asked in person order up to most; the rest count as left, and a one-letter name is not counted."""
        ada, bo = self.person_named("Ada Moss"), self.person_named("Bo Rink")
        self.claim_of(ada, "Zeta Works")
        names = [f"Alpha Lab {n:02d}" for n in range(1, 41)]
        for name in names:
            self.claim_of(bo, name)
        self.claim_of(bo, "X")
        out = self.match_for(person_ids=[ada.id, bo.id], most=40)
        self.assertEqual((out.asked, out.left), (40, 1))
        self.assertEqual(self.asked, ["Zeta Works", *names[:39]])
        self.assertNotIn(orgs.fold(names[-1]), self.store.org_answers())

    def test_a_one_letter_name_beside_forty_names_leaves_none_left(self):
        """Forty askable names fit most=40, so the unaskable one adds nothing to left."""
        bo = self.person_named("Bo Rink")
        for n in range(1, 41):
            self.claim_of(bo, f"Alpha Lab {n:02d}")
        self.claim_of(bo, "X")
        self.assertEqual(self.match_for(person_ids=[bo.id], most=40).left, 0)

    def test_a_person_given_twice_and_a_name_in_two_cases_make_one_call_and_two_links(self):
        """Ada listed twice and Bo's upper-case INBO share one call and both claims link."""
        ada, bo = self.person_named("Ada Moss"), self.person_named("Bo Rink")
        claims = [self.claim_of(ada, INBO), self.claim_of(bo, INBO.upper())]
        out = self.match_for(person_ids=[ada.id, ada.id, bo.id])
        self.assertEqual((out.asked, out.linked, len(self.asked)), (1, 2, 1))
        self.assertEqual(self.org_of(*claims), ["ror:00j54wy13"] * 2)

    def test_a_hit_on_a_merged_record_links_the_claims_of_the_whole_person(self):
        """The id of a record merged into Ada reaches Ada's own claim."""
        ada, twin = self.person_named("Ada Moss"), self.person_named("Ada M Moss")
        claim = self.claim_of(ada, INBO)
        self.store.set_merged_into(twin.id, ada.id, NOW)
        self.assertEqual(self.match_for(person_ids=[twin.id]).linked, 1)
        self.assertEqual(self.org_of(claim), ["ror:00j54wy13"])

    def test_the_search_links_the_hit_before_resolve_and_the_first_rank_knows_the_place_and_a_rerank_asks_nothing(self):
        """A link step stands right before resolve with the match counts; a rerank adds no link row and no call."""
        ada = self.person_named("Ada Moss")
        self.claim_of(ada, INBO)
        search_id = self.search_with({"seeds": (ada, 1)}, self.routed())
        names = [s.step for s in self.store.list_steps(search_id)]
        self.assertEqual(names[names.index("resolve") - 1], "link")
        link = self.steps_of(search_id, "link")[0]
        self.assertEqual(OrgMatchOut.model_validate_json(self.store.get_payload(link.id)[1]),
                         OrgMatchOut(asked=1, chosen=1, linked=1, failed=0))
        self.assertEqual(self.first_place(search_id, ada), "abroad")
        self.claim_of(ada, "Example Lab")
        ctx = StepContext(search_id=search_id, store=self.store, llm=None, http=None, now=now, new_id=new_id,
                          log=mock.Mock(), settings=self.settings)
        search.refinish(ctx, self.store.get_search(search_id))
        self.assertEqual((self.asked, len(self.steps_of(search_id, "link"))), ([INBO], 1))

    def test_the_search_asks_by_hit_rank_across_lanes_so_a_second_lane_is_not_behind_forty_names(self):
        """Bo's lane comes first but ranks lower, so Ada's INBO is asked within the limit of 40."""
        ada, bo = self.person_named("Ada Moss"), self.person_named("Bo Rink")
        self.claim_of(ada, INBO)
        for n in range(1, 41):
            self.claim_of(bo, f"Alpha Lab {n:02d}")
        search_id = self.search_with({"seeds": (bo, 2), "scout": (ada, 1)}, self.routed())
        self.assertIn(INBO, self.asked)
        self.assertEqual(self.first_place(search_id, ada), "abroad")

    def test_a_stored_answer_links_the_hit_with_no_call(self):
        """With INBO answered before the search, the link step links Ada and ROR is not called."""
        ada = self.person_named("Ada Moss")
        self.claim_of(self.person_named("Cy Dell"), INBO)
        self.match_for()
        claim = self.claim_of(ada, INBO)
        self.asked.clear()
        search_id = self.search_with({"seeds": (ada, 1)}, self.routed())
        self.assertEqual((self.asked, self.org_of(claim)), ([], ["ror:00j54wy13"]))
        self.assertEqual(self.first_place(search_id, ada), "abroad")

    def test_a_503_fails_the_link_step_and_the_search_still_links_stored_answers_ranks_and_ends_done(self):
        """INBO answers 503: the link step is an error, Zeta Works is linked from its stored answer, rank and save follow."""
        ada = self.person_named("Ada Moss")
        zeta, inbo = self.claim_of(ada, "Zeta Works"), self.claim_of(ada, INBO)
        source, _ = record_source("https://example.org/zeta", "org", [("id", "z")], {}, NOW)
        orgs.save(self.store, [OrgFacts(id="ror:0zeta0000", name="Zeta", country_code="BE")], source, replace=False)
        self.store.save_org_answer(orgs.fold("Zeta Works"), "Zeta Works", "ror:0zeta0000", NOW)
        self.answers[INBO] = (503, b"{}")
        search_id = self.search_with({"seeds": (ada, 1)}, self.routed())
        self.assertEqual(self.store.get_search(search_id).status, "done")
        self.assertEqual([s.status for s in self.steps_of(search_id, "link")], ["error"])
        self.assertEqual(self.org_of(zeta, inbo), ["ror:0zeta0000", None])
        self.assertEqual(len(self.steps_of(search_id, "save")), 1)

    def test_no_link_step_runs_without_an_http_client_or_with_version_1_chips(self):
        """Version 2 with a client has a link row; version 2 without a client and version 1 with one have none."""
        ada = self.person_named("Ada Moss")
        self.claim_of(ada, INBO)
        for http, version, rows in ((self.routed(), 2, 1), (None, 2, 0), (self.routed(), 1, 0)):
            with self.subTest(http=http is not None, version=version):
                self.asked.clear()
                search_id = self.search_with({"seeds": (ada, 1)}, http, version)
                self.assertEqual(len(self.steps_of(search_id, "link")), rows)
                self.assertEqual(len(self.asked), rows)
                self.store.conn.execute("UPDATE claims SET org_id = NULL")
                self.store.conn.execute("DELETE FROM org_matches")


if __name__ == "__main__":
    unittest.main()
