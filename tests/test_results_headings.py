import re
import unittest
from datetime import date

from fn import network, present
from fn.contracts import Candidate, CardFit, Chips, Search
from fn.present import ASIDE_HEADINGS, HEADINGS, UNFIT_LINE
from fn.worker import now
from tests.test_results_page import ResultsPageCase

NEW = [*HEADINGS.values()]


class ResultsHeadingsTest(ResultsPageCase):
    def listing(self, rows: list[tuple[int | None, str | None]], status: str = "done") -> list[str]:
        """A search s1 of made-up people, one per (tier, tie grade); a grade of None leaves fit empty."""
        people = [self.person(f"Person {n:02}") for n in range(len(rows))]
        self.store.create_search(Search(id="s1", question="q", status=status, created_at=now(), code_sha=None,
                                        dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        self.store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=p, person_ids=[p], hit_person_ids=[p], card_person_ids=[p], section="new",
                      rank=n, score=1.0, lane_ranks={"seeds": n}, tier=tier,
                      fit=CardFit(tie_grade=grade) if grade else None)
            for n, (p, (tier, grade)) in enumerate(zip(people, rows), 1)], [])
        return people

    def headings(self, html: str) -> list[tuple[str, str]]:
        return re.findall(r'<h2 class="fn-section text-label">(.*?) <span>(.*?)</span></h2>', html)

    def test_four_headings_in_order_with_their_counts(self):
        """Tiers 1, 3, 5, 6 with a medium tie, 6 with none and 7 stand under four headings with 1, 1, 2 and 2 people."""
        self.listing([(1, "strong"), (3, "strong"), (5, "weak"), (6, "medium"), (6, "none"), (7, "none")])
        self.assertEqual(self.headings(self.page()), [(NEW[0], "1"), (NEW[1], "1"), (NEW[2], "2"), (NEW[3], "2")])

    def test_a_must_tie_list_has_three_headings(self):
        """Tiers 1, 5, 6 and 7, all with a strong tie, give three headings: tier 6 joins tier 5, tier 7 stands apart."""
        self.listing([(1, "strong"), (5, "strong"), (6, "strong"), (7, "strong")])
        self.assertEqual(self.headings(self.page()), [(NEW[0], "1"), (NEW[2], "2"), (NEW[3], "1")])

    def test_a_tier_with_no_fit_stands_under_other_people(self):
        """A tier 6 candidate without fit has grade none and stands under Other people found."""
        self.listing([(6, None)])
        self.assertEqual(self.headings(self.page()), [(NEW[3], "1")])

    def test_a_search_without_tiers_keeps_new(self):
        """Tier None everywhere, or on one candidate only, gives the single heading New."""
        for rows in ([(None, None), (None, None)], [(1, "strong"), (None, None)]):
            with self.subTest(rows=rows):
                self.setUp()
                self.listing(rows)
                self.assertEqual(self.headings(self.page()), [("New", "2")])

    def test_a_heading_after_the_first_page_shows_once_before_its_first_card(self):
        """25 tier 1 people and 5 tier 3 people: page one has one heading of 25; shown=40 adds the second before card 26."""
        people = self.listing([(1, "strong")] * 25 + [(3, "strong")] * 5)
        self.assertEqual(self.headings(self.page()), [(NEW[0], "25")])
        html = self.page(shown="40")
        self.assertEqual(self.headings(html), [(NEW[0], "25"), (NEW[1], "5")])
        self.assertLess(html.index(f'id="card-{people[24]}"'), html.index(NEW[1]))
        self.assertLess(html.index(NEW[1]), html.index(f'id="card-{people[25]}"'))

    def test_the_count_leaves_out_people_skipped_elsewhere(self):
        """A person skipped on another search is not counted under the heading."""
        people = self.listing([(1, "strong"), (1, "strong"), (1, "strong")])
        network.skip(self.store, [people[2]], now=now())
        self.assertEqual(self.headings(self.page()), [(NEW[0], "2")])

    def test_a_heading_with_nobody_left_shows_no_number(self):
        """A heading whose only person was skipped on this search still stands above the card, without a number."""
        people = self.listing([(1, "strong"), (3, "strong")])
        network.skip(self.store, [people[0]], now=now(), search_id="s1")
        html = self.page()
        self.assertIn(f'<h2 class="fn-section text-label">{NEW[0]} </h2>', html)
        self.assertIn(f'<h2 class="fn-section text-label">{NEW[1]} <span>1</span></h2>', html)

    def test_a_running_search_counts_the_whole_list(self):
        """While a search runs, a heading counts every person under it, also past the shown cards."""
        self.listing([(1, "strong")] * 22, status="running")
        self.assertEqual(self.headings(self.page()), [(NEW[0], "22")])

    def test_the_fragment_shows_the_same_headings(self):
        """The poll fragment reads the same list, so it carries the same headings as the page."""
        self.listing([(1, "strong"), (3, "strong")], status="running")
        self.assertEqual(self.headings(self.page("/searches/s1/cards")), [(NEW[0], "1"), (NEW[1], "1")])

    def test_no_page_shows_a_tier_or_a_grade(self):
        """The page holds no tier number and no tie grade in words or attributes."""
        self.listing([(1, "strong"), (3, "medium"), (6, "none")])
        html = self.page()
        self.assertNotIn("tier", html.lower())
        text = re.sub(r"<[^>]*>", " ", html)
        self.assertNotIn("strong", text)
        self.assertNotIn("medium", text)


