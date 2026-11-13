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

    def stored(self, cards: list[tuple[str, str | None, CardFit | None]], place: Place | None = BOSTON,
               tiers: list[int | None] | None = None) -> str:
        """A done search s1 with a card per (person, reason claim, fit); a reason is also the topic part."""
        self.store.create_search(search_of(place))
        self.store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=person, person_ids=[person], hit_person_ids=[person],
                      card_person_ids=[person], section="new", rank=n, score=1.0, lane_ranks={"seeds": n},
                      reason_claim_ids=[reason] if reason else [], fit=found, tier=(tiers or [None] * len(cards))[n - 1],
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
            ("Topic: AI in health care · example.org", "Fellow of Belgian American Educational Foundation · place unknown"),
            ("Paper: Deep learning for early warning of sepsis in intensive care units…, 2023 · OpenAlex work",
             "Studied at KU Leuven · place unknown"),
            (None, "Origin: Belgian · place unknown"),
            (None, "Worked at ULB · place unknown"),
            (None, "No known tie to Flanders"),
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
        self.assertEqual(self.lines(html, weak)[1], "No known tie to Flanders · place unknown")
        self.assertEqual(self.lines(html, bare), (None, "No known tie to Flanders · place unknown"))

    def test_a_reason_never_passes_15_words_and_no_card_shows_a_quote_or_an_unknown_date(self):
        """A 40-word role and a 300-character paper title are cut at a word with '…'; no 'date unknown', 'Matches:'
        or blockquote reaches the page.
        """
        long = self.person("Lotte Long", "long")
        words = " ".join(f"word{n}" for n in range(40))
        job = self.claim(long, "topic", words, src=self.source(f"Lotte Long {words}", url="https://www.example.org/long"))
        paper = self.person("Pim Paper", "paper", "openalex")
        title = " ".join(["Tidal"] + ["coastal"] * 42)
        work = self.source(title, kind="record", url="https://openalex.org/W7", title=f"OpenAlex work {title}")
        found = self.claim(paper, "topic", title, src=work)
        html = self.stored([(long, job, fit("none", [], "inside")), (paper, found, fit("none", [], "inside"))])
        for person in (long, paper):
            reason = self.lines(html, person)[0]
            self.assertLessEqual(words_of(reason), 15, reason)
            self.assertIn("…", reason)
        self.assertIn("Topic: word0 word1", self.lines(html, long)[0])
        for text in ("date unknown", "Matches:", "<blockquote"):
            self.assertNotIn(text, html)

    def test_a_card_whose_role_line_shows_a_place_says_no_place_words_and_one_without_says_place_unknown(self):
        """No place fit, chip or city words beside a shown place; 'place unknown' (card) and 'Place unknown' (why) without."""
        rows = []
        for found in ("inside", "outside", "abroad", "unknown", "none"):
            plain = self.person(f"Petra {found}", f"plain-{found}")
            page = self.source(f"Petra is Director of robotics, Example Health ({found})", url=f"https://examplehealth.org/{found}")
            self.claim(plain, "role", "Director of robotics, Example Health", src=page)
            self.claim(plain, "location", "Boston, MA", relation="lives_in", lat=42.36, lon=-71.06, src=page,
                       quote="Petra is Director")
            rows.append((plain, None, fit("none", [], found)))
        lost = self.person("Lena Lost", "lost")
        self.claim(lost, "role", "Director of robotics, Example Health")
        html = self.stored([*rows, (lost, None, fit("none", [], "inside"))])
        for plain, _, found in rows:
            with self.subTest(fit=found.place):
                self.assertEqual(self.lines(html, plain), (None, "No known tie to Flanders"))
                self.assertEqual(re.findall(r"<li>(.*?)</li>", self.page(plain, search="s1", card=plain)),
                                 ["No known tie to Flanders"])
        self.assertEqual(self.lines(html, lost), (None, "No known tie to Flanders · place unknown"))
        self.assertEqual(re.findall(r"<li>(.*?)</li>", self.page(lost, search="s1", card=lost)),
                         ["No known tie to Flanders", "Place unknown"])


