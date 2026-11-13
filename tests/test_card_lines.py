import re
import statistics
import unittest
from html import unescape

from fn import present
from fn.contracts import (
    Candidate,
    CardFit,
    Chips,
    Place,
    ScorePart,
    Search,
)
from fn.worker import now
from tests import test_person_content as base

ULB = base.org("ror:01r9htc13", "ULB", "BE", city="Brussels")
TITLE = "Deep learning for early warning of sepsis in intensive care units across three Boston hospitals"
BOSTON = Place(text="Boston", origin="edited", kind="metro")


def search_of(place: Place | None, search_id: str = "s1") -> Search:
    return Search(id=search_id, question="Example question", status="done", created_at=now(), code_sha=None, dirty=False,
                  llm_mode="replay", settings_json="{}", boot_id="b", chips=Chips(place=place) if place else None)


def words_of(markup: str) -> int:
    """The words of the markup's text; a lone '·' between two parts is no word."""
    return sum(1 for w in re.sub(r"<[^>]+>", " ", markup).split() if re.search(r"\w", w))


def fit(grade: str = "none", ids: list[str] | None = None, place: str = "none") -> CardFit:
    return CardFit(tie_grade=grade, tie_claim_ids=ids or [], place=place)


class CardLinesCase(base.PersonContentCase):
    def setUp(self):
        super().setUp()
        self.store.upsert_org(ULB, replace=True)

    def stored(self, cards: list[tuple[str, str | None, CardFit | None]], place: Place | None = BOSTON) -> str:
        """A done search s1 with a card per (person, reason claim, fit); a reason is also the topic part."""
        self.store.create_search(search_of(place))
        self.store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=person, person_ids=[person], hit_person_ids=[person],
                      card_person_ids=[person], section="new", rank=n, score=1.0, lane_ranks={"seeds": n},
                      reason_claim_ids=[reason] if reason else [], fit=found,
                      score_parts=[ScorePart(feature="topic", rank=1, points=0.1, claim_ids=[reason], detail="x")]
                      if reason else [])
            for n, (person, reason, found) in enumerate(cards, 1)], [])
        return self.raw("/searches/s1")

    def lines(self, html: str, key: str) -> tuple[str | None, str | None]:
        """The text of the reason line (source link included) and of the second line of the card."""
        card = re.search(rf'<article [^>]*id="card-{key}".*?</article>', unescape(html), re.DOTALL).group(0)
        reason = re.search(r'<p class="fn-card__reason text-body">(.*?)</p>', card)
        second = re.search(r'<p class="fn-card__fit text-small">(.*?)</p>', card)
        return (re.sub(r"<[^>]+>", "", reason.group(1)) if reason else None, second.group(1) if second else None)

    def seed_row(self) -> tuple[str, str, CardFit]:
        seed = self.person("Sofie Seed", "seed")
        fellow = self.claim(seed, "role", "Fellow", src=self.source("Sofie Seed, fellow", kind="seed_page",
                                                                     title="BAEF fellows"),
                            relation="fellow_of", org_id=base.BAEF.id)
        topic = self.claim(seed, "topic", "AI in health care", quote="Sofie Seed on AI in health care",
                           src=self.source("Sofie Seed on AI in health care", url="https://example.org/ai"))
        return seed, topic, fit("strong", [fellow], "inside")

    def paper_row(self) -> tuple[str, str, CardFit]:
        oa = self.person("Pieter Paper", "oa", "openalex")
        record = self.source("OpenAlex record", kind="record", url="https://openalex.org/A9", title="Pieter Paper")
        studied = self.claim(oa, "affiliation", "KU Leuven", src=record, relation="studied_at", org_id=base.LEUVEN.id,
                             valid_from="2012", valid_to="2017", claim_date="2017")
        work = self.source(TITLE, kind="record", url="https://openalex.org/W9", title=f"OpenAlex work {TITLE}")
        paper = self.claim(oa, "topic", TITLE, src=work, claim_date="2023", date_precision="year")
        return oa, paper, fit("strong", [studied], "outside")

    def web_row(self) -> tuple[str, str, CardFit]:
        web = self.person("Wanda Web", "web")
        page = self.source("Wanda Web is Founder and CEO, Fictional Robotics", url="https://fictionalrobotics.com/about")
        role = self.claim(web, "role", "Founder and CEO, Fictional Robotics", src=page)
        origin = self.claim(web, "location", "Belgian", relation="origin", quote="Wanda Web is Founder",
                            src=page)
        return web, role, fit("strong", [origin, role], "unknown")

    def old_row(self) -> tuple[str, str, None]:
        old = self.person("Olaf Oud", "old")
        job = self.claim(old, "affiliation", "ULB", relation="worked_at", org_id=ULB.id, valid_from="2013",
                         valid_to="2018", claim_date="2018", src=self.source("Olaf Oud, ULB", url="https://example.org/olaf"))
        return old, job, None

    def plain_row(self) -> tuple[str, str, CardFit]:
        plain = self.person("Petra Plain", "plain")
        page = self.source("Petra Plain is Director of robotics, Example Health", url="https://examplehealth.org/team")
        role = self.claim(plain, "role", "Director of robotics, Example Health", src=page)
        self.claim(plain, "location", "Boston, MA", relation="lives_in", lat=42.36, lon=-71.06, src=page,
                   quote="Petra Plain")
        return plain, role, fit("none", [], "inside")


