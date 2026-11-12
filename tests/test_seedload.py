import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import get_args
from unittest import mock

from fn import present, seedload
from fn.contracts import DateMethod, Person
from tests.helpers import FIXTURES, StubHttp, make_db, make_seeded_db, make_settings

ROWS = [json.loads(line) for path in sorted(seedload.SEEDS.glob("*.jsonl")) for line in path.read_text().splitlines()]


load = seedload.load


class SeedLoadTest(unittest.TestCase):
    def setUp(self):
        self.store = make_seeded_db(self)

    def person(self, row_key: str) -> Person:
        row = self.store.conn.execute(
            "SELECT p.id, p.display_name, p.name_key, p.list_status FROM person_identifiers i "
            "JOIN persons p ON p.id = i.person_id WHERE i.scheme = 'seed' AND i.value = ?", (row_key,)).fetchone()
        return Person.model_validate(dict(row))

    def claims(self, row_key: str) -> dict[str, list]:
        found: dict[str, list] = {}
        for claim in self.store.claims_of([self.person(row_key).id]):
            found.setdefault(claim.kind, []).append(claim)
        return found

    def test_every_seed_row_yields_a_dated_claim_quoted_at_its_offsets(self):
        """Each of the 5,035 rows is one person whose claims carry a date, a known date method and a quote at its offsets."""
        self.assertEqual(len(ROWS), 5035)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0], 5035)
        by_person: dict[str, list] = {}
        persons = {r["row_key"]: self.person(r["row_key"]).id for r in ROWS}
        for claim in self.store.claims_of(list(persons.values())):
            by_person.setdefault(claim.person_id, []).append(claim)
        sources = self.store.get_sources(list({c.source_id for cs in by_person.values() for c in cs}))
        for row_key, person_id in persons.items():
            claims = by_person.get(person_id, [])
            self.assertTrue(claims, row_key)
            for claim in claims:
                self.assertTrue(claim.claim_date and claim.date_precision, row_key)
                self.assertIn(claim.date_method, get_args(DateMethod), row_key)
                self.assertEqual(sources[claim.source_id].text[claim.quote_start:claim.quote_end], claim.quote)

    def test_a_second_load_changes_nothing(self):
        before = self.store.conn.total_changes
        self.assertEqual(seedload.load(self.store), 5035)
        self.assertEqual(self.store.conn.total_changes - before, 0)

    def test_a_rerun_rewrites_changed_org_ids_and_relations_and_a_second_rerun_changes_nothing(self):
        """Stored claims whose org id or relation differs from the seed rows get them back; the next load writes nothing."""
        query = "SELECT id, org_id, relation FROM claims WHERE org_id = ? ORDER BY id"
        expected = self.store.conn.execute(query, ("ror:05f950310",)).fetchall()
        self.store.conn.execute("UPDATE claims SET org_id = 'ku-leuven', relation = 'studied_at' WHERE org_id = 'ror:05f950310'")
        self.assertEqual(self.store.conn.execute(query, ("ror:05f950310",)).fetchall(), [])
        seedload.load(self.store)
        self.assertEqual([tuple(r) for r in self.store.conn.execute(query, ("ror:05f950310",))], [tuple(r) for r in expected])
        self.assertGreater(len(expected), 500)
        before = self.store.conn.total_changes
        seedload.load(self.store)
        self.assertEqual(self.store.conn.total_changes - before, 0)

    def test_seed_fields_map_to_relations_orgs_and_dates(self):
        """home, host, employer and member_of map to relations; a year dates by record field, else the source date."""
        goemans = self.claims("francqui|michel-goemans|1987|")
        self.assertEqual([(c.relation, c.org_id) for c in goemans["role"]], [("fellow_of", "ror:00m1rny06")])
        self.assertEqual({(c.value, c.relation, c.org_id) for c in goemans["affiliation"]}, {
            ("Université catholique de Louvain", "affiliated_with", "ror:02495e989"),
            ("Massachusetts Institute of Technology", "hosted_by", "ror:042nb2s44")})
        self.assertEqual({(c.claim_date, c.date_precision, c.date_method) for cs in goemans.values() for c in cs},
                         {("1987", "year", "record_field")})
        self.assertEqual([c.value for c in goemans["topic"]], ["Combinative optimisation"])
        climate = self.claims("climate|gregoire-wallenborn||")
        self.assertEqual([(c.value, c.relation) for c in climate["affiliation"]], [("ULB", "works_at")])
        self.assertEqual(climate["role"][0].date_method, "sitemap")
        kvab = self.claims("kvab|peter-verhoyen||kunsten-gewone-leden")
        self.assertEqual([(c.relation, c.claim_date, c.date_precision, c.date_method) for c in kvab["affiliation"]],
                         [("member_of", "2025-12", "month", "document_heading")])
        consul = self.claims("consuls|jonathan-hoffmann||")
        self.assertEqual([(c.relation, c.date_method) for c in consul["role"]], [("consul_for", "page_date"), (None, "page_date")])

    def test_names_are_stored_as_on_the_page_and_folded_in_the_key(self):
        person = self.person("climate|gregoire-wallenborn||")
        self.assertEqual((person.display_name, person.name_key), ("Grégoire Wallenborn", "gregoire wallenborn"))


PAGE = "Dr. Ada Example Senior researcher Example University Portland, OR 97201"


def made_up_row(list_name: str, name: str, role: str | None, **fields) -> dict:
    return {"list": list_name, "row_key": f"{list_name}|{name.lower().replace(' ', '-')}||", "name": name,
            "name_on_page": name, "year": None, "role": role, "institutions": [], "field": None, "place": None,
            "jurisdiction": [], "profile_url": None, "source_url": f"https://example.org/{list_name}",
            "source_title": "Example list", "source_date": "2026-07-16", "date_method": "page text", "page": None,
            "quote": PAGE.replace("Ada Example", name), "raw_path": "", "fetched_at": "2026-10-29"} | fields


