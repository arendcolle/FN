import contextlib
import csv
import hashlib
import io
import unittest
from datetime import UTC, datetime
from unittest import mock

import httpx

from fn import gold, net, orgs
from fn.contracts import (
    Candidate,
    CaseResult,
    ClaimDraft,
    GoldPick,
    Identifier,
    OrgFacts,
    PickResult,
    Source,
)
from fn.lanes import openalex, web
from fn.worker import Worker
from tests.helpers import StubHttp, StubLLM, make_db, make_settings
from tests.test_openalex import route

GS10_CHIPS = {"institutions": [{"text": "MIT", "span": {"start": 25, "end": 28}, "origin": "parsed"}]}
EVENT = "https://www.example.org/events/summit"
LINKEDIN_POST = "https://www.linkedin.com/posts/example-org_summit-activity-7000000000000000000-AbCd"


def candidate(person_ids: list[str], section: str = "new", rank: int = 1) -> Candidate:
    return Candidate(search_id="s", person_id=person_ids[0], person_ids=person_ids, section=section, rank=rank,
                     score=0.1, lane_ranks={"seeds": rank})


def pick(name: str, **fields) -> GoldPick:
    return GoldPick(case_id="GS-00", name=name, gold_tie=fields.pop("gold_tie", "belgian"), **fields)


class PickKeyTest(unittest.TestCase):
    def test_pick_key_gives_the_keys_it_gave_when_frozen(self):
        """Ten names, with a middle initial, accents, a hyphen, a tussenvoegsel and extra spaces, key as when frozen."""
        keys = {"Pat Lee": "pat lee", "Maya J. Ostrand": "maya ostrand", "François Müller": "francois muller",
                "Zoë  Van den Berg": "zoe van den berg", "Jean-Luc Picard": "jean luc picard", "Åsa Lind": "asa lind",
                "O'Neil Brandt": "o neil brandt", "Ana": "ana", "J Visser": "j visser",
                "Karel de Groot-Smit": "karel de groot smit"}
        for name, key in keys.items():
            with self.subTest(name=name):
                self.assertEqual(gold.pick_key(name), key)


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.store = make_db(self)

    def person(self, name: str, openalex_id: str | None = None):
        ident = Identifier(scheme="openalex", value=openalex_id) if openalex_id else Identifier(scheme="seed", value=name)
        return self.store.resolve_person([ident], name)

    def test_a_pinned_pick_matches_its_own_person_and_not_a_namesake(self):
        """Two people named Pat Lee are two candidates; the pin picks the candidate that holds its own person."""
        first, second = self.person("Pat Lee", "A1"), self.person("Pat Lee", "A2")
        candidates = [candidate([first.id], rank=1), candidate([second.id], rank=2)]
        persons = {first.id: first, second.id: second}
        pins = self.store.person_ids_by_identifier("openalex", ["A2", "A9"])
        self.assertEqual(pins, {"A2": second.id})
        found = gold.match(pick("Pat Lee", openalex_id="A2"), candidates, persons, pins.get("A2"))
        self.assertEqual(found.person_id, second.id)

    def test_an_unpinned_pick_matches_by_group_key_ignoring_accents_and_middle_initials(self):
        """The name key folds accents and case, and the group key drops middle initials, as resolve and the trace do."""
        muller, lee = self.person("Francois Q. Muller"), self.person("Pat Lee")
        candidates = [candidate([lee.id], rank=1), candidate([muller.id], rank=2)]
        persons = {muller.id: muller, lee.id: lee}
        self.assertEqual(gold.match(pick("François Müller"), candidates, persons, None).person_id, muller.id)
        self.assertIsNone(gold.match(pick("Pat Leigh"), candidates, persons, None))

    def test_a_pin_the_store_does_not_hold_falls_back_to_the_name(self):
        """An OpenAlex id with no stored person (the author was dropped) matches the seed record of the same name."""
        seed = self.person("Michel Goemans")
        found = gold.match(pick("Michel Goemans", openalex_id="A404"), [candidate([seed.id], rank=8)],
                           {seed.id: seed}, None)
        self.assertEqual(found.rank, 8)

    def test_the_network_candidate_wins_over_a_better_ranked_new_one(self):
        """Two candidates carry the same name: the one in section network is the match, whatever the ranks."""
        a, b = self.person("Pat Lee", "A1"), self.person("Pat Lee", "A2")
        candidates = [candidate([a.id], "new", 1), candidate([b.id], "network", 3)]
        found = gold.match(pick("Pat Lee"), candidates, {a.id: a, b.id: b}, None)
        self.assertEqual((found.section, found.rank), ("network", 3))


