import json
import unittest
from datetime import timedelta

from fn import stats
from fn.contracts import Candidate, Event, Search, StepCall, StepRun
from fn.worker import now
from tests.helpers import make_db

START = now()
CREATED: dict[str, object] = {}


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.store = make_db(self)

    def search(self, search_id: str, minutes: int = 0, question: str = "Who knows wind?") -> None:
        CREATED[search_id] = START + timedelta(minutes=minutes)
        self.store.create_search(Search(
            id=search_id, question=question, status="done", created_at=START + timedelta(minutes=minutes),
            finished_at=START + timedelta(minutes=minutes, seconds=30), code_sha=None, dirty=False, llm_mode="replay",
            settings_json="{}", boot_id="b"))

    def step(self, search_id: str, seq: int, name: str, seconds: float, cost: float = 0.0, calls: int = 0,
             status: str = "ok", output: dict | None = None) -> None:
        run = StepRun(id=f"{search_id}-{seq}", search_id=search_id, seq=seq, step=name, status=status, started_at=CREATED[search_id],
                      ended_at=CREATED[search_id] + timedelta(seconds=seconds), input_model="In", cost_usd=cost)
        self.store.start_step(run, "{}")
        self.store.finish_step(run, json.dumps(output) if output is not None else None)
        for n in range(calls):
            self.store.add_call(StepCall(step_run_id=run.id, seq=n, kind="http", request="r", duration_ms=1))

    def candidate(self, search_id: str, person: str, rank: int, lanes: dict, cut: bool = False) -> None:
        self.store.conn.execute("INSERT INTO persons (id, display_name, name_key, list_status) VALUES (?, ?, ?, 'candidate')",
                                (person, person, person))
        self.store.save_candidates(search_id, [*self.store.list_candidates(search_id), Candidate(
            search_id=search_id, person_id=person, person_ids=[person], section="new", rank=rank, score=1.0,
            lane_ranks=lanes, cut_reason="no_belgian_evidence" if cut else None)], [])

    def event(self, event_id: str, kind: str, search_id: str, person: str, rank: int, undoes: str | None = None) -> None:
        self.store.add_event(Event(id=event_id, at=now(), kind=kind, person_id=person, search_id=search_id, rank=rank,
                                   undoes=undoes))

    def test_steps_give_median_and_slowest_over_runs(self):
        """Per step name: runs, errors, median and slowest seconds, and median cost and call count."""
        for n, (seconds, cost, calls, status) in enumerate([(1, 0.1, 1, "ok"), (3, 0.3, 3, "error"), (10, 0.2, 2, "ok")]):
            self.search(f"s{n}", n)
            self.step(f"s{n}", 1, "rank", seconds, cost, calls, status)
        (stat,) = stats.steps(self.store)
        self.assertEqual((stat.step, stat.runs, stat.errors), ("rank", 3, 1))
        self.assertEqual((stat.median_seconds, stat.slowest_seconds), (3.0, 10.0))
        self.assertEqual((stat.median_cost_usd, stat.median_calls), (0.2, 2))

    def test_steps_look_only_at_the_newest_searches(self):
        """An older search than the newest `last` adds no runs."""
        for n in range(3):
            self.search(f"s{n}", n)
            self.step(f"s{n}", 1, "rank", 1)
        self.assertEqual(stats.steps(self.store, last=2)[0].runs, 2)

    def test_time_to_first_person_is_empty_without_a_publish_with_people(self):
        """Seconds to the first person come from a publish or save step with a count above 0, else they are None."""
        self.search("none")
        self.step("none", 1, "save", 2, output={"count": 0})
        self.search("some", 1, "q" * 100)
        self.step("some", 1, "save", 7, output={"count": 0})
        self.step("some", 2, "publish", 4, output={"count": 3})
        found = {s.search_id: s for s in stats.searches(self.store)}
        self.assertIsNone(found["none"].first_person_seconds)
        self.assertEqual(found["some"].first_person_seconds, 4.0)
        self.assertEqual(len(found["some"].question), 80)
        self.assertEqual(found["some"].seconds, 30.0)

    def test_feedback_counts_adds_leaves_out_undone_ones_and_reads_lanes_from_the_candidate(self):
        """Kept and cut come from the candidates; an undone add counts nowhere; lanes are the candidate's lane ranks."""
        self.search("s")
        self.candidate("s", "anne", 3, {"seeds": 1, "openalex": 3})
        self.candidate("s", "bob", 120, {"web": 2})
        self.candidate("s", "cara", 4, {"seeds": 4})
        self.candidate("s", "dan", 5, {"seeds": 5}, cut=True)
        self.event("e1", "add", "s", "anne", 3)
        self.event("e2", "add", "s", "bob", 120)
        self.event("e3", "undo", "s", "bob", 120, undoes="e2")
        self.event("e4", "skip", "s", "cara", 4)
        self.search("quiet", 1)
        (found,) = stats.feedback(self.store)
        self.assertEqual((found.kept, found.cut, found.added, found.skipped), (3, 1, 1, 1))
        self.assertEqual(found.added_ranks, [3])
        self.assertEqual(found.added_by_lane, {"seeds": 1, "openalex": 1})