class SeedPlacesAndTitlesTest(unittest.TestCase):
    def setUp(self):
        self.store = make_db(self)
        self.seeds = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.seeds)

    def load(self, rows: list[dict], locate=None) -> int:
        raw = self.seeds / "page.txt"
        raw.write_text(" ".join(r["quote"] for r in rows), encoding="utf-8")
        text = "\n".join(json.dumps(r | {"raw_path": str(raw)}) for r in rows)
        (self.seeds / "rows.jsonl").write_text(text + "\n", encoding="utf-8")
        return seedload.load(self.store, self.seeds, locate)

    def view(self, row: dict) -> present.PersonView:
        (person,) = self.store.person_ids_by_identifier("seed", [row["row_key"]]).values()
        (found,) = present.person_views(self.store, [[person]], date(2026, 11, 12))
        return found

    def claims(self, row: dict) -> list:
        (person,) = self.store.person_ids_by_identifier("seed", [row["row_key"]]).values()
        return self.store.claims_of([person])

    def test_a_climate_row_gives_a_job_title_on_the_view_and_keeps_its_list_claim(self):
        """The title is a role claim without a relation; the member_of claim stays; a BAEF role is still no job."""
        climate = made_up_row("climate", "Ada Example", "Senior researcher")
        baef = made_up_row("baef", "Bo Example", "Fellow 2012")
        self.load([climate, baef])
        self.assertEqual(self.view(climate).role, "Senior researcher")
        self.assertEqual(sorted((c.relation or "") for c in self.claims(climate) if c.kind == "role"), ["", "member_of"])
        self.assertIsNone(self.view(baef).role)
        self.assertEqual([c.relation for c in self.claims(baef) if c.kind == "role"], ["fellow_of"])

    def test_a_consul_title_is_a_job_even_when_the_quote_does_not_hold_it(self):
        row = made_up_row("consuls", "Cy Example", "Honorary Consul of Belgium")
        self.load([row])
        self.assertEqual(self.view(row).role, "Honorary Consul of Belgium")

    def test_a_consul_place_is_a_located_claim_dated_like_the_row_and_none_without_locate(self):
        """The location claim has the coordinates locate returned; without locate it has none; no place, no claim."""
        row = made_up_row("consuls", "Cy Example", "Honorary Consul of Belgium", place="Portland", jurisdiction=["Oregon"])
        bare = made_up_row("consuls", "Di Example", "Honorary Consul of Belgium")
        calls = []

        def locate(city: str, states: list[str]):
            calls.append((city, states))
            return 45.5, -122.6

        self.load([row, bare], locate)
        (place,) = [c for c in self.claims(row) if c.kind == "location"]
        self.assertEqual((place.value, place.lat, place.lon, place.claim_date, place.date_method),
                         ("Portland", 45.5, -122.6, "2026-07-16", "page_date"))
        self.assertEqual(calls, [("Portland", ["Oregon"])])
        self.assertEqual([c for c in self.claims(bare) if c.kind == "location"], [])
        store, self.store = self.store, make_db(self, make_settings(self))
        self.load([row])
        (unplaced,) = [c for c in self.claims(row) if c.kind == "location"]
        self.assertEqual((unplaced.lat, unplaced.lon), (None, None))
        store.close()

    def test_loading_the_same_rows_twice_writes_nothing_the_second_time(self):
        rows = [made_up_row("climate", "Ada Example", "Senior researcher"),
                made_up_row("consuls", "Cy Example", "Honorary Consul of Belgium", place="Portland", jurisdiction=["Oregon"])]
        self.load(rows, lambda city, states: (45.5, -122.6))
        before = self.store.conn.total_changes
        self.load(rows, lambda city, states: (45.5, -122.6))
        self.assertEqual(self.store.conn.total_changes - before, 0)

    def test_the_fn_seed_job_locates_a_consul_city_with_each_state_then_the_city_alone(self):
        """Springfield is in Missouri, not Maine; Portland in Oregon is not Portland in Maine; an unknown city has no pin."""
        rows = [made_up_row("consuls", "Cy Example", "Honorary Consul of Belgium", place="Portland", jurisdiction=["Oregon"]),
                made_up_row("consuls", "Di Example", "Honorary Consul of Belgium", place="Springfield",
                            jurisdiction=["Maine", "Missouri"]),
                made_up_row("consuls", "Ed Example", "Honorary Consul of Belgium", place="Nowhereville",
                            jurisdiction=["Oregon"])]
        raw = self.seeds / "page.txt"
        raw.write_text(" ".join(r["quote"] for r in rows), encoding="utf-8")
        text = "\n".join(json.dumps(r | {"raw_path": str(raw)}) for r in rows)
        (self.seeds / "rows.jsonl").write_text(text + "\n", encoding="utf-8")
        settings = make_settings(self)
        with mock.patch.object(seedload, "load", lambda store, locate: load(store, self.seeds, locate)):
            job = seedload.refresh(self.store, settings, StubHttp())
        self.assertEqual(job.status, "done", job.error)
        cities = [line.split("\t") for line in (FIXTURES / "geo" / "cities15000-extract.txt").read_text().splitlines()]
        pin = {(c[1], c[10]): (float(c[4]), float(c[5])) for c in cities if c[8] == "US"}
        found = {r["name"]: [(c.lat, c.lon) for c in self.claims(r) if c.kind == "location"] for r in rows}
        self.assertEqual(found, {"Cy Example": [pin["Portland", "OR"]], "Di Example": [pin["Springfield", "MO"]],
                                 "Ed Example": [(None, None)]})


if __name__ == "__main__":
    unittest.main()
