import json
import unittest
from datetime import UTC, datetime, timedelta

from fn import importer, network
from fn.contracts import Identifier
from fn.worker import Worker
from tests.helpers import StubHttp, make_db, make_settings

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
HEADER = "name,email,phone,organization,role,city,state,country,linkedin_url,orcid"
PEOPLE = [
    "Ann Example,ann@example.org,+1 617 555 0101,KU Leuven,Professor,Cambridge,MA,USA,,",
    "Bert Sample,,,,Engineer,Gotham,,,https://www.linkedin.com/in/bert-sample,",
    "Cleo Fiction,,,,,,,,,0000-0002-1825-0097",
]


def csv_bytes(*rows: str, header: str = HEADER, sep: str = ",") -> bytes:
    return "\n".join([header, *rows]).replace(",", sep).encode()


class ImporterTest(unittest.TestCase):
    def setUp(self):
        settings = make_settings(self)
        self.store = make_db(self, settings)
        self.worker = Worker(self.store, settings, llm=None, http=StubHttp())
        self.addCleanup(self.worker.pool.shutdown)

    def upload(self, raw: bytes, filename: str = "people.csv", when: datetime = T0) -> importer.ImportPreview:
        return importer.get(self.store, importer.upload(self.worker, filename, raw, when))

    def network(self) -> list[str]:
        return [p for ids in self.store.network_by_group_key().values() for p in ids]

    def person(self, name: str, *idents: tuple[str, str], in_list: bool = False) -> str:
        found = self.store.resolve_person([Identifier(scheme=s, value=v) for s, v in idents], name).id
        if in_list:
            network.add(self.store, [found], via="search", now=T0)
        return found


class ReadTest(ImporterTest):
    def test_commas_and_semicolons_give_the_same_preview(self):
        """The delimiter the header has more of splits the rows, so both files read the same rows."""
        commas, semicolons = self.upload(csv_bytes(*PEOPLE)), self.upload(csv_bytes(*PEOPLE, sep=";"))
        self.assertEqual([r.model_dump() for r in commas.rows], [r.model_dump() for r in semicolons.rows])
        self.assertEqual(commas.counts, {"new": 3, "update": 0, "name_match": 0, "skipped": 0})
        self.assertEqual(commas.rows[0].cells["organization"], "KU Leuven")

    def test_a_byte_order_mark_and_windows_1252_accents_read_correctly(self):
        """UTF-8 with a byte-order mark keeps the name header; Windows-1252 bytes decode to their accents."""
        bom = self.upload(b"\xef\xbb\xbf" + "name,city\nZoë Exemple,Leuven".encode())
        self.assertEqual((bom.rows[0].name, bom.rows[0].cells["city"]), ("Zoë Exemple", "Leuven"))
        latin = self.upload("name;role\nJosé Façade;Directrice générale".encode("cp1252"))
        self.assertEqual((latin.rows[0].name, latin.rows[0].cells["role"]), ("José Façade", "Directrice générale"))

    def test_headers_match_in_capitals_and_with_spaces_and_other_columns_are_listed(self):
        """Headers are trimmed, lower-cased and spaces become underscores; other columns are named as ignored."""
        found = self.upload(csv_bytes("Ann Example,Leuven,https://linkedin.com/in/ann,x",
                                      header=" NAME ,City,LinkedIn URL,Notes"))
        self.assertEqual(found.rows[0].cells, {"name": "Ann Example", "city": "Leuven",
                                               "linkedin_url": "https://linkedin.com/in/ann"})
        self.assertEqual(found.ignored_columns, ["Notes"])

    def test_files_fn_cannot_read_are_refused_with_one_sentence(self):
        """No name column, empty, header only, .xlsx, UTF-16, tabs and over 5 MB each raise ImportRefused."""
        cases = [
            (csv_bytes("ann@example.org", header="email"),
             "f.csv has no name column. Rename the column that holds names to name and upload it again."),
            (b"", "f.csv is empty. Upload a CSV file with the column names in its first row."),
            (b"name,email\n,\n", "f.csv has no rows under the column names."),
            (b"PK\x03\x04\x14\x00\x06\x00", "f.csv is not a CSV file. In Excel, use Save as and pick CSV."),
            ("name\nAnn Example".encode("utf-16"), "f.csv is not a CSV file. In Excel, use Save as and pick CSV."),
            (b"name\temail\nAnn Example\tann@example.org", "f.csv is not a CSV file. In Excel, use Save as and pick CSV."),
            (csv_bytes("Ann Example," + "x" * 10_000_000, header="name,notes"),
             "f.csv is larger than 5 MB. Split it into smaller files and upload them one by one."),
        ]
        for raw, sentence in cases:
            with self.subTest(sentence=sentence, start=raw[:12]):
                with self.assertRaises(importer.ImportRefused) as refused:
                    importer.upload(self.worker, "f.csv", raw, T0)
                self.assertEqual(str(refused.exception), sentence)

    def test_a_formula_and_a_line_break_stay_text(self):
        """A cell starting with = is stored as typed, and a quoted cell keeps its line break and its delimiter."""
        found = self.upload(b'name,role,organization\nAnn Example,=HYPERLINK("x"),"Lab A,\nLab B"\n')
        self.assertEqual(found.rows[0].cells["role"], '=HYPERLINK("x")')
        self.assertEqual(found.rows[0].cells["organization"], "Lab A,\nLab B")
        done = importer.confirm(self.worker, found.import_id, set(), T0)
        claims = self.store.claims_of([done.rows[0].person_id])
        self.assertIn(("role", '=HYPERLINK("x")'), [(c.kind, c.value) for c in claims])
        self.assertIn(("affiliation", "Lab A,\nLab B"), [(c.kind, c.value) for c in claims])


