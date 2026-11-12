import csv
import io
import re
import unittest
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from fn import importer
from fn.contracts import IMPORT_COLUMNS
from fn.exporter import place_parts
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_seeded_db, make_settings

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
PEOPLE = ("name,email,phone,organization,role,city,state,country,linkedin_url,orcid\n"
          "Ann Example,ann@example.org,+1 617 555 0101,KU Leuven,Professor,Cambridge,MA,USA,"
          "linkedin.com/in/ann-example/,0000-0002-1825-0097\n"
          'Zoë "Zo" Exemple,,,"Acme, Labs",=SUM(A1),Leuven,,Belgium,,\n'
          "Bert Sample,,,,Engineer,Boston,MA,USA,,\n")


class ExporterTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_seeded_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.worker = app.state.worker

    def imported(self, text: str = PEOPLE, filename: str = "people.csv", merge_all: bool = False) -> str:
        import_id = importer.upload(self.worker, filename, text.encode(), T0)
        rows = importer.get(self.store, import_id).rows
        importer.confirm(self.worker, import_id, {r.n for r in rows if merge_all and r.outcome == "name_match"}, T0)
        return import_id

    def export(self, **params) -> tuple[str, list[dict[str, str]]]:
        response = self.client.get("/people/export.csv", params=params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        return response.text, list(csv.DictReader(io.StringIO(response.text.removeprefix("﻿"))))

    def network_size(self) -> int:
        return sum(len(ids) for ids in self.store.network_by_group_key().values())

    def test_the_export_route_answers_with_a_dated_csv_download(self):
        """/people/export.csv is the export, not a profile: a CSV attachment named after today."""
        response = self.client.get("/people/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-disposition"],
                         f'attachment; filename="fn-network-{now().astimezone().date().isoformat()}.csv"')

    def test_the_header_starts_with_the_import_columns_and_a_row_holds_the_person(self):
        """Columns are the import columns, then the Belgian organizations, added and profile; cells come from the person."""
        self.imported()
        text, rows = self.export()
        self.assertTrue(text.startswith("﻿name,email,phone,organization,role,city,state,country,linkedin_url,orcid,"
                                        "belgian_organizations,added,profile\r\n"))
        self.assertEqual(list(rows[0])[:len(IMPORT_COLUMNS)], list(IMPORT_COLUMNS))
        ann = next(r for r in rows if r["name"] == "Ann Example")
        person_id = ann["profile"].rsplit("/", 1)[-1]
        self.assertEqual(ann, {
            "name": "Ann Example", "email": "ann@example.org", "phone": "'+1 617 555 0101", "organization": "KU Leuven",
            "role": "Professor", "city": "Cambridge", "state": "MA", "country": "USA",
            "linkedin_url": "https://www.linkedin.com/in/ann-example", "orcid": "https://orcid.org/0000-0002-1825-0097",
            "belgian_organizations": "KU Leuven 2026", "added": f"{T0.astimezone().day} November 2026",
            "profile": f"http://127.0.0.1/people/{person_id}",
        })

    def test_a_formula_is_quoted_and_accents_commas_and_quotes_survive(self):
        """A cell starting with = gets an apostrophe; an accented name with quotes and a comma in a cell read back whole."""
        self.imported()
        zoe = next(r for r in self.export()[1] if r["name"].startswith("Zo"))
        self.assertEqual((zoe["name"], zoe["organization"], zoe["role"], zoe["city"], zoe["country"]),
                         ('Zoë "Zo" Exemple', "Acme, Labs", "'=SUM(A1)", "Leuven", "Belgium"))

    def test_a_filter_narrows_the_rows_to_the_count_line_and_records_the_export(self):
        """The export of a filtered list has as many rows as its count line says, and writes one export event."""
        self.imported()
        for params in ({}, {"q": "ma"}, {"q": "cambridge"}):
            with self.subTest(params=params):
                count = re.search(r'<p class="fn-count text-meta"><span>(\d+) (?:person|people)',
                                  self.client.get("/people", params=params).text).group(1)
                self.assertEqual(len(self.export(**params)[1]), int(count))
        self.assertEqual(len(self.export(q="cambridge")[1]), 1)
        events = self.store.conn.execute("SELECT detail_json FROM events WHERE kind = 'export' ORDER BY rowid").fetchall()
        self.assertEqual([e[0] for e in events][-2:], ['{"count": 1, "filtered": true}', '{"count": 1, "filtered": true}'])

    def test_an_exported_file_imports_again_without_adding_anyone(self):
        """The export uploads without a refusal, and confirming it with every name match ticked keeps the network size."""
        self.imported()
        before = self.network_size()
        text, _ = self.export()
        import_id = self.imported(text, "fn-network.csv", merge_all=True)
        self.assertEqual(importer.get(self.store, import_id).counts["skipped"], 0)
        self.assertEqual(self.network_size(), before)
        values = [v for (v,) in self.store.conn.execute("SELECT value FROM claims")]
        self.assertFalse([v for v in values if v.startswith("'")])

    def test_a_place_splits_into_city_state_and_country(self):
        """The first part is the city; known states and countries go to their column, an unknown middle part is the state."""
        for place, expected in (("Cambridge, MA, USA", ("Cambridge", "MA", "USA")), ("Leuven, Belgium", ("Leuven", "", "Belgium")),
                                ("Greater Boston", ("Greater Boston", "", "")), (None, ("", "", "")),
                                ("Leuven, Vlaams-Brabant, Belgium", ("Leuven", "Vlaams-Brabant", "Belgium")),
                                ("Boston, Massachusetts", ("Boston", "Massachusetts", ""))):
            with self.subTest(place=place):
                self.assertEqual(tuple(place_parts(place).values()), expected)


if __name__ == "__main__":
    unittest.main()
