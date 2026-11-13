import re
import unittest
from datetime import timedelta
from html import unescape

from fastapi.testclient import TestClient

from fn import network
from fn.contracts import ClaimDraft, Identifier, Org, PersonView, Source
from fn.web.app import create_app
from fn.web.parts import person_card
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

EARLIER = now() - timedelta(days=2)
GENT_UNI = Org(id="ror:00cv9y106", name="Gent University", country_code="BE", source_id="org-src", fetched_at=EARLIER)


class PersonPageTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False,
                                 follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store.upsert_source(Source(id="org-src", kind="page", url="https://example.org/orgs", text="orgs",
                                        content_hash="h-orgs"))
        self.store.upsert_org(GENT_UNI, replace=True)
        self.n = 0

    def claim(self, person_id: str, kind: str, value: str, at=None, title: str = "Example page",
              source_kind: str = "page", **fields) -> str:
        """A claim from its own source, first seen at at (default EARLIER); returns the claim id."""
        self.n += 1
        text = f"{value} of {person_id} {self.n}"
        source = Source(id=f"src-{self.n}", kind=source_kind, url=f"https://example.org/{self.n}", title=title,
                        text=text, content_hash=f"h-{self.n}")
        return self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, value=value, quote=text,
                                                  quote_start=0, quote_end=len(text), source=source, **fields),
                                       at or EARLIER).id

    def person(self, name: str, key: str, member: bool = True) -> str:
        person_id = self.store.resolve_person([Identifier(scheme="seed", value=key)], name).id
        if member:
            network.add(self.store, [person_id], via="search", now=EARLIER)
        return person_id

    def page(self, person_id: str, **params) -> str:
        response = self.client.get(f"/people/{person_id}", params=params)
        self.assertEqual(response.status_code, 200)
        return unescape(response.text)

    def post(self, path: str, **fields) -> str:
        """POST the form and return where it redirects."""
        response = self.client.post(path, data=fields)
        self.assertEqual(response.status_code, 303, response.text[:300])
        return response.headers["location"]

    def undo_id(self, html: str) -> str:
        return re.search(r'action="/events/([^"]+)/undo"', html).group(1)

    def test_a_network_persons_page_shows_head_contact_and_groups_in_order(self):
        """The head names the person with their role line and network date; contact, then the three fact groups.

        A person with one record has no Found as.
        """
        ada = self.person("Ada Example", "ada")
        self.claim(ada, "location", "Gent", relation="lives_in")
        self.claim(ada, "affiliation", "Example Labs", relation="works_at")
        self.claim(ada, "affiliation", "Gent University", relation="studied_at", org_id=GENT_UNI.id)
        html = self.page(ada)
        self.assertIn('<h1 class="fn-profile__name text-name">Ada Example</h1>', html)
        self.assertIn('<p class="fn-profile__role text-body">Example Labs · Gent</p>', html)
        self.assertIn(f"In your network since {EARLIER.astimezone().day} {EARLIER.astimezone():%B %Y}", html)
        self.assertEqual(html.count("Not provided"), 2)
        headings = re.findall(r'<h2 class="fn-section text-label"[^>]*>([^<]+)</h2>', html)
        self.assertEqual(headings, ["Contact", "Ties to Belgium", "Work", "Places"])
        self.assertIn("Studied at Gent University", html)
        self.assertNotIn("Found as", html)

    def test_a_fact_from_two_sources_shows_once_with_the_newer_citation(self):
        """Claims with one kind, relation and value are one line, cited by the newest, with the years of both."""
        ada = self.person("Ada Example", "ada")
        self.claim(ada, "affiliation", "Example Labs", relation="works_at", title="Older page", claim_date="2019")
        self.claim(ada, "affiliation", "Example Labs", relation="works_at", title="Newer page", claim_date="2024")
        html = self.page(ada)
        self.assertEqual(html.count("Works at Example Labs"), 1)
        self.assertIn('Works at Example Labs, <span class="text-year">2019, 2024</span>', html)
        self.assertIn(">Newer page</a>, 2024", html)
        self.assertNotIn("Older page", html)

    def test_new_marks_show_once_and_only_a_network_person_moves_seen_at(self):
        """A fact stored after seen_at is New on the first visit and not on the second; a candidate's seen_at stays."""
        ada = self.person("Ada Example", "ada")
        self.claim(ada, "topic", "Tidal energy", at=now() - timedelta(hours=1))
        before = self.store.get_persons([ada])[ada].seen_at
        self.assertIn('<span class="fn-new text-label">New</span>Field: Tidal energy', self.page(ada))
        self.assertGreater(self.store.get_persons([ada])[ada].seen_at, before)
        self.assertNotIn("fn-new", self.page(ada))
        bo = self.person("Bo Candidate", "bo", member=False)
        self.claim(bo, "topic", "Tidal energy", at=now() - timedelta(hours=1))
        self.assertNotIn("fn-new", self.page(bo))
        self.assertIsNone(self.store.get_persons([bo])[bo].seen_at)

    def test_an_unknown_id_is_404_and_a_merged_record_redirects_to_its_person(self):
        """An id nobody has is a 404; a record merged into another person sends a 303 to that person's page."""
        self.assertEqual(self.client.get("/people/nobody").status_code, 404)
        ada, twin = self.person("Ada Example", "ada"), self.person("Ada Example", "ada-2", member=False)
        network.merge(self.store, [twin], ada, now=now())
        response = self.client.get(f"/people/{twin}", params={"from": "row"})
        self.assertEqual((response.status_code, response.headers["location"]), (303, f"/people/{ada}?from=row"))

    def test_each_decision_shows_its_done_line_and_undo_restores_the_page(self):
        """Add, Skip, Remove, a contact edit, merge, not-same and a removed fact each show Undo; Undo puts it back."""
        ada = self.person("Ada Example", "ada")
        fact = self.claim(ada, "topic", "Tidal energy")
        bo = self.person("Bo Candidate", "bo", member=False)
        twin = self.person("Ada Example", "ada-2", member=False)
        self.claim(twin, "topic", "Wind energy")
        cases = [
            (bo, f"/people/{bo}/add", {}, "Added to your network", ">Add</button>"),
            (bo, f"/people/{bo}/skip", {}, ">Skipped</span>", ">Skip</button>"),
            (ada, f"/people/{ada}/remove", {}, "Ada Example removed from your network.", "In your network since"),
            (ada, f"/people/{ada}/contact", {"kind": "email", "value": "ada@example.org"}, " · Saved ", "Not provided"),
            (ada, f"/people/{ada}/not-same", {"other": twin}, "Marked as a different person", ">Different person<"),
            (ada, f"/people/{ada}/merge", {"other": twin}, "Merged into this profile", ">Same person<"),
            (ada, f"/claims/{fact}/reject", {}, "Field: Tidal energy · Removed", ">Remove</button>"),
        ]
        for person_id, path, fields, done, restored in cases:
            with self.subTest(path=path):
                self.assertEqual(self.post(path, next=f"/people/{person_id}", **fields), f"/people/{person_id}")
                html = self.page(person_id)
                self.assertIn(done, html)
                self.post(f"/events/{self.undo_id(html)}/undo", next=f"/people/{person_id}")
                html = self.page(person_id)
                self.assertNotIn(done, html)
                self.assertIn(restored, html)
                self.assertNotIn("/undo", html)

    def test_a_second_press_of_any_button_writes_nothing(self):
        """Each decision pressed twice in a row leaves one event, so its Undo still works."""
        ada = self.person("Ada Example", "ada")
        fact = self.claim(ada, "topic", "Tidal energy")
        bo = self.person("Bo Candidate", "bo", member=False)
        twin = self.person("Ada Example", "ada-2", member=False)
        events = self.store.conn.execute
        for path, fields in ((f"/people/{bo}/skip", {}), (f"/people/{bo}/add", {}), (f"/people/{ada}/remove", {}),
                             (f"/people/{ada}/add", {}), (f"/claims/{fact}/reject", {}),
                             (f"/people/{ada}/contact", {"kind": "phone", "value": "+32 9 555 01 00"}),
                             (f"/people/{ada}/not-same", {"other": twin}), (f"/people/{ada}/merge", {"other": bo})):
            with self.subTest(path=path):
                self.post(path, **fields)
                count = events("SELECT COUNT(*) FROM events").fetchone()[0]
                self.post(path, **fields)
                self.assertEqual(events("SELECT COUNT(*) FROM events").fetchone()[0], count)
        last = self.undo_id(self.page(ada))
        self.post(f"/events/{last}/undo")
        count = events("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(self.post(f"/events/{last}/undo"), f"/people/{ada}")
        self.assertEqual(events("SELECT COUNT(*) FROM events").fetchone()[0], count)

    def test_a_refused_contact_value_reopens_the_field_with_its_sentence(self):
        """No @, empty, 300 characters or another person's email give 400 with the sentence; a good one is saved."""
        ada = self.person("Ada Example", "ada")
        bo = self.person("Bo Example", "bo")
        network.set_contact(self.store, bo, "email", "bo@example.org", now=now())
        for value, sentence in (("no-at-sign", "Enter an email address like name@example.org."), ("", "Enter an email address like name@example.org."),
                                ("a@" + "x" * 298, "That is too long: at most 200 characters."),
                                ("bo@example.org", "Another person in FN already has this email address.")):
            with self.subTest(value=value):
                response = self.client.post(f"/people/{ada}/contact", data={"kind": "email", "value": value,
                                                                           "next": f"/people/{ada}"})
                self.assertEqual(response.status_code, 400)
                html = unescape(response.text)
                self.assertIn(f'<p class="fn-error text-small" id="contact-error">{sentence}</p>', html)
                self.assertIn('aria-invalid="true"', html)
                self.assertIn(f'value="{value}"', html)
        self.post(f"/people/{ada}/contact", kind="email", value="ada@example.org")
        html = self.page(ada)
        self.assertIn('<a href="mailto:ada@example.org">ada@example.org</a>', html)
        self.assertRegex(html, r'>Entered in FN</a>, \d+ \w+ \d{4} · Saved ')

    def test_an_undo_after_a_later_decision_comes_back_with_the_refusal_banner(self):
        """Undoing a decision that is no longer the person's latest changes nothing and shows the failed Banner."""
        ada = self.person("Ada Example", "ada")
        fact = self.claim(ada, "topic", "Tidal energy")
        self.post(f"/claims/{fact}/reject")
        removed = self.undo_id(self.page(ada))
        self.post(f"/people/{ada}/contact", kind="phone", value="+32 9 555 01 00")
        location = self.post(f"/events/{removed}/undo", next=f"/people/{ada}")
        self.assertEqual(location, f"/people/{ada}?undo=refused")
        html = self.page(ada, undo="refused")
        self.assertIn('<p class="fn-banner fn-banner--failed text-body" role="status"><span>This could not be undone, '
                      'because Ada Example changed since.</span></p>', html)
        self.assertNotIn("Tidal energy", html)

    def test_next_pointing_at_another_site_is_ignored(self):
        """Only a path on this site is followed after a decision; anything else goes to the person's page."""
        ada = self.person("Ada Example", "ada")
        for target in ("//evil.example", "https://evil.example", "/\\evil.example", "javascript:alert(1)"):
            with self.subTest(target=target):
                self.assertEqual(self.post(f"/people/{ada}/remove", next=target), f"/people/{ada}")
                self.post(f"/people/{ada}/add")
        self.assertEqual(self.post(f"/people/{ada}/remove", next="/people?q=ada"), "/people?q=ada")

    def test_a_long_group_shows_ten_facts_and_all_with_all_1(self):
        """A group with 40 facts shows 10 and 'Show 30 more'; ?all=1 shows every fact."""
        ada = self.person("Ada Example", "ada")
        for n in range(40):
            self.claim(ada, "topic", f"Topic {n:02}")
        html = self.page(ada)
        self.assertEqual(html.count('class="fn-claim"'), 10)
        self.assertIn('<span>10 of 40 shown</span><a class="fn-btn fn-btn--quiet text-control" '
                      f'href="/people/{ada}?all=1#work">Show 30 more</a>', html)
        self.assertEqual(self.page(ada, all="1").count('class="fn-claim"'), 40)

    def test_a_person_with_two_records_can_separate_one(self):
        """Found as lists each record's source; Not this person separates it and both pages exist afterwards."""
        ada, twin = self.person("Ada Example", "ada"), self.person("Ada Example", "ada-2", member=False)
        self.claim(ada, "topic", "Tidal energy", title="Ada page")
        self.claim(twin, "topic", "Wind energy", title="Twin page")
        self.claim(twin, "topic", "Solar energy", title="Twin page")
        network.merge(self.store, [twin], ada, now=now())
        html = self.page(ada)
        self.assertIn("Found as", html)
        self.assertEqual(html.count(">Not this person</button>"), 2)
        self.assertIn('Twin page</a> <span class="fn-line__meta text-meta">· 1 fact</span>', html)
        self.post(f"/people/{ada}/not-same", other=twin, next=f"/people/{ada}")
        html = self.page(ada)
        self.assertIn("Twin page · Separated", html)
        self.assertNotIn("Wind energy", html)
        self.assertIn("Wind energy", self.page(twin))

    def test_a_same_name_candidate_can_join_the_network_person(self):
        """A candidate named like a network person gets Same person, Add as new and Skip; Same person merges it.

        The merged facts show as new on the network person's page.
        """
        ada = self.person("Ada Example", "ada")
        twin = self.person("Ada Example", "ada-2", member=False)
        self.claim(twin, "topic", "Wind energy")
        html = self.page(twin)
        self.assertIn(f'Same name as <a href="/people/{ada}?back=%2Fpeople%2F{twin}">Ada Example</a> in your network', html)
        self.assertEqual(re.findall(r'class="fn-btn fn-btn--quiet text-control">([^<]+)<', html),
                         ["Same person", "Add as new", "Skip"])
        self.assertEqual(self.post(f"/people/{ada}/merge", other=twin, next=f"/people/{ada}"), f"/people/{ada}")
        self.assertIn('<span class="fn-new text-label">New</span>Field: Wind energy', self.page(ada))
        self.assertEqual(self.client.get(f"/people/{twin}").status_code, 303)

    def test_card_and_network_row_names_link_to_the_person_page(self):
        """A card's name links to the page with its search; a network row's name links to the page."""
        ada = self.person("Ada Example", "ada")
        card = person_card(PersonView(person_id=ada, name="Ada Example"), "s1")
        self.assertIn(f'<h3 class="fn-card__name text-name"><a href="/people/{ada}?search=s1&amp;from=card">'
                      'Ada Example</a></h3>', card)
        self.assertIn(f'<a href="/people/{ada}?from=row&amp;back=%2Fpeople%23person-1">Ada Example</a>',
                      self.client.get("/people").text)


if __name__ == "__main__":
    unittest.main()
