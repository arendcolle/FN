import hashlib
import re
import unittest
from html import unescape
from pathlib import Path

from fastapi.testclient import TestClient

from fn import network, orgs
from fn.contracts import (
    Candidate,
    ClaimDraft,
    Identifier,
    OrgFacts,
    ScorePart,
    Search,
    Source,
)
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

ROOT = Path(__file__).resolve().parent.parent
# sha256 of components/bundle.css in version 11 of the design system.
BUNDLE_SHA = "4f1a844883605813c3dd6c1e0faf0b156f2618607965ac516bf6094b5c41da81"
YEAR = str(now().year)


class ResultsPageCase(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.count = 0

    def person(self, name: str) -> str:
        return self.store.resolve_person([Identifier(scheme="seed", value=name)], name).id

    def claim(self, person_id: str, kind: str, value: str, source_kind: str = "page", title: str = "Example page",
              **fields) -> str:
        self.count += 1
        text = f"{value} of {person_id}"
        source = Source(id=f"src-{self.count}", kind=source_kind, url=f"https://example.org/{self.count}", title=title,
                        text=text, content_hash=f"h-{self.count}")
        return self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, value=value, quote=text, quote_start=0,
                                                  quote_end=len(text), source=source, **fields)).id

    def org(self, org_id: str, name: str, country: str, city: str | None = None, lat: float | None = None,
            lon: float | None = None) -> None:
        record = Source(id=f"org-{org_id}", kind="record", url="https://ror.org/x", text="id", content_hash=f"h-{org_id}",
                        fetched_at=now())
        orgs.save(self.store, [OrgFacts(id=org_id, name=name, country_code=country, city=city, lat=lat, lon=lon)], record,
                  replace=True)

    def search(self, cards: list[tuple[list[str], list[ScorePart]]]) -> str:
        """A done search s1 whose kept candidates are (card records, score parts), in rank order."""
        self.store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None,
                                        dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        self.store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=card[0], person_ids=card, hit_person_ids=card[:1], card_person_ids=card,
                      section="new", rank=n, score=1.0, lane_ranks={"seeds": n}, score_parts=found)
            for n, (card, found) in enumerate(cards, 1)], [])
        return "s1"

    def page(self, path: str = "/searches/s1", **params) -> str:
        response = self.client.get(path, params=params)
        self.assertEqual(response.status_code, 200)
        return unescape(response.text)

    def card(self, html: str, key: str) -> str:
        return re.search(rf'<article [^>]*id="card-{key}".*?</article>', html, re.DOTALL).group(0)


