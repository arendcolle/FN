import json
import unittest
from typing import get_args

from fn import seedload
from fn.contracts import DateMethod, Person
from tests.helpers import make_seeded_db

ROWS = [json.loads(line) for path in sorted(seedload.SEEDS.glob("*.jsonl")) for line in path.read_text().splitlines()]


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
        self.assertEqual([(c.relation, c.date_method) for c in consul["role"]], [("consul_for", "page_date")])

    def test_names_are_stored_as_on_the_page_and_folded_in_the_key(self):
        person = self.person("climate|gregoire-wallenborn||")
        self.assertEqual((person.display_name, person.name_key), ("Grégoire Wallenborn", "gregoire wallenborn"))


if __name__ == "__main__":
    unittest.main()
