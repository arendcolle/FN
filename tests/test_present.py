import unittest
from datetime import UTC, date, datetime, timedelta

from fn import network, orgs, present
from fn.contracts import (
    Candidate,
    Chip,
    Chips,
    Claim,
    ClaimDraft,
    Identifier,
    Org,
    OrgFacts,
    Place,
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
    def test_the_day_an_undated_page_was_read_says_read(self):
        """A read date reads 'read 13 November 2026'; a page's own date and a record's date read as the date alone."""
        day = dict(claim_date="2026-11-13", date_precision="day")
        self.assertEqual(present.date_words(claim(date_method="read_date", **day)), "read 13 November 2026")
        self.assertEqual(present.date_words(claim(date_method="page_date", **day)), "13 November 2026")
        self.assertEqual(present.date_words(claim(**day)), "13 November 2026")

    def test_each_kind_and_relation_reads_as_one_plain_line(self):
        """A relation reads as its verb and the stored org's name, else the value; other kinds as the table says.

        A role and an availability keep their value as it is.
        """
        rows = [
            (claim(relation="studied_at", org_id=LEUVEN.id, value="Katholieke Universiteit Leuven"), LEUVEN,
             "Studied at KU Leuven"),
            (claim(relation="works_at", value="Columbia University"), None, "Works at Columbia University"),
            (claim(relation="worked_at", value="imec"), None, "Worked at imec"),
            (claim(relation="affiliated_with"), None, "Named at KU Leuven"),
            (claim(relation="hosted_by", value="MIT"), None, "Hosted by MIT"),
            (claim(relation="member_of", value="KVAB"), None, "Member of KVAB"),
            (claim(relation="fellow_of", value="Example Foundation"), None, "Fellow of Example Foundation"),
            (claim(relation="consul_for", value="Belgium"), None, "Consul for Belgium"),
            (claim("role", "Research scientist", relation="fellow_of"), None, "Research scientist"),
            (claim("topic", "6G"), None, "Topic: 6G"),
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
        labels = {"vendor_record": "LinkedIn record", "seed_page": "Lab people"}
        for kind, label in labels.items():
            with self.subTest(kind=kind):
                self.assertEqual(present.claim_view(claim(), source(kind), None).label, label)
        imported = Source(id="i", kind="import", url="fn:import/x#row-14", title="contacts.csv, row 14", text="a", content_hash="h")
        self.assertEqual(present.claim_view(claim(), imported, None).label, "Import contacts.csv, row 14")
        self.assertEqual(present.claim_view(claim(), source(title=None), None).label, "example.org")

    def test_years_read_as_runs(self):
        """A span reads 'from–to', also for separate years, and an undated claim has no years."""
        self.assertEqual(present.claim_view(claim(valid_from="2008", valid_to="2013"), source(), None).years, "2008–2013")
        self.assertEqual(present.claim_view(claim(years=[2001, 2008]), source(), None).years, "2001–2008")
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


class DeathFactTest(unittest.TestCase):
    setUp, person, claim = PersonViewsTest.setUp, PersonViewsTest.person, PersonViewsTest.claim

    def test_a_death_reads_died_and_its_year_once_under_work_on_the_card_reason_and_the_person_page(self):
        """A death claim is a Work fact in plain words, with no years beside the year it names."""
        person = self.person("late")
        found = self.claim(person, "death", "1966", claim_date="1966", date_precision="year", date_method="stated_in_quote")
        view = present.claim_view(found, self.store.get_sources([found.source_id])[found.source_id], None)
        self.assertEqual((view.what, view.years, view.all_years), ("Died 1966", "", ""))
        self.assertEqual(present.reason_of(view, view.href).text, "Died 1966")
        page = present.profile(self.store, person, TODAY)
        self.assertEqual([(g.title, [(f.what, f.years) for f in g.facts]) for g in page.facts], [("Work", [("Died 1966", "")])])


class ReadingTest(unittest.TestCase):
    def chip(self, text: str, need: str = "must") -> Chip:
        return Chip(text=text, origin="parsed", need=need)

    def place(self, text: str, kind: str | None, need: str = "must") -> Place:
        return Place(text=text, origin="parsed", kind=kind, need=need)

    def test_a_place_reads_as_an_area_a_region_or_the_us(self):
        """A city or metro reads as an area, a state keeps its name, a free region takes 'the', the US reads 'the US'."""
        rows = [("New York", "metro", "in the New York area"), ("Washington D.C.", None, "in the Washington D.C. area"),
                ("the Bay Area", "metro", "in the Bay Area"), ("North Carolina", "anywhere_us", "in North Carolina"),
                ("US West Coast", "anywhere_us", "in the US West Coast"), ("US", "anywhere_us", "in the US"),
                ("United States", "anywhere_us", "in the US"), ("Belgium", "abroad", "in Belgium")]
        for text, kind, words in rows:
            with self.subTest(text=text):
                self.assertEqual(present.area_words(self.place(text, kind)), words)

    def test_the_reading_splits_required_from_wished_in_the_words_of_the_question(self):
        """Roles, topics, institutions, the tie and the place stand under Required or Wished by their need."""
        must = Chips(version=2, roles=[self.chip("scientists")], tie=self.chip("Belgian"),
                     place=self.place("Washington D.C.", "metro"))
        self.assertEqual(present.reading(must), ("Required: scientists, Belgian, in the Washington D.C. area", None))
        wish = Chips(version=2, roles=[self.chip("founders")], tie=self.chip("Flemish", "nice"),
                     place=self.place("Boston", "metro"))
        self.assertEqual(present.reading(wish), ("Required: founders, in the Boston area", "Wished: Flemish"))
        only = Chips(version=2, tie=self.chip("Flemish", "nice"))
        self.assertEqual(present.reading(only), (None, "Wished: Flemish"))

    def test_the_reading_drops_softeners_repeats_and_empty_parts_and_cuts_long_ones(self):
        """'ideally' and a trailing 'if possible' go, a repeat by folded name stays once, an empty chip is skipped and a
        300-character chip is cut to 60 characters."""
        nice = Chips(version=2, tie=self.chip("ideally someone connected to Flanders", "nice"),
                     topics=[self.chip("Tides"), self.chip("tides"), self.chip("  "), self.chip("wind if possible", "nice")])
        self.assertEqual(present.reading(nice), ("Required: Tides", "Wished: wind, someone connected to Flanders"))
        long = Chips(version=2, topics=[self.chip(" ".join(["tidal"] * 60))])
        text = present.reading(long)[0].removeprefix("Required: ")
        self.assertTrue(len(text) <= 61 and text.endswith("…"), text)

    def test_there_is_no_reading_without_chips_on_version_1_or_without_a_part(self):
        """None for no chips, version 1 chips, and version 2 chips that name nothing."""
        self.assertIsNone(present.reading(None))
        self.assertIsNone(present.reading(Chips(version=1, topics=[self.chip("tides")])))
        self.assertIsNone(present.reading(Chips(version=2)))

    def test_an_outside_person_under_a_question_without_a_place_stands_in_other(self):
        """group_key sends an outside candidate to 'other' when the chips have no place; without chips the person is open."""
        outside = Candidate(search_id="s", person_id="p", person_ids=["p"], hit_person_ids=["p"], card_person_ids=["p"],
                            section="new", rank=1, score=1.0, lane_ranks={}, tier=2, aside="outside")
        self.assertEqual(present.group_key(outside, Chips(version=2)), "other")
        self.assertEqual(present.group_key(outside, Chips(version=2, place=self.place("Boston", "metro"))), "outside")
        self.assertIsNone(present.group_key(outside, None))


def value(field: str, text: str, **fields) -> present.Value:
    return present.keyed(field, text, **fields)


class CompareViewTest(unittest.TestCase):
    def view(self, left: present.Side, right: present.Side, fields=present.COMPARE_FIELDS):
        return present.compare_view(left, right, fields, ("Left", "Right"), "Caption", "Not known")

    def differs(self, field: str, left: list[present.Value], right: list[present.Value]) -> bool:
        (row,) = self.view({field: left}, {field: right}, (field,)).rows
        return row.differs

    def test_a_row_differs_only_when_no_value_on_one_side_equals_one_on_the_other(self):
        """Same organization id, same spot, case, digits and identifier forms agree; Job and Name never differ."""
        self.assertFalse(self.differs("Employer", [value("Employer", "MIT", org="ror:1")],
                                      [value("Employer", "Massachusetts Institute", org="ror:1")]))
        self.assertTrue(self.differs("Employer", [value("Employer", "MIT", org="ror:1")], [value("Employer", "MIT", org="ror:2")]))
        city = value("Place", "Cambridge, MA", spot=(42.37, -71.11))
        employer_based = value("Place", "Harvard University", spot=(42.375, -71.12))
        self.assertFalse(self.differs("Place", [city], [employer_based]))
        self.assertFalse(self.differs("Place", [city], [value("Place", "Leuven", spot=(50.88, 4.7)),
                                                         value("Place", "Boston", spot=(42.36, -71.06))]))
        self.assertTrue(self.differs("Place", [city], [value("Place", "Leuven", spot=(50.88, 4.7))]))
        self.assertTrue(self.differs("Place", [value("Place", "Cambridge, MA")], [value("Place", "Cambridge")]))
        self.assertFalse(self.differs("Place", [value("Place", "Murray Hill, NJ, USA")], [value("Place", "Murray Hill, NJ")]))
        self.assertFalse(self.differs("Email", [value("Email", "Ann@Example.org")], [value("Email", "ann@example.org")]))
        self.assertFalse(self.differs("Phone", [value("Phone", "+1 (617) 555-0101")], [value("Phone", "1 617 555 0101")]))
        self.assertFalse(self.differs("LinkedIn", [value("LinkedIn", "linkedin.com/in/ann", href="https://www.linkedin.com/in/ann")],
                                      [value("LinkedIn", "linkedin.com/in/ann", href="https://www.linkedin.com/in/ann")]))
        self.assertFalse(self.differs("ORCID", [value("ORCID", "0000-0002-1825-0097")], [value("ORCID", "0000-0002-1825-0097")]))
        self.assertTrue(self.differs("ORCID", [value("ORCID", "0000-0002-1825-0097")], [value("ORCID", "0000-0001-5109-3700")]))
        for field in ("Job", "Name"):
            self.assertFalse(self.differs(field, [value(field, "Ann")], [value(field, "Bo")]))
        self.assertFalse(self.differs("Email", [value("Email", "ann@example.org")], []))

    def test_rows_keep_order_and_a_side_shows_three_then_and_n_more(self):
        """Twelve employers give three values and 9 more, a repeated value shows once, an empty field is left out and
        the left Name has no link."""
        left = {"Employer": [value("Employer", f"Firm {n}") for n in range(12)] + [value("Employer", "firm 0")],
                "Name": [value("Name", "Ann Example", href="/people/p1")], "Job": [value("Job", "Chair")]}
        right = {"Name": [value("Name", "Ann Example", href="/people/p2")], "Found in": [value("Found in", "OpenAlex record, 2024")]}
        view = self.view(left, right)
        self.assertEqual([r.field for r in view.rows], ["Name", "Job", "Employer", "Found in"])
        name, _, employer, found = view.rows
        self.assertEqual(([v.text for v in employer.left], employer.left_more, employer.right), (["Firm 0", "Firm 1", "Firm 2"], 9, []))
        self.assertEqual((name.left[0].href, name.right[0].href), (None, "/people/p2"))
        self.assertEqual((found.left, found.right[0].text), ([], "OpenAlex record, 2024"))

    def test_one_employer_written_two_ways_does_not_differ(self):
        """An employer without an id is the one with an id when one name stands inside the other as whole words, or
        differs only by a country in brackets. Two ids of one registry still decide, and one word never matches a longer name."""
        dallas = value("Employer", "The University of Example at Springfield", org="ror:049")
        self.assertFalse(self.differs("Employer", [value("Employer", "University of Example at Springfield")], [dallas]))
        self.assertFalse(self.differs("Employer", [value("Employer", "Imec (Belgium)")], [value("Employer", "imec", org="ror:02k")]))
        self.assertFalse(self.differs("Employer", [value("Employer", "Example Labs", org="wikidata:Q1")],
                                      [value("Employer", "Example Labs", org="ror:03x")]))
        self.assertTrue(self.differs("Employer", [value("Employer", "University")], [dallas]))
        self.assertTrue(self.differs("Employer", [value("Employer", "University of Example", org="ror:01a")], [dallas]))
        self.assertTrue(self.differs("Employer", [value("Employer", "University of Example (Springfield campus)")],
                                     [value("Employer", "University of Example (Shelbyville campus)")]))

    def test_a_shared_value_shows_first_and_values_at_one_spot_show_once(self):
        """Of five employers the one the other side also holds is shown first, not hidden behind 'and 2 more', and two
        wordings of one place at one spot are one value."""
        left = {"Employer": [value("Employer", "Example Labs")],
                "Place": [value("Place", "Springfield IL", spot=(39.8, -89.65)), value("Place", "Springfield", spot=(39.8, -89.65))]}
        right = {"Employer": [value("Employer", f"Firm {n}") for n in range(4)] + [value("Employer", "Example Labs", org="ror:03x")],
                 "Place": [value("Place", "Shelbyville", spot=(39.41, -88.79))]}
        employer, place = self.view(left, right, ("Employer", "Place")).rows
        self.assertEqual(([v.text for v in employer.right], employer.right_more, employer.differs),
                         (["Example Labs", "Firm 0", "Firm 1"], 2, False))
        self.assertEqual(([v.text for v in place.left], place.left_more), (["Springfield IL"], 0))

    def test_a_shared_value_is_kept_when_it_also_matches_an_unshared_one(self):
        """A side holds a campus with an id and the bare university name. The other side holds another campus. The bare
        name is what both share, so it is the value shown, and the row does not differ."""
        left = {"Employer": [value("Employer", "University of Example, Springfield", org="ror:01a"),
                             value("Employer", "University of Example")]}
        right = {"Employer": [value("Employer", "University of Example, Shelbyville", org="ror:01b")]}
        (employer,) = self.view(left, right, ("Employer",)).rows
        self.assertEqual(([v.text for v in employer.left], employer.differs), (["University of Example"], False))


if __name__ == "__main__":
    unittest.main()
