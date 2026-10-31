import contextlib
import io
import json
import logging
import unittest

from fn.contracts import ParseIn, ParseOut
from fn.steps import StepContext, current_recorder, redact, run_step, setup_logging
from fn.worker import Worker
from tests.helpers import SECRET, StubHttp, StubLLM, make_db, make_settings


class StepTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)

    def worker(self, llm: StubLLM) -> Worker:
        worker = Worker(self.store, self.settings, llm=llm, http=StubHttp())
        self.addCleanup(worker.shutdown)
        return worker

    def context(self) -> StepContext:
        worker = self.worker(StubLLM())
        search = worker.create_search("question")
        return StepContext(
            search_id=search.id, store=self.store, llm=worker.llm, http=None, now=lambda: search.created_at,
            new_id=lambda: f"step-{self.store.next_step_seq(search.id)}", log=logging.getLogger("fn.step"),
            settings=self.settings,
        )

    def test_failing_step_stores_error_and_fails_search(self):
        """A step that raises gets status error with its traceback, and its search ends failed."""
        worker = self.worker(StubLLM(error=ValueError("model said no")))
        with self.assertLogs("fn.worker", "ERROR"):
            search = worker.execute(worker.create_search("Who knows wind?").id)
        (step,) = self.store.list_steps(search.id)
        self.assertEqual((step.step, step.status, step.error_type), ("parse", "error", "ValueError"))
        self.assertEqual(step.error_message, "model said no")
        self.assertIn("Traceback (most recent call last)", step.traceback)
        self.assertIn("raise self.error", step.traceback)
        self.assertEqual(search.status, "failed")
        self.assertIn("ValueError: model said no", search.error)
        self.assertIsNotNone(search.finished_at)

    def test_step_row_is_running_while_step_runs(self):
        """The step row exists with status running before the step function returns."""
        ctx = self.context()
        seen = []

        def step(c: StepContext, inp: ParseIn) -> ParseOut:
            seen.extend((s.step, s.status, s.ended_at) for s in c.store.list_steps(c.search_id))
            return ParseOut(chips={})

        run_step(ctx, "parse", step, ParseIn(question="q"))
        self.assertEqual(seen, [("parse", "running", None)])
        self.assertEqual(self.store.list_steps(ctx.search_id)[0].status, "ok")

    def test_ok_step_stores_output_and_call_totals(self):
        """An ok step stores its output payload, its calls, and their summed cost, tokens and model."""
        worker = self.worker(StubLLM(answer={"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "parsed"}]}))
        search = worker.execute(worker.create_search("Who knows wind?").id)
        step = self.store.list_steps(search.id)[0]
        self.assertEqual((search.status, step.status, step.output_model), ("done", "ok", "ParseOut"))
        self.assertEqual((step.cost_usd, step.tokens_in, step.tokens_out), (0.002, 10, 4))
        self.assertEqual((step.model, step.prompt_sha), ("stub", "sha-stub"))
        self.assertEqual(search.chips.topics[0].text, "wind")
        _, output_json = self.store.get_payload(step.id)
        self.assertEqual(json.loads(output_json)["chips"]["topics"][0]["text"], "wind")
        self.assertEqual([c.kind for c in self.store.list_calls(step.id)], ["llm"])

    def test_secret_is_redacted_everywhere(self):
        """The secret value never reaches the payloads, call, error message, traceback or log line."""
        ctx = self.context()

        def leaky(c: StepContext, inp: ParseIn) -> ParseOut:
            c.log.info("calling with %s", inp.question)
            current_recorder().record("http", f"GET https://api.example.org?key={SECRET}", 3, error=SECRET)
            raise RuntimeError(f"bad key {SECRET}")

        with self.assertRaises(RuntimeError):
            run_step(ctx, "parse", leaky, ParseIn(question=f"key {SECRET}"))
        (step,) = self.store.list_steps(ctx.search_id)
        (call,) = self.store.list_calls(step.id)
        input_json, _ = self.store.get_payload(step.id)
        stored = [input_json, step.error_message, step.traceback, step.log, call.request, call.error]
        for text in stored:
            self.assertNotIn(SECRET, text)
            self.assertIn("***", text)
        self.assertIn("calling with key ***", step.log)
        run_step(ctx, "parse", lambda c, inp: ParseOut(chips={"topics": [{"text": inp.question, "origin": "parsed"}]}),
                 ParseIn(question=f"key {SECRET}"))
        _, output_json = self.store.get_payload(self.store.list_steps(ctx.search_id)[1].id)
        self.assertNotIn(SECRET, output_json)
        self.assertIn("key ***", output_json)

    def test_log_file_is_redacted_and_tagged_with_search_and_step(self):
        """The log file holds no secret, not even in a traceback, and tags a line with its search id and step."""
        root = logging.getLogger()
        saved, level = root.handlers[:], root.level
        with contextlib.redirect_stderr(io.StringIO()):
            setup_logging(self.settings)

        def restore():
            for handler in root.handlers[:]:
                root.removeHandler(handler)
                handler.close()
            root.handlers[:], root.level = saved, level

        self.addCleanup(restore)
        ctx = self.context()

        def noisy(c: StepContext, inp: ParseIn) -> ParseOut:
            c.log.info("calling with %s", SECRET)
            try:
                raise KeyError(SECRET)
            except KeyError:
                c.log.exception("failed for %s", SECRET)
            return ParseOut(chips={})

        run_step(ctx, "parse", noisy, ParseIn(question="q"))
        logging.getLogger("fn.test").warning("outside a step %s", SECRET)
        for handler in root.handlers:
            handler.flush()
        text = (self.settings.var_dir / "log" / "fn.log").read_text()
        self.assertNotIn(SECRET, text)
        self.assertIn(f"fn.step [{ctx.search_id} parse] calling with ***", text)
        self.assertIn("KeyError: '***'", text)
        self.assertIn("fn.test [- -] outside a step ***", text)

    def test_redact_replaces_each_secret(self):
        self.assertEqual(redact("a s1 b s2 s1", ["s1", "s2"]), "a *** b *** ***")


if __name__ == "__main__":
    unittest.main()
