import re
import unittest
from html import unescape
from urllib.parse import quote

from fastapi.testclient import TestClient

from fn import network
from fn.contracts import Candidate, ClaimDraft, Identifier, Search, Source
from fn.present import results, walk
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

REFUSED = ["//evil.example", "https://evil.example", "/\\evil.example", "javascript:alert(1)", "/people/" + "x" * 3000,
           "/elsewhere", "/people/unknown-person", "/searches/unknown-search"]


class WayBackTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False,
                                 follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.n = 0

    def person(self, name: str, member: bool = False, key: str | None = None) -> str:
        found = self.store.resolve_person([Identifier(scheme="seed", value=key or name)], name).id
        if member:
            network.add(self.store, [found], via="import", now=now())
        return found

    def claim(self, person_id: str, kind: str, value: str, **fields) -> str:
        self.n += 1
        text = f"{value} of {person_id}"
        source = Source(id=f"src-{self.n}", kind="page", url=f"https://example.org/{self.n}", title="Example page",
                        text=text, content_hash=f"h-{self.n}")
        return self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, value=value, quote=text, quote_start=0,
                                                  quote_end=len(text), source=source, **fields)).id

    def search(self, people: list[str | list[str]], question: str = "Example question", search_id: str = "s1",
               reasons: dict[str, list[str]] | None = None) -> str:
        """A done search whose kept candidates are the people in order; a list is one card of several records."""
        self.store.create_search(Search(id=search_id, question=question, status="done", created_at=now(), code_sha=None,
                                        dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        self.store.save_candidates(search_id, [
            Candidate(search_id=search_id, person_id=ids[0], person_ids=ids, hit_person_ids=ids[:1], card_person_ids=ids,
                      section="new", rank=n, score=1.0, lane_ranks={"seeds": n},
                      reason_claim_ids=(reasons or {}).get(ids[0], []))
            for n, ids in enumerate([p if isinstance(p, list) else [p] for p in people], 1)], [])
        return search_id

    def get(self, path: str, **params) -> str:
        response = self.client.get(path, params=params or None)
        self.assertEqual(response.status_code, 200, response.text[:300])
        return unescape(response.text)

    def back(self, html: str) -> list[str]:
        return re.findall(r'<p class="fn-back text-meta"><a href="([^"]*)">([^<]*)</a></p>', html)

    def walk_line(self, html: str) -> str:
        return re.search(r'<p class="fn-walk text-meta">(.*?)</p>', html).group(1)

    def named(self, count: int) -> list[str]:
        return [self.person(f"Person {n:02}") for n in range(1, count + 1)]

    def test_a_card_on_the_second_step_links_with_its_shown_count_and_returns_to_it(self):
        """A card's name carries the search, shown, card and origin; its page returns to that card at that count."""
        people = self.named(40)
        self.search(people)
        key = people[26]
        html = self.get("/searches/s1", shown=40)
        link = re.search(r'<h3 class="fn-card__name text-name"><a href="([^"]+)">Person 27</a>', html).group(1)
        self.assertEqual(link, f"/people/{key}?search=s1&shown=40&card={key}&from=card")
        page = self.get(link)
        self.assertEqual(self.back(page), [(f"/searches/s1?shown=40#card-{key}", "Back to the results for “Example question”")])
        first = self.get("/searches/s1")
        self.assertIn(f'href="/people/{people[0]}?search=s1&card={people[0]}&from=card"', first)

    def test_the_walk_line_covers_the_whole_list_and_passes_skipped_people(self):
        """First, middle and last of three show their line; a skipped person is passed over and left out of the count."""
        people = self.named(3)
        self.search(people)
        lines = [self.walk_line(self.get(f"/people/{p}", search="s1", card=p)) for p in people]
        self.assertEqual(lines[0], f'<span>1 of 3</span> · <a href="/people/{people[1]}?search=s1&card={people[1]}'
                                   f'&from=card" rel="next">Next</a>')
        self.assertIn(f'<span>2 of 3</span> · <a href="/people/{people[0]}', lines[1])
        self.assertIn(f'rel="prev">Previous</a> · <a href="/people/{people[2]}', lines[1])
        self.assertTrue(lines[2].startswith("<span>3 of 3</span> · <a ") and lines[2].endswith('rel="prev">Previous</a>'))
        network.skip(self.store, [people[1]], now=now())
        lines = [self.walk_line(self.get(f"/people/{p}", search="s1", card=p)) for p in (people[0], people[2])]
        self.assertIn(f'<a href="/people/{people[2]}?search=s1&card={people[2]}&from=card" rel="next">', lines[0])
        self.assertTrue(lines[0].startswith("<span>1 of 2</span>"))
        self.assertTrue(lines[1].startswith("<span>2 of 2</span>"))
        self.assertIn(f'/people/{people[0]}?', lines[1])
        skipped = self.get(f"/people/{people[1]}", search="s1", card=people[1])
        self.assertEqual(len(self.back(skipped)), 1)
        self.assertNotIn("fn-walk", skipped)

    def test_a_list_of_one_has_neither_link_and_the_first_person_does_not_start_with_a_dot(self):
        one = self.named(1)[0]
        self.search([one])
        self.assertEqual(self.walk_line(self.get(f"/people/{one}", search="s1", card=one)), "<span>1 of 1</span>")
        people = self.named(3)[1:]
        self.search(people, search_id="s2")
        line = self.walk_line(self.get(f"/people/{people[0]}", search="s2", card=people[0]))
        self.assertNotIn("Previous", line)
        self.assertTrue(line.startswith("<span>1 of 2</span> · <a "))

    def test_walk_agrees_with_the_results_order_and_counts_the_whole_list(self):
        """On 25 people the 4th reads '4 of 25' while 20 are shown, and Next from the 20th opens shown=40."""
        people = self.named(25)
        self.search(people)
        network.skip(self.store, [people[5]], now=now())
        search = self.store.get_search("s1")
        order = results(self.store, search, now().astimezone().date(), shown=0).order
        for n, (_, key) in enumerate(order, 1):
            position, total, before, after = walk(self.store, search, key)
            self.assertEqual((position, total), (n, len(order)))
            self.assertEqual(before, order[n - 2] if n > 1 else None)
            self.assertEqual(after, order[n] if n < len(order) else None)
        self.assertIsNone(walk(self.store, search, "no-such-card"))
        self.assertIsNone(walk(self.store, search, people[5]))
        key = order[3][1]
        self.assertIn("<span>4 of 24</span>", self.get(f"/people/{key}", search="s1", card=key))
        twentieth = order[19][1]
        line = self.walk_line(self.get(f"/people/{twentieth}", search="s1", card=twentieth))
        self.assertIn(f'href="/people/{order[20][0]}?search=s1&shown=40&card={order[20][1]}&from=card" rel="next"', line)

    def test_a_network_row_returns_to_the_filtered_list(self):
        gent = self.person("Gent Example", member=True)
        row = re.search(rf'<a href="(/people/{gent}[^"]*)">Gent Example</a>', self.get("/people", q="gent")).group(1)
        self.assertEqual(row, f"/people/{gent}?from=row&back=%2Fpeople%3Fq%3Dgent%23person-1")
        self.assertEqual(self.back(self.get(row)), [("/people?q=gent#person-1", "Back to your network")])

    def test_a_possible_match_and_a_source_return_to_the_person_page(self):
        """The links on Ada's page carry her page as back; a fact's source returns to that fact's line."""
        ada, twin = self.person("Ada Example", member=True), self.person("Ada Example", member=True, key="ada-2")
        fact = self.claim(ada, "topic", "Tidal energy")
        self.claim(twin, "topic", "Wind energy")
        html = self.get(f"/people/{ada}")
        match = re.search(rf'<a href="(/people/{twin}[^"]*)">', html).group(1)
        self.assertEqual(match, f"/people/{twin}?back=%2Fpeople%2F{ada}%23matches")
        self.assertEqual(self.back(self.get(match)), [(f"/people/{ada}#matches", "Back to Ada Example")])
        source = re.search(rf'<a href="(/sources/src-1\?claim={fact}[^"]*)"', html).group(1)
        here = quote(f"/people/{ada}#claim-{fact}", safe="")
        self.assertEqual(source, f"/sources/src-1?claim={fact}&back={here}#quote")
        self.assertEqual(self.back(self.get(source)), [(f"/people/{ada}#claim-{fact}", "Back to Ada Example")])
        self.assertIn(f'id="claim-{fact}"', html)

    def test_a_back_that_is_not_a_page_of_this_site_gives_no_back_link(self):
        ada = self.person("Ada Example", member=True)
        self.claim(ada, "topic", "Tidal energy")
        for value in REFUSED:
            with self.subTest(back=value[:40]):
                self.assertEqual(self.back(self.get("/sources/src-1", back=value)), [])
                self.assertEqual(self.back(self.get(f"/people/{ada}", back=value)), [])
        merged = self.person("Ada Twin")
        network.merge(self.store, [merged], ada, now=now())
        self.assertEqual(self.back(self.get("/sources/src-1", back=f"/people/{merged}"))[0][1], "Back to Ada Example")
        self.assertEqual(self.back(self.get(f"/people/{ada}")), [])

    def test_the_results_label_cuts_a_long_question_at_a_word(self):
        question = "Flemish experts in telecom and 6G research in the area around New York with a focus on antennas"
        person = self.named(2)[0]
        self.search([person], question=question)
        href, label = self.back(self.get(f"/people/{person}", search="s1", card=person))[0]
        self.assertEqual(href, f"/searches/s1#card-{person}")
        words = re.fullmatch("Back to the results for “(.*)”", label).group(1)
        self.assertTrue(words.endswith("…") and len(words) <= 61, words)
        self.assertTrue(question.startswith(words[:-1]) and question[len(words) - 1] == " ")

    def test_a_hostile_question_is_escaped_in_the_label(self):
        person = self.named(1)[0]
        self.search([person], question="<script>alert(1)</script>")
        raw = self.client.get(f"/people/{person}", params={"search": "s1", "card": person}).text
        self.assertNotIn("<script>", raw)
        self.assertIn(f'<a href="/searches/s1#card-{person}">', raw)
        self.assertIn("Back to the results for “&lt;script&gt;alert(1)&lt;/script&gt;”", raw)

    def test_the_header_marks_search_for_a_page_opened_from_a_search(self):
        person = self.named(1)[0]
        self.search([person])
        self.claim(person, "topic", "Tidal energy")
        mark = lambda html: re.search(r'<a href="[^"]*" aria-current="page">(\w+)</a>', html).group(1)
        self.assertEqual(mark(self.get(f"/people/{person}", search="s1", card=person)), "Search")
        self.assertEqual(mark(self.get(f"/people/{person}", back="/searches/s1")), "Search")
        self.assertEqual(mark(self.get(f"/people/{person}")), "Network")
        self.assertEqual(mark(self.get(f"/people/{person}", back="/people")), "Network")
        self.assertEqual(mark(self.get("/sources/src-1", back="/searches/s1")), "Search")
        self.assertNotIn('aria-current="page">Search', self.get("/sources/src-1", back="/people"))

    def test_bad_search_card_and_shown_values_still_give_a_page(self):
        people = self.named(3)
        self.search(people)
        cases = [{}, {"search": "nope"}, {"search": "s1", "card": "nope"}, {"search": "s1", "card": people[0], "shown": "abc"},
                 {"search": "s1", "card": people[0], "shown": "0"}, {"search": "s1", "card": people[0], "shown": "-1"},
                 {"search": "s1", "card": people[0], "shown": "1234567"}]
        for params in cases:
            with self.subTest(params=params):
                html = self.get(f"/people/{people[0]}", **params)
                self.assertLessEqual(len(self.back(html)), 1)
        self.assertEqual(self.back(self.get(f"/people/{people[0]}", search="nope")), [])
        html = self.get(f"/people/{people[0]}", search="s1", card="nope", shown="1234567")
        self.assertEqual(self.back(html), [("/searches/s1#card-nope", "Back to the results for “Example question”")])
        self.assertNotIn("fn-walk", html)

    def test_decisions_keep_the_search_shown_count_and_card_and_a_reject_lands_on_its_fact(self):
        """Every form on the page returns to it with its origin; a reject also returns to the fact's line."""
        people = self.named(40)
        self.search(people)
        ada, other = people[26], self.person("Person 27", member=True, key="twin")
        fact = self.claim(ada, "topic", "Tidal energy")
        query = f"search=s1&shown=40&card={ada}"
        html = self.get(f"/people/{ada}", search="s1", shown="40", card=ada)
        nexts = re.findall(r'name="next" value="([^"]+)"', html)
        self.assertTrue(nexts and all(n.startswith((f"/people/{ada}?{query}", f"/people/{other}?{query}")) for n in nexts), nexts)
        reject = re.search(rf'action="/claims/{fact}/reject">.*?name="next" value="([^"]+)"', html).group(1)
        self.assertEqual(reject, f"/people/{ada}?{query}#claim-{fact}")
        for path, fields in ((f"/people/{ada}/add", {}), (f"/people/{ada}/not-same", {"other": other}),
                             (f"/people/{ada}/merge", {"other": other}), (f"/claims/{fact}/reject", {})):
            with self.subTest(path=path):
                response = self.client.post(path, data={**fields, "next": f"/people/{ada}?{query}" +
                                                        (f"#claim-{fact}" if "claims" in path else "")})
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers["location"],
                                 f"/people/{ada}?{query}" + (f"#claim-{fact}" if "claims" in path else ""))
        bare = self.client.post(f"/claims/{fact}/reject", data={})
        self.assertEqual(bare.headers["location"], f"/people/{ada}#claim-{fact}")
        page = self.get(f"/people/{ada}", search="s1", shown="40", card=ada)
        undo = re.search(r'action="/events/[^"]+/undo"[^>]*>.*?name="next" value="([^"]+)"', page).group(1)
        self.assertTrue(undo.startswith(f"/people/{ada}?{query}"), undo)

    def test_same_person_on_a_candidate_page_goes_to_the_network_person_with_the_same_query(self):
        ada = self.person("Ada Example", member=True)
        twin = self.person("Ada Example", key="ada-2")
        self.claim(twin, "topic", "Wind energy")
        self.search([twin])
        html = self.get(f"/people/{twin}", search="s1", card=twin)
        same = re.search(rf'action="/searches/s1/people/{twin}/same">(.*?)</form>', html, re.DOTALL).group(1)
        self.assertIn(f'name="match" value="{ada}"', same)
        self.assertIn(f'name="next" value="/people/{twin}?search=s1&card={twin}"', same)

    def test_the_results_geo_answer_links_each_person_with_the_search(self):
        people = self.named(2)
        for p in people:
            self.claim(p, "location", "Gent", claim_date="2024-01-01", date_precision="day", lat=51.05, lon=3.72)
        self.search(people)
        found = self.client.get("/api/searches/s1/geo", params={"shown": "40"}).json()
        self.assertEqual(sorted(found["list"]), sorted(people))
        for p, listed in found["list"].items():
            self.assertEqual(listed["profile"], f"/people/{p}?search=s1&shown=40&card={p}&from=popup")
        again = self.client.get("/api/searches/s1/geo").json()
        self.assertIn(f"/people/{people[1]}?search=s1&card={people[1]}&from=popup", again["list"][people[1]]["profile"])

    def test_a_cards_same_name_note_and_quote_links_return_to_the_card(self):
        """On a card the same-name link, the possible-match note and the quote link carry the results url and anchor."""
        ada = self.person("Ada Example", member=True)
        twin, bob, other = self.person("Ada Example", key="ada-2"), self.person("Bob Example"), self.person("Bob Example", key="bob-2")
        self.store.add_identifier(bob, Identifier(scheme="orcid", value="0000-0001"))
        self.store.add_identifier(other, Identifier(scheme="orcid", value="0000-0002"))
        fact = self.claim(twin, "topic", "Wind energy")
        self.search([twin, [bob, other]], reasons={twin: [fact]})
        html = self.get("/searches/s1", shown="40")
        card = re.search(rf'<article [^>]*id="card-{twin}".*?</article>', html, re.DOTALL).group(0)
        back = quote(f"/searches/s1?shown=40#card-{twin}", safe="")
        self.assertIn(f'<a href="/people/{ada}?back={back}">Ada Example</a>', card)
        self.assertRegex(card, rf'<a href="/sources/src-1\?claim=[0-9a-f]+&back={re.escape(back)}#quote">')
        added = unescape(self.client.post(f"/searches/s1/people/{bob}/add", headers={"x-requested-with": "fetch"},
                                          data={"next": "/searches/s1?shown=40"}).text)
        back = quote(f"/searches/s1?shown=40#card-{bob}", safe="")
        self.assertIn(f'href="/people/{bob}?back={back}#matches">1 possible match</a>', added)


if __name__ == "__main__":
    unittest.main()
