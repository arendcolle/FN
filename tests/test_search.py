import contextlib
import io
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from fn.contracts import Chip, Chips, FitAnswer, FitRow, Identifier, LaneHit, LaneIn, LaneOut, RankIn
from fn import search
from fn.lanes import scout as scout_lane
from fn.steps import StepContext
from fn.worker import Worker, new_id, now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

CHIPS = Chips(topics=[Chip(text="wind", origin="edited")])
V2 = Chips(topics=[Chip(text="wind", origin="edited")], version=2)


class FitLLM:
    """Says "partly" for every numbered line of a fit call and counts the calls."""

    def __init__(self):
        self.calls = 0

    def structured(self, task, data, schema):
        self.calls += 1
        rows = [FitRow(n=n, fit="partly") for n in range(1, len(data["people"].splitlines()) + 1)]
        return type("Result", (), {"value": FitAnswer(people=rows)})()


class SearchStepsTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.worker = Worker(self.store, self.settings, llm=StubLLM(), http=StubHttp())
        self.addCleanup(self.worker.shutdown)

    def finds(self, lane: str, name: str):
        """A fake lane that hits one stored person named name."""
        person = self.store.resolve_person([Identifier(scheme="seed", value=name)], name)

        def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
            hit = LaneHit(person_id=person.id, name_key=person.name_key, lane=lane, rank=1, score=1.0, matched_on="wind")
            return LaneOut(lane=lane, query="wind", total_seen=1, hits=[hit])

        return SimpleNamespace(name=lane, run=run)

    def raises(self, lane: str):
        def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
            raise ConnectionError(f"{lane} is down")

        return SimpleNamespace(name=lane, run=run)

    def execute(self, lanes) -> str:
        search_id = self.worker.create_search("Who knows wind?", CHIPS, "edited").id
        with mock.patch("fn.search.LANES", lanes):
            self.worker.execute(search_id)
        return search_id

    def test_the_first_lane_s_people_are_saved_before_the_next_lane_returns(self):
        """After the first lane a publish step saves its people and version is 1 while the next lane still runs.

        When the search ends done, the final save raises version again.
        """
        release = threading.Event()
        blocked = self.finds("web", "Pat Lee")

        def wait(ctx: StepContext, inp: LaneIn) -> LaneOut:
            self.assertTrue(release.wait(10))
            return blocked.run(ctx, inp)

        search_id = self.worker.create_search("Who knows wind?", CHIPS, "edited").id
        with mock.patch("fn.search.LANES", [self.finds("seeds", "Ann Smith"), SimpleNamespace(name="web", run=wait)]):
            future = self.worker.submit(search_id)
            deadline = time.monotonic() + 10
            while (progress := self.store.search_progress(search_id)).version < 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(progress.model_dump(), {"status": "running", "people": 1, "version": 1})
            self.assertEqual(len(self.store.list_candidates(search_id)), 1)
            release.set()
            self.assertEqual(future.result(timeout=10).status, "done")
        self.assertEqual(self.store.search_progress(search_id).model_dump(),
                         {"status": "done", "people": 2, "version": 2})
        self.assertEqual([s.step for s in self.store.list_steps(search_id)],
                         ["parse", "lane:seeds", "publish", "lane:web", "resolve", "rank", "save", "fit"])

    def run_with(self, given: Chips, lanes) -> str:
        search_id = self.worker.create_search("Who knows wind?", given, "edited").id
        with mock.patch("fn.search.LANES", lanes):
            self.worker.execute(search_id)
        return search_id

    def test_openalex_is_skipped_when_no_research_is_asked_and_runs_for_version_1_chips(self):
        """Version 2 chips with only a business role give a skipped lane:openalex step and no call; version 1 runs it."""
        calls = []
        seen = self.finds("openalex", "Bo Lind")
        counted = SimpleNamespace(name="openalex", run=lambda ctx, inp: calls.append(1) or seen.run(ctx, inp))
        founders = Chip(text="founders", origin="edited", research=False)
        for given, status, called in ((Chips(roles=[founders], version=2), "skipped", 0),
                                      (Chips(roles=[founders]), "ok", 1)):
            with self.subTest(version=given.version):
                calls.clear()
                search_id = self.run_with(given, [self.finds("seeds", "Ann Smith"), counted])
                steps = {s.step: s for s in self.store.list_steps(search_id)}
                self.assertEqual((steps["lane:openalex"].status, len(calls)), (status, called))
                self.assertEqual(self.store.get_search(search_id).status, "done")
                self.assertEqual(self.store.failed_lanes(search_id), [])

    def test_web_topic_gets_the_tier_1_and_2_people_the_publish_before_it_saved(self):
        """first_heading counts the kept new-section people in tier 1 or 2 that the earlier lanes' publish saved."""
        got = {}

        def watch(ctx: StepContext, inp: LaneIn) -> LaneOut:
            got[ctx.store.list_steps(ctx.search_id)[-1].step] = inp.first_heading
            return LaneOut(lane="web_topic", query="", total_seen=0)

        lanes = [self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee"), SimpleNamespace(name="web_topic", run=watch)]
        with mock.patch("fn.rank.tier", return_value=2):
            self.run_with(CHIPS, lanes)
        self.assertEqual(got, {"lane:web_topic": 2})

    def test_the_lane_input_carries_the_question_and_scout_runs_after_web_topic_on_or_off(self):
        """LaneIn.question is the search's question; lane:scout follows lane:web_topic with the lane on and off, and off says why."""
        for scout in (True, False):
            with self.subTest(scout=scout):
                settings = self.settings.model_copy(update={"scout": scout})
                worker = Worker(self.store, settings, llm=StubLLM(), http=StubHttp())
                self.addCleanup(worker.shutdown)
                search_id = worker.create_search("Who knows wind?", CHIPS, "edited").id
                seen = []

                def watch(ctx: StepContext, inp: LaneIn) -> LaneOut:
                    seen.append(inp.question)
                    return LaneOut(lane="web_topic", query="", total_seen=0)

                with mock.patch("fn.search.LANES", [SimpleNamespace(name="web_topic", run=watch), scout_lane,
                                                    self.finds("linkedin", "Ann Smith")]):
                    worker.execute(search_id)
                steps = self.store.list_steps(search_id)
                self.assertEqual(seen, ["Who knows wind?"])
                self.assertEqual([s.step for s in steps][:5], ["parse", "lane:web_topic", "publish", "lane:scout", "publish"])
                (scouted,) = [s for s in steps if s.step == "lane:scout"]
                self.assertEqual(scouted.status, "ok")
                if not scout:
                    out = LaneOut.model_validate_json(self.store.get_payload(scouted.id)[1])
                    self.assertEqual([c.reason for c in out.considered], ["web research is off"])
        self.assertEqual([lane.name for lane in search.LANES][-3:], ["web_topic", "scout", "linkedin"])

    def test_a_lane_that_raises_is_kept_as_an_error_and_the_search_ends_done(self):
        """The failing lane's step holds the error, failed_lanes names it and the other lanes' people are saved."""
        search_id = self.execute([self.finds("seeds", "Ann Smith"), self.raises("openalex"), self.finds("web", "Pat Lee")])
        self.assertEqual(self.store.get_search(search_id).status, "done")
        steps = {s.step: s for s in self.store.list_steps(search_id)}
        self.assertEqual((steps["lane:openalex"].status, steps["lane:openalex"].error_type), ("error", "ConnectionError"))
        self.assertIn("openalex is down", steps["lane:openalex"].traceback)
        self.assertEqual(self.store.failed_lanes(search_id), ["lane:openalex"])
        self.assertEqual(self.store.search_progress(search_id).people, 2)

    def test_a_search_in_which_every_lane_raises_fails(self):
        """With no lane left standing the search ends failed, and failed_lanes names every lane."""
        with self.assertLogs("fn.worker", "ERROR"):
            search_id = self.execute([self.raises("seeds"), self.raises("openalex")])
        self.assertEqual(self.store.get_search(search_id).status, "failed")
        self.assertEqual(self.store.failed_lanes(search_id), ["lane:seeds", "lane:openalex"])

    def test_a_parse_error_still_fails_the_search(self):
        """A search without chips whose parse step raises ends failed, with no lane run and nothing published."""
        worker = Worker(self.store, self.settings, llm=StubLLM(error=RuntimeError("logged out")), http=StubHttp())
        self.addCleanup(worker.shutdown)
        search_id = worker.create_search("Who knows wind?").id
        with mock.patch("fn.search.LANES", [self.finds("seeds", "Ann Smith")]), self.assertLogs("fn.worker", "ERROR"):
            worker.execute(search_id)
        self.assertEqual([(s.step, s.status) for s in self.store.list_steps(search_id)], [("parse", "error")])
        self.assertEqual(self.store.search_progress(search_id).model_dump(), {"status": "failed", "people": 0, "version": 0})

    def context(self, search_id: str) -> StepContext:
        return StepContext(search_id=search_id, store=self.store, llm=None, http=None, now=now,
                           new_id=new_id, log=mock.Mock(), settings=self.settings)

    def fitted(self, lanes, fit_run=None) -> str:
        """Run a version-2 search over lanes with tier 2 for everybody and a model that says partly."""
        llm = FitLLM()
        worker = Worker(self.store, self.settings, llm=llm, http=StubHttp())
        self.addCleanup(worker.shutdown)
        search_id = worker.create_search("Who knows wind?", V2, "edited").id
        with mock.patch("fn.search.LANES", lanes), mock.patch("fn.rank.tier", return_value=2):
            if fit_run:
                with mock.patch("fn.fitcheck.run", fit_run):
                    worker.execute(search_id)
            else:
                worker.execute(search_id)
        self.llm = llm
        return search_id

    def rank_verdicts(self, search_id: str) -> list[dict]:
        return [RankIn.model_validate_json(self.store.get_payload(s.id)[0]).verdicts
                for s in self.store.list_steps(search_id) if s.step == "rank"]

    def test_the_fit_step_runs_once_after_the_first_save_and_the_search_ranks_again_with_its_verdicts(self):
        """Publishes between lanes run no fit step; after the first save fit runs, then rank and save run again."""
        search_id = self.fitted([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")])
        steps = [(s.step, s.status) for s in self.store.list_steps(search_id)]
        self.assertEqual([s for s, _ in steps], ["parse", "lane:seeds", "publish", "lane:web", "resolve", "rank", "save",
                                                 "fit", "rank", "save"])
        self.assertEqual(self.llm.calls, 1)
        ids = {c.person_id for c in self.store.list_candidates(search_id)}
        self.assertEqual(self.rank_verdicts(search_id), [{}, {i: "partly" for i in ids}])
        self.assertEqual(self.store.get_search(search_id).status, "done")

    def test_refinish_ranks_with_the_stored_verdicts_and_makes_no_model_call(self):
        """A rerank reads the verdicts of the last fit step that ended ok and runs no fit step of its own."""
        search_id = self.fitted([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")])
        ids = {c.person_id for c in self.store.list_candidates(search_id)}
        llm = mock.Mock()
        ctx = self.context(search_id)
        ctx = StepContext(**{**ctx.__dict__, "llm": llm})
        search.refinish(ctx, self.store.get_search(search_id))
        llm.structured.assert_not_called()
        self.assertEqual(self.rank_verdicts(search_id)[-1], {i: "partly" for i in ids})
        self.assertEqual([s.step for s in self.store.list_steps(search_id)].count("fit"), 1)

    def test_a_fit_step_that_raises_leaves_the_search_done_with_the_first_ranking(self):
        """The error stays on the fit step row; no second rank runs and the first candidates stay saved."""
        search_id = self.fitted([self.finds("seeds", "Ann Smith")], mock.Mock(side_effect=ConnectionError("model is down")))
        steps = [(s.step, s.status) for s in self.store.list_steps(search_id)]
        self.assertEqual(steps[-4:], [("resolve", "ok"), ("rank", "ok"), ("save", "ok"), ("fit", "error")])
        self.assertEqual(self.store.get_search(search_id).status, "done")
        self.assertEqual(len(self.store.list_candidates(search_id)), 1)
        search.refinish(self.context(search_id), self.store.get_search(search_id))
        self.assertEqual(self.rank_verdicts(search_id)[-1], {})

    def test_refinish_gives_back_the_stored_candidates_and_a_search_without_lane_outputs_raises(self):
        """Running the steps after the lanes on the stored outputs saves the same candidates; no lane output raises ValueError."""
        search_id = self.execute([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")])
        stored = self.store.get_search(search_id)
        before = self.store.list_candidates(search_id)
        search.refinish(self.context(search_id), stored)
        self.assertEqual(self.store.list_candidates(search_id), before)
        self.assertEqual(len(before), 2)
        empty = self.worker.create_search("Who knows solar?", CHIPS, "edited")
        with self.assertRaisesRegex(ValueError, empty.id):
            search.refinish(self.context(empty.id), empty)

    def test_fn_rerank_changes_the_named_search_and_leaves_another_alone(self):
        """fn-rerank ID saves new candidates for that search only and prints its kept count before and after."""
        first = self.execute([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")])
        other = self.execute([self.finds("seeds", "Bo Lind")])
        for search_id in (first, other):
            self.store.save_candidates(search_id, [], [])
        printed = io.StringIO()
        with (mock.patch("fn.config.from_env", return_value=self.settings), mock.patch("fn.net.Client", return_value=StubHttp()),
              contextlib.redirect_stdout(printed)):
            self.assertEqual(search.rerank_main([first]), 0)
            self.assertEqual(search.rerank_main(["no-such-search"]), 1)
        self.assertEqual(len(self.store.list_candidates(first)), 2)
        self.assertEqual(self.store.list_candidates(other), [])
        self.assertEqual(printed.getvalue().splitlines(), [f"{first}: kept 0 -> 2", "no-such-search: no such search"])

    def test_progress_of_an_unknown_search_is_none(self):
        """search_progress returns None for an id with no search."""
        self.assertIsNone(self.store.search_progress("no-such-search"))


if __name__ == "__main__":
    unittest.main()
