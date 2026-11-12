import logging
import re
import threading
import time
import unittest
from unittest import mock

import httpx
from pydantic import BaseModel, SecretStr

from fn import llm, net
from fn.contracts import LaneIn, LaneOut, LLMResult
from fn.lanes import web
from fn.steps import StepContext, current_recorder, run_step
from fn.worker import Worker, new_id, now
from tests.helpers import make_db, make_settings
from tests.test_extract import mention
from tests.test_web_lane import KEY, NEW_YORK

FIRSTS = ["Anke", "Bram", "Cato", "Daan", "Elke", "Floor", "Gijs", "Hanne", "Ivo", "Jolien"]
FILLER = "\n".join(["x" * 79] * 50)
log = logging.getLogger("fn.test.fan_out")


def name(page: int) -> str:
    return f"{FIRSTS[page - 1]} Proefmans"


def content(page: int) -> str:
    """Two paragraphs of about 4,000 characters, so the page is read in two chunks; part 1 names one person."""
    return (f"Page {page:02d} part 1. {name(page)} works at KU Leuven.\n{FILLER}\n\n"
            f"Page {page:02d} part 2. Nobody here.\n{FILLER}")


class SlowLLM:
    """Sleeps less for later chunks, so they finish first; logs a line, records its call with tokens, then answers.

    The chunk of `fail` raises `error` after its call is recorded.
    """

    def __init__(self, scale: float = 1.0, fail: tuple[int, int] | None = None, error: Exception | None = None):
        self.scale, self.fail, self.error = scale, fail, error
        self.sleeps: list[float] = []

    def structured[T: BaseModel](self, task: str, data: dict[str, str], schema: type[T]) -> LLMResult[T]:
        page, part = map(int, re.search(r"Page (\d+) part (\d+)", data["page"]).groups())
        k = 2 * (page - 1) + part - 1
        self.sleeps.append(self.scale * (0.1 + 0.005 * (19 - k)))
        time.sleep(self.sleeps[-1])
        log.info("read page %d part %d", page, part)
        tokens_in, tokens_out, cost = 100 + k, 10 + k, 0.001 * (k + 1)
        current_recorder().record("llm", f"{task}: page {page} part {part}", 1, status=0, tokens_in=tokens_in,
                                  tokens_out=tokens_out, cost_usd=cost, model="stub", prompt_sha="sha-stub")
        if (page, part) == self.fail:
            raise self.error
        people = [mention(name(page), f"{name(page)} works at KU Leuven.", "researcher")] if part == 1 else []
        return LLMResult[schema](value=schema.model_validate({"people": people}), model="stub", cost_usd=cost,
                                 tokens_in=tokens_in, tokens_out=tokens_out, billing="stub")


class FanOutTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={
            "http_mode": "live", "parallel_api_key": SecretStr(KEY), "llm_workers": 8})
        self.store = make_db(self, self.settings)
        urls = [f"https://events.example.org/talk-{p}" for p in range(1, 11)]
        self.search = {"results": [{"url": u, "title": f"Talk {p}"} for p, u in enumerate(urls, 1)]}
        self.extract = {"results": [{"url": u, "title": f"Talk {p}", "full_content": content(p)}
                                    for p, u in enumerate(urls, 1)]}

    def handle(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"/v1/search": self.search, "/v1/extract": self.extract}[request.url.path])

    def run_lane(self, model: SlowLLM, workers: int = 8) -> LaneOut:
        """Run lane:web with the model as a step of a new search; keeps the step row as self.step."""
        settings = self.settings.model_copy(update={"llm_workers": workers})
        http = net.Client(settings, httpx.MockTransport(self.handle))
        worker = Worker(self.store, settings, llm=model, http=http)
        self.addCleanup(worker.shutdown)
        search_id = worker.create_search("question", NEW_YORK, "edited").id
        ctx = StepContext(search_id=search_id, store=self.store, llm=model, http=http, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        try:
            return run_step(ctx, "lane:web", web.run, LaneIn(search_id=search_id, chips=NEW_YORK))
        finally:
            self.step = self.store.list_steps(search_id)[-1]

    def calls(self) -> list[tuple[int, str]]:
        return [(c.seq, c.request) for c in self.store.list_calls(self.step.id)]

    def names(self, out: LaneOut) -> list[str]:
        persons = self.store.get_persons([h.person_id for h in out.hits])
        return [persons[h.person_id].display_name for h in out.hits]

    def test_twenty_chunks_on_eight_workers_take_under_a_quarter_of_the_serial_time_and_log_in_page_then_chunk_order(self):
        """Chunks are read at the same time, yet the calls are logged in page rank, then chunk order, on every run.

        seq runs 1..N with no gap whatever order the calls finish in.
        """
        expected = [f"extract: page {p} part {c}" for p in range(1, 11) for c in (1, 2)]
        for run in (1, 2):
            with self.subTest(run=run):
                model = SlowLLM()
                started = time.monotonic()
                out = self.run_lane(model)
                self.assertLess(time.monotonic() - started, sum(model.sleeps) / 4)
                calls = self.calls()
                self.assertEqual([seq for seq, _ in calls], list(range(1, 23)))
                self.assertEqual([r for _, r in calls if r.startswith("extract")], expected)
                self.assertEqual(self.names(out), [name(p) for p in range(1, 11)])

    def test_one_worker_gives_the_same_people_and_call_order(self):
        """With one worker the calls run one after another on the pool, with the same results."""
        many = self.run_lane(SlowLLM(scale=0))
        many_calls = [r for _, r in self.calls()]
        one = self.run_lane(SlowLLM(scale=0), workers=1)
        self.assertEqual(self.names(one), self.names(many))
        self.assertEqual([r for _, r in self.calls()], many_calls)

    def test_every_store_write_comes_from_the_step_thread(self):
        """Calls and claims are written by the thread that runs the step, never by a pool thread."""
        threads: dict[str, set[int]] = {"add_call": set(), "upsert_claim": set()}
        for method, seen in threads.items():
            real = getattr(self.store, method)

            def spy(*args, real=real, seen=seen, **kwargs):
                seen.add(threading.get_ident())
                return real(*args, **kwargs)

            patcher = mock.patch.object(self.store, method, spy)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.run_lane(SlowLLM(scale=0.1))
        self.assertEqual(threads, {"add_call": {threading.get_ident()}, "upsert_claim": {threading.get_ident()}})

    def test_a_chunk_that_times_out_gives_one_chunk_row_and_the_other_chunks_people(self):
        """An LLMCallError on one chunk is one chunk row and a warning; every other page's person is a hit.

        The step ends ok and the failed call is still logged.
        """
        timeout = llm.LLMCallError("claude timed out after 120s", None, "", 120000)
        out = self.run_lane(SlowLLM(scale=0.1, fail=(4, 1), error=timeout))
        self.assertEqual(self.names(out), [name(p) for p in range(1, 11) if p != 4])
        (row,) = [c for c in out.considered if c.stage == "chunk"]
        self.assertEqual((row.person_key, row.kept), ("https://events.example.org/talk-4", False))
        self.assertRegex(row.reason, r"^chunk 1 of 2 \[[0-9]+:[0-9]+\]: LLMCallError: claude timed out")
        self.assertRegex(self.step.log, r"WARNING .*extract on https://events.example.org/talk-4, chunk 1 of 2")
        self.assertEqual((self.step.status, len(self.calls())), ("ok", 22))

    def test_an_unexpected_exception_fails_the_step_and_every_call_is_still_logged(self):
        """An exception the extract does not expect fails the lane step, after the calls of all chunks are logged."""
        with self.assertRaises(KeyError):
            self.run_lane(SlowLLM(scale=0.1, fail=(4, 1), error=KeyError("boom")))
        self.assertEqual((self.step.status, self.step.error_type), ("error", "KeyError"))
        self.assertEqual([seq for seq, _ in self.calls()], list(range(1, 23)))

    def test_the_step_totals_are_the_sums_over_all_calls(self):
        """The step's tokens_in, tokens_out and cost_usd add up every chunk's call, from whichever thread it ran on."""
        self.run_lane(SlowLLM(scale=0.1))
        self.assertEqual((self.step.tokens_in, self.step.tokens_out),
                         (sum(100 + k for k in range(20)), sum(10 + k for k in range(20))))
        self.assertAlmostEqual(self.step.cost_usd, sum(0.001 * (k + 1) for k in range(20)))

    def test_a_log_line_written_inside_a_task_is_in_the_step_log(self):
        """Lines a pool thread logs while it reads a chunk are kept in the step's log."""
        self.run_lane(SlowLLM(scale=0.1))
        for p in range(1, 11):
            for c in (1, 2):
                self.assertIn(f"read page {p} part {c}", self.step.log)


if __name__ == "__main__":
    unittest.main()
