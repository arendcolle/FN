import contextlib
import csv
import io
import unittest
from datetime import UTC, datetime
from unittest import mock

import httpx

from fn import gold, net, orgs
from fn.contracts import Candidate, ClaimDraft, GoldPick, Identifier, OrgFacts, Source
from fn.lanes import openalex
from fn.worker import Worker
from tests.helpers import StubHttp, StubLLM, make_db, make_settings
from tests.test_openalex import route

GS10_CHIPS = {"institutions": [{"text": "MIT", "span": {"start": 25, "end": 28}, "origin": "parsed"}]}


def candidate(person_ids: list[str], section: str = "new", rank: int = 1) -> Candidate:
    return Candidate(search_id="s", person_id=person_ids[0], person_ids=person_ids, section=section, rank=rank,
                     score=0.1, lane_ranks={"seeds": rank})


def pick(name: str, **fields) -> GoldPick:
    return GoldPick(case_id="GS-00", name=name, gold_tie=fields.pop("gold_tie", "belgian"), **fields)


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
        """reach.json decides the label of a pick that is not in the list; its evidence becomes the reason."""
        unreachable = gold.judge(pick("A B", reachable=False, reach_evidence="in none of the files"), None, self.NOWHERE)
        self.assertEqual((unreachable.verdict, unreachable.lost_step, unreachable.lost_reason),
                         ("no lane in slice", "lane:seeds", "in none of the files"))
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
                         ("missed", "lane:seeds, lane:openalex, lane:web, lane:linkedin"))
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
        """Search ids differ between runs, but every pick row (verdict, section, rank, Belgian claims, lost at) is the same."""
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


class StubbedRunTest(unittest.TestCase):
    def test_a_search_that_finds_nobody_still_reports_every_pick(self):
        """An empty result list gives no top-five cards and a missed row per reachable pick."""
        settings = make_settings(self)
        worker = Worker(make_db(self, settings), settings, llm=StubLLM(GS10_CHIPS), http=StubHttp())
        self.addCleanup(worker.shutdown)
        result = gold.run_case(worker, gold.load_cases(["GS-10"])[0])
        self.assertEqual(result.top, [])
        self.assertEqual(sorted({p.verdict for p in result.picks}), ["missed", "no lane in slice"])