class JudgeTest(unittest.TestCase):
    NOWHERE = ("lane:seeds", "not found by any lane; lane:seeds query q")

    def test_found_means_the_top_ten_of_its_section(self):
        """Rank 10 is found; rank 11 is missed at the rank step, with its section and rank still reported."""
        top = gold.judge(pick("A B"), candidate(["p"], "new", 10), ("", ""))
        self.assertEqual((top.verdict, top.section, top.rank, top.lost_step), ("found", "new", 10, ""))
        below = candidate(["p"], "new", 11)
        low = gold.judge(pick("A B"), below, gold.lost_at([], below))
        self.assertEqual((low.verdict, low.rank, low.lost_step), ("missed", 11, "rank"))
        self.assertEqual(low.lost_reason, "ranked new #11, below the top 10")
        network = gold.judge(pick("A B"), candidate(["p"], "network", 2), ("", ""))
        self.assertEqual((network.verdict, network.section), ("found", "network"))

    def test_an_unreachable_pick_is_labelled_no_lane_in_slice_and_a_reachable_one_is_missed(self):
        """reach.json decides the label of a pick that is not in the list.

        The pick keeps the trace's step and reason, and reach.json's evidence follows the reason.
        """
        unreachable = gold.judge(pick("A B", reachable=False, reach_evidence="in none of the files"), None, self.NOWHERE)
        self.assertEqual((unreachable.verdict, unreachable.lost_step), ("no lane in slice", "lane:seeds"))
        self.assertEqual(unreachable.lost_reason, f"{self.NOWHERE[1]}; reach.json: in none of the files")
        reachable = gold.judge(pick("A B", reachable=True), None, self.NOWHERE)
        self.assertEqual((reachable.verdict, reachable.lost_reason), ("missed", self.NOWHERE[1]))
        unknown = gold.judge(pick("A B"), None, self.NOWHERE)
        self.assertEqual(unknown.verdict, "missed")
        ranked_low = gold.judge(pick("A B", reachable=False), candidate(["p"], "new", 40), ("rank", "r"))
        self.assertEqual(ranked_low.verdict, "missed")

    def test_lost_at_prefers_a_dropped_row_then_a_kept_one_then_names_every_lane(self):
        """The step comes from the first dropped row; with none, the last kept row; with no row, every lane and its query."""
        dropped = [[2, "lane:seeds", "-", "-", "not present; query q"],
                   [3, "lane:openalex", "rank", "dropped", "rank 167, below the top 100, score 1.04"]]
        self.assertEqual(gold.lost_at(dropped, None), ("lane:openalex", "rank 167, below the top 100, score 1.04"))
        kept = [[2, "lane:seeds", "fts", "kept", "fts rank 1"], [4, "resolve", "entry", "kept", "1 record"]]
        self.assertEqual(gold.lost_at(kept, None)[0], "resolve")
        absent = [[2, "lane:seeds", "-", "-", "not present; query q1"], [3, "lane:openalex", "-", "-", "not present; query q2"],
                  [4, "resolve", "-", "-", "not present"]]
        self.assertEqual(gold.lost_at(absent, None), (
            "lane:seeds, lane:openalex", "not found by any lane; lane:seeds query q1; lane:openalex query q2"))


