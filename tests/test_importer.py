import json
import unittest
import uuid
from datetime import UTC, datetime, timedelta

from fn import importer, network
from fn.contracts import ClaimDraft, Identifier, Org, Source
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


PROFILE_HEADER = "name,orcid,email,organization,profile"


class ProfileTest(ImporterTest):
    def setUp(self):
        super().setUp()
        self.ann = self.person("Ann Fictive", ("seed", "ann"), in_list=True)
        self.bo = self.person("Bo Madeup", ("seed", "bo"))
        self.cy = self.person("Cy Invented", ("seed", "cy"), ("orcid", "https://orcid.org/0000-0002-1825-0097"),
                              in_list=True)

    def rows(self, *lines: str):
        return self.upload(csv_bytes(*lines, header=PROFILE_HEADER)).rows

    def people_count(self) -> int:
        return self.store.conn.execute("SELECT count(*) FROM persons").fetchone()[0]

    def claim_count(self) -> int:
        return self.store.conn.execute("SELECT count(*) FROM claims").fetchone()[0]

    def test_a_profile_address_ties_the_row_on_any_host(self):
        """A profile address of a person in the network puts the row with that person, whatever host and form it has."""
        forms = [f"http://127.0.0.1:8765/people/{self.ann}", f"https://other.example/people/{self.ann.upper()}/",
                 f"https://other.example/people/{self.ann}?x=1#top"]
        found = self.upload(csv_bytes(*[f"Ann Fictive,,,,{f}" for f in forms], header=PROFILE_HEADER))
        self.assertEqual(found.counts, {"new": 0, "update": 3, "name_match": 0, "skipped": 0})
        self.assertEqual({r.person_id for r in found.rows}, {self.ann})
        before = (self.people_count(), self.claim_count())
        importer.confirm(self.worker, found.import_id, set(), T0)
        self.assertEqual((self.people_count(), self.claim_count()), before)

    def test_a_profile_outside_the_network_adds_that_person_as_new(self):
        """A profile of a stored person outside the network is new once, and a second row with it joins the first."""
        found = self.upload(csv_bytes(f"Bo Madeup,,,,https://x.example/people/{self.bo}",
                                      f"Bo Madeup,,bo@example.org,,https://x.example/people/{self.bo}",
                                      header=PROFILE_HEADER))
        first, second = found.rows
        self.assertEqual((first.outcome, first.person_id, second.outcome, second.person_id),
                         ("new", self.bo, "update", self.bo))
        self.assertIn("Row 2 has the same profile address, so FN adds it to the same person.", second.message)
        before = self.people_count()
        importer.confirm(self.worker, found.import_id, set(), T0)
        self.assertEqual(self.people_count(), before)
        self.assertEqual(self.store.get_persons([self.bo])[self.bo].list_status, "in_list")

    def test_a_profile_that_agrees_with_the_identifier_counts_once(self):
        """A person outside the network with his ORCID and his own address is new once, then update."""
        dee = self.person("Dee Madeup", ("orcid", "https://orcid.org/0000-0001-2345-6789"))
        first, second = self.rows(f"Dee Madeup,0000-0001-2345-6789,,,https://x.example/people/{dee}",
                                  f"Dee Madeup,0000-0001-2345-6789,dee@example.org,,https://x.example/people/{dee}")
        self.assertEqual((first.outcome, second.outcome, first.person_id), ("new", "update", dee))

    def test_a_merged_record_counts_as_its_person(self):
        """An address of a record merged into another person puts the row with that person when the names agree."""
        self.store.set_merged_into(self.bo, self.ann, T0)
        (row,) = self.rows(f"Ann Fictive,,,,https://x.example/people/{self.bo}")
        self.assertEqual((row.outcome, row.person_id), ("update", self.ann))

    def test_a_cell_that_is_no_profile_address_is_said_and_ignored(self):
        """Each unread form is said in the row and ignored; the name rules decide, and the column is not ignored."""
        for cell in (f"https://x.example/searches/{self.ann}", self.ann, f"ftp://x.example/people/{self.ann}",
                     "http://[::1", f"'https://x.example/people/{self.ann}"):
            with self.subTest(cell=cell):
                found = self.upload(csv_bytes(f"Ann Fictive,,,,{cell}", header=PROFILE_HEADER))
                (row,) = found.rows
                self.assertEqual((row.outcome, row.person_id, row.message), ("name_match", self.ann,
                                                                          importer.NOT_PROFILE))
                self.assertEqual(found.ignored_columns, [])
        (row,) = self.rows("Ann Fictive,,,,https://x.example/people/00000000-0000-4000-8000-000000000000")
        self.assertEqual((row.outcome, row.message), ("name_match", importer.NO_PROFILE))
        (row,) = self.rows("Ann Fictive,,,,")
        self.assertEqual((row.outcome, row.message), ("name_match", ""))
        with self.assertRaises(importer.ImportRefused) as raised:
            self.upload(b"profile\nhttps://x.example/people/" + self.ann.encode())
        self.assertEqual(str(raised.exception), importer.NO_NAME.format(file="people.csv"))

    def test_a_changed_name_does_not_use_the_profile(self):
        """A row whose name is not the profile person's name is not tied; a case or initial difference still is."""
        address = f"https://x.example/people/{self.ann}"
        other, same = self.rows(f"Ann Other,,,,{address}", f"ann fictive q.,,,,{address}")
        self.assertEqual((other.outcome, other.person_id), ("new", None))
        self.assertEqual(other.message, importer.OTHER_NAME.format(name="Ann Fictive"))
        self.assertEqual((same.outcome, same.person_id), ("update", self.ann))

    def test_an_identifier_decides_first_and_a_clash_skips_the_row(self):
        """An identifier and a profile of one person agree; of two people, the row is skipped with both named."""
        ann_address = f"https://x.example/people/{self.ann}"
        self.store.add_identifier(self.cy, Identifier(scheme="email", value="cy@example.org"))
        agree, orcid, email = self.rows(
            f"Cy Invented,0000-0002-1825-0097,,,https://x.example/people/{self.cy}",
            f"Ann Fictive,0000-0002-1825-0097,,,{ann_address}", f"Ann Fictive,,cy@example.org,,{ann_address}")
        self.assertEqual((agree.outcome, agree.message), ("update", ""))
        self.assertEqual((orcid.outcome, orcid.message), ("skipped",
            "Row 3's ORCID belongs to Cy Invented and its profile address to Ann Fictive, so FN skips it."))
        self.assertEqual((email.outcome, email.message), ("skipped",
            "Row 4's email address belongs to Cy Invented and its profile address to Ann Fictive, so FN skips it."))

    def test_an_employer_written_as_its_organizations_name_adds_no_claim(self):
        """A claim worded "Example Labs Inc" and linked to the org "Example Labs" holds the row's organization."""
        text = "Example Labs Inc"
        source = Source(id="src-ann", kind="page", url="https://example.org/ann", title="Example page", text=text,
                        content_hash="h-ann")
        self.store.upsert_source(source)
        org = Org(id="ror:0abc12399", name="Example Labs", source_id=source.id, fetched_at=T0)
        self.store.upsert_org(org, replace=True)
        self.store.upsert_claim(ClaimDraft(person_id=self.ann, kind="affiliation", value=text, quote=text,
                                           quote_start=0, quote_end=len(text), source=source, org_id=org.id,
                                           relation="works_at"), T0)
        found = self.upload(csv_bytes(f"Ann Fictive,,,Example Labs,https://x.example/people/{self.ann}",
                                      header=PROFILE_HEADER))
        before = self.claim_count()
        importer.confirm(self.worker, found.import_id, set(), T0)
        self.assertEqual(self.claim_count(), before)

    def test_a_five_megabyte_file_of_profile_addresses_previews_with_its_first_row_recognized(self):
        """A file near the size cap, every row with a profile address, previews and its first row is tied."""
        lines = [f"Ann Fictive,,,,https://x.example/people/{self.ann}"] + [
            f"Person {n:05d} Example,,,,https://x.example/people/{uuid.uuid4()}" for n in range(60000)]
        raw = csv_bytes(*lines, header=PROFILE_HEADER)
        self.assertLess(len(raw), importer.MAX_BYTES)
        found = self.upload(raw)
        self.assertEqual(found.rows[0].outcome, "update")
        self.assertEqual(len(found.rows), 60001)


if __name__ == "__main__":
    unittest.main()