class CardLinesTest(CardLinesCase):
    def test_the_five_examples_give_exactly_their_reason_line_and_second_line(self):
        """Each stored person reads a reason line with its source link and a second line of tie words and place words."""
        rows = [self.seed_row(), self.paper_row(), self.web_row(), self.old_row(), self.plain_row()]
        html = self.stored(rows)
        expected = [
            ("Topic: AI in health care · example.org", "Fellow of Belgian American Educational Foundation · in Boston"),
            ("Paper: Deep learning for early warning of sepsis in intensive care units…, 2023 · OpenAlex work",
             "Studied at KU Leuven · elsewhere in the US"),
            ("Founder and CEO, Fictional Robotics · fictionalrobotics.com", "Origin: Belgian · place unknown"),
            ("Worked at ULB, 2013–2018 · example.org", None),
            ("Director of robotics, Example Health · examplehealth.org", "No known tie to Flanders · in Boston"),
        ]
        for (person, _, _), want in zip(rows, expected):
            with self.subTest(want=want[0]):
                self.assertEqual(self.lines(html, person), want)
        self.assertIn('class="fn-card__source"', html)

    def test_a_weak_tie_a_missing_reason_and_a_search_without_a_place_still_read_right(self):
        """A weak tie reads as no tie, a card without evidence has no reason line, and no place chip leaves out the place."""
        weak = self.person("Wies Weak", "weak")
        tie = self.claim(weak, "affiliation", "Example Lab", relation="worked_at", claim_date="2020")
        bare = self.person("Bram Bare", "bare")
        html = self.stored([(weak, tie, fit("weak", [tie], "inside")), (bare, None, fit("none", [], "inside"))])
        self.assertEqual(self.lines(html, weak)[1], "No known tie to Flanders · in Boston")
        self.assertEqual(self.lines(html, bare), (None, "No known tie to Flanders · in Boston"))

    def test_a_reason_never_passes_15_words_and_no_card_shows_a_quote_or_an_unknown_date(self):
        """A 40-word role and a 300-character paper title are cut at a word with '…'; no 'date unknown', 'Matches:'
        or blockquote reaches the page.
        """
        long = self.person("Lotte Long", "long")
        words = " ".join(f"word{n}" for n in range(40))
        job = self.claim(long, "role", words, src=self.source(f"Lotte Long {words}", url="https://www.example.org/long"))
        paper = self.person("Pim Paper", "paper", "openalex")
        title = " ".join(["Tidal"] + ["coastal"] * 42)
        work = self.source(title, kind="record", url="https://openalex.org/W7", title=f"OpenAlex work {title}")
        found = self.claim(paper, "topic", title, src=work)
        html = self.stored([(long, job, fit("none", [], "inside")), (paper, found, fit("none", [], "inside"))])
        for person in (long, paper):
            reason = self.lines(html, person)[0]
            self.assertLessEqual(words_of(reason), 15, reason)
            self.assertIn("…", reason)
        self.assertIn("Word0 word1", self.lines(html, long)[0])
        for text in ("date unknown", "Matches:", "<blockquote"):
            self.assertNotIn(text, html)

    def test_place_words_for_each_fit_and_each_kind_of_place_chip(self):
        """inside reads the chip's text or 'the US'; outside, abroad and unknown read their words; nothing without a
        chip, with an abroad chip or without a fit.
        """
        metro = search_of(Place(text="Boston", origin="edited", kind="metro"))
        anywhere = search_of(Place(text="the US", origin="edited", kind="anywhere_us"))
        abroad = search_of(Place(text="Paris", origin="edited", kind="abroad"))
        for found, words in (("inside", "in Boston"), ("outside", "elsewhere in the US"), ("abroad", "outside the US"),
                             ("unknown", "place unknown"), ("none", None)):
            with self.subTest(fit=found):
                self.assertEqual(present.place_words(metro, fit(place=found)), words)
        self.assertEqual(present.place_words(anywhere, fit(place="inside")), "in the US")
        self.assertEqual(present.place_words(anywhere, fit(place="outside")), "elsewhere in the US")
        self.assertIsNone(present.place_words(abroad, fit(place="inside")))
        self.assertIsNone(present.place_words(search_of(None), fit(place="inside")))
        self.assertIsNone(present.place_words(metro, None))