class EventPageTest(unittest.TestCase):
    def judged(self, reasons, event_url: str | None = EVENT, near: Candidate | None = None) -> PickResult:
        return gold.judge(pick("A B"), near or candidate(["p"]), ("", ""), reasons=reasons, event_url=event_url)

    def test_a_found_pick_with_every_reason_source_at_the_event_page_is_labelled_event_page(self):
        """The label replaces found only; the pick keeps its section, rank and lanes and has no lost step."""
        near = Candidate(search_id="s", person_id="p", person_ids=["p"], section="new", rank=4, score=0.1,
                         lane_ranks={"web": 4})
        for reasons in ([("vendor_page", EVENT)], [("page", EVENT)], [("vendor_page", EVENT), ("page", EVENT)]):
            with self.subTest(reasons=reasons):
                result = self.judged(reasons, near=near)
                self.assertEqual((result.verdict, result.section, result.rank), ("event page", "new", 4))
                self.assertEqual((result.lanes, result.lost_step, result.lost_reason), ("web #4", "", ""))

    def test_the_same_page_in_another_spelling_on_either_side_is_still_the_event_page(self):
        """URLs compare by host without a leading www. and by decoded path without a trailing slash.

        A query, a fragment, a trailing slash or a percent escape does not make another page.
        """
        spaced = "https://example.org/events/spring summit"
        for reason, event in (("https://example.org/events/summit", EVENT),
                              (EVENT, "https://example.org/events/summit"),
                              ("https://www.example.org/events/summit?utm_source=x#top", EVENT),
                              (EVENT, "https://www.example.org/events/summit?id=7"),
                              ("https://WWW.Example.org/events/summit", EVENT),
                              (EVENT + "/", EVENT),
                              (EVENT, EVENT + "/"),
                              ("https://example.org/events/spring%20summit", spaced),
                              (spaced, "https://example.org/events/spring%20summit/")):
            with self.subTest(reason=reason, event=event):
                self.assertEqual(self.judged([("vendor_page", reason)], event).verdict, "event page")

    def test_one_more_reason_source_or_another_page_makes_the_pick_found(self):
        """Any reason source off the event page, on its host or not, means the pick has other evidence."""
        other = "https://www.example.org/events/other"
        for reasons in ([("vendor_page", EVENT), ("vendor_page", other)],
                        [("vendor_page", EVENT), ("vendor_record", "https://openalex.org/A1")],
                        [("vendor_page", other)],
                        [("vendor_page", "https://www.example.org/")],
                        [("vendor_page", "https://other.org/events/summit")]):
            with self.subTest(reasons=reasons):
                self.assertEqual(self.judged(reasons).verdict, "found")

    def test_only_a_page_source_can_be_the_event_page(self):
        """A record, a vendor record, a seed page or an import at the event page's URL is not the event page."""
        for kind in ("record", "vendor_record", "seed_page", "import"):
            with self.subTest(kind=kind):
                self.assertEqual(self.judged([(kind, EVENT)]).verdict, "found")

    def test_linkedin_finds_are_found_in_a_case_whose_source_is_a_linkedin_post(self):
        """A profile from the LinkedIn lane or a profile page from the web lane is not the post the case names."""
        other_post = LINKEDIN_POST.replace("AbCd", "XyZw")
        for reasons in ([("vendor_record", "https://www.linkedin.com/in/jan-doe")],
                        [("vendor_page", "https://www.linkedin.com/in/jan-doe")],
                        [("vendor_page", other_post)]):
            with self.subTest(reasons=reasons):
                self.assertEqual(self.judged(reasons, LINKEDIN_POST).verdict, "found")
        self.assertEqual(self.judged([("vendor_page", LINKEDIN_POST)], LINKEDIN_POST).verdict, "event page")

    def test_a_pick_with_no_reason_source_or_a_case_without_a_source_is_never_event_page(self):
        """No reason claims, no reasons argument and no event URL each leave a found pick found."""
        self.assertEqual(self.judged([]).verdict, "found")
        self.assertEqual(gold.judge(pick("A B"), candidate(["p"]), ("", "")).verdict, "found")
        self.assertEqual(self.judged([("vendor_page", EVENT)], event_url=None).verdict, "found")

    def test_only_a_pick_that_would_be_found_gets_the_label(self):
        """Event-page reasons change nothing for a pick below the top 10 or one no lane can reach."""
        low = candidate(["p"], "new", 11)
        self.assertEqual(self.judged([("vendor_page", EVENT)], near=low).verdict, "missed")
        unreachable = gold.judge(pick("A B", reachable=False), None, ("lane:seeds", "r"),
                                 reasons=[("vendor_page", EVENT)], event_url=EVENT)
        self.assertEqual(unreachable.verdict, "no lane in slice")

    def test_the_lanes_of_a_pick_come_from_its_candidate_and_a_pick_without_one_has_none(self):
        """lane_ranks gives each lane with its rank, in the candidate's order."""
        near = Candidate(search_id="s", person_id="p", person_ids=["p"], section="new", rank=2, score=0.1,
                         lane_ranks={"seeds": 3, "web": 12})
        self.assertEqual(self.judged([], near=near).lanes, "seeds #3; web #12")
        self.assertEqual(gold.judge(pick("A B"), None, ("lane:seeds", "r")).lanes, "")


