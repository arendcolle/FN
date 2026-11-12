import csv
import io
import re
import unittest
from html import unescape

from fastapi.testclient import TestClient

from fn import network
from fn.contracts import Candidate, Identifier, Search
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

FETCH = {"X-Requested-With": "fetch"}


class CardActionsTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False,
                                 follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def person(self, name: str, key: str, member: bool = False, scheme: str = "seed") -> str:
        person_id = self.store.resolve_person([Identifier(scheme=scheme, value=key)], name).id
        if member:
            network.add(self.store, [person_id], via="import", now=now())
        return person_id

    def search(self, search_id: str, cards: list[tuple[list[str], str]], cut: list[str] = ()) -> str:
        """A done search whose kept candidates are (hit person ids, section), in rank order, then the cut ids."""
        self.store.create_search(Search(id=search_id, question="q", status="done", created_at=now(), code_sha=None,
                                        dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        rows = [Candidate(search_id=search_id, person_id=hits[0], person_ids=hits, hit_person_ids=hits, section=section,
                          rank=n, score=1.0, lane_ranks={"seeds": n}) for n, (hits, section) in enumerate(cards, 1)]
        rows += [Candidate(search_id=search_id, person_id=p, person_ids=[p], hit_person_ids=[p], section="new",
                           rank=len(rows) + n, score=0.1, lane_ranks={"openalex": 1}, cut_reason="no_belgian_evidence")
                 for n, p in enumerate(cut, 1)]
        self.store.save_candidates(search_id, rows, [])
        return search_id

    def page(self, search_id: str, **params) -> str:
        response = self.client.get(f"/searches/{search_id}", params=params)
        self.assertEqual(response.status_code, 200)
        return unescape(response.text)

    def card(self, html: str, key: str) -> str:
        """The card element with id card-<key> in the page."""
        match = re.search(rf'<article [^>]*id="card-{key}".*?</article>', html, re.DOTALL)
        self.assertIsNotNone(match, f"no card {key}")
        return match.group(0)

    def act(self, search_id: str, key: str, action: str, **fields) -> str:
        """POST a card's button as results.js does and return the card it gets back."""
        response = self.client.post(f"/searches/{search_id}/people/{key}/{action}", data=fields, headers=FETCH)
        self.assertEqual(response.status_code, 200, response.text[:300])
        return unescape(response.text)

    def buttons(self, html: str) -> list[str]:
        return re.findall(r'<button type="submit" class="fn-btn[^"]*">([^<]+)<', html)

    def undo(self, html: str) -> None:
        event_id = re.search(r'action="/events/([^"]+)/undo"', html).group(1)
        self.assertEqual(self.client.post(f"/events/{event_id}/undo", data={"next": "/searches/s1"}).status_code, 303)

    def test_a_card_shows_the_buttons_of_its_state(self):
        """A new card has Add and Skip, a network card none, and a card whose name a network person has the three
        same-name buttons under a link to that person."""
        ada, bob = self.person("Ada Example", "ada", member=True), self.person("Bob Example", "bob")
        twin = self.person("Ada Example", "ada-2")
        html = self.page(self.search("s1", [([ada], "network"), ([bob], "new"), ([twin], "new")]))
        self.assertEqual(self.buttons(self.card(html, ada)), [])
        self.assertEqual(self.buttons(self.card(html, bob)), ["Add", "Skip"])
        twin_card = self.card(html, twin)
        self.assertEqual(self.buttons(twin_card), ["Same person", "Add as new", "Skip"])
        self.assertIn(f'Same name as <a href="/people/{ada}">Ada Example</a> in your network', twin_card)

    def test_add_puts_the_person_in_the_network_once_with_where_it_was_decided(self):
        """Add sets the person in the network and writes one event with the search, rank and section; the card
        reads 'Added to your network' with Undo. A second Add changes nothing."""
        ada, bob = self.person("Ada Example", "ada"), self.person("Bob Example", "bob")
        self.search("s1", [([ada], "new"), ([bob], "new")])
        card = self.act("s1", bob, "add")
        self.assertIn('<span class="fn-done text-strong">Added to your network</span>', card)
        self.assertIn(">Undo</button>", card)
        self.assertEqual(self.store.get_persons([bob])[bob].list_status, "in_list")
        self.act("s1", bob, "add")
        (event,) = self.store.events_of(bob)
        self.assertEqual((event.kind, event.search_id, event.rank, event.section), ("add", "s1", 2, "new"))
        self.assertIn("Added to your network", self.card(self.page("s1"), bob))

    def test_add_merges_the_hits_and_leaves_a_conflicting_hit_apart(self):
        """Add on a two-record card merges a record without a veto; a record with another ORCID stays apart and
        the card says '· 1 possible match', linking to the profile's matches."""
        ada, mention = self.person("Ada Example", "ada"), self.person("Ada Example", "ada page", scheme="mention")
        bob, other = self.person("Bob Example", "bob"), self.person("Bob Example", "bob-2")
        self.store.add_identifier(bob, Identifier(scheme="orcid", value="0000-0001"))
        self.store.add_identifier(other, Identifier(scheme="orcid", value="0000-0002"))
        self.search("s1", [([ada, mention], "new"), ([bob, other], "new")])
        self.act("s1", ada, "add")
        self.assertEqual(self.store.canonical_ids([mention])[mention], ada)
        card = self.act("s1", bob, "add")
        self.assertEqual(self.store.canonical_ids([other])[other], other)
        self.assertIn(f'<span class="text-body">·</span><a class="text-body" href="/people/{bob}#matches">'
                      '1 possible match</a>', card)

    def test_same_person_merges_and_add_as_new_keeps_them_apart(self):
        """Same person merges the card into the network person; Add as new adds the card and stores the pair as
        different people. Each card names what happened and keeps its same-name line."""
        ada, twin = self.person("Ada Example", "ada", member=True), self.person("Ada Example", "ada-2")
        bob, other = self.person("Bob Example", "bob", member=True), self.person("Bob Example", "bob-2")
        self.search("s1", [([twin], "new"), ([other], "new")])
        same = self.act("s1", twin, "same", match=ada)
        self.assertEqual(self.store.canonical_ids([twin])[twin], ada)
        self.assertIn("· same person as Ada Example", same)
        self.assertIn("Same name as <a", same)
        apart = self.act("s1", other, "new", match=bob)
        self.assertEqual(self.store.get_persons([other])[other].list_status, "in_list")
        self.assertEqual(self.store.not_same_pairs([other]), {frozenset((bob, other))})
        self.assertIn("· as a new person", apart)
        self.assertIn(f'Same name as <a href="/people/{bob}">Bob Example</a> in your network', apart)

    def test_skip_shrinks_the_card_here_and_hides_the_person_elsewhere(self):
        """A person skipped on this search is the one-line card with Undo; another search hides them and counts
        them, ?skipped=1 shows them, and Undo brings the card back."""
        ada, bob = self.person("Ada Example", "ada"), self.person("Bob Example", "bob")
        self.search("s1", [([ada], "new"), ([bob], "new")])
        self.search("s2", [([ada], "new"), ([bob], "new")])
        card = self.act("s1", bob, "skip")
        self.assertIn("fn-card fn-card--skipped", card)
        self.assertIn("Skipped Bob Example ", card)
        self.assertIn(">Undo</button>", card)
        here = self.page("s1")
        self.assertIn("Skipped Bob Example", here)
        self.assertIn("1 person · 1 not on the map · Export", re.sub("<[^>]+>", "", here))
        other = self.page("s2")
        self.assertNotIn(f'id="card-{bob}"', other)
        self.assertIn('<span>1 skipped person hidden</span><a class="fn-link" href="/searches/s2?skipped=1">Show</a>',
                      other)
        shown = self.page("s2", skipped="1")
        self.assertIn("Skipped Bob Example", self.card(shown, bob))
        self.assertIn('<span>1 skipped person shown</span><a class="fn-link" href="/searches/s2">Hide</a>', shown)
        self.undo(card)
        self.assertEqual(self.buttons(self.card(self.page("s2"), bob)), ["Add", "Skip"])

    def test_a_fetch_gets_the_card_and_a_form_post_goes_back_to_the_card(self):
        """With the fetch header the answer is the card's HTML; without it a 303 to the results page at the card."""
        ada = self.person("Ada Example", "ada")
        self.search("s1", [([ada], "new")])
        card = self.act("s1", ada, "skip")
        self.assertTrue(card.startswith(f'<article class="fn-card fn-card--skipped" id="card-{ada}">'))
        bob = self.person("Bob Example", "bob")
        self.search("s2", [([bob], "new")])
        response = self.client.post(f"/searches/s2/people/{bob}/add", data={"next": "/searches/s2?shown=100"})
        self.assertEqual((response.status_code, response.headers["location"]), (303, f"/searches/s2?shown=100#card-{bob}"))
        response = self.client.post(f"/searches/s2/people/{bob}/add", data={"next": "https://example.org/"})
        self.assertEqual(response.headers["location"], f"/searches/s2#card-{bob}")

    def test_the_page_shows_twenty_kept_people_at_a_time(self):
        """20 cards by default and 40 with ?shown=40; a shown that is not a positive number is 20. The count
        is of kept people who are not skipped, and a cut candidate never shows."""
        people = [self.person(f"Person {n:03}", f"p{n}") for n in range(120)]
        cut, gone = self.person("Cut Example", "cut"), self.person("Gone Example", "gone")
        network.skip(self.store, [gone], now=now(), search_id="elsewhere")
        self.search("s1", [*[([p], "new") for p in people], ([gone], "new")], cut=[cut])
        first = self.page("s1")
        self.assertEqual(first.count('class="fn-card"'), 20)
        self.assertIn(f'<span>20 of 120 shown</span><a class="fn-btn fn-btn--quiet text-control" '
                      f'href="/searches/s1?shown=40#card-{people[20]}">Show 20 more</a>', first)
        self.assertEqual(self.page("s1", shown="40").count('class="fn-card"'), 40)
        for bad in ("abc", "0", "-1"):
            self.assertEqual(self.page("s1", shown=bad).count('class="fn-card"'), 20)
        everyone = self.page("s1", shown="1000")
        self.assertEqual(everyone.count('class="fn-card"'), 120)
        self.assertNotIn("Cut Example", everyone)
        self.assertNotIn("of 120 shown", everyone)

    def test_an_old_search_shows_who_was_added_since(self):
        """A search stored before a person was added shows that person's card as added."""
        ada = self.person("Ada Example", "ada")
        self.search("s1", [([ada], "new")])
        network.add(self.store, [ada], via="profile", now=now())
        self.assertIn("Added to your network", self.card(self.page("s1"), ada))

    def test_the_export_of_a_search_has_one_row_per_kept_person_who_is_not_skipped(self):
        """The CSV holds the kept people of the search, not the cut ones nor the skipped ones."""
        ada, bob = self.person("Ada Example", "ada"), self.person("Bob Example", "bob")
        cut, gone = self.person("Cut Example", "cut"), self.person("Gone Example", "gone")
        network.skip(self.store, [gone], now=now())
        self.search("s1", [([ada], "new"), ([bob], "new"), ([gone], "new")], cut=[cut])
        response = self.client.get("/searches/s1/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.headers["content-disposition"], r'filename="fn-search-\d{4}-\d{2}-\d{2}\.csv"')
        rows = list(csv.DictReader(io.StringIO(response.text.lstrip("﻿"))))
        self.assertEqual(sorted(r["name"] for r in rows), ["Ada Example", "Bob Example"])

    def test_an_unknown_search_or_person_is_404(self):
        """The card routes and the export answer 404 for a search or a person that is not there, a cut person
        included, and change nothing; the search's own person gets an answer."""
        ada, cut = self.person("Ada Example", "ada"), self.person("Cut Example", "cut")
        self.search("s1", [([ada], "new")], cut=[cut])
        for path in (f"/searches/nope/people/{ada}/add", "/searches/s1/people/nope/skip",
                     f"/searches/s1/people/{cut}/add", f"/searches/s1/people/{ada}/explode"):
            self.assertEqual(self.client.post(path, data={}).status_code, 404, path)
        self.assertEqual(self.client.get("/searches/nope/export.csv").status_code, 404)
        self.assertEqual(self.store.events_of(ada) + self.store.events_of(cut), [])
        self.assertEqual(self.client.post(f"/searches/s1/people/{ada}/skip", data={}).status_code, 303)


if __name__ == "__main__":
    unittest.main()
