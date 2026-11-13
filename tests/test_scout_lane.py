import logging
import unittest
from unittest import mock

from fn import pageread
from fn.contracts import Chip, Chips, LaneIn, ScoutLead, ScoutLeads
from fn.lanes import scout as lane
from fn.steps import StepContext, run_step
from fn.worker import Worker, new_id, now
from tests.helpers import StubHttp, make_db, make_settings
from tests.test_extract import by_marker, mention, relation

WISH = Chips(tie=Chip(text="Belgian", origin="edited", need="nice"), version=2)
QUESTION = "Which Belgian-born chefs work in Chicago?"
JAN, EVA = "https://example.org/jan", "https://example.org/eva"
JAN_TEXT = "Cafe Test\nJan Peeters is head chef at Cafe Test."
EVA_TEXT = "Cafe Test\nEva Maes is pastry chef at Cafe Test."


class ResearchLLM:
    """Answers the scout task with the same leads for every angle and the extract task per page by marker."""

    def __init__(self, leads: list[ScoutLead], people: dict[str, list[dict]]):
        self.leads, self.answer, self.calls = leads, by_marker(people), []

    def structured(self, task, data, schema):
        self.calls.append(task)
        value = ScoutLeads(searches=["q"], people=self.leads) if task == "scout" else schema.model_validate(
            {"people": self.answer(data["page"])})
        return type("Result", (), {"value": value})()


def lead(name: str, *pages: str, place: str = "", employer: str = "Cafe Test") -> ScoutLead:
    return ScoutLead(name=name, role="Chef", employer=employer, place=place, pages=list(pages))


def head(name: str, text: str, *relations: dict) -> dict:
    return mention(name, f"{name} is head chef at Cafe Test.", "head chef", *relations) | {"quote": text}


class ScoutLaneTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"scout": True})
        self.store = make_db(self, self.settings)

    def run_lane(self, leads: list[ScoutLead], pages: dict[str, str | None], people: dict[str, list[dict]] | None = None,
                 chips: Chips = WISH, question: str = QUESTION, settings=None):
        """Run the lane with the pages given by address (None fails to read) and return its output."""
        self.llm = ResearchLLM(leads, people or {})
        self.urls, self.windowed = [], []

        def read_all(ctx, urls):
            self.urls = list(urls)
            return [pageread.Read(u, f"Title {i}", pages.get(u), None if pages.get(u) else "a 404",
                                  published=getattr(self, "published", {}).get(u)) for i, u in enumerate(urls)]

        def windows(text, names, **kwargs):
            self.windowed.append(names)
            return text

        settings = settings or self.settings
        worker = Worker(self.store, settings, llm=self.llm, http=StubHttp())
        self.addCleanup(worker.shutdown)
        search_id = worker.create_search(question, chips, "edited").id
        ctx = StepContext(search_id=search_id, store=self.store, llm=self.llm, http=StubHttp(), now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        with mock.patch("fn.pageread.read_all", read_all), mock.patch("fn.pageread.windows", windows):
            return run_step(ctx, "lane:scout", lane.run, LaneIn(search_id=search_id, chips=chips, question=question))

    def reasons(self, out, stage: str, kept: bool | None = None) -> list[str]:
        return [c.reason for c in out.considered if c.stage == stage and kept in (None, c.kept)]

    def test_two_leads_on_three_pages_give_two_hits_with_claims_on_page_sources(self):
        """Each lead is a hit of lane scout; its claims sit on sources of kind page; windows got the giving leads' names."""
        out = self.run_lane([lead("Jan Peeters", JAN, "https://example.org/more"), lead("Eva Maes", EVA)],
                            {JAN: JAN_TEXT, EVA: EVA_TEXT, "https://example.org/more": "Cafe Test, about us"},
                            {"Jan Peeters is": [head("Jan Peeters", "Jan Peeters is head chef at Cafe Test.")],
                             "Eva Maes is": [head("Eva Maes", "Eva Maes is pastry chef at Cafe Test.")]})
        self.assertEqual([(h.lane, h.name_key) for h in out.hits], [("scout", "jan peeters"), ("scout", "eva maes")])
        self.assertEqual(out.total_seen, 2)
        self.assertEqual(out.query, "press; lists; born; place; speakers; boards")
        kinds = {s.kind for h in out.hits for c in h.claim_ids
                 for s in self.store.get_sources([self.store.get_claim(c).source_id]).values()}
        self.assertEqual(kinds, {"page"})
        self.assertEqual(sorted(map(sorted, self.windowed)), [["Eva Maes"], ["Jan Peeters"], ["Jan Peeters"]])
        self.assertEqual(self.llm.calls.count("scout"), 6)

    def test_a_person_the_page_names_who_is_not_a_lead_is_not_stored(self):
        """A second name on the page gets a dropped row and no stored person."""
        text = JAN_TEXT + "\nZoe Other is sous chef at Cafe Test."
        out = self.run_lane([lead("Jan Peeters", JAN)], {JAN: text}, {"Jan Peeters is": [
            head("Jan Peeters", "Jan Peeters is head chef at Cafe Test."), head("Zoe Other", "Zoe Other is sous chef at Cafe Test.")]})
        self.assertEqual(len(out.hits), 1)
        self.assertTrue(any(r.endswith("Zoe Other is not a lead") for r in self.reasons(out, "mention", False)))
        key = "https://example.org/jan#zoe other"
        self.assertEqual(self.store.person_ids_by_identifier("mention", [key]), {})

    def test_an_initial_matches_the_lead_and_a_namesake_with_the_same_initial_does_not(self):
        """J. Peeters is Jan Peeters; Joris Peeters is not."""
        self.assertTrue(lane.same_person("Jan Peeters", "J. Peeters"))
        self.assertTrue(lane.same_person("J. Peeters", "Dr. Jan Peeters"))
        for lead_, found in (("Jan Peeters", "Joris Peeters"), ("Jan Peeters", "Peeters"), ("Peeters", "Jan Peeters"),
                             ("", "Jan Peeters"), ("Jan Peeters", "Jan Maes")):
            with self.subTest(found=found):
                self.assertFalse(lane.same_person(lead_, found))
        text = "Cafe Test\nJ. Peeters is head chef at Cafe Test.\nJoris Peeters is sous chef at Cafe Test."
        out = self.run_lane([lead("Jan Peeters", JAN)], {JAN: text}, {"J. Peeters is": [
            head("J. Peeters", "J. Peeters is head chef at Cafe Test."),
            head("Joris Peeters", "Joris Peeters is sous chef at Cafe Test.")]})
        self.assertEqual(len(out.hits), 1)
        self.assertTrue(any("Joris Peeters is not a lead" in r for r in self.reasons(out, "mention", False)))

    def test_a_namesake_of_a_lead_on_another_leads_page_is_not_kept(self):
        """Jan Peeters is named on Eva's page, which Jan did not give: only the hit from Jan's own page exists."""
        out = self.run_lane([lead("Jan Peeters", JAN), lead("Eva Maes", EVA)], {JAN: JAN_TEXT, EVA: EVA_TEXT + "\n" + JAN_TEXT},
                            {"Eva Maes is": [head("Eva Maes", "Eva Maes is pastry chef at Cafe Test."),
                                             head("Jan Peeters", "Jan Peeters is head chef at Cafe Test.")],
                             "Jan Peeters is": [head("Jan Peeters", "Jan Peeters is head chef at Cafe Test.")]})
        self.assertEqual(sorted(h.name_key for h in out.hits), ["eva maes", "jan peeters"])
        self.assertEqual(len([r for r in self.reasons(out, "mention", False) if r.endswith("Jan Peeters is not a lead")]), 1)

    def test_a_failed_page_a_lead_without_a_read_page_and_a_lead_nobody_names_each_have_a_row(self):
        """Pages: Jan's fails; Eva's reads but the page reader names nobody; the third lead is named."""
        third = "https://example.org/kim"
        out = self.run_lane([lead("Jan Peeters", JAN), lead("Eva Maes", EVA), lead("Kim Lee", third)],
                            {JAN: None, EVA: EVA_TEXT, third: "Cafe Test\nKim Lee is head chef at Cafe Test."},
                            {"Kim Lee is": [head("Kim Lee", "Kim Lee is head chef at Cafe Test.")]})
        self.assertEqual([h.name_key for h in out.hits], ["kim lee"])
        self.assertIn(f"{JAN}: FN could not read it (a 404)", self.reasons(out, "page", False))
        self.assertIn("Jan Peeters: none of its pages could be read", self.reasons(out, "mention", False))
        self.assertIn("Eva Maes: named on none of its read pages", self.reasons(out, "mention", False))
        self.assertTrue(any(r.endswith("characters read by FN") for r in self.reasons(out, "page", True)))

    def leads_of(self, count: int, pages_each: int = 2) -> list[ScoutLead]:
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return [lead(f"Lead {letters[i // 26]}{letters[i % 26]}", *(f"https://example.org/{i}/{p}" for p in range(pages_each)))
                for i in range(count)]

    def test_thirty_leads_with_two_pages_read_all_first_pages_and_ten_second_pages(self):
        """60 pages are named; 40 are read: the 30 first pages, then the second pages of the first 10 leads."""
        leads = self.leads_of(30)
        out = self.run_lane(leads, {u: "Cafe Test text" for ld in leads for u in ld.pages})
        self.assertEqual(self.urls, [ld.pages[0] for ld in leads] + [ld.pages[1] for ld in leads[:10]])
        over = [r for r in self.reasons(out, "page", False) if "over the limit of 40 pages" in r]
        self.assertEqual(over, [f"{ld.pages[1]}: over the limit of 40 pages" for ld in leads[10:]])
        self.assertEqual(self.reasons(out, "mention", False).count("Lead AK: over the limit of 40 pages"), 0)
        self.assertFalse([r for r in self.reasons(out, "mention", False) if "over the limit" in r])

    def test_fifty_leads_leave_the_last_ten_without_a_page(self):
        """40 first pages fill the limit, so the last 10 leads get the over-the-limit row and the first 40 do not."""
        leads = self.leads_of(50)
        out = self.run_lane(leads, {u: "Cafe Test text" for ld in leads for u in ld.pages})
        self.assertEqual(len(self.urls), 40)
        self.assertEqual([r for r in self.reasons(out, "mention", False) if "over the limit" in r],
                         [f"{ld.name}: over the limit of 40 pages" for ld in leads[40:]])

    def test_pages_past_two_are_not_read_and_one_address_is_read_once(self):
        """A third page of a lead is ignored; two leads giving one page read it once, with both names to windows."""
        shared = "https://example.org/shared"
        self.run_lane([lead("Jan Peeters", shared, JAN, EVA), lead("Eva Maes", shared)], {shared: JAN_TEXT, JAN: JAN_TEXT})
        self.assertEqual(self.urls, [shared, JAN])
        self.assertEqual(sorted(self.windowed[0]), ["Eva Maes", "Jan Peeters"])

    PLACE = "Fairfield, Connecticut"

    def place_claims(self, text: str, place: str = PLACE, *relations: dict):
        out = self.run_lane([lead("Jan Peeters", JAN, place=place)], {JAN: text}, {"Jan Peeters is": [
            head("Jan Peeters", "Jan Peeters is head chef at Cafe Test.", *relations)]})
        (hit,) = out.hits
        return out, [c for c in map(self.store.get_claim, hit.claim_ids) if c.relation == "lives_in"]

    def test_a_place_printed_near_the_name_becomes_a_lives_in_claim_with_the_page_line_as_quote(self):
        """The city before the comma stands in the line next to the name; the claim value is the lead's full place."""
        line = "The Fairfield shop opened in 2019."
        out, found = self.place_claims(f"{JAN_TEXT}\n{line}")
        (claim,) = found
        self.assertEqual((claim.value, claim.quote, claim.kind), (self.PLACE, line, "location"))
        self.assertIn("Jan Peeters: place Fairfield, Connecticut from the page line", self.reasons(out, "mention", True))

    def test_a_place_far_from_the_name_or_absent_gives_no_claim(self):
        """1,500 characters between the name and the city, or no city at all, leave the page reader's claims alone."""
        far = f"{JAN_TEXT}\n" + "x " * 750 + "\nThe Fairfield shop opened in 2019."
        self.assertEqual(self.place_claims(far)[1], [])
        self.assertEqual(self.place_claims(JAN_TEXT + "\nNothing about a town here.")[1], [])
        self.assertEqual(self.place_claims(JAN_TEXT + "\nThe Fairfieldton shop opened in 2019.")[1], [])

    def test_a_hit_that_already_has_a_lives_in_claim_gets_no_second_one(self):
        """The page reader states Stamford; the lead's place Fairfield is not added beside it."""
        text = f"{JAN_TEXT}\nJan Peeters lives in Stamford. The Fairfield shop opened in 2019."
        _, found = self.place_claims(text, self.PLACE, relation("lives_in", "Stamford", "Jan Peeters lives in Stamford."))
        self.assertEqual([c.value for c in found], ["Stamford"])

    def employer_claims(self, text: str, employer: str, *relations: dict):
        out = self.run_lane([lead("Jan Peeters", JAN, employer=employer)], {JAN: text}, {"Jan Peeters is": [
            head("Jan Peeters", "Jan Peeters is head chef.", *relations)]})
        (hit,) = out.hits
        return out, [c for c in map(self.store.get_claim, hit.claim_ids) if c.relation == "works_at"]

    def test_an_employer_the_page_prints_becomes_a_works_at_claim_with_the_page_line_as_quote(self):
        """The reader gave no employer; the lead's stands on the page without its legal form and becomes the claim."""
        out, (claim,) = self.employer_claims("Jan Peeters is head chef.\nCafe Test opened in 2019.", "Cafe Test LLC")
        self.assertEqual((claim.value, claim.quote, claim.kind), ("Cafe Test", "Cafe Test opened in 2019.", "affiliation"))
        self.assertIn("Jan Peeters: employer Cafe Test LLC from the page line", self.reasons(out, "mention", True))

    def test_an_employer_only_in_the_page_title_is_found_on_the_first_line(self):
        """A bio page names the firm in its title alone; the stored text opens with the title, so the claim quotes it."""
        _, (claim,) = self.employer_claims("Jan Peeters is head chef.", "Title 0")
        self.assertEqual((claim.value, claim.quote_start), ("Title 0", 0))

    def test_an_employer_the_page_does_not_print_or_the_reader_gave_adds_nothing(self):
        """No line holds the lead's employer, or the page reader already gave a works_at claim."""
        self.assertEqual(self.employer_claims("Jan Peeters is head chef.", "Bistro Elsewhere")[1], [])
        text = "Jan Peeters is head chef.\nHe works at Bakery Voorbeeld. Cafe Test is next door."
        _, found = self.employer_claims(text, "Cafe Test", relation("works_at", "Bakery Voorbeeld", "He works at Bakery Voorbeeld."))
        self.assertEqual([c.value for c in found], ["Bakery Voorbeeld"])

    def test_a_past_job_at_the_employer_is_not_restated_as_current(self):
        """The page reader read 'previously worked at Cafe Test'; the lead's employer Cafe Test adds no works_at claim."""
        text = "Jan Peeters is head chef.\nHe previously worked at Cafe Test."
        past = relation("worked_at", "Cafe Test", "He previously worked at Cafe Test.")
        self.assertEqual(self.employer_claims(text, "Cafe Test", past)[1], [])

    def test_an_employer_far_from_the_name_and_a_one_word_rest_of_a_legal_form_add_nothing(self):
        """A line 1,500 characters from the name is someone else's; 'Baker LLP' is never cut to the word 'baker'."""
        far = "Jan Peeters is head chef.\n" + "x " * 750 + "\nCafe Test hired a new manager."
        self.assertEqual(self.employer_claims(far, "Cafe Test")[1], [])
        self.assertEqual(self.employer_claims("Jan Peeters is head chef.\nThe head baker left.", "Baker LLP")[1], [])

    def test_a_page_that_never_writes_the_leads_name_gives_no_place_or_employer(self):
        """The page reader matched 'J. Peeters'; the family name stands on the page, so the lines count. A page
        without the family name at all gives nothing from the lead."""
        from fn import extract
        from fn.contracts import page_source
        source = page_source(JAN, "Team", "Our chef runs Cafe Test in Fairfield.", {}, now(), None, kind="page", plain=True)
        self.assertIsNone(extract.stated_employer("p", source, "Jan Peeters", "Cafe Test"))
        self.assertIsNone(extract.stated_place("p", source, "Jan Peeters", "Fairfield, Connecticut", None))

    def test_claims_carry_the_pages_own_date_or_the_day_it_was_read(self):
        """An undated page dates its claims by the day FN read it; a page with a date of its own by that date."""
        out = self.run_lane([lead("Jan Peeters", JAN)], {JAN: JAN_TEXT}, {"Jan Peeters is": [head("Jan Peeters", "Jan Peeters is head chef at Cafe Test.")]})
        claims = [self.store.get_claim(c) for c in out.hits[0].claim_ids]
        self.assertEqual({(c.claim_date, c.date_method) for c in claims}, {(now().date().isoformat(), "read_date")})
        self.published = {EVA: "2024-05-17"}
        out = self.run_lane([lead("Eva Maes", EVA)], {EVA: EVA_TEXT}, {"Eva Maes is": [head("Eva Maes", "Eva Maes is pastry chef at Cafe Test.")]})
        claims = [self.store.get_claim(c) for c in out.hits[0].claim_ids]
        self.assertEqual({(c.claim_date, c.date_method, c.date_precision) for c in claims}, {("2024-05-17", "page_date", "day")})

    def test_a_long_line_is_cut_to_300_characters_around_the_place(self):
        """The quote holds the place and is at most 300 characters."""
        line = "a " * 400 + "The Fairfield shop opened " + "b " * 400
        _, (claim,) = self.place_claims(f"{JAN_TEXT}\n{line}")
        self.assertLessEqual(len(claim.quote), 300)
        self.assertIn("Fairfield", claim.quote)

    def test_the_lane_off_old_chips_and_an_empty_question_give_a_note_and_make_no_call(self):
        """Each reason is one note row, with no LLM call and no page read."""
        off = self.settings.model_copy(update={"scout": False})
        for kwargs, reason in (({"settings": off}, "web research is off"),
                               ({"chips": Chips()}, "chips stored before this round, so no web research"),
                               ({"question": ""}, "no question text")):
            with self.subTest(reason=reason):
                out = self.run_lane([lead("Jan Peeters", JAN)], {JAN: JAN_TEXT}, **kwargs)
                self.assertEqual([c.reason for c in out.considered], [reason])
                self.assertEqual((self.llm.calls, self.urls, out.hits, out.total_seen), ([], [], [], 0))

    def test_no_leads_give_no_hits_and_read_nothing(self):
        """When the researcher names nobody, the lane returns its angle rows only."""
        out = self.run_lane([], {})
        self.assertEqual((out.hits, out.total_seen, self.urls), ([], 0, []))
        self.assertEqual(len(out.considered), 6)

    def test_without_an_llm_or_http_client_the_lane_raises(self):
        """The check comes after the notes."""
        ctx = StepContext(search_id="s", store=self.store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        with self.assertRaisesRegex(RuntimeError, "needs an HTTP client and an LLM"):
            lane.run(ctx, LaneIn(search_id="s", chips=WISH, question=QUESTION))