class SummaryTest(unittest.TestCase):
    def result(self, verdicts: dict[str, str]) -> CaseResult:
        picks = [PickResult(case_id="GS-10", name=name, verdict=verdict, gold_tie="belgian",
                            section="new" if verdict in ("found", "event page") else None,
                            rank=1 if verdict in ("found", "event page") else None)
                 for name, verdict in verdicts.items()]
        return CaseResult(case_id="GS-10", group="dev", question="q", chips="none", search_id="s", status="done",
                          picks=picks, top=[])

    def test_the_dev_measure_does_not_count_event_page_picks_and_the_summary_has_their_column(self):
        """Two found and two event page picks give 2 of 4, not met, and the Event page column holds the 2."""
        result = self.result({"Michel Goemans": "found", "Pierre Lermusiaux": "found",
                              "Julien de Wit": "event page", "Milena Janjevic": "event page"})
        self.assertEqual(gold.dev_found([result]), (2, 4))
        text = gold.summary([result])
        self.assertIn("Dev success measure: 2 of 4 reachable dev picks rank in the top 10 of their section "
                      "(target 3): not met.", text)
        self.assertIn("| Group | Cases | Picks | Found, network | Found, new | Event page | Missed | No lane in slice |",
                      text)
        self.assertIn("| dev | 1 | 4 | 0 | 2 | 2 | 0 | 0 |", text)

    def test_three_found_and_one_event_page_pick_meet_the_dev_target(self):
        """The measure counts the found picks only, so one event page pick beside three found ones still meets 3."""
        result = self.result({"Michel Goemans": "found", "Pierre Lermusiaux": "found", "Julien de Wit": "found",
                              "Milena Janjevic": "event page"})
        self.assertIn("Dev success measure: 3 of 4 reachable dev picks rank in the top 10 of their section "
                      "(target 3): met.", gold.summary([result]))


