import unittest
from datetime import UTC, date, datetime, timedelta

from fn import network, orgs, present
from fn.contracts import (
    Candidate,
    Claim,
    ClaimDraft,
    Identifier,
    Org,
    OrgFacts,
    Search,
    Source,
)
from fn.worker import now
from tests.helpers import make_db

TODAY = date(2026, 11, 12)
LEUVEN = Org(id="ror:05f950310", name="KU Leuven", country_code="BE", source_id="org", fetched_at=now())


def source(kind: str = "page", title: str | None = "Lab people", url: str = "https://example.org/lab") -> Source:
    return Source(id=f"src-{kind}", kind=kind, url=url, title=title, text="Anne Example, KU Leuven", content_hash="h")


def claim(kind: str = "affiliation", value: str = "KU Leuven", **fields) -> Claim:
    fields = {"source_id": "src-page", "quote": "Anne Example, KU Leuven", "quote_start": 0, "quote_end": 23} | fields
    return Claim(id="c1", person_id="p1", kind=kind, value=value, **fields)


class ClaimViewTest(unittest.TestCase):
    def test_each_kind_and_relation_reads_as_one_plain_line(self):
        """A relation reads as its verb and the stored org's name, else the value; other kinds as the table says.

        A role and an availability keep their value as it is.
        """
        rows = [
            (claim(relation="studied_at", org_id=LEUVEN.id, value="Katholieke Universiteit Leuven"), LEUVEN,
             "Studied at KU Leuven"),
            (claim(relation="works_at", value="Columbia University"), None, "Works at Columbia University"),
            (claim(relation="worked_at", value="imec"), None, "Worked at imec"),
            (claim(relation="affiliated_with"), None, "Affiliated with KU Leuven"),
            (claim(relation="hosted_by", value="MIT"), None, "Hosted by MIT"),
            (claim(relation="member_of", value="KVAB"), None, "Member of KVAB"),
            (claim(relation="fellow_of", value="Example Foundation"), None, "Fellow of Example Foundation"),
            (claim(relation="consul_for", value="Belgium"), None, "Honorary consul for Belgium"),
            (claim("role", "Research scientist", relation="fellow_of"), None, "Research scientist"),
            (claim("topic", "6G"), None, "Field: 6G"),
            (claim("location", "Leuven", relation="born_in"), None, "Born in Leuven"),
            (claim("location", "Boston", relation="lives_in"), None, "Based in Boston"),
            (claim("location", "Boston"), None, "Based in Boston"),
            (claim("email", "anne@example.org"), None, "Email: anne@example.org"),
            (claim("phone", "+1 555 0100"), None, "Phone: +1 555 0100"),
            (claim("availability", "Open to mentoring"), None, "Open to mentoring"),
        ]
        for found, org, what in rows:
            with self.subTest(what=what):
                self.assertEqual(present.claim_view(found, source(), org).what, what)

    def test_a_record_gives_a_citation_and_a_page_gives_its_quote(self):
        """Only a prose source gives a quote; every source gives the label, the source link and the date."""
        record = present.claim_view(claim(claim_date="2025", date_precision="year"),
                                    source("record", "OpenAlex author Anne Example", "https://openalex.org/A1"), None)
        self.assertIsNone(record.quote)
        self.assertEqual((record.label, record.href, record.date),
                         ("OpenAlex record", "/sources/src-page?claim=c1#quote", "2025"))
        page = present.claim_view(claim(quote='Anne "the engineer" Example'), source("vendor_page"), None)
        self.assertEqual(page.quote.text, "“Anne 'the engineer' Example”")
        self.assertEqual((page.quote.label, page.quote.date, page.label), ("Lab people", "date unknown", "Lab people"))
        labels = {"vendor_record": "LinkedIn record", "staff": "Entered in FN", "seed_page": "Lab people"}
        for kind, label in labels.items():
            with self.subTest(kind=kind):
                self.assertEqual(present.claim_view(claim(), source(kind), None).label, label)
        imported = Source(id="i", kind="import", url="fn:import/x#row-14", title="contacts.csv, row 14", text="a", content_hash="h")
        self.assertEqual(present.claim_view(claim(), imported, None).label, "Import contacts.csv, row 14")
        self.assertEqual(present.claim_view(claim(), source(title=None), None).label, "example.org")

    def test_years_read_as_runs(self):
        """A span reads 'from–to', separate years are joined by a comma, and an undated claim has no years."""
        self.assertEqual(present.claim_view(claim(valid_from="2008", valid_to="2013"), source(), None).years, "2008–2013")
        self.assertEqual(present.claim_view(claim(years=[2001, 2008]), source(), None).years, "2001, 2008")
        self.assertEqual(present.claim_view(claim(), source(), None).years, "")

    def test_a_claim_is_new_only_when_stored_after_seen_at(self):
        """is_new needs a seen_at and a first_seen_at later than it."""
        seen = datetime(2026, 11, 1, tzinfo=UTC)
        self.assertTrue(present.claim_view(claim(first_seen_at=seen + timedelta(days=1)), source(), None, seen).is_new)
        self.assertFalse(present.claim_view(claim(first_seen_at=seen - timedelta(days=1)), source(), None, seen).is_new)
        self.assertFalse(present.claim_view(claim(first_seen_at=seen), source(), None).is_new)


