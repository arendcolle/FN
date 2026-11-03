import logging
import unittest

import httpx

from fn import net
from fn.contracts import ParseIn, ParseOut
from fn.steps import StepContext, run_step
from fn.worker import Worker, new_id, now
from tests.helpers import SECRET, StubLLM, make_db, make_settings


class NetTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live"})
        self.store = make_db(self, self.settings)
        self.sent: list[httpx.Request] = []
        self.waits: list[float] = []

    def client(self, answers: list[httpx.Response], settings=None) -> net.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            return answers.pop(0)

        return net.Client(settings or self.settings, httpx.MockTransport(handle), sleep=self.waits.append)

    def step(self, client: net.Client, *urls: str):
        """Run one step that GETs every url through client; returns the step row, or raises what the client raised."""
        worker = Worker(self.store, self.settings, llm=StubLLM())
        self.addCleanup(worker.shutdown)
        search = worker.create_search("question")
        self.search_id = search.id
        ctx = StepContext(search_id=search.id, store=self.store, llm=None, http=client, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)

        def fetch(c: StepContext, inp: ParseIn) -> ParseOut:
            for url in urls:
                c.log.info("fetched %s", c.http.get(url, {"q": inp.question}).text)
            return ParseOut(chips={})

        run_step(ctx, "fetch", fetch, ParseIn(question="wind"))
        return self.store.list_steps(search.id)[-1]

    def test_key_goes_in_the_header_to_openalex_only_and_is_never_stored(self):
        """The OpenAlex call carries the key as a Bearer header; no other host gets it, and no call, payload or log holds it."""
        client = self.client([httpx.Response(200, json={"meta": {"cost_usd": 0.0001}, "results": []}),
                              httpx.Response(200, text="ok")])
        step = self.step(client, "https://api.openalex.org/works", "https://example.org/page")
        self.assertEqual(self.sent[0].headers["authorization"], f"Bearer {SECRET}")
        self.assertNotIn(SECRET, str(self.sent[0].url))
        self.assertNotIn("authorization", self.sent[1].headers)
        calls = self.store.list_calls(step.id)
        self.assertEqual([(c.status, c.cost_usd) for c in calls], [(200, 0.0001), (200, None)])
        stored = [c.request for c in calls] + [step.log, *self.store.get_payload(step.id)]
        for text in stored:
            self.assertNotIn(SECRET, text)
        self.assertIn("GET https://api.openalex.org/works?q=wind", calls[0].request)

    def test_every_request_names_fn_and_its_repository_in_the_user_agent(self):
        """Each request to any host carries FN's agent with the repository URL as contact, never httpx's default."""
        client = self.client([httpx.Response(200, text="ok"), httpx.Response(200, text="ok")])
        self.step(client, "https://www.wikidata.org/w/api.php", "https://api.ror.org/v2/organizations/x")
        self.assertEqual({r.headers["user-agent"] for r in self.sent},
                         {f"FN/0.1 (https://github.com/arendcolle/FN) httpx/{httpx.__version__}"})

    def test_retry_after_is_honoured_once_up_to_30s_and_a_longer_wait_fails_the_step(self):
        """A 429 asking for 2 s is retried after 2 s; one asking for 120 s fails the step and names the wait."""
        ok = self.client([httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, text="ok")])
        self.assertEqual(self.step(ok, "https://api.openalex.org/works").status, "ok")
        self.assertEqual(self.waits, [2.0])
        slow = self.client([httpx.Response(429, headers={"Retry-After": "120"})])
        with self.assertRaises(net.HttpError):
            self.step(slow, "https://api.openalex.org/works")
        step = self.store.list_steps(self.search_id)[-1]
        self.assertEqual(step.status, "error")
        self.assertIn("returned 429; Retry-After 120s is over 30s", step.error_message)
        self.assertEqual(self.waits, [2.0])
        twice = self.client([httpx.Response(503, headers={"Retry-After": "1"}), httpx.Response(503)])
        self.assertRaises(net.HttpError, self.step, twice, "https://api.openalex.org/works")

    def test_a_5xx_or_a_timeout_fails_the_step_with_the_status_or_the_timeout(self):
        """A 500 without Retry-After and a read timeout are not retried; the step error names the status or timeout."""
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("The read operation timed out", request=request)

        for client, expected in ((self.client([httpx.Response(500)]), "returned 500"),
                                 (net.Client(self.settings, httpx.MockTransport(timeout)), "ReadTimeout: The read operation timed out")):
            with self.subTest(expected=expected):
                self.assertRaises(net.HttpError, self.step, client, "https://api.openalex.org/works")
                step = self.store.list_steps(self.search_id)[-1]
                self.assertEqual(step.status, "error")
                self.assertIn(expected, step.error_message)
        self.assertEqual((len(self.sent), self.waits), (1, []))

    def test_replay_serves_what_live_cached_and_raises_on_a_miss(self):
        """A live call writes the cache that replay mode serves without the network; an uncached URL raises."""
        live = self.client([httpx.Response(200, json={"results": [1]})])
        self.step(live, "https://api.openalex.org/works")
        replay = self.client([], self.settings.model_copy(update={"http_mode": "replay"}))
        self.assertEqual(self.step(replay, "https://api.openalex.org/works").status, "ok")
        self.assertIn('{"results":[1]}', self.store.list_steps(self.search_id)[-1].log)
        with self.assertRaises(net.HttpError) as raised:
            self.step(replay, "https://api.openalex.org/authors")
        self.assertIn("replay: no cached response for GET https://api.openalex.org/authors?q=wind", str(raised.exception))
        self.assertEqual(len(self.sent), 1)

    def test_oversized_body_and_other_schemes_are_refused(self):
        """A body over 5 MB fails the call; a non-http URL is refused before any request."""
        big = self.client([httpx.Response(200, content=b"x" * (net.MAX_BYTES + 1))])
        self.assertRaises(net.HttpError, self.step, big, "https://example.org/big")
        self.assertIn("over 5 MB", self.store.list_calls(self.store.list_steps(self.search_id)[-1].id)[0].error)
        self.assertRaises(net.HttpError, self.step, self.client([]), "file:///etc/passwd")
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
