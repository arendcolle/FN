import re
import unittest
from datetime import date

from fn import network, present
from fn.contracts import Candidate, CardFit, Chip, Chips, Place, Search, StepRun
from fn.present import HEADINGS, OLD_LINE
from fn.worker import now
from tests.test_results_page import YEAR, ResultsPageCase

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
                                        chips=Chips(version=version, place=Place(text="Boston", origin="parsed", kind="metro",
                                                                                 need="must"))))
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
        """The groups set aside stand under one Set aside heading after the open headings, each as a group in order."""
        self.listing([("new", 1, None), ("new", 3, None), ("new", 2, "outside"), ("new", 1, "abroad"), ("new", 5, "unfit")])
        html = self.page()
        self.assertEqual(self.headings(html), [(NEW[0], "1"), (NEW[1], "1"), ("Set aside", "3")])
        self.assertEqual(re.findall(r'<span class="fn-aside__title">(.*?)</span>', html),
                         ["Outside the Boston area", "Outside the US", "Other roles or topics"])

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

    def test_an_unfit_card_shows_no_line_beyond_the_tie_line(self):
        """A card set aside by the fit check has its tie line and no line that says why it is set aside."""
        (person,) = self.listing([("new", 5, "unfit")])
        card = self.card(self.page(), person)
        self.assertEqual(re.findall(r'<p class="(fn-card__[a-z]+)', card), ["fn-card__fit"])

BOSTON = Place(text="Boston", origin="parsed", kind="metro", need="must")


def chip(text: str, need: str = "must") -> Chip:
    return Chip(text=text, origin="parsed", need=need)