class PersonViewsTest(unittest.TestCase):
    def setUp(self):
        self.store = make_db(self)
        self.count = 0

    def person(self, key: str, name: str = "Anne Example") -> str:
        return self.store.resolve_person([Identifier(scheme="seed", value=key)], name).id

    def claim(self, person_id: str, kind: str, value: str, *, source_kind: str = "page", title: str | None = "Lab",
              at: datetime | None = None, **fields) -> Claim:
        self.count += 1
        text = f"{value} quoted"
        found = Source(id=f"src-{self.count}", kind=source_kind, url=f"https://example.org/{self.count}", title=title,
                       text=text, content_hash=f"h{self.count}")
        return self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, value=value, quote=text, quote_start=0,
                                                  quote_end=len(text), source=found, **fields), at)

    def view(self, *ids: str):
        (found,) = present.person_views(self.store, [list(ids)], TODAY)
        return found

    def test_the_place_is_the_newest_dated_one_with_coordinates_and_never_a_birthplace(self):
        """A dated place with coordinates beats a newer undated one; an undated one with coordinates comes next.

        Without coordinates the newest place gives the text only, and a born_in claim never places anyone.
        """
        dated = self.person("dated")
        self.claim(dated, "location", "Boston, MA", claim_date="2020", lat=42.36, lon=-71.06)
        self.claim(dated, "location", "Leuven", claim_date="2025", relation="born_in", lat=50.88, lon=4.7)
        self.claim(dated, "location", "Gent", lat=51.05, lon=3.72)
        self.assertEqual((self.view(dated).place, self.view(dated).lat), ("Boston, MA", 42.36))
        undated = self.person("undated")
        self.claim(undated, "location", "Gent", lat=51.05, lon=3.72)
        self.claim(undated, "location", "Leuven", relation="born_in", lat=50.88, lon=4.7)
        self.assertEqual((self.view(undated).place, self.view(undated).lon), ("Gent", 3.72))
        text = self.person("text")
        self.claim(text, "location", "Somewhere, NY", claim_date="2024")
        self.claim(text, "location", "Leuven", relation="born_in", claim_date="2025")
        self.assertEqual((self.view(text).place, self.view(text).lat), ("Somewhere, NY", None))
        born = self.person("born")
        self.claim(born, "location", "Leuven", relation="born_in", lat=50.88, lon=4.7)
        self.assertIsNone(self.view(born).place)

    def test_an_origin_claim_reads_as_origin_and_never_becomes_the_place(self):
        """An origin claim such as Belgian is a fact line 'Origin: Belgian', even with coordinates, and places nobody."""
        origin = self.person("origin")
        self.claim(origin, "location", "Belgian", relation="origin", lat=50.5, lon=4.4)
        self.assertIsNone(self.view(origin).place)
        self.assertEqual(present.what_of(self.store.claims_of([origin])[0], None), "Origin: Belgian")
        both = self.person("both")
        self.claim(both, "location", "Belgian", relation="origin")
        self.claim(both, "location", "Boston", relation="lives_in", lat=42.36, lon=-71.06)
        self.assertEqual(self.view(both).place, "Boston")

    def test_the_role_is_a_job_not_a_seed_list_or_a_page_title(self):
        """A seed list role and a web-page role equal to the page title or host are skipped for the newest job."""
        anne = self.person("anne")
        self.claim(anne, "role", "Research scientist", claim_date="2020")
        self.claim(anne, "role", "Fellow 2024", claim_date="2024", relation="fellow_of")
        self.claim(anne, "role", "Lab", claim_date="2025", source_kind="vendor_page")
        self.claim(anne, "role", "example.org", claim_date="2025", source_kind="vendor_page", title=None)
        self.assertEqual(self.view(anne).role, "Research scientist")
        bob = self.person("bob", "Bob Example")
        self.claim(bob, "role", "Lab", source_kind="vendor_page")
        self.assertIsNone(self.view(bob).role)

    def test_a_card_reads_only_the_records_a_lane_hit(self):
        """A candidate's same-name record that no lane hit adds nothing to its card."""
        hit, other = self.person("hit"), self.person("other")
        self.claim(hit, "affiliation", "Columbia University", relation="works_at", claim_date="2020")
        self.claim(other, "affiliation", "Elsewhere Inc", relation="works_at", claim_date="2025")
        search = Search(id="s1", question="q", status="done", created_at=now(), code_sha=None, dirty=False,
                        llm_mode="replay", settings_json="{}", boot_id="b")
        self.store.create_search(search)
        self.store.save_candidates("s1", [Candidate(
            search_id="s1", person_id=hit, person_ids=[hit, other], section="new", rank=1, score=1.0,
            lane_ranks={"seeds": 1}, hit_person_ids=[hit])], [])
        found = present.results(self.store, search, TODAY)
        self.assertEqual(([v.person_id for v in found.new], found.network), ([hit], []))
        self.assertEqual(found.new[0].employer, "Columbia University")

    def test_a_merged_record_reads_as_its_person(self):
        """An id merged into another person gives that person's view with the claims of both records."""
        anne, record = self.person("anne"), self.person("record")
        self.claim(record, "affiliation", "Columbia University", relation="works_at")
        self.store.set_merged_into(record, anne, now())
        found = self.view(record)
        self.assertEqual((found.person_id, found.employer), (anne, "Columbia University"))

    def test_new_facts_count_claims_stored_after_the_person_was_last_seen(self):
        """A network person counts the claims first stored after seen_at; a person outside the network counts none."""
        added_at = datetime(2026, 11, 3, 12, tzinfo=UTC)
        anne = self.person("anne")
        self.claim(anne, "topic", "6G", at=added_at - timedelta(days=1))
        network.add(self.store, [anne], via="profile", now=added_at)
        self.claim(anne, "topic", "radio", at=added_at + timedelta(days=1))
        self.claim(anne, "email", "anne@example.org", at=added_at + timedelta(days=2))
        found = self.view(anne)
        self.assertEqual((found.status, found.new_facts, found.added), ("in_list", 2, "3 November 2026"))
        self.assertEqual(found.email, "anne@example.org")
        bob = self.person("bob", "Bob Example")
        self.claim(bob, "topic", "6G", at=added_at + timedelta(days=1))
        self.assertEqual((self.view(bob).new_facts, self.view(bob).added), (0, None))

    def test_the_card_lists_three_belgian_organizations_and_counts_the_rest(self):
        """The first three Belgian organizations show with their first and last year, and more_orgs counts the rest."""
        names = ["ULB", "KU Leuven", "VUB", "UGent"]
        ids = ["ror:01r9htc13", "ror:05f950310", "ror:006e5kg04", "ror:00cv9y106"]
        record = Source(id="org", kind="record", url="https://ror.org/x", text="id", content_hash="h0", fetched_at=now())
        orgs.save(self.store, [OrgFacts(id=i, name=n, country_code="BE") for i, n in zip(ids, names)], record,
                  replace=True)
        anne = self.person("anne")
        for n, (org_id, name) in enumerate(zip(ids, names)):
            self.claim(anne, "affiliation", name, relation="worked_at", org_id=org_id, valid_from=str(2001 + 4 * n),
                       valid_to=str(2003 + 4 * n), claim_date=str(2003 + 4 * n), source_kind="record")
        found = self.view(anne)
        self.assertEqual([(o.org, o.years) for o in found.orgs],
                         [("ULB", "2001–2003"), ("KU Leuven", "2005–2007"), ("VUB", "2009–2011")])
        self.assertEqual(found.more_orgs, 1)
        self.assertEqual((found.evidence.what, found.evidence.years, found.evidence.label, found.evidence.quote),
                         ("Worked at UGent", "2013–2015", "OpenAlex record", None))


if __name__ == "__main__":
    unittest.main()