class OutcomeTest(ImporterTest):
    def test_each_row_gets_the_outcome_of_the_table(self):
        """Blank rows are not counted; no name, a repeat and identifiers of two people are skipped with a sentence.

        An identifier of one person is an update, a network name without identifier a name match, else new.
        """
        linked = self.person("Lina Known", ("profile_url", "https://www.linkedin.com/in/lina"))
        orcid = self.person("Otto Known", ("orcid", "https://orcid.org/0000-0001-0000-0001"))
        named = self.person("Nora Network", ("seed", "nora"), in_list=True)
        found = self.upload(csv_bytes(
            ",,,,,,,,,",
            ",nobody@example.org,,,,,,,,",
            "Ann Example,,,,Professor,,,,,",
            "Ann Example,,,,Professor,,,,,",
            "Two Ids,,,,,,,,linkedin.com/in/lina,0000-0001-0000-0001",
            "Lina Known,,,,Advisor,,,,https://www.linkedin.com/in/lina/,",
            "Nora Network,,,,,,,,,",
            "Paul New,,,,,,,,,",
        ))
        got = [(r.n, r.outcome, r.person_id, r.message) for r in found.rows]
        self.assertEqual(got, [
            (3, "skipped", None, "Row 3 has no name, so FN skips it."),
            (4, "new", None, ""),
            (5, "skipped", None, "Row 5 is the same as row 4, so FN skips it."),
            (6, "skipped", None, "Row 6's LinkedIn URL belongs to Lina Known and its ORCID to Otto Known, so FN skips it."),
            (7, "update", linked, ""),
            (8, "name_match", named, ""),
            (9, "new", None, ""),
        ])
        self.assertEqual(found.counts, {"new": 2, "update": 1, "name_match": 1, "skipped": 3})
        self.assertNotEqual(orcid, linked)

    def test_two_rows_with_one_name_and_other_details_become_two_people(self):
        """The second row says it is another person, and confirm makes two network people."""
        found = self.upload(csv_bytes("Ann Example,,,,Professor,,,,,", "Ann Example,,,,Painter,,,,,"))
        self.assertEqual([r.outcome for r in found.rows], ["new", "new"])
        self.assertEqual(found.rows[1].message, "Row 2 has the same name, so FN imports this row as another person.")
        importer.confirm(self.worker, found.import_id, set(), T0)
        self.assertEqual(len(self.network()), 2)

    def test_other_spellings_of_an_identifier_find_the_person(self):
        """A LinkedIn URL without www, with a slash or a query, a bare ORCID and an email in capitals are updates."""
        first = self.upload(csv_bytes(
            "Ann Example,,,,,,,,https://www.linkedin.com/in/ann-example,",
            "Bea Example,,,,,,,,,https://orcid.org/0000-0002-1825-0097",
            "Cas Example,cas@example.org,,,,,,,,",
        ))
        people = importer.confirm(self.worker, first.import_id, set(), T0).rows
        again = self.upload(csv_bytes(
            "Ann E.,,,,,,,,linkedin.com/in/ann-example,",
            "Ann E,,,,,,,,https://www.linkedin.com/in/ann-example/,",
            "Ann X,,,,,,,,https://linkedin.com/in/ann-example?trk=abc,",
            "B. Example,,,,,,,,,0000-0002-1825-0097",
            "C Example, CAS@Example.ORG ,,,,,,,,",
        ))
        ids = [p.person_id for p in people]
        self.assertEqual([(r.outcome, r.person_id) for r in again.rows],
                         [("update", ids[0])] * 3 + [("update", ids[1]), ("update", ids[2])])

    def test_a_place_fn_cannot_find_is_said_and_a_state_works_as_a_name_or_a_code(self):
        """A city with its state as a code or a name locates; an unknown city says the person is not on the map."""
        found = self.upload(csv_bytes("Ann Example,,,,,Cambridge,Massachusetts,,,", "Bea Example,,,,,Cambridge,MA,,,",
                                      "Cas Example,,,,,Gotham,NY,USA,,"))
        self.assertEqual([r.message for r in found.rows], [
            "", "", "FN cannot find Gotham, NY, USA on the map, so this person will not be on the map."])
        done = importer.confirm(self.worker, found.import_id, set(), T0)
        places = [[(c.value, c.lat is not None) for c in self.store.claims_of([r.person_id]) if c.kind == "location"]
                  for r in done.rows]
        self.assertEqual(places, [[("Cambridge, Massachusetts", True)], [("Cambridge, MA", True)],
                                  [("Gotham, NY, USA", False)]])