class ReasonTest(CardLinesCase):
    def worker(self, name: str, key: str, role: str = "Partner, Example LLP", date: str = "2024") -> tuple[str, str]:
        """A person with a stated role on a page; returns the person and the role claim."""
        person = self.person(name, key)
        page = self.source(f"{name} is {role}", url=f"https://{key}.example.org/about")
        return person, self.claim(person, "role", role, src=page, claim_date=date)

    def test_a_host_a_study_or_an_affiliation_is_no_reason_but_a_stated_role_or_a_topic_is(self):
        """A stored reason of relation hosted_by, studied_at or affiliated_with gives no reason line when the person has
        no role or topic claim, and the stated role or the topic claim when the person has one.
        """
        rows, bare = [], []
        for relation in ("hosted_by", "studied_at", "affiliated_with"):
            person = self.person(f"Hanna {relation}", relation)
            record = self.source("OpenAlex record", kind="record", url=f"https://openalex.org/{relation}", title="Record")
            bare.append((person, self.claim(person, "affiliation", "KU Leuven", src=record, relation=relation,
                                            org_id=base.LEUVEN.id, claim_date="2015"), fit("strong", [], "none")))
        topical = self.person("Tessa Topical", "topical")
        host = self.claim(topical, "affiliation", "KU Leuven", relation="hosted_by", org_id=base.LEUVEN.id, claim_date="2015",
                          src=self.source("Tessa", kind="record", url="https://openalex.org/T", title="Record"))
        self.claim(topical, "topic", "wind energy", quote="Tessa on wind energy",
                   src=self.source("Tessa on wind energy", url="https://example.org/wind"))
        html = self.stored([*bare, (topical, host, fit("strong", [], "none"))])
        for person, _, _ in bare:
            self.assertEqual(self.lines(html, person)[0], None)
        self.assertEqual(self.lines(html, topical)[0], "Topic: wind energy · example.org")

    def test_a_topic_from_a_page_that_lists_the_person_as_a_fellow_is_no_reason(self):
        """A study or project on a fellows list is the fellow's own work, so the card gets no reason line."""
        person = self.person("Fenna Fellow", "fellow")
        page = self.source("Fenna Fellow, fellow. Study of tidal power", url="https://fellows.example.org/list")
        fellow = self.claim(person, "affiliation", "Example Foundation", relation="fellow_of", src=page, claim_date="2015")
        self.claim(person, "topic", "tidal power", quote="Study of tidal power", src=page)
        html = self.stored([(person, fellow, fit("strong", [], "none"))])
        self.assertEqual(self.lines(html, person)[0], None)

    def test_a_page_title_role_is_never_the_reason_nor_the_first_why_line(self):
        """A role equal to its page's title is no stated role: no reason line and no first line in the why block."""
        web = self.person("Wanda Web", "web")
        page = self.source("Wanda Web at the lab", url="https://lab.example.org/wanda", title="Wanda Web at the lab")
        title = self.claim(web, "role", "Wanda Web at the lab", src=page)
        html = self.stored([(web, title, fit("none", [], "inside"))])
        self.assertEqual(self.lines(html, web)[0], None)
        self.assertNotIn("Wanda Web at the lab", re.sub(r"<[^>]+>", " ", self.page(web, search="s1", card=web).split("fn-why")[1]))

    def test_a_reason_that_repeats_the_role_line_is_dropped_and_one_that_adds_a_topic_stays(self):
        """The role line 'Partner, Example LLP' holds every word of the reason 'Partner'; 'Topic: export controls' adds some."""
        repeat, old = self.worker("Rik Repeat", "repeat")
        short = self.claim(repeat, "role", "Partner", src=self.source("Rik Repeat, partner", url="https://old.example.org/rik"),
                           claim_date="2020")
        topical, _ = self.worker("Tom Topical", "tomt")
        topic = self.claim(topical, "topic", "export controls", quote="Tom Topical on export controls",
                           src=self.source("Tom Topical on export controls", url="https://example.org/export"))
        html = self.stored([(repeat, short, fit("none", [], "inside")), (topical, topic, fit("none", [], "inside"))])
        self.assertEqual(self.lines(html, repeat)[0], None)
        self.assertEqual(self.lines(html, topical)[0], "Topic: export controls · example.org")

    def test_the_first_heading_names_belgium_and_no_tie_is_repeated_under_topic_no_known_tie(self):
        """Tier 1 reads 'Topic and a tie to Flanders or Belgium'; 'No known tie to Flanders' leaves the cards under
        'Topic, no known tie' and stays under 'Other people found' and on a search without tiers.
        """
        self.assertEqual(present.HEADINGS[1], "Topic and a tie to Flanders or Belgium")
        a, b, c = (self.worker(n, k)[0] for n, k in (("Ann Aa", "aa"), ("Bea Bb", "bb"), ("Cor Cc", "cc")))
        rows = [(p, None, fit("none", [], "inside")) for p in (a, b, c)]
        html = self.stored(rows, tiers=[1, 3, 7])
        self.assertIn("Topic and a tie to Flanders or Belgium", html)
        self.assertEqual([self.lines(html, p)[1] for p in (a, b, c)],
                         ["No known tie to Flanders · place unknown", "place unknown", "No known tie to Flanders · place unknown"])

    def test_a_card_under_topic_no_known_tie_keeps_place_unknown(self):
        """Without the tie words the second line still says 'place unknown' when the role line shows no place."""
        a = self.worker("Ann Aa", "aa")[0]
        html = self.stored([(a, None, fit("none", [], "unknown"))], tiers=[3])
        self.assertEqual(self.lines(html, a)[1], "place unknown")

    def test_a_why_block_with_two_equal_lines_shows_one(self):
        """A reason that reads like the tie line is left out of the later line: the block shows it once."""
        job = self.person("Dina Dup", "dup")
        self.claim(job, "affiliation", "Example Health", relation="works_at", org_id=base.HEALTH.id, claim_date="2024",
                   src=self.source("Dina Dup works at Example Health", url="https://examplehealth.org/dina"))
        said = self.claim(job, "role", "No known tie to Flanders", src=self.source("Dina Dup, no known tie", url="https://x.example.org/d"))
        self.stored([(job, said, fit("none", [], "inside"))])
        lines = re.findall(r"<li>(.*?)</li>", self.page(job, search="s1", card=job))
        self.assertEqual(lines.count("No known tie to Flanders"), 1)


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
        """The why block lists the tie words; the reason repeats the role line and the head shows the place; none without search."""
        plain, role, found = self.plain_row()
        self.stored([(plain, role, found)])
        html = self.page(plain, search="s1", card=plain)
        why = re.search(r'<section class="fn-why">(.*?)</section>', html, re.DOTALL).group(0)
        self.assertEqual(re.findall(r"<li>(.*?)</li>", why),
                         ["No known tie to Flanders"])
        self.assertNotIn("examplehealth.org", why)
        self.assertLess(html.index('class="fn-profile__head"'), html.index('<section class="fn-why">'))
        self.assertLess(html.index('<section class="fn-why">'), html.index('<dl class="fn-summary-list">'))
        self.assertNotIn("fn-why", self.page(plain))
        self.assertNotIn("fn-why", self.page(plain, search="s1"))


if __name__ == "__main__":
    unittest.main()