class SetAsideGroupsTest(ResultsPageCase):
    def listing(self, rows: list[tuple[str, int, str | None]], chips: Chips | None = None, status: str = "done") -> list[str]:
        """A search s1 with the chips, one made-up person per (section, tier, aside), a strong tie each."""
        people = [self.person(f"Person {n:02}") for n in range(len(rows))]
        self.store.create_search(Search(id="s1", question="q", status=status, created_at=now(), code_sha=None, dirty=False,
                                        llm_mode="replay", settings_json="{}", boot_id="b",
                                        chips=chips or Chips(version=2, place=BOSTON)))
        self.store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=p, person_ids=[p], hit_person_ids=[p], card_person_ids=[p], section=section,
                      rank=n, score=1.0, lane_ranks={"seeds": n}, tier=tier, fit=CardFit(tie_grade="strong"), aside=aside)
            for n, (p, (section, tier, aside)) in enumerate(zip(people, rows), 1)], [])
        return people

    def titles(self, html: str) -> list[tuple[str, str]]:
        return re.findall(r'<span class="fn-aside__title">(.*?)</span>(?: <span class="fn-aside__count text-meta">(.*?)</span>)?', html)

    def opened(self, html: str) -> list[str]:
        return re.findall(r'<details class="fn-aside" data-group="(\w+)" open>', html)

    def cards_in(self, html: str, group: str) -> int:
        body = re.search(rf'<details class="fn-aside" data-group="{group}"[^>]*>(.*?)</details>', html, re.DOTALL).group(1)
        return body.count('<article class="fn-card"')

    def count_text(self, html: str) -> str:
        return re.sub(r"<[^>]*>", "", re.search(r'<p class="fn-count text-meta">(.*?)</p>', html, re.DOTALL).group(1))

    def test_the_groups_follow_group_keys_under_set_aside_with_their_total_and_empty_ones_are_left_out(self):
        """People set aside in any order stand in GROUP_KEYS order under one Set aside heading with their total."""
        self.listing([("new", 1, None), ("new", 5, "unfit"), ("new", 2, "abroad"), ("new", 2, "abroad"), ("new", 7, None),
                      ("new", 3, "outside")])
        html = self.page()
        self.assertIn('<h2 class="fn-section text-label">Set aside <span>5</span></h2>', html)
        self.assertEqual(self.titles(html), [("Other people found", "1"), ("Outside the Boston area", "1"),
                                             ("Outside the US", "2"), ("Other roles or topics", "1")])
        self.assertEqual(self.opened(html), [])
        self.setUp()
        self.listing([("new", 1, None), ("new", 2, "abroad")])
        self.assertEqual(self.titles(self.page()), [("Outside the US", "1")])

    def test_everyone_set_aside_gives_zero_people_and_the_groups_without_a_notice(self):
        """A done search whose people are all set aside has the count line, the groups and no empty-results notice."""
        self.listing([("new", 2, "abroad"), ("new", 5, "unfit")])
        html = self.page()
        self.assertTrue(self.count_text(html).startswith("0 people"))
        self.assertEqual(self.titles(html), [("Outside the US", "1"), ("Other roles or topics", "1")])
        self.assertNotIn("fn-notice", html)
        self.assertIn("FN found no", html)

    def test_the_status_element_holds_the_status_line_while_running_and_the_count_when_done(self):
        """One div with role status stands first in the list: the status line while running, the count line when done."""
        self.listing([("new", 1, None)], status="running")
        self.assertIn('<div role="status"><p class="fn-status text-strong">', self.page())
        self.setUp()
        self.listing([("new", 1, None)])
        self.assertIn('<div role="status"><p class="fn-count text-meta">', self.page())

    def test_a_group_of_61_shows_20_cards_and_show_more_opens_it_at_40(self):
        """The first 20 cards, '20 of 61 shown' and a link that opens the group at 40; the group in the query opens
        with its shown count and the others stay closed."""
        people = self.listing([("new", 2, "abroad")] * 61 + [("new", 5, "unfit")])
        html = self.page()
        self.assertEqual((self.cards_in(html, "abroad"), self.opened(html)), (20, []))
        self.assertIn('<span>20 of 61 shown</span><a class="fn-btn fn-btn--quiet text-control" '
                      f'href="/searches/s1?group=abroad&group_shown=40#card-{people[20]}">Show 20 more</a>', html)
        html = self.page(group="abroad", group_shown="40")
        self.assertEqual((self.cards_in(html, "abroad"), self.opened(html)), (40, ["abroad"]))
        self.assertIn(f'href="/searches/s1?group=abroad&group_shown=60#card-{people[40]}">Show 20 more</a>', html)
        self.assertIn(f'<a href="/people/{people[0]}?search=s1&shown=40&card={people[0]}&from=card">', html)

    def test_bad_group_values_give_the_default_page(self):
        """An unknown group, a huge or non-numeric shown count and no group at all give closed groups of 20 cards."""
        self.listing([("new", 2, "abroad")] * 25)
        for params in ({"group": "died", "group_shown": "9999999"}, {"group": "abroad", "group_shown": "9999999"},
                       {"group": "abroad", "group_shown": "x"}, {"group_shown": "40"}):
            with self.subTest(params=params):
                html = self.page(**params)
                self.assertEqual(self.cards_in(html, "abroad"), 20)
                self.assertEqual(self.opened(html), ["abroad"] if params.get("group") == "abroad" else [])

    def test_a_group_whose_only_person_was_skipped_here_stays_with_the_skipped_card_and_no_number(self):
        """The group keeps its title and the skipped card, and its count is left out."""
        people = self.listing([("new", 2, "abroad")])
        network.skip(self.store, [people[0]], now=now(), search_id="s1")
        html = self.page()
        self.assertEqual(self.titles(html), [("Outside the US", "")])
        self.assertIn("Skipped Person 00", html)

    def test_an_outside_card_has_no_place_in_its_role_line_and_its_set_aside_line_comes_before_the_reason(self):
        """The role line ends after the employer; 'Based in …' with its source follows it and precedes the reason."""
        (person,) = self.listing([("new", 2, "outside")])
        self.claim(person, "affiliation", "Example Lab", relation="works_at", claim_date=YEAR)
        self.claim(person, "location", "Denver, CO", lat=39.74, lon=-104.99, claim_date=YEAR)
        reason = self.claim(person, "topic", "Tides", source_kind="record", title="OpenAlex work Tides")
        self.store.save_candidates("s1", [self.store.list_candidates("s1")[0].model_copy(update={"reason_claim_ids": [reason]})], [])
        card = self.card(self.page(), person)
        self.assertIn('<p class="fn-card__role text-body">Example Lab</p>', card)
        line = re.search(r'<p class="fn-card__fit text-small">Based in Denver, CO · <a href="[^"]+" class="fn-card__source">'
                         r'example.org</a></p>', card)
        self.assertTrue(line, card)
        self.assertLess(line.start(), card.index("fn-card__reason"))

    def test_an_employer_place_reads_works_at_the_organization_and_its_city(self):
        """With no stated place the line names the employer and its city, and the role line does not repeat the city."""
        (person,) = self.listing([("new", 2, "outside")])
        self.org("ror:0fict0003", "Example Lab", "US", "Houston", 29.76, -95.37)
        self.claim(person, "affiliation", "Example Lab", relation="works_at", org_id="ror:0fict0003", claim_date=YEAR)
        card = self.card(self.page(), person)
        self.assertIn("Works at Example Lab, Houston · ", card)
        self.assertNotIn("Houston</p>", card.split("Works at")[0])

    def test_the_reading_line_follows_the_button_and_a_running_list_holds_it_in_a_template(self):
        """The line stands after the Search button on the page, not on Home or for version 1 chips; only a running
        list holds it in template data-read."""
        chips = Chips(version=2, roles=[chip("scientists")], tie=chip("Flemish", "nice"), place=BOSTON)
        self.listing([("new", 1, None)], chips=chips)
        html = self.page()
        self.assertIn('text-control">Search</button><p class="fn-search__read text-small">'
                      '<span>Required: scientists, in the Boston area</span><span> · Wished: Flemish</span></p></form>', html)
        self.assertNotIn("<template", html)
        self.assertNotIn("fn-search__read", self.page("/"))
        self.setUp()
        self.listing([("new", 1, None)], chips=Chips(version=1, roles=[chip("scientists")]))
        self.assertNotIn("fn-search__read", self.page())
        self.setUp()
        self.listing([("new", 1, None)], chips=chips, status="running")
        self.assertIn('<template data-read><p class="fn-search__read text-small">', self.page("/searches/s1/cards"))

    def test_the_no_match_line_names_what_was_not_found_in_each_form(self):
        """Nobody under the first heading gives the line; a required tie changes its second sentence, a required place
        adds the place words, roles come before topics and join with 'or', and a question without a tie leaves the tie out."""
        found = "with a known tie to Flanders or Belgium. "
        rows = [("new", 5, None)]
        cases = [
            (Chips(version=2, roles=[chip("marine biologists")], place=BOSTON),
             "FN found no marine biologists in the Boston area. "
             "The people below have a known tie, but FN could not confirm their topic."),
            (Chips(version=2, roles=[chip("marine biologists")], tie=chip("Flemish", "nice"), place=BOSTON),
             f"FN found no marine biologists in the Boston area {found}The closest people are below."),
            (Chips(version=2, topics=[chip("tides"), chip("wind")], tie=chip("Flemish", "nice")),
             f"FN found no tides or wind {found}The closest people are below."),
            (Chips(version=2, roles=[chip("a"), chip("b"), chip("c")], tie=chip("Flemish"), place=BOSTON),
             f"FN found no a, b or c in the Boston area {found}"
             "The people below have a known tie, but FN could not confirm their topic."),
            (Chips(version=2, tie=chip("Flemish"), place=BOSTON.model_copy(update={"need": "nice"})),
             f"FN found no people {found}The people below have a known tie, but FN could not confirm their topic."),
        ]
        for chips, line in cases:
            with self.subTest(line=line[:40]):
                self.setUp()
                self.listing(rows, chips=chips)
                self.assertIn(f'<p class="fn-note text-body">{line}</p>', self.page())

    def test_the_no_match_line_is_left_out_while_running_with_a_first_heading_person_and_on_version_1(self):
        """A running search, a first-heading person or version 1 chips give no line."""
        chips = Chips(version=2, roles=[chip("scientists")])
        self.listing([("new", 5, None)], chips=chips, status="running")
        self.assertNotIn("FN found no", self.page())
        self.setUp()
        self.listing([("new", 1, None), ("new", 5, None)], chips=chips)
        self.assertNotIn("FN found no", self.page())
        self.setUp()
        self.listing([("new", 5, None)], chips=Chips(version=1, roles=[chip("scientists")]))
        self.assertNotIn("FN found no", self.page())

    def test_without_a_tie_chip_a_person_with_the_topic_and_no_tie_is_a_full_match(self):
        """A question that asks for no tie gives no line when someone stands under "Topic, no known tie"; with a wished
        tie the same list still gets the line."""
        rows = [("new", 3, None), ("new", 5, None)]
        self.listing(rows, chips=Chips(version=2, roles=[chip("scientists")], place=BOSTON))
        self.assertNotIn("FN found no", self.page())
        self.setUp()
        self.listing(rows, chips=Chips(version=2, roles=[chip("scientists")], tie=chip("Flemish", "nice"), place=BOSTON))
        self.assertIn("FN found no scientists in the Boston area with a known tie", self.page())

    def test_the_geo_answer_counts_only_open_people_when_it_says_who_is_shown(self):
        """A set-aside person ahead of 21 open people does not move them: the first 20 are shown, the 21st is not."""
        people = self.listing([("new", 2, "abroad")] + [("new", 1, None)] * 21)
        for p in people:
            self.claim(p, "location", "Gent", lat=51.05, lon=3.72)
        listed = self.client.get("/api/searches/s1/geo").json()["list"]
        self.assertEqual([listed[p]["shown"] for p in people[1:]], [True] * 20 + [False])

    def cut_died(self, people: list[str]) -> None:
        """Store the search with the given people cut as died."""
        kept = [Candidate.model_validate({**c.model_dump(), "cut_reason": "died", "aside": None}) if c.person_id in people else c
                for c in self.store.list_candidates("s1")]
        self.store.save_candidates("s1", kept, [])

    def test_a_person_cut_as_died_gives_no_set_aside_heading_group_or_count(self):
        """An open person and one cut as died give one person, no Set aside heading and no group."""
        _, dead = self.listing([("new", 1, None), ("new", 1, None)])
        self.cut_died([dead])
        html = self.page()
        self.assertTrue(self.count_text(html).startswith("1 person"))
        self.assertNotIn("Set aside", html)
        self.assertEqual((self.titles(html), self.opened(html)), ([], []))
        self.assertNotIn("Person 01", html)

    def test_the_group_died_in_the_query_opens_no_group(self):
        """An old link with group=died shows the closed groups, none of them for the dead."""
        people = self.listing([("new", 2, "abroad"), ("new", 1, None)])
        self.cut_died([people[1]])
        html = self.page(group="died", group_shown="40")
        self.assertEqual((self.titles(html), self.opened(html)), ([("Outside the US", "1")], []))

    def test_an_old_first_record_is_its_own_paragraph_with_the_year_marked_and_an_aside_card_has_none(self):
        """The old line is a fit paragraph of its own with the year in text-year; a card set aside shows none."""
        for aside, shown in ((None, True), ("unfit", False)):
            with self.subTest(aside=aside):
                self.setUp()
                (person,) = self.listing([("new", 1, aside)])
                self.claim(person, "affiliation", "Example University", relation="studied_at", claim_date="1958",
                           date_method="record_field")
                self.assertEqual('<p class="fn-card__fit text-small">First record <span class="text-year">1958</span>, '
                                 'nothing recent</p>' in self.card(self.page(), person), shown)

    def test_the_status_line_says_looking_up_only_for_version_2_chips_with_a_running_deepen_step(self):
        """While the deepen step runs on version-2 chips the status line, data-progress and status JSON say so; version 1,
        a finished step and another step do not."""
        cases = [(2, "deepen", "running", True), (2, "deepen", "ok", False), (2, "fit", "running", False),
                 (1, "deepen", "running", False)]
        for version, step, status, looking in cases:
            with self.subTest(version=version, step=step, status=status):
                self.setUp()
                self.listing([("new", 1, None)], chips=Chips(version=version, place=BOSTON), status="running")
                self.store.start_step(StepRun(id="r1", search_id="s1", seq=0, step=step, status=status, started_at=now(),
                                              input_model="DeepenIn"), "{}")
                html = self.page()
                progress = re.search(r'data-progress="([^"]*)"', html).group(1)
                self.assertEqual(("Looking up missing facts…" in html, progress.endswith(" looking")), (looking, looking))
                self.assertEqual("Searching…" in html, not looking)
                self.assertEqual(self.page("/searches/s1/cards").count("Looking up missing facts…"), int(looking))
                self.assertEqual(self.client.get("/searches/s1/status").json().get("looking"), True if looking else None)

    def test_an_old_first_record_ends_the_second_line_on_version_2_only(self):
        """A first record from 1958 with nothing recent says so on a version-2 card and not on a version-1 card."""
        for version, ends in ((2, True), (1, False)):
            with self.subTest(version=version):
                self.setUp()
                (person,) = self.listing([("new", 1, None)], chips=Chips(version=version, place=BOSTON))
                self.claim(person, "affiliation", "Example University", relation="studied_at", claim_date="1958",
                           date_method="record_field")
                fits = re.findall(r'<p class="fn-card__fit text-small">(.*?)</p>', self.card(self.page(), person))
                old = re.sub(r"<[^>]*>", "", fits[-1])
                self.assertEqual(old == OLD_LINE.format(year=1958), ends, fits)
                self.assertEqual(old == "First record 1958, nothing recent", ends)


if __name__ == "__main__":
    unittest.main()