class ConfirmTest(ImporterTest):
    def test_confirm_puts_new_people_in_the_network_with_claims_quoting_their_line(self):
        """Each claim quotes its own line of the row's import source, dated the import's day by sheet_date.

        The location joins city, state and country and has coordinates when the place is known.
        """
        found = self.upload(csv_bytes(*PEOPLE), filename="contacts.csv")
        done = importer.confirm(self.worker, found.import_id, set(), T0 + timedelta(days=1))
        self.assertEqual(done.status, "confirmed")
        self.assertEqual(sorted(self.network()), sorted(r.person_id for r in done.rows))
        ann = self.store.claims_of([done.rows[0].person_id])
        source = self.store.get_sources([ann[0].source_id])[ann[0].source_id]
        self.assertEqual((source.kind, source.url, source.title, source.source_date, source.date_method),
                         ("import", f"fn:import/{found.import_id}#row-2", "contacts.csv, row 2", "2026-11-02",
                          "sheet_date"))
        self.assertEqual(source.text, "name: Ann Example\nemail: ann@example.org\nphone: +1 617 555 0101\n"
                                      "organization: KU Leuven\nrole: Professor\ncity: Cambridge\nstate: MA\n"
                                      "country: USA")
        got = {(c.kind, c.relation, c.org_id, c.value, c.quote, c.date_method, c.claim_date) for c in ann}
        self.assertEqual(got, {
            ("email", None, None, "ann@example.org", "email: ann@example.org", "sheet_date", "2026-11-02"),
            ("phone", None, None, "+1 617 555 0101", "phone: +1 617 555 0101", "sheet_date", "2026-11-02"),
            ("affiliation", "works_at", "ror:05f950310", "KU Leuven", "organization: KU Leuven", "sheet_date",
             "2026-11-02"),
            ("role", None, None, "Professor", "role: Professor", "sheet_date", "2026-11-02"),
            ("location", "lives_in", None, "Cambridge, MA, USA", "city: Cambridge\nstate: MA\ncountry: USA",
             "sheet_date", "2026-11-02"),
        })
        for claim in ann:
            self.assertEqual(source.text[claim.quote_start:claim.quote_end], claim.quote)
        location = next(c for c in ann if c.kind == "location")
        self.assertAlmostEqual(location.lat, 42.37, places=1)
        gotham = next(c for c in self.store.claims_of([done.rows[1].person_id]) if c.kind == "location")
        self.assertEqual((gotham.value, gotham.lat, gotham.lon), ("Gotham", None, None))
        self.assertEqual(self.store.claims_of([done.rows[2].person_id]), [])

    def test_a_second_import_of_the_same_file_adds_nobody_when_every_name_match_is_ticked(self):
        """Rows with an identifier are updates and rows without one are name matches.

        With every name match ticked, the network keeps its size and no claim is written.
        """
        rows = [*PEOPLE, "Dora Plain,,,,Curator,Leuven,,Belgium,,"]
        first = importer.confirm(self.worker, self.upload(csv_bytes(*rows)).import_id, set(), T0)
        claims = len(self.store.claims_of(self.network()))
        second = self.upload(csv_bytes(*rows), when=T0 + timedelta(days=7))
        self.assertEqual([r.outcome for r in second.rows], ["update", "update", "update", "name_match"])
        self.assertEqual(second.rows[3].person_id, first.rows[3].person_id)
        done = importer.confirm(self.worker, second.import_id, {r.n for r in second.rows}, T0 + timedelta(days=7))
        self.assertEqual(len(self.network()), 4)
        self.assertEqual(len(self.store.claims_of(self.network())), claims)
        self.assertEqual([r.person_id for r in done.rows], [r.person_id for r in first.rows])

    def test_an_unticked_name_match_is_a_new_person(self):
        """A name match without a tick becomes another network person; the ticked one merges into the match."""
        nora = self.person("Nora Network", ("seed", "nora"), in_list=True)
        found = self.upload(csv_bytes("Nora Network,,,,Curator,,,,,", "Nora Network,,,,Painter,,,,,"))
        done = importer.confirm(self.worker, found.import_id, {2}, T0)
        self.assertEqual(done.rows[0].person_id, nora)
        self.assertNotEqual(done.rows[1].person_id, nora)
        self.assertEqual(len(self.network()), 2)

    def test_a_ticked_match_who_left_the_network_since_the_preview_is_a_new_person(self):
        """The row imports as a new person and its message says the match left."""
        nora = self.person("Nora Network", ("seed", "nora"), in_list=True)
        found = self.upload(csv_bytes("Nora Network,,,,Curator,,,,,"))
        network.remove(self.store, nora, now=T0)
        done = importer.confirm(self.worker, found.import_id, {2}, T0)
        self.assertEqual((done.rows[0].outcome, done.rows[0].message), (
            "new", "Nora Network left your network since this preview, so FN imported this row as a new person."))
        self.assertNotEqual(done.rows[0].person_id, nora)
        self.assertEqual(self.network(), [done.rows[0].person_id])

    def test_confirm_twice_changes_nothing_and_confirm_after_discard_raises(self):
        """A second confirm returns the stored preview and writes no event, claim or job; a discarded import refuses."""
        found = self.upload(csv_bytes(*PEOPLE))
        done = importer.confirm(self.worker, found.import_id, set(), T0)
        jobs = self.store.conn.execute("SELECT count(*) FROM searches").fetchone()[0]
        events = self.store.conn.execute("SELECT count(*) FROM events").fetchone()[0]
        self.assertEqual(importer.confirm(self.worker, found.import_id, set(), T0 + timedelta(hours=1)), done)
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM searches").fetchone()[0], jobs)
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM events").fetchone()[0], events)
        other = self.upload(csv_bytes(*PEOPLE), filename="again.csv")
        importer.discard(self.store, other.import_id)
        self.assertEqual(importer.get(self.store, other.import_id).status, "discarded")
        with self.assertRaises(importer.ImportRefused) as refused:
            importer.confirm(self.worker, other.import_id, set(), T0)
        self.assertEqual(str(refused.exception), "again.csv was discarded, so it cannot be imported. "
                                                 "Upload it again to import it.")

    def test_the_import_event_holds_counts_and_no_contact_value(self):
        """One import event with the counts; its detail names no email, phone or name of the file."""
        found = self.upload(csv_bytes(*PEOPLE))
        importer.confirm(self.worker, found.import_id, set(), T0)
        rows = self.store.conn.execute("SELECT detail_json FROM events WHERE kind = 'import' AND import_id = ?",
                                       (found.import_id,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][0]), {"counts": {"new": 3, "update": 0, "name_match": 0, "skipped": 0}})
        adds = self.store.conn.execute("SELECT count(*) FROM events WHERE kind = 'add' AND import_id = ?",
                                       (found.import_id,)).fetchone()[0]
        self.assertEqual(adds, 3)

    def test_preview_and_confirm_each_run_as_a_step_of_a_job(self):
        """Each is a job with one ok step, and the steps' payloads hold counts but no contact value."""
        found = self.upload(csv_bytes(*PEOPLE))
        importer.confirm(self.worker, found.import_id, set(), T0)
        jobs = self.store.conn.execute("SELECT id, status FROM searches WHERE kind = 'job' ORDER BY created_at")
        steps = [(s.step, s.status, job["status"]) for job in jobs for s in self.store.list_steps(job["id"])]
        self.assertEqual(steps, [("import_preview", "ok", "done"), ("import_confirm", "ok", "done")])
        payloads = self.store.conn.execute("SELECT input_json || output_json FROM step_payloads").fetchall()
        self.assertFalse(any("ann@example.org" in p[0] for p in payloads))

    def test_five_thousand_rows_import(self):
        """A file of 5,000 rows previews and confirms into 5,000 network people."""
        rows = [f"Person {n:04d} Example,p{n}@example.org,,,Role {n},,,,," for n in range(5000)]
        found = self.upload(csv_bytes(*rows))
        self.assertEqual(found.counts["new"], 5000)
        importer.confirm(self.worker, found.import_id, set(), T0)
        self.assertEqual(len(self.network()), 5000)


if __name__ == "__main__":
    unittest.main()