class LoadTest(unittest.TestCase):
    def test_all_28_cases_load_and_only_the_nine_dev_picks_carry_a_pin_and_reach(self):
        """reach.json supplies the OpenAlex pin and the reach verdict of the GS-02 and GS-10 picks and no other."""
        cases = gold.load_cases([])
        self.assertEqual(len(cases), 28)
        picks = [p for c in cases for p in c.picks]
        pinned = [p for p in picks if p.openalex_id]
        self.assertEqual({p.case_id for p in pinned}, {"GS-02", "GS-10"})
        self.assertEqual(len(pinned), 9)
        self.assertEqual([p.name for p in pinned if p.reachable], ["Michel Goemans", "Pierre Lermusiaux", "Julien de Wit", "Milena Janjevic"])
        self.assertTrue(all(p.reachable is None for p in picks if not p.openalex_id))
        self.assertEqual([c.id for c in gold.load_cases(["GS-10", "GS-02"])], ["GS-02", "GS-10"])

    def test_every_case_carries_the_source_url_of_the_gold_set(self):
        """GoldCase.source_url is the question's source: 13 cases name a LinkedIn post and GS-09 a page of its own."""
        cases = gold.load_cases([])
        self.assertTrue(all(c.source_url and c.source_url.startswith("http") for c in cases))
        self.assertEqual(sum(c.source_url.startswith("https://www.linkedin.com/posts/") for c in cases), 13)
        urls = {c.id: c.source_url for c in cases}
        self.assertTrue(urls["GS-09"].startswith("https://flandersintheusa.org/event/"))
        self.assertTrue(urls["GS-11"].startswith("https://www.flandersintheusa.org/event/"))

    def test_an_unknown_case_id_is_refused_by_name(self):
        """main prints the unknown id and returns 2 before it opens the database."""
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(gold.main(["GS-02", "GS-99"]), 2)
        self.assertIn("GS-99", errors.getvalue())


class RunCaseTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live"})
        self.store = make_db(self, self.settings)
        self.case = gold.load_cases(["GS-10"])[0]

    def worker(self, llm=None) -> Worker:
        http = net.Client(self.settings, httpx.MockTransport(route))
        worker = Worker(self.store, self.settings, llm=llm or StubLLM(GS10_CHIPS), http=http)
        self.addCleanup(worker.shutdown)
        return worker

    def results(self, case):
        return {p.name: p for p in gold.run_case(self.worker(), case).picks}

    def test_gs10_picks_are_found_by_pin_and_the_rest_are_labelled_with_a_step_and_reason(self):
        """On the recorded MIT responses the four reachable picks rank, Deconinck has no lane, a stranger is missed."""
        stranger = pick("Nobody Atall", reachable=True)
        by_name = self.results(self.case.model_copy(update={"picks": [*self.case.picks, stranger]}))
        for name in ("Michel Goemans", "Pierre Lermusiaux", "Julien de Wit", "Milena Janjevic"):
            self.assertEqual((by_name[name].verdict, by_name[name].section), ("found", "new"), name)
            self.assertTrue(by_name[name].belgian.startswith("Belgian claims: "), name)
        self.assertIn("Université Libre de Bruxelles (no region, name language unknown) affiliated_with 2018",
                      by_name["Milena Janjevic"].belgian)
        self.assertEqual(by_name["Anne Deconinck"].verdict, "no lane in slice")
        self.assertIn("authors_institution_mit_p1.json", by_name["Anne Deconinck"].lost_reason)
        missed = by_name["Nobody Atall"]
        self.assertEqual((missed.verdict, missed.lost_step),
                         ("missed", "lane:seeds, lane:openalex, lane:web, lane:web_topic, lane:linkedin"))
        self.assertIn("not found by any lane; lane:seeds query", missed.lost_reason)
        self.assertIn("lane:openalex query authors filter=last_known_institutions.ror", missed.lost_reason)

    def test_the_belgian_text_gives_scored_years_the_count_and_rank_and_stored_records_of_unfound_picks(self):
        """A found pick lists its scored claims with their years, then belgian_years N, rank R.

        A pick no candidate carries names the Belgian claims of its stored records, or says none is stored.
        """
        facts = Source(id="org", kind="record", url="https://www.wikidata.org/wiki/Q1301699", text="id: Q1301699",
                       content_hash="h0", fetched_at=datetime(2026, 11, 3, tzinfo=UTC))
        orgs.save(self.store, [OrgFacts(id="wikidata:Q1301699", name="KVAB", country_code="BE")], facts, replace=True)
        for name in ("Nobody Atall", "Julien de Wit"):
            text = f"{name}, member of KVAB"
            person = self.store.resolve_person([Identifier(scheme="seed", value=name)], name)
            self.store.upsert_claim(ClaimDraft(
                person_id=person.id, kind="role", relation="member_of", org_id="wikidata:Q1301699", value="KVAB",
                quote=text, quote_start=0, quote_end=len(text),
                source=Source(id=name, kind="page", url="https://example.org/kvab", text=text, content_hash=name)))
        by_name = self.results(self.case.model_copy(update={"picks": [*self.case.picks, pick("Nobody Atall")]}))
        self.assertEqual(by_name["Julien de Wit"].belgian,
                         "Belgian claims: University of Liège (no region, name language unknown) affiliated_with 2023, "
                         "years 2012, 2023; not scored: KVAB (no region, name language unknown) member_of no date; "
                         "belgian_years 2, rank 3")
        self.assertTrue(by_name["Milena Janjevic"].belgian.endswith("years 2013-2014, 2016-2018; belgian_years 5, rank 1"))
        self.assertEqual(by_name["Anne Deconinck"].belgian, "no stored record")
        self.assertEqual(by_name["Nobody Atall"].belgian,
                         "stored, not in the result: KVAB (no region, name language unknown) member_of no date")

    def test_a_pick_cut_by_the_openalex_fetch_limit_is_missed_at_that_lane_with_the_reason(self):
        """With the fetch limit at 1 author, every reachable pick is missed at lane:openalex as 'not fetched'."""
        with mock.patch.object(openalex, "MAX_AUTHORS", 1):
            by_name = self.results(self.case)
        reachable = [by_name[p.name] for p in self.case.picks if p.reachable]
        self.assertEqual([p.verdict for p in reachable], ["missed"] * 4)
        for p in reachable:
            self.assertEqual(p.lost_step, "lane:openalex", p.name)
            self.assertEqual(p.lost_reason, "not fetched: beyond the first 1 authors seen", p.name)

    def test_two_runs_give_the_same_pick_rows(self):
        """After one run has stored what the lanes find, two more runs differ in search id only: every pick row is the same."""
        gold.run_case(self.worker(), self.case)
        first, second = (gold.run_case(self.worker(), self.case) for _ in range(2))
        self.assertNotEqual(first.search_id, second.search_id)
        self.assertEqual(first.picks, second.picks)
        self.assertEqual(first.top, second.top)

    def test_a_failed_search_misses_every_pick_at_the_failed_step(self):
        """When the parse step fails, each pick reports that step and the error instead of a lane trace."""
        llm = StubLLM(error=RuntimeError("claude is logged out"))
        with self.assertLogs("fn.worker", "ERROR"):
            result = gold.run_case(self.worker(llm), self.case)
        self.assertEqual(result.status, "failed")
        goemans = result.picks[0]
        self.assertEqual((goemans.verdict, goemans.lost_step, goemans.lost_reason),
                         ("missed", "parse", "RuntimeError: claude is logged out"))

    def test_a_done_case_with_a_failed_lane_names_the_lane_in_its_line(self):
        """A lane error does not fail the search; the case's status line in the report names the lane that failed."""
        with mock.patch.object(web, "run", side_effect=ConnectionError("search vendor down")):
            result = gold.run_case(self.worker(), self.case)
        self.assertEqual((result.status, result.failed_lanes), ("done", ["lane:web"]))
        self.assertEqual(gold.status_text(result), "done, lane error in lane:web")
        text = gold.report([result], datetime(2026, 10, 30, tzinfo=UTC), "abc123", True, "replay", "live")
        self.assertIn(f"search `{result.search_id}` done, lane error in lane:web, vendor calls", text)

    def test_report_and_top5_hold_the_header_the_pick_rows_and_blank_mark_columns(self):
        """The report names code state and modes and has one table row per pick; top5.csv has at most five cards a case."""
        result = gold.run_case(self.worker(), self.case)
        text = gold.report([result], datetime(2026, 10, 30, tzinfo=UTC), "abc123", True, "replay", "live")
        self.assertIn("code sha `abc123`, dirty True, llm mode replay, http mode live", text)
        self.assertIn("Dev success measure: 4 of 4 reachable dev picks rank in the top 10 of their section", text)
        self.assertIn("| Anne Deconinck | no lane in slice |", text)
        rows = list(csv.DictReader(io.StringIO(gold.top5_csv([result]))))
        self.assertLessEqual(len(rows), 5)
        self.assertEqual(list(rows[0]), gold.TOP5_COLUMNS)
        self.assertEqual({r["good_pick"] for r in rows}, {""})
        self.assertTrue(all(r["reason_quote"] for r in rows))

    def test_the_report_names_the_lanes_behind_each_pick_and_the_vendor_and_llm_cost_of_the_search(self):
        """Lanes come from the candidate's lane_ranks; vendor spend is the OpenAlex calls, LLM cost the parse call."""
        result = gold.run_case(self.worker(), self.case)
        by_name = {p.name: p for p in result.picks}
        self.assertEqual({n: p.lanes for n, p in by_name.items()}, {
            "Michel Goemans": "openalex #3", "Pierre Lermusiaux": "openalex #1", "Julien de Wit": "openalex #2",
            "Milena Janjevic": "openalex #4", "Anne Deconinck": ""})
        self.assertAlmostEqual(result.http_cost_usd, 0.0002)
        self.assertAlmostEqual(result.llm_cost_usd, 0.002)
        text = gold.report([result], datetime(2026, 10, 30, tzinfo=UTC), "abc123", True, "replay", "live")
        self.assertIn("| Pick | Result | Section | Rank | Lanes |", text)
        self.assertRegex(text, r"\| Milena Janjevic \| found \| new \| \d+ \| openalex #4 \|")
        self.assertIn(f"search `{result.search_id}` done, vendor calls $0.0002; "
                      "LLM $0.0020 as the CLI reports it (subscription);", text)

    def test_an_unreachable_pick_no_lane_found_keeps_the_trace_step_and_reason_and_reach_evidence_follows(self):
        """Anne Deconinck is in no recorded file: her row names every lane that missed her, then reach.json's evidence."""
        anne = next(p for p in self.case.picks if p.name == "Anne Deconinck")
        result = self.results(self.case)["Anne Deconinck"]
        self.assertEqual((result.verdict, result.lost_step),
                         ("no lane in slice", "lane:seeds, lane:openalex, lane:web, lane:web_topic, lane:linkedin"))
        self.assertTrue(result.lost_reason.startswith("not found by any lane; lane:seeds query"))
        self.assertTrue(result.lost_reason.endswith(f"; reach.json: {anne.reach_evidence}"))
        self.assertIn("lane:openalex query authors filter=last_known_institutions.ror", result.lost_reason)

    def test_a_cut_pick_is_lost_at_the_rank_step_with_the_reason(self):
        """A pick the ranker cuts is not a candidate of the kept list; its dropped rank row names the reason."""
        with mock.patch("fn.rank.cut_reason", return_value="no_belgian_evidence"):
            result = self.results(self.case)["Michel Goemans"]
        self.assertEqual((result.verdict, result.lost_step, result.lost_reason), ("missed", "rank", "no_belgian_evidence"))


