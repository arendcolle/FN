import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from fn.contracts import Chip, Chips, Identifier, LaneHit, LaneIn, LaneOut
from fn.steps import StepContext
from fn.worker import Worker
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

CHIPS = Chips(topics=[Chip(text="wind", origin="edited")])


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
                         ["parse", "lane:seeds", "publish", "lane:web", "resolve", "rank", "save"])

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

    def test_progress_of_an_unknown_search_is_none(self):
        """search_progress returns None for an id with no search."""
        self.assertIsNone(self.store.search_progress("no-such-search"))


if __name__ == "__main__":
    unittest.main()
