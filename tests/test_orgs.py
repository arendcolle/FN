import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import httpx

from fn import db, orgs, seedload
from fn.contracts import REGISTRY_ID, Chip, Chips, ClaimDraft, OrgFacts, Search, Source, record_source
from fn.store import Store
from fn.web.debug import debug_search_page
from tests.helpers import (
    FIXTURES,
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


class OrgPlacesMigrationTest(MigrationTest):
    def test_008_reads_an_old_org_row_back_with_empty_places(self):
        """A database at schema version 7 with an org keeps it, and the row reads back without city, lat and lon."""
        self.migrate_to(7)
        conn = self.store.conn
        conn.execute("INSERT INTO sources (id, kind, url, text, content_hash, normalize_version)"
                     " VALUES ('s1', 'record', 'https://example.org', 'text', 'h', 1)")
        conn.execute("INSERT INTO orgs (id, name, country_code, source_id, fetched_at)"
                     " VALUES ('ror:0aaaaaa11', 'Example Institute', 'BE', 's1', '2026-11-02T00:00:00+00:00')")
        self.assertEqual(self.store.migrate(), [8])
        old = self.store.get_orgs(["ror:0aaaaaa11"])["ror:0aaaaaa11"]
        self.assertEqual((old.name, old.country_code, old.city, old.lat, old.lon), ("Example Institute", "BE", None, None, None))


if __name__ == "__main__":
    unittest.main()