class EventPageRunTest(unittest.TestCase):
    """Whole searches over page claims in the store, so run_case reads the reason sources itself."""

    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.case = gold.load_cases(["GS-10"])[0]

    def claim(self, name: str, url: str, kind: str = "page", line: int = 0):
        """A role claim quoting line 0 or 1 of a two-line page source of the person at url."""
        lines = [f"{name}, professor at MIT", f"{name}, member of KVAB"]
        text = "\n".join(lines)
        person = self.store.resolve_person([Identifier(scheme="seed", value=name)], name)
        source = Source(id=f"{kind}-{url}-{name}", kind=kind, url=url, text=text,
                        content_hash=hashlib.sha256(text.encode()).hexdigest())
        start = text.index(lines[line])
        quote = lines[line]
        return self.store.upsert_claim(ClaimDraft(person_id=person.id, kind="role", value=quote, quote=quote,
                                                  quote_start=start, quote_end=start + len(quote), source=source))

    def run_case(self, source_url: str | None):
        worker = Worker(self.store, self.settings, llm=StubLLM(GS10_CHIPS), http=StubHttp())
        self.addCleanup(worker.shutdown)
        picks = [pick(n) for n in ("Pat Lee", "Kim Roe", "Sam Poe")]
        return {p.name: p for p in gold.run_case(worker, self.case.model_copy(
            update={"picks": picks, "source_url": source_url})).picks}

    def test_a_pick_found_only_on_the_event_page_is_labelled_event_page_and_the_rest_are_found(self):
        """The reasons come from the stored claims of each result card, the event URL from the case.

        Only a pick whose every reason source is a page or vendor page at the case's event URL is labelled
        event page; the rest stay found.
        """
        self.claim("Pat Lee", "https://example.org/events/summit?ref=1")
        self.claim("Kim Roe", "https://www.example.org/events/other")
        self.claim("Sam Poe", EVENT, kind="seed_page")
        by_name = self.run_case(EVENT)
        self.assertEqual({n: p.verdict for n, p in by_name.items()},
                         {"Pat Lee": "event page", "Kim Roe": "found", "Sam Poe": "found"})
        self.assertRegex(by_name["Pat Lee"].lanes, r"^seeds #[123]$")
        self.assertEqual(by_name["Pat Lee"].lost_step, "")

    def test_a_case_without_a_source_keeps_found(self):
        """With no source_url there is no event page to compare with."""
        self.claim("Pat Lee", EVENT)
        self.assertEqual(self.run_case(None)["Pat Lee"].verdict, "found")

    def test_reason_sources_lists_the_kind_and_url_of_each_reason_claim_source_once(self):
        """Claims that are not reasons, and a second claim on the same source, add nothing."""
        first = self.claim("Pat Lee", EVENT)
        second = self.claim("Pat Lee", "https://example.org/other", kind="seed_page")
        same_source = self.claim("Pat Lee", EVENT, line=1)
        self.claim("Pat Lee", "https://example.org/not-a-reason")
        self.assertEqual(len({first.id, second.id, same_source.id}), 3)
        person_id = first.person_id
        near = Candidate(search_id="s", person_id=person_id, person_ids=[person_id], section="new", rank=1, score=0.1,
                         lane_ranks={"seeds": 1}, reason_claim_ids=[first.id, second.id, same_source.id])
        self.assertEqual(gold.reason_sources(self.store, near),
                         [("page", EVENT), ("seed_page", "https://example.org/other")])


class StubbedRunTest(unittest.TestCase):
    def test_a_search_that_finds_nobody_still_reports_every_pick(self):
        """An empty result list gives no top-five cards and a missed row per reachable pick."""
        settings = make_settings(self)
        worker = Worker(make_db(self, settings), settings, llm=StubLLM(GS10_CHIPS), http=StubHttp())
        self.addCleanup(worker.shutdown)
        result = gold.run_case(worker, gold.load_cases(["GS-10"])[0])
        self.assertEqual(result.top, [])
        self.assertEqual(sorted({p.verdict for p in result.picks}), ["missed", "no lane in slice"])

    def test_the_search_cost_is_split_into_vendor_and_llm_call_costs(self):
        """Only the stub parse call is paid in this search, $0.002, and it counts as LLM cost, not vendor spend."""
        settings = make_settings(self)
        worker = Worker(make_db(self, settings), settings, llm=StubLLM(GS10_CHIPS), http=StubHttp())
        self.addCleanup(worker.shutdown)
        result = gold.run_case(worker, gold.load_cases(["GS-10"])[0])
        self.assertAlmostEqual(result.llm_cost_usd, 0.002)
        self.assertEqual(result.http_cost_usd, 0.0)