class BudgetTest(CardLinesCase):
    def twenty(self) -> list[tuple[str, str, CardFit]]:
        rows = []
        for n in range(20):
            person = self.person(f"Person{n:02d} Voorbeeld", f"p{n}")
            quote = " ".join(f"quote{n}-{k}" for k in range(30))
            page = self.source(f"Person{n:02d} Voorbeeld is Head of research, Example Lab {n}. {quote}",
                               url=f"https://lab{n}.example.org/team")
            role = self.claim(person, "role", f"Head of research, Example Lab {n}", src=page)
            tie = self.claim(person, "affiliation", "KU Leuven", relation="studied_at", org_id=base.LEUVEN.id,
                             claim_date="2010", src=self.source(f"Person{n:02d} Voorbeeld, KU Leuven", kind="record",
                                                                url=f"https://openalex.org/A{n}", title="Record"))
            self.claim(person, "location", "Boston, MA", relation="lives_in", lat=42.36, lon=-71.06, src=page,
                       quote=f"Person{n:02d} Voorbeeld")
            rows.append((person, role, fit("strong", [tie], ("inside", "outside", "unknown")[n % 3])))
        return rows

    def test_a_card_reads_at_most_25_words_at_the_median_and_30_at_most(self):
        """Twenty people with 30-word quotes, roles, tie claims and places: median of words per card <= 25, none over 30."""
        html = self.stored(self.twenty())
        cards = re.findall(r'<article class="fn-card".*?</article>', html, re.DOTALL)
        self.assertEqual(len(cards), 20)
        counts = [words_of(re.sub(r"<form.*?</form>", "", unescape(c), flags=re.DOTALL)) for c in cards]
        self.assertLessEqual(statistics.median(counts), 25, counts)
        self.assertLessEqual(max(counts), 30, counts)
        self.assertNotIn("quote0-1", html)

    def test_a_person_page_reads_at_most_90_words_before_its_first_section(self):
        """Five pages opened from the search: back link, head, why block and summary stay within 90 words."""
        rows = self.twenty()
        self.stored(rows)
        for person, _, _ in rows[:5]:
            with self.subTest(person=person):
                html = self.page(person, search="s1", card=person)
                main = re.search(r"<main.*?</main>", html, re.DOTALL).group(0).split('<section class="fn-profile__section"')[0]
                main = re.sub(r"<details.*?</details>", "", re.sub(r"<form.*?</form>", "", main, flags=re.DOTALL), flags=re.DOTALL)
                self.assertLessEqual(words_of(main), 90, words_of(main))


class MapAndWhyTest(CardLinesCase):
    def test_the_geo_answer_gives_each_listed_person_its_place_fit_and_none_for_an_old_search(self):
        """place_fit is the stored card fit's place, None without a fit."""
        rows = [self.plain_row(), self.old_row()]
        self.claim(rows[1][0], "location", "Gent", relation="lives_in", lat=51.05, lon=3.72)
        self.stored(rows)
        listed = self.client.get("/api/searches/s1/geo").json()["list"]
        self.assertEqual(listed[rows[0][0]]["place_fit"], "inside")
        self.assertIsNone(listed[rows[1][0]]["place_fit"])

    def test_the_why_block_sits_between_the_head_and_the_summary_and_needs_a_search(self):
        """Three lines: the reason without its source, the tie words and the capitalised place; none without search."""
        plain, role, found = self.plain_row()
        self.stored([(plain, role, found)])
        html = self.page(plain, search="s1", card=plain)
        why = re.search(r'<section class="fn-why">(.*?)</section>', html, re.DOTALL).group(0)
        self.assertEqual(re.findall(r"<li>(.*?)</li>", why),
                         ["Director of robotics, Example Health", "No known tie to Flanders", "In Boston"])
        self.assertNotIn("examplehealth.org", why)
        self.assertLess(html.index('class="fn-profile__head"'), html.index('<section class="fn-why">'))
        self.assertLess(html.index('<section class="fn-why">'), html.index('<dl class="fn-summary-list">'))
        self.assertNotIn("fn-why", self.page(plain))
        self.assertNotIn("fn-why", self.page(plain, search="s1"))


if __name__ == "__main__":
    unittest.main()
