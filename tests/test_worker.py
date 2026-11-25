import json
import sqlite3
import unittest
from unittest import mock

from fn.contracts import Chip, Chips, StepRun
from fn.store import Store
from fn.worker import Worker
from tests.helpers import SECRET, StubHttp, StubLLM, make_db, make_settings


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)

    def worker(self) -> Worker:
        worker = Worker(self.store, self.settings, llm=StubLLM(), http=StubHttp())
        self.addCleanup(worker.shutdown)
        return worker

    def test_sweep_interrupts_searches_from_earlier_boots(self):
        """Queued and running searches of an earlier boot, and their running steps, become interrupted."""
        old = self.worker()
        running, queued, finished = (old.create_search(q) for q in ("running", "queued", "finished"))
        self.store.set_search_status(running.id, "running")
        self.store.set_search_status(finished.id, "done", finished_at=running.created_at)
        self.store.start_step(StepRun(id="s1", search_id=running.id, seq=1, step="parse", status="running",
                                      started_at=running.created_at, input_model="ParseIn"), "{}")
        new = self.worker()
        current = new.create_search("this boot")
        self.assertCountEqual(new.sweep(), [running.id, queued.id])
        status = {s: self.store.get_search(s.id).status for s in (running, queued, finished, current)}
        self.assertEqual(list(status.values()), ["interrupted", "interrupted", "done", "queued"])
        (step,) = self.store.list_steps(running.id)
        self.assertEqual(step.status, "interrupted")
        self.assertIsNotNone(step.ended_at)

    def test_sweep_interrupts_a_running_step_of_a_done_search_from_an_earlier_boot(self):
        """A step left running under a done search of an earlier boot becomes interrupted with an end time; the search
        stays done and is not returned, and a done search of this boot is untouched."""
        old = self.worker()
        earlier = old.create_search("earlier")
        self.store.set_search_status(earlier.id, "done", finished_at=earlier.created_at)
        step = StepRun(id="s1", search_id=earlier.id, seq=1, step="deepen", status="running",
                       started_at=earlier.created_at, input_model="DeepenIn")
        self.store.start_step(step, "{}")
        new = self.worker()
        current = new.create_search("this boot")
        self.store.set_search_status(current.id, "done", finished_at=current.created_at)
        self.store.start_step(step.model_copy(update={"id": "s2", "search_id": current.id}), "{}")
        self.assertEqual(new.sweep(), [])
        self.assertEqual(self.store.get_search(earlier.id).status, "done")
        (stopped,) = self.store.list_steps(earlier.id)
        self.assertEqual(stopped.status, "interrupted")
        self.assertIsNotNone(stopped.ended_at)
        (mine,) = self.store.list_steps(current.id)
        self.assertEqual((mine.status, mine.ended_at), ("running", None))

    def test_exception_outside_a_step_fails_the_search(self):
        """An exception raised by the workflow itself, before any step, still marks the search failed."""
        worker = self.worker()
        search_id = worker.create_search("question").id
        with mock.patch("fn.search.run", side_effect=KeyError("workflow broke")), self.assertLogs("fn.worker", "ERROR"):
            search = worker.execute(search_id)
        self.assertEqual(search.status, "failed")
        self.assertIn("KeyError: 'workflow broke'", search.error)
        self.assertEqual(self.store.list_steps(search_id), [])

    def test_search_failure_is_logged_and_stored_redacted(self):
        """The failure log line and the search's error hold the traceback with every secret replaced."""
        worker = self.worker()
        search_id = worker.create_search("question").id
        with mock.patch("fn.search.run", side_effect=ValueError(f"bad {SECRET}")), \
                self.assertLogs("fn.worker", "ERROR") as logs:
            search = worker.execute(search_id)
        for text in [*logs.output, search.error]:
            self.assertNotIn(SECRET, text)
            self.assertIn("ValueError: bad ***", text)

    def test_unknown_search_is_refused(self):
        """execute() raises for an id with no search and writes nothing."""
        with self.assertRaises(LookupError):
            self.worker().execute("no-such-search")

    def test_search_with_chips_skips_parse_and_keeps_them(self):
        """A search created with chips records a skipped parse step holding them and never calls the LLM."""
        worker = Worker(self.store, self.settings, llm=StubLLM(error=AssertionError("parse must not run")), http=StubHttp())
        self.addCleanup(worker.shutdown)
        chips = Chips(topics=[Chip(text="wind", origin="edited")])
        search = worker.execute(worker.create_search("Who knows wind?", chips, "edited").id)
        step = self.store.list_steps(search.id)[0]
        self.assertEqual((search.status, search.chips, search.chips_origin), ("done", chips, "edited"))
        self.assertEqual((step.step, step.status, step.output_model), ("parse", "skipped", "ParseOut"))
        self.assertEqual(json.loads(self.store.get_payload(step.id)[1])["chips"]["topics"][0]["text"], "wind")

    def test_exception_escaping_execute_is_logged_redacted(self):
        """A database error outside execute's guard is logged from the submit() callback with the secret replaced."""
        worker = self.worker()
        search_id = worker.create_search("question").id
        error = sqlite3.OperationalError(f"disk full {SECRET}")
        with mock.patch.object(Store, "set_search_status", side_effect=error), \
                self.assertLogs("fn.worker", "ERROR") as logs:
            self.assertRaises(sqlite3.OperationalError, worker.submit(search_id).result, 10)
            worker.pool.submit(int).result(timeout=10)
        text = "\n".join(logs.output)
        self.assertIn("OperationalError: disk full ***", text)
        self.assertIn(search_id, text)
        self.assertNotIn(SECRET, text)

    def test_submit_runs_the_search_on_the_worker_thread(self):
        """submit() runs the search on the one worker thread, with its own connection, to done."""
        worker = self.worker()
        search_id = worker.create_search("question").id
        self.assertEqual(worker.submit(search_id).result(timeout=10).status, "done")
        self.assertEqual(self.store.get_search(search_id).status, "done")

    def test_submit_runs_a_given_workflow_instead_of_the_search_steps(self):
        """submit() with a workflow runs that workflow on the search and ends it done."""
        worker = self.worker()
        seen = []
        job_id = worker.create_search("fn-job", kind="job").id
        self.assertEqual(worker.submit(job_id, lambda ctx, found: seen.append(found.question)).result(timeout=10).status, "done")
        self.assertEqual((seen, self.store.list_steps(job_id)), (["fn-job"], []))

    def test_search_records_code_state_and_redacted_settings(self):
        """A search stores its boot, llm mode and settings, with the secret replaced."""
        worker = self.worker()
        search = self.store.get_search(worker.create_search("question").id)
        self.assertEqual((search.boot_id, search.llm_mode), (worker.boot_id, "replay"))
        self.assertNotIn(self.settings.openalex_api_key.get_secret_value(), search.settings_json)


if __name__ == "__main__":
    unittest.main()
