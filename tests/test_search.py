import contextlib
import io
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from fn.contracts import (
    Candidate,
    Chip,
    Chips,
    CitiesOut,
    ClaimDraft,
    DeepenIn,
    DeepenOut,
    FitAnswer,
    FitOut,
    FitRow,
    Identifier,
    LaneHit,
    LaneIn,
    LaneOut,
    PublishIn,
    PublishOut,
    RankIn,
    ResolveIn,
    Search,
    Source,
)
from fn import geo, network, present, rank, search
from fn.lanes import scout as scout_lane
from fn.net import HttpError
from fn.steps import StepContext, run_step
from fn.store import Store
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
        steps = [s.step for s in self.store.list_steps(search_id)]
        self.assertEqual((steps[:2], steps[-5:]), (["parse", "cities"], ["resolve", "rank", "save", "fit", "deepen"]))
        self.assertEqual(sorted(steps[2:-5]), ["deepen", "lane:seeds", "lane:web", "publish"])

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

    def test_first_heading_leaves_out_a_person_cut_as_died(self):
        """Of 20 saved kept tier-1 people in the new section, one cut as died, first_heading counts 19."""
        self.store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None, dirty=False,
                                        llm_mode="replay", settings_json="{}", boot_id="b"))
        people = [self.store.resolve_person([Identifier(scheme="seed", value=f"Person {n:02}")], f"Person {n:02}").id
                  for n in range(20)]
        rows = [Candidate(search_id="s1", person_id=p, person_ids=[p], hit_person_ids=[p], section="new", rank=n, score=1.0,
                          lane_ranks={"seeds": n}, tier=1, cut_reason="died" if n == 20 else None)
                for n, p in enumerate(people, 1)]
        self.store.save_candidates("s1", rows, [])
        self.assertEqual(search.first_heading(self.context("s1")), 19)

    def test_the_lane_input_carries_the_question_and_scout_runs_on_or_off(self):
        """LaneIn.question is the search's question; lane:scout runs once with the lane on and off, and off says why."""
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
                names = [s.step for s in steps]
                self.assertEqual(names[:2], ["parse", "cities"])
                self.assertEqual(sorted(names[2:7]), ["lane:linkedin", "lane:scout", "lane:web_topic", "publish", "publish"])
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
        names = [s for s, _ in steps]
        self.assertEqual((names[:2], names[-7:]),
                         (["parse", "cities"], ["resolve", "rank", "save", "fit", "rank", "save", "deepen"]))
        self.assertEqual(sorted(names[2:-7]), ["deepen", "lane:seeds", "lane:web", "link", "publish"])
        self.assertEqual(self.llm.calls, 3)
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
        self.assertEqual(steps[-5:], [("resolve", "ok"), ("rank", "ok"), ("save", "ok"), ("fit", "error"), ("deepen", "ok")])
        self.assertEqual(self.store.get_search(search_id).status, "done")
        self.assertEqual(len(self.store.list_candidates(search_id)), 1)
        search.refinish(self.context(search_id), self.store.get_search(search_id))
        self.assertEqual(self.rank_verdicts(search_id)[-1], {})

    def test_a_lookup_that_added_claims_ranks_and_saves_again_after_the_fit_step(self):
        """With claim ids from the deepen step the search links the new employers, ranks and saves again, after the fit
        step ran."""
        with mock.patch("fn.deepen.run", return_value=DeepenOut(claim_ids=["c1"])):
            search_id = self.fitted([self.finds("seeds", "Ann Smith")])
        names = [s.step for s in self.store.list_steps(search_id)]
        self.assertEqual(names[-10:], ["resolve", "rank", "save", "fit", "rank", "save", "deepen", "link", "rank", "save"])

    def test_a_deepen_step_that_raises_keeps_the_first_ranking_and_the_fit_step_runs(self):
        """The error stays on the deepen step row, no extra rank runs and the search ends done."""
        with mock.patch("fn.deepen.run", side_effect=ConnectionError("search is down")):
            search_id = self.fitted([self.finds("seeds", "Ann Smith")])
        steps = [(s.step, s.status) for s in self.store.list_steps(search_id)]
        self.assertEqual(steps[-7:], [("resolve", "ok"), ("rank", "ok"), ("save", "ok"), ("fit", "ok"),
                                      ("rank", "ok"), ("save", "ok"), ("deepen", "error")])
        self.assertEqual(self.store.get_search(search_id).status, "done")
        self.assertEqual(len(self.store.list_candidates(search_id)), 1)

    def test_refinish_runs_no_deepen_step(self):
        """A rerank makes no lookup."""
        search_id = self.fitted([self.finds("seeds", "Ann Smith")])
        with mock.patch("fn.deepen.run") as looked_up:
            search.refinish(self.context(search_id), self.store.get_search(search_id))
        looked_up.assert_not_called()
        self.assertEqual([s.step for s in self.store.list_steps(search_id)].count("deepen"), 1)

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

    def sleeps(self, lane: str, seconds: float, events: list | None = None, name: str | None = None):
        """A fake lane that notes its start and end in events, sleeps, and hits one stored person when name is given."""
        found = self.finds(lane, name) if name else None

        def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
            if events is not None:
                events.append(("start", lane))
            time.sleep(seconds)
            out = found.run(ctx, inp) if found else LaneOut(lane=lane, query="", total_seen=0)
            if events is not None:
                events.append(("end", lane))
            return out

        return SimpleNamespace(name=lane, run=run)

    def payloads(self, search_id: str, step: str, part: int) -> list[str]:
        return [self.store.get_payload(s.id)[part] for s in self.store.list_steps(search_id) if s.step == step]

    def test_the_lanes_after_seeds_take_about_the_slowest_lane_not_the_sum(self):
        """Lanes sleeping 0.5, 1.0 and 1.5 s after the seeds lane end in under 2.5 s, not the 3 s of their sum."""
        lanes = [self.sleeps("seeds", 0), self.sleeps("web", 0.5), self.sleeps("linkedin", 1.0), self.sleeps("scout", 1.5)]
        started = time.monotonic()
        search_id = self.execute(lanes)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(self.store.get_search(search_id).status, "done")

    def test_seeds_is_published_first_then_each_lane_as_it_ends_and_resolve_gets_lane_order(self):
        """Seeds runs and is published alone; a later lane that ends first is published next, the last one is not.

        Resolve gets the outputs in lane order whatever the order in which the lanes ended.
        """
        lanes = [self.sleeps("seeds", 0, name="Ann Smith"), self.sleeps("web", 0.6, name="Pat Lee"),
                 self.sleeps("linkedin", 0, name="Bo Lind")]
        search_id = self.execute(lanes)
        given = [PublishIn.model_validate_json(p).lanes for p in self.payloads(search_id, "publish", 0)]
        counts = [PublishOut.model_validate_json(p).count for p in self.payloads(search_id, "publish", 1)]
        self.assertEqual((given, counts), ([["seeds"], ["seeds", "linkedin"]], [1, 2]))
        (resolved,) = self.payloads(search_id, "resolve", 0)
        self.assertEqual([o.lane for o in ResolveIn.model_validate_json(resolved).outs], ["seeds", "web", "linkedin"])

    def test_web_topic_waits_for_the_lanes_before_it_and_no_other(self):
        """web_topic starts once seeds and web have ended and been published, while a later lane still runs.

        Placed first in LANES, it starts after seeds and while web still runs.
        """
        events, got = [], []

        def watch(ctx: StepContext, inp: LaneIn) -> LaneOut:
            events.append(("start", "web_topic"))
            got.append(inp.first_heading)
            return LaneOut(lane="web_topic", query="", total_seen=0)

        topic = SimpleNamespace(name="web_topic", run=watch)
        lanes = [self.sleeps("seeds", 0, events, "Ann Smith"), self.sleeps("web", 0.3, events, "Pat Lee"), topic,
                 self.sleeps("linkedin", 0.6, events)]
        with mock.patch("fn.rank.tier", return_value=2):
            self.execute(lanes)
        at = events.index(("start", "web_topic"))
        self.assertEqual(got, [2])
        self.assertLess(events.index(("end", "web")), at)
        self.assertLess(events.index(("start", "linkedin")), at)
        self.assertLess(at, events.index(("end", "linkedin")))
        events.clear()
        self.execute([topic, self.sleeps("seeds", 0.3, events), self.sleeps("web", 0.5, events)])
        at = events.index(("start", "web_topic"))
        self.assertLess(events.index(("end", "seeds")), at)
        self.assertLess(at, events.index(("end", "web")))

    def test_refinish_gives_resolve_the_stored_lane_outputs_in_lane_order(self):
        """Stored lane steps out of order, of a removed lane or twice of one lane reach resolve in LANES order.

        Outputs of one lane keep their stored order and a lane missing from LANES comes last.
        """
        search_id = self.worker.create_search("Who knows wind?", CHIPS, "edited").id
        ctx = self.context(search_id)
        for lane, query in (("web", "first"), ("linkedin", "gone"), ("seeds", "seeds"), ("web", "second")):
            run_step(ctx, f"lane:{lane}", lambda c, inp, lane=lane, query=query: LaneOut(lane=lane, query=query, total_seen=0),
                     LaneIn(search_id=search_id, chips=CHIPS))
        with mock.patch("fn.search.LANES", [SimpleNamespace(name="seeds"), SimpleNamespace(name="web")]):
            search.refinish(ctx, self.store.get_search(search_id))
        (resolved,) = self.payloads(search_id, "resolve", 0)
        self.assertEqual([(o.lane, o.query) for o in ResolveIn.model_validate_json(resolved).outs],
                         [("seeds", "seeds"), ("web", "first"), ("web", "second"), ("linkedin", "gone")])

    def test_the_city_index_is_built_in_its_own_step_before_the_lanes(self):
        """A cities step follows parse with the names it indexed, so no lane step fetches the dump.

        A fetch that fails gives 0 names and an ok step; a worker without an HTTP client writes no cities step.
        """
        def area(ctx: StepContext, inp: LaneIn) -> LaneOut:
            geo.cities(ctx.http)
            return LaneOut(lane="seeds", query="", total_seen=0)

        search_id = self.execute([SimpleNamespace(name="seeds", run=area)])
        steps = self.store.list_steps(search_id)
        self.assertEqual([(s.step, s.status) for s in steps][:2], [("parse", "skipped"), ("cities", "ok")])
        self.assertGreater(CitiesOut.model_validate_json(self.store.get_payload(steps[1].id)[1]).names, 0)
        (lane,) = [s for s in steps if s.step == "lane:seeds"]
        self.assertFalse([c for c in self.store.list_calls(lane.id) if geo.CITIES_URL in c.request])

        class Down(StubHttp):
            def get(self, url: str, params: dict[str, str] | None = None, **options):
                raise HttpError("GeoNames is down")

        for http, expected in ((Down(), [("cities", "ok")]), (None, [])):
            worker = Worker(self.store, self.settings, llm=StubLLM(), http=http)
            self.addCleanup(worker.shutdown)
            found = worker.create_search("Who knows wind?", CHIPS, "edited").id
            with mock.patch("fn.search.LANES", [self.finds("seeds", "Ann Smith")]):
                worker.execute(found)
            steps = [s for s in self.store.list_steps(found) if s.step == "cities"]
            self.assertEqual([(s.step, s.status) for s in steps], expected)
            if steps:
                self.assertEqual(CitiesOut.model_validate_json(self.store.get_payload(steps[0].id)[1]).names, 0)

    def test_each_lane_and_the_first_lookup_pass_close_their_thread_s_connection(self):
        """Store.close runs once on a lane thread for every lane and once for the first lookup pass."""
        closed = []
        close = Store.close

        def note(store: Store) -> None:
            closed.append(threading.current_thread().name)
            close(store)

        with mock.patch.object(Store, "close", note):
            self.execute([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee"), self.sleeps("linkedin", 0)])
        self.assertEqual(len([n for n in closed if n.startswith("fn-lane")]), 4)

    def passes(self, *runs):
        """A stand-in for deepen.run that calls runs[n] on its nth call (the last one after that) and keeps each input."""
        self.inputs = []

        def run(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            self.inputs.append(inp)
            return runs[min(len(self.inputs), len(runs)) - 1](ctx, inp)

        return mock.patch("fn.deepen.run", run)

    def first_slow(self, seconds: float):
        return self.passes(lambda ctx, inp: time.sleep(seconds) or DeepenOut(), lambda ctx, inp: DeepenOut())

    def test_the_first_lookup_pass_runs_beside_the_other_lanes(self):
        """The first deepen step starts after the seeds publish and before a slower lane ends, so the search takes about
        the longer of the two."""
        with self.first_slow(1.0):
            started = time.monotonic()
            search_id = self.execute([self.finds("seeds", "Ann Smith"), self.sleeps("web", 1.0)])
            elapsed = time.monotonic() - started
        steps = self.store.list_steps(search_id)
        first = next(s for s in steps if s.step == "deepen")
        self.assertLess(first.started_at, next(s for s in steps if s.step == "lane:web").ended_at)
        self.assertLess(elapsed, 1.8)

    def test_the_first_pass_s_claims_reach_the_rank_after_the_lanes_and_the_second_pass_skips_its_people(self):
        """Claims the first pass stores are absent at the seeds publish and present at the first rank after the lanes;
        the second pass gets the first one's picks and gaps."""
        found = self.finds("seeds", "Ann Smith")
        person_id = self.store.resolve_person([Identifier(scheme="seed", value="Ann Smith")], "Ann Smith").id
        stored, seen, run = [], [], rank.run

        def first(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            time.sleep(0.6)
            text = "Example University"
            stored.append(ctx.store.upsert_claim(ClaimDraft(
                person_id=person_id, kind="affiliation", relation="works_at", value=text, quote=text, quote_start=0,
                quote_end=len(text), source=Source(id="src-a", kind="record", url="https://example.org/a", text=text,
                                                   content_hash="h-a"))).id)
            return DeepenOut(picked=[person_id], gaps=1)

        def ranks(ctx: StepContext, inp: RankIn):
            seen.append({c.id for c in ctx.store.claims_of([person_id])})
            return run(ctx, inp)

        with self.passes(first, lambda ctx, inp: DeepenOut()), mock.patch("fn.rank.run", ranks):
            self.fitted([found, self.sleeps("web", 0.2)])
        self.assertEqual((stored[0] in seen[0], stored[0] in seen[1]), (False, True))
        self.assertEqual([(i.skip, i.used) for i in self.inputs], [([], 0), ([person_id], 1)])

    def test_a_seeds_lane_without_hits_gives_a_first_pass_with_nobody_and_a_second_with_no_lookups_used(self):
        """The first pass runs on an empty seeds publish and notes nobody; the second pass starts from zero used."""
        given = []
        real = search.deepen.run

        def run(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            given.append(inp)
            return real(ctx, inp)

        with mock.patch("fn.deepen.run", run):
            search_id = self.run_with(V2, [self.sleeps("seeds", 0), self.sleeps("web", 0.3)])
        first = next(s for s in self.store.list_steps(search_id) if s.step == "deepen")
        self.assertEqual(DeepenOut.model_validate_json(self.store.get_payload(first.id)[1]).note, "nobody to look up")
        self.assertEqual([i.used for i in given], [0, 0])

    def test_seeds_as_the_only_lane_gives_one_lookup_pass(self):
        """With no publish after the seeds lane no first pass starts; the one pass after the save uses no lookups."""
        with self.passes(lambda ctx, inp: DeepenOut()):
            search_id = self.execute([self.finds("seeds", "Ann Smith")])
        self.assertEqual([s.step for s in self.store.list_steps(search_id)].count("deepen"), 1)
        self.assertEqual([(i.skip, i.used) for i in self.inputs], [([], 0)])

    def test_a_first_pass_that_raises_keeps_its_error_row_and_the_search_ends_done(self):
        """The first pass's error stays on its deepen row; the second pass runs and the search ends done."""
        def fails(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            raise ConnectionError("search is down")

        with self.passes(fails, lambda ctx, inp: DeepenOut()):
            search_id = self.execute([self.finds("seeds", "Ann Smith"), self.sleeps("web", 0.3)])
        steps = [(s.step, s.status) for s in self.store.list_steps(search_id) if s.step == "deepen"]
        self.assertEqual(steps, [("deepen", "error"), ("deepen", "ok")])
        self.assertEqual(self.store.get_search(search_id).status, "done")

    def test_when_every_lane_fails_the_search_fails_after_the_first_pass_closed_its_connection(self):
        """A search whose lanes all raise ends failed only once the first pass has ended, and that pass's thread closed
        its connection."""
        events = []
        close = Store.close

        def note(store: Store) -> None:
            events.append(("close", threading.current_thread().name))
            close(store)

        def slow(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            time.sleep(0.3)
            events.append(("deepen", threading.current_thread().name))
            return DeepenOut()

        with self.passes(slow), mock.patch.object(Store, "close", note):
            search_id = self.execute([self.raises("seeds"), self.raises("web")])
        self.assertEqual(self.store.get_search(search_id).status, "failed")
        ended = [e for e in events if e[0] == "deepen"]
        self.assertEqual(len(ended), 1)
        self.assertIn(("close", ended[0][1]), events[events.index(ended[0]) + 1:])

    def second(self, run):
        """A stand-in for deepen.run: the first pass, beside the lanes, finds nothing, and the second calls run."""
        return self.passes(lambda ctx, inp: DeepenOut(), run)

    def test_the_second_pass_starts_after_the_search_is_done_and_the_fit_check_ended(self):
        """The second pass runs when the search is done and the fit step ended ok, and a pass that picks nobody adds no
        rank or save."""
        seen = []

        def look(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            seen.append((ctx.store.get_search(ctx.search_id).status, [(s.step, s.status) for s in ctx.store.list_steps(ctx.search_id)]))
            return DeepenOut()

        with self.second(look):
            search_id = self.fitted([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")])
        self.assertEqual(seen[0][0], "done")
        self.assertIn(("fit", "ok"), seen[0][1])
        steps = self.store.list_steps(search_id)
        self.assertEqual([s.step for s in steps][-4:], ["fit", "rank", "save", "deepen"])
        self.assertGreaterEqual(steps[-1].started_at, self.store.get_search(search_id).finished_at)

    def test_a_second_pass_that_adds_a_claim_reranks_and_keeps_every_fit_verdict(self):
        """A pass that stored a claim links, ranks and saves again with the verdicts of the fit step, so a person it
        said no to stays set aside, and the version goes up by one."""
        ann = self.store.resolve_person([Identifier(scheme="seed", value="Ann Smith")], "Ann Smith").id
        pat = self.store.resolve_person([Identifier(scheme="seed", value="Pat Lee")], "Pat Lee").id
        verdicts = {ann: "no", pat: "yes"}
        versions = []

        def look(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            versions.append(ctx.store.search_progress(ctx.search_id).version)
            return DeepenOut(claim_ids=["c1"])

        with self.second(look):
            search_id = self.fitted([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")],
                                    lambda ctx, inp: FitOut(verdicts=verdicts))
        names = [s.step for s in self.store.list_steps(search_id)]
        self.assertEqual(names[-7:], ["fit", "rank", "save", "deepen", "link", "rank", "save"])
        self.assertEqual(self.rank_verdicts(search_id)[-1], verdicts)
        self.assertEqual({c.person_id: c.aside for c in self.store.list_candidates(search_id)}[ann], "unfit")
        self.assertEqual(self.store.search_progress(search_id).version, versions[0] + 1)

    def test_a_pass_that_raises_after_done_keeps_the_list_and_the_search_done(self):
        """A raising lookup keeps its error row and a raising rank after a claim is logged; both leave the list saved
        and the search done."""
        def fails(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            raise ConnectionError("search is down")

        with self.second(fails):
            search_id = self.fitted([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")])
        self.assertEqual([(s.step, s.status) for s in self.store.list_steps(search_id)][-1], ("deepen", "error"))
        self.assertEqual((self.store.get_search(search_id).status, len(self.store.list_candidates(search_id))), ("done", 2))
        real, after = rank.run, []

        def broken(ctx: StepContext, inp: RankIn):
            if after:
                raise RuntimeError("rank is broken")
            return real(ctx, inp)

        with self.second(lambda ctx, inp: after.append(1) or DeepenOut(claim_ids=["c1"])), \
                mock.patch("fn.rank.run", broken), \
                self.assertLogs("fn.worker", "ERROR") as logs:
            search_id = self.fitted([self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")])
        self.assertIn("the lookups after done failed", logs.output[0])
        self.assertEqual((self.store.get_search(search_id).status, len(self.store.list_candidates(search_id))), ("done", 2))

    def test_a_search_queued_behind_waits_for_the_second_pass(self):
        """While the second pass of A runs, A is done and looking up and B waits queued; B's first step starts once the
        pass ended."""
        inside, release = threading.Event(), threading.Event()

        def hold(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            inside.set()
            self.assertTrue(release.wait(10))
            return DeepenOut()

        with self.second(hold), mock.patch("fn.search.LANES", [self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")]):
            first = self.worker.create_search("Who knows wind?", V2, "edited").id
            second = self.worker.create_search("Who knows wind?", V2, "edited").id
            futures = [self.worker.submit(first), self.worker.submit(second)]
            self.assertTrue(inside.wait(10))
            self.assertEqual((self.store.get_search(first).status, self.store.get_search(second).status), ("done", "queued"))
            self.assertTrue(present.looking(self.store, self.store.get_search(first)))
            release.set()
            for future in futures:
                future.result(timeout=10)
        deepen_ended = [s for s in self.store.list_steps(first) if s.step == "deepen"][-1].ended_at
        self.assertGreaterEqual(self.store.list_steps(second)[0].started_at, deepen_ended)

    def test_a_person_added_during_the_pass_is_in_the_network_section_after_it(self):
        """Pat added to the network while the second pass runs stands in the network section once the pass reranked."""
        pat = self.store.resolve_person([Identifier(scheme="seed", value="Pat Lee")], "Pat Lee").id
        inside, release = threading.Event(), threading.Event()

        def hold(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
            inside.set()
            self.assertTrue(release.wait(10))
            return DeepenOut(claim_ids=["c1"])

        with self.second(hold), mock.patch("fn.search.LANES", [self.finds("seeds", "Ann Smith"), self.finds("web", "Pat Lee")]):
            search_id = self.worker.create_search("Who knows wind?", V2, "edited").id
            future = self.worker.submit(search_id)
            self.assertTrue(inside.wait(10))
            self.assertEqual(self.store.get_search(search_id).status, "done")
            self.assertEqual({c.person_id: c.section for c in self.store.list_candidates(search_id)}[pat], "new")
            network.add(self.store, [pat], via="search", now=now())
            release.set()
            future.result(timeout=10)
        self.assertEqual({c.person_id: c.section for c in self.store.list_candidates(search_id)}[pat], "network")

    def test_progress_of_an_unknown_search_is_none(self):
        """search_progress returns None for an id with no search."""
        self.assertIsNone(self.store.search_progress("no-such-search"))


if __name__ == "__main__":
    unittest.main()