class AsideHeadingsTest(ResultsPageCase):
    def listing(self, rows: list[tuple[str, int, str | None]], version: int = 2) -> list[str]:
        """A search s1 with chips of the version, one made-up person per (section, tier, aside), a strong tie each."""
        people = [self.person(f"Person {n:02}") for n in range(len(rows))]
        self.store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None,
                                        dirty=False, llm_mode="replay", settings_json="{}", boot_id="b",
                                        chips=Chips(version=version)))
        self.store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=p, person_ids=[p], hit_person_ids=[p], card_person_ids=[p], section=section,
                      rank=n, score=1.0, lane_ranks={"seeds": n}, tier=tier, fit=CardFit(tie_grade="strong"), aside=aside)
            for n, (p, (section, tier, aside)) in enumerate(zip(people, rows), 1)], [])
        return people

    def headings(self, html: str) -> list[tuple[str, str]]:
        return re.findall(r'<h2 class="fn-section text-label">(.*?) <span>(.*?)</span></h2>', html)

    def count_text(self, html: str) -> str:
        return re.sub(r"<[^>]*>", "", re.search(r'<p class="fn-count text-meta">(.*?)</p>', html, re.DOTALL).group(1))

    def results(self):
        return present.results(self.store, self.store.get_search("s1"), date(2026, 11, 17))

    def test_the_aside_groups_follow_the_open_headings(self):
        """Each group set aside stands under its own heading after the open headings, in list order."""
        self.listing([("new", 1, None), ("new", 3, None), ("new", 2, "outside"), ("new", 1, "abroad"), ("new", 5, "unfit")])
        self.assertEqual(self.headings(self.page()), [(NEW[0], "1"), (NEW[1], "1"), (ASIDE_HEADINGS["outside"], "1"),
                                                      (ASIDE_HEADINGS["abroad"], "1"), (ASIDE_HEADINGS["unfit"], "1")])

    def test_the_count_covers_the_network_and_headings_1_to_3(self):
        """A network person and tiers 1, 3 and 5 are counted; tier 7 and a person set aside are not."""
        self.listing([("network", 7, None), ("new", 1, None), ("new", 3, None), ("new", 5, None), ("new", 7, None),
                      ("new", 2, "outside")])
        self.assertTrue(self.count_text(self.page()).startswith("4 people"))
        found = self.results()
        self.assertEqual((found.matched, found.total, len(found.order)), (4, 6, 6))

    def test_a_network_person_and_a_heading_1_person_without_a_place_are_both_matched_and_off_the_map(self):
        """matched and not_on_map count the same open people."""
        self.listing([("network", None, None), ("new", 1, None), ("new", 7, None), ("new", 2, "outside")])
        found = self.results()
        self.assertEqual((found.matched, found.not_on_map, len(found.network), len(found.new)), (2, 2, 1, 1))

    def test_a_version_1_search_keeps_its_list_count_and_map(self):
        """On version-1 chips every kept person is open, heading 4 included."""
        self.listing([("new", 1, None), ("new", 7, None)], version=1)
        self.assertTrue(self.count_text(self.page()).startswith("2 people"))
        found = self.results()
        self.assertEqual((found.matched, found.not_on_map, len(found.new)), (2, 2, 2))
        self.assertTrue(all(present.is_open(c, chips) for c in self.store.list_candidates("s1") for chips in (Chips(), None)))

    def test_an_outside_card_names_its_place_fact_and_source(self):
        """The reason line of a card set aside as outside is the place the ranker read, with its source."""
        (person,) = self.listing([("new", 2, "outside")])
        self.claim(person, "location", "Denver", lat=39.74, lon=-104.99)
        card = self.card(self.page(), person)
        self.assertIn("Based in Denver", card)
        self.assertIn("example.org", card)

    def test_an_outside_card_whose_place_claim_is_gone_has_no_reason_line(self):
        """Without a located place the card renders with no place fact."""
        (person,) = self.listing([("new", 2, "outside")])
        self.assertNotIn("Based in", self.card(self.page(), person))

    def test_an_unfit_card_shows_the_fit_check_line(self):
        """A card set aside by the fit check says so in its second line."""
        (person,) = self.listing([("new", 5, "unfit")])
        self.assertIn(UNFIT_LINE, self.card(self.page(), person))

if __name__ == "__main__":
    unittest.main()