class ResultsPageTest(ResultsPageCase):
    def test_a_list_of_21_shows_20_cards_then_show_1_more(self):
        """The first page holds 20 cards and Show more names the one left; ?shown=40 shows all 21 and no Show more."""
        people = [self.person(f"Person {n:02}") for n in range(21)]
        self.search([([p], []) for p in people])
        first = self.page()
        self.assertEqual(first.count('class="fn-card"'), 20)
        self.assertIn(f'<span>20 of 21 shown</span><a class="fn-btn fn-btn--quiet text-control" '
                      f'href="/searches/s1?shown=40#card-{people[20]}">Show 1 more</a>', first)
        everyone = self.page(shown="40")
        self.assertEqual(everyone.count('class="fn-card"'), 21)
        self.assertNotIn("Show 1 more", everyone)

    def test_a_card_without_a_place_ends_after_the_employer(self):
        """The role line of a person without a place is the employer alone, and no source file words a missing place."""
        ada = self.person("Ada Fictief")
        self.claim(ada, "affiliation", "Example Labs", relation="works_at", claim_date="2015")
        self.search([([ada], [])])
        self.assertIn('<p class="fn-card__role text-body">Example Labs</p>', self.card(self.page(), ada))
        found = [p for p in (ROOT / "src").rglob("*") if p.is_file() and b"location not found" in p.read_bytes()]
        self.assertEqual(found, [])

    def test_the_why_line_names_the_topic_words_and_an_employer_place(self):
        """The why line reads the topic part's words, adds 'Place from the employer' when the place is the city of a
        recent employer, reads 'Based in' for a place part alone, and is absent for a candidate without parts."""
        self.org("ror:0fict0001", "Fictional University", "US", "Boston", 42.36, -71.06)
        ada, bea, cas = self.person("Ada Fictief"), self.person("Bea Fictief"), self.person("Cas Fictief")
        self.claim(ada, "affiliation", "Fictional University", relation="works_at", org_id="ror:0fict0001",
                   claim_date=YEAR)
        topic = ScorePart(feature="topic", rank=1, points=0.1, detail="tidal, energy")
        place = ScorePart(feature="place", rank=1, points=0.1, detail="stated: Gent, Flanders, Belgium")
        self.search([([ada], [topic]), ([bea], [place]), ([cas], [])])
        html = self.page()
        self.assertIn('<p class="fn-card__why text-small">Matches: tidal, energy · Place from the employer</p>',
                      self.card(html, ada))
        self.assertIn("Fictional University · Boston", self.card(html, ada))
        self.assertIn('<p class="fn-card__why text-small">Based in Gent, Flanders, Belgium</p>', self.card(html, bea))
        self.assertNotIn("fn-card__why", self.card(html, cas))

    def test_the_evidence_is_the_topic_claim_and_a_work_reads_as_a_paper(self):
        """With a topic part the card shows its first claim, not the Belgian tie; an OpenAlex work reads 'Paper: ' and
        its title with the year, cited 'OpenAlex work', cut on the card and whole on the profile."""
        self.org("ror:0fict0002", "Fictional Hogeschool", "BE")
        ada = self.person("Ada Fictief")
        self.claim(ada, "affiliation", "Fictional Hogeschool", relation="worked_at", org_id="ror:0fict0002",
                   claim_date="2020")
        title = "Tidal energy " + "and coastal grids " * 20
        work = self.claim(ada, "topic", title.strip(), source_kind="record", title=f"OpenAlex work {title.strip()}",
                          claim_date="2023", date_precision="year")
        self.search([([ada], [ScorePart(feature="topic", rank=1, points=0.1, claim_ids=[work], detail="tidal")])])
        card = self.card(self.page(), ada)
        self.assertIn('<p class="fn-fact text-body">Paper: Tidal energy and coastal grids', card)
        self.assertIn('…, <span class="text-year">2023</span></p>', card)
        self.assertIn(">OpenAlex work</a>, 2023</p>", card)
        self.assertNotIn("Worked at Fictional Hogeschool", card)
        self.assertIn(f"Paper: {title.strip()}", self.page(f"/people/{ada}"))

    def test_the_combined_line_shows_for_two_records_not_merged_into_one(self):
        """A card of two separate records links 'Combined from 2 records' to the first one's Sources; a card of
        one record, or of two records merged into one person, has no such line."""
        ada, twin = self.person("Ada Fictief"), self.person("Ada Fictief 2")
        bea = self.person("Bea Fictief")
        cas, merged = self.person("Cas Fictief"), self.person("Cas Fictief 2")
        network.merge(self.store, [merged], cas, now=now())
        self.search([([ada, twin], []), ([bea], []), ([cas, merged], [])])
        html = self.page()
        self.assertIn(f'<p class="fn-card__combined text-small"><a href="/people/{ada}?search=s1&card={ada}&from=card#sources">'
                      'Combined from 2 records'
                      '</a></p>', self.card(html, ada))
        self.assertNotIn("Combined from", self.card(html, bea))
        self.assertNotIn("Combined from", self.card(html, cas))

    def test_the_geo_answer_marks_people_beyond_the_shown_cards_with_their_link(self):
        """Per placed person the answer says whether the shown cards hold them and links the list that does."""
        people = [self.person(f"Person {n:02}") for n in range(21)]
        for p in people:
            self.claim(p, "location", "Gent", lat=51.05, lon=3.72)
        self.search([([p], []) for p in people])
        listed = self.client.get("/api/searches/s1/geo").json()["list"]
        self.assertEqual([listed[p]["shown"] for p in people], [True] * 20 + [False])
        self.assertEqual(listed[people[20]]["href"], f"/searches/s1?shown=40#card-{people[20]}")
        self.assertTrue(self.client.get("/api/searches/s1/geo", params={"shown": "40"}).json()["list"][people[20]]["shown"])
        self.assertIn('data-geo="/api/searches/s1/geo?shown=40"', self.page(shown="40"))

    def test_the_stylesheet_is_the_design_system_bundle(self):
        """fn.css is a byte copy of the design system's bundle.css."""
        css = (ROOT / "src" / "fn" / "web" / "static" / "fn.css").read_bytes()
        self.assertEqual(hashlib.sha256(css).hexdigest(), BUNDLE_SHA)


if __name__ == "__main__":
    unittest.main()
