import hashlib
import json
import logging
import os
import unittest
from unittest import mock

import httpx
from pydantic import SecretStr

from fn import config, net
from fn.contracts import ParseIn, ParseOut
from fn.steps import StepContext, run_step
from fn.worker import Worker, new_id, now
from tests.helpers import SECRET, StubLLM, make_db, make_settings

PARALLEL_KEY = "px-parallel-0123456789"
APIFY_TOKEN = "apify_api_test_0123456789"
SEARCH = "https://api.parallel.ai/v1/search"
BODY = {"objective": "Belgian 6G researchers", "search_queries": ["6G Belgian"], "mode": "fast"}


class NetTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live"})
        self.store = make_db(self, self.settings)
        self.keyed = self.settings.model_copy(update={"parallel_api_key": SecretStr(PARALLEL_KEY),
                                                      "apify_token": SecretStr(APIFY_TOKEN)})
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

    def send(self, client: net.Client, call):
        """Run call(client) as the one call of a step; returns the step row, or raises what call raised."""
        worker = Worker(self.store, client.settings, llm=StubLLM())
        self.addCleanup(worker.shutdown)
        search = worker.create_search("question")
        self.search_id = search.id
        ctx = StepContext(search_id=search.id, store=self.store, llm=None, http=client, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=client.settings)

        def send(c: StepContext, inp: ParseIn) -> ParseOut:
            call(c.http)
            return ParseOut(chips={})

        run_step(ctx, "send", send, ParseIn(question="wind"))
        return self.store.list_steps(search.id)[-1]

    def calls(self, step) -> list:
        return self.store.list_calls(step.id)

    def test_post_cache_file_follows_url_and_body_and_ignores_key_order(self):
        """Bodies that differ get different cache files; the same body, in any key order, rewrites the same file."""
        client = self.client([httpx.Response(200, json={"n": n}) for n in range(3)], self.keyed)
        first = {"objective": "x", "mode": "fast"}
        for body in (first, {"objective": "y", "mode": "fast"}, {"mode": "fast", "objective": "x"}):
            self.send(client, lambda http, body=body: http.post(SEARCH, body))
        compact = json.dumps(first, sort_keys=True, separators=(",", ":"))
        name = hashlib.sha256(f"POST {SEARCH}\n{compact}".encode()).hexdigest() + ".json"
        self.assertEqual(len(list(client.cache.glob("*.json"))), 2)
        self.assertEqual(json.loads((client.cache / name).read_text()), {"n": 2})
        self.assertEqual((self.sent[0].method, json.loads(self.sent[0].content)), ("POST", first))

    def test_replayed_post_serves_its_file_and_a_miss_raises_cache_miss(self):
        """Replay returns what a live POST cached, without a key or a transport call; another body raises CacheMiss."""
        self.send(self.client([httpx.Response(200, json={"results": [1]})], self.keyed), lambda http: http.post(SEARCH, BODY))
        replay = self.client([], self.settings.model_copy(update={"http_mode": "replay"}))
        served = []
        step = self.send(replay, lambda http: served.append(http.post(SEARCH, BODY)))
        self.assertEqual(served[0].json(), {"results": [1]})
        self.assertTrue(self.calls(step)[0].request.startswith(f"replay POST {SEARCH} "))
        with self.assertRaises(net.CacheMiss) as raised:
            self.send(replay, lambda http: http.post(SEARCH, {**BODY, "mode": "base"}))
        self.assertIn(f"replay: no cached response for POST {SEARCH} ", str(raised.exception))
        self.assertIsInstance(raised.exception, net.HttpError)
        self.assertEqual(len(self.sent), 1)

    def test_each_key_goes_only_over_https_to_its_own_host(self):
        """x-api-key goes to https://api.parallel.ai and Bearer tokens to the Apify and OpenAlex hosts, each its own key.

        An http URL, another host and a host that only starts with a keyed name get no key header.
        """
        expected = {
            SEARCH: {"x-api-key": PARALLEL_KEY},
            "https://api.apify.com/v2/acts": {"authorization": f"Bearer {APIFY_TOKEN}"},
            "https://api.openalex.org/works": {"authorization": f"Bearer {SECRET}"},
            "http://api.parallel.ai/v1/search": {},
            "http://api.apify.com/v2/acts": {},
            "http://api.openalex.org/works": {},
            "https://example.org/v1/search": {},
            "https://api.parallel.ai.example.org/v1/search": {},
        }
        client = self.client([httpx.Response(200, json={}) for _ in expected for _ in (0, 1)], self.keyed)

        def call_each(http):
            for url in expected:
                http.get(url)
                http.post(url, BODY)

        self.send(client, call_each)
        self.assertEqual(len(self.sent), 2 * len(expected))
        for request in self.sent:
            sent = {k: v for k, v in request.headers.items() if k in ("authorization", "x-api-key")}
            self.assertEqual(sent, expected[str(request.url)], f"{request.method} {request.url}")

    def test_live_post_without_its_key_raises_missing_key_before_any_call(self):
        """A live POST without its own key, or with only the other vendor's, never reaches the transport.

        OpenAlex still goes out without a key.
        """
        apify = "https://api.apify.com/v2/acts/x/runs"
        only_openalex = self.client([], self.settings)
        only_apify = self.client([], self.settings.model_copy(update={"apify_token": SecretStr(APIFY_TOKEN)}))
        only_parallel = self.client([], self.settings.model_copy(update={"parallel_api_key": SecretStr(PARALLEL_KEY)}))
        for client, url, name in ((only_openalex, SEARCH, "PARALLEL_API_KEY"), (only_openalex, apify, "APIFY_TOKEN"),
                                  (only_apify, SEARCH, "PARALLEL_API_KEY"), (only_parallel, apify, "APIFY_TOKEN")):
            with self.subTest(url=url, name=name):
                with self.assertRaises(net.MissingKey) as raised:
                    self.send(client, lambda http, url=url: http.post(url, BODY))
                self.assertIn(name, str(raised.exception))
                step = self.store.list_steps(self.search_id)[-1]
                self.assertEqual((step.status, step.error_type), ("error", "MissingKey"))
                self.assertIn(name, self.calls(step)[0].error)
        self.assertTrue(issubclass(net.MissingKey, net.HttpError))
        self.assertEqual(self.sent, [])
        keyless = self.client([httpx.Response(200, json={})], self.settings.model_copy(update={"openalex_api_key": None}))
        self.send(keyless, lambda http: http.get("https://api.openalex.org/works"))
        self.assertNotIn("authorization", self.sent[0].headers)

    def test_the_recorded_post_holds_the_body_and_no_key_appears_in_any_error(self):
        """The recorded request shows the URL and the compact body.

        A 401 whose body echoes the keys leaves them in no exception, call, log or payload.
        """
        client = self.client([httpx.Response(200, json={"results": []}),
                              httpx.Response(401, json={"error": f"bad key {PARALLEL_KEY} and {APIFY_TOKEN}"})], self.keyed)
        step = self.send(client, lambda http: http.post(SEARCH, BODY))
        self.assertEqual(self.calls(step)[0].request,
                         f'POST {SEARCH} {{"objective":"Belgian 6G researchers","search_queries":["6G Belgian"],"mode":"fast"}}')
        with self.assertRaises(net.HttpError) as raised:
            self.send(client, lambda http: http.post(SEARCH, {**BODY, "mode": "base"}))
        failed = self.store.list_steps(self.search_id)[-1]
        stored = [str(raised.exception), failed.error_message, failed.traceback, failed.log, *self.store.get_payload(failed.id),
                  *(c.request for c in self.calls(failed)), *(c.error for c in self.calls(failed))]
        self.assertIn("returned 401: ", str(raised.exception))
        for text in filter(None, stored):
            self.assertNotIn(PARALLEL_KEY, text)
            self.assertNotIn(APIFY_TOKEN, text)

    def test_only_never_calls_out_and_prefer_serves_a_cached_answer_without_a_key(self):
        """cache="only" raises CacheMiss on a miss; "prefer" serves a file with no transport call and no key.

        On a miss "prefer" calls out, so it needs the key, and the answer it caches is served the next time.
        """
        self.send(self.client([httpx.Response(200, json={"results": [1]})], self.keyed), lambda http: http.post(SEARCH, BODY))
        keyless = self.client([], self.settings)
        other = {**BODY, "mode": "base"}
        for cache in ("prefer", "only"):
            served = []
            step = self.send(keyless, lambda http, cache=cache: served.append(http.post(SEARCH, BODY, cache=cache)))
            self.assertEqual(served[0].json(), {"results": [1]})
            self.assertTrue(self.calls(step)[0].request.startswith(f"cache POST {SEARCH} "))
        with self.assertRaises(net.CacheMiss):
            self.send(keyless, lambda http: http.post(SEARCH, other, cache="only"))
        with self.assertRaises(net.MissingKey):
            self.send(keyless, lambda http: http.post(SEARCH, other, cache="prefer"))
        self.assertEqual(len(self.sent), 1)
        online = self.client([httpx.Response(200, json={"results": [2]})], self.keyed)
        for _ in range(2):
            served = []
            self.send(online, lambda http: served.append(http.post(SEARCH, other, cache="prefer")))
            self.assertEqual(served[0].json(), {"results": [2]})
        self.assertEqual(len(self.sent), 2)
        with self.assertRaises(net.CacheMiss):
            self.send(online, lambda http: http.post(SEARCH, {**BODY, "mode": "deep"}, cache="only"))
        self.assertEqual(len(self.sent), 2)

    def test_keep_false_leaves_no_cache_file_but_the_call_is_recorded_and_returned(self):
        """An answer keep() refuses is returned and recorded with its status and hash but not written.

        The next prefer call goes out again; an answer keep() accepts is written and then served.
        """
        client = self.client([httpx.Response(200, json={"items": []}), httpx.Response(200, json={"items": [1]})], self.keyed)

        def keep(body: bytes) -> bool:
            return bool(json.loads(body)["items"])

        refused = []
        step = self.send(client, lambda http: refused.append(http.post(SEARCH, BODY, cache="prefer", keep=keep)))
        self.assertEqual(refused[0].json(), {"items": []})
        (call,) = self.calls(step)
        self.assertEqual((call.status, call.response_path), (200, None))
        self.assertIsNotNone(call.response_sha)
        self.assertEqual(list(client.cache.glob("*.json")), [])
        for _ in range(2):
            self.send(client, lambda http: http.post(SEARCH, BODY, cache="prefer", keep=keep))
        self.assertEqual((len(self.sent), len(list(client.cache.glob("*.json")))), (2, 1))

    def test_cost_prices_a_live_answer_and_a_cached_or_replayed_call_records_zero(self):
        """cost(body) runs only on a live 2xx answer.

        A call from the cache or replay records 0.0, even for a GET whose cached body states a cost.
        """
        answer = {"usage": [{"name": "sku_search", "count": 1}], "meta": {"cost_usd": 9.0}}
        client = self.client([httpx.Response(200, json=answer), httpx.Response(200, json=answer)], self.keyed)
        priced = []

        def cost(body: bytes) -> float:
            priced.append(body)
            return 0.001

        live = self.send(client, lambda http: http.post(SEARCH, BODY, cost=cost))
        unpriced = self.send(client, lambda http: http.post(SEARCH, {**BODY, "mode": "base"}))
        self.assertEqual([self.calls(live)[0].cost_usd, self.calls(unpriced)[0].cost_usd], [0.001, None])
        cached = self.send(client, lambda http: http.post(SEARCH, BODY, cache="prefer", cost=cost))
        replay = self.client([], self.keyed.model_copy(update={"http_mode": "replay"}))
        replayed = self.send(replay, lambda http: http.post(SEARCH, BODY, cost=cost))
        self.assertEqual([self.calls(cached)[0].cost_usd, self.calls(replayed)[0].cost_usd], [0.0, 0.0])
        self.assertEqual(len(priced), 1)
        stated = self.client([httpx.Response(200, json={"meta": {"cost_usd": 0.0001}})])
        self.send(stated, lambda http: http.get("https://api.openalex.org/works"))
        got = self.send(replay, lambda http: http.get("https://api.openalex.org/works"))
        self.assertEqual(self.calls(got)[0].cost_usd, 0.0)

    def test_a_cost_or_keep_that_raises_still_records_the_paid_call_and_caches_nothing(self):
        """A live 2xx answer is recorded with its status, hash and the error even when cost() or keep() raises.

        The exception reaches the caller and no cache file is written, so a later prefer call goes out again.
        """
        def unreadable(body: bytes):
            return json.loads(body)["usage"]

        for option in ("cost", "keep"):
            with self.subTest(option=option):
                client = self.client([httpx.Response(201, content=b"not json")], self.keyed)
                self.assertRaises(json.JSONDecodeError, self.send, client,
                                  lambda http, kw={option: unreadable}: http.post(SEARCH, BODY, cache="prefer", **kw))
                (call,) = self.calls(self.store.list_steps(self.search_id)[-1])
                self.assertEqual((call.status, call.response_path), (201, None))
                self.assertEqual(call.response_sha, hashlib.sha256(b"not json").hexdigest())
                self.assertIn("JSONDecodeError", call.error)
                self.assertEqual(list(client.cache.glob("*")), [])

    def test_a_cache_file_is_moved_into_place_whole_so_a_killed_write_leaves_none(self):
        """The answer is written to a temporary file and renamed to <sha>.json, never written to that name directly.

        When the rename does not happen, no <sha>.json exists for cache="only" or "prefer" to serve.
        """
        client = self.client([httpx.Response(200, json={"n": 1})], self.keyed)
        with mock.patch("fn.net.os.replace", side_effect=OSError("killed")):
            self.assertRaises(OSError, self.send, client, lambda http: http.post(SEARCH, BODY))
        self.assertEqual(list(client.cache.glob("*.json")), [])

    def test_a_non_2xx_post_puts_the_first_300_characters_of_its_body_in_the_error(self):
        """A 402 names the vendor's message in the exception and the recorded call; a longer body is cut at 300 characters."""
        client = self.client([httpx.Response(402, json={"detail": "credit exhausted"}), httpx.Response(422, text="x" * 1000)],
                             self.keyed)
        with self.assertRaises(net.HttpError) as raised:
            self.send(client, lambda http: http.post(SEARCH, BODY))
        self.assertIn("returned 402", str(raised.exception))
        self.assertIn("credit exhausted", str(raised.exception))
        step = self.store.list_steps(self.search_id)[-1]
        self.assertIn("credit exhausted", self.calls(step)[0].error)
        self.assertIn("credit exhausted", step.error_message)
        with self.assertRaises(net.HttpError) as long:
            self.send(client, lambda http: http.post(SEARCH, BODY))
        self.assertTrue(str(long.exception).endswith(": " + "x" * 300))

    def test_a_post_retries_a_429_but_never_a_503_and_a_get_still_retries_both(self):
        """A 429 with Retry-After is retried once for a POST; a 503 with Retry-After is not.

        The vendor may have started work before a 503, so a retry could pay twice.
        """
        post = lambda http: http.post(SEARCH, BODY)
        busy = self.client([httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json={})], self.keyed)
        self.assertEqual(self.send(busy, post).status, "ok")
        self.assertEqual((len(self.sent), self.waits), (2, [2.0]))
        down = self.client([httpx.Response(503, headers={"Retry-After": "1"}), httpx.Response(200, json={})], self.keyed)
        self.assertRaises(net.HttpError, self.send, down, post)
        self.assertIn("returned 503", self.store.list_steps(self.search_id)[-1].error_message)
        self.assertEqual((len(self.sent), self.waits), (3, [2.0]))
        get = self.client([httpx.Response(503, headers={"Retry-After": "1"}), httpx.Response(200, json={})], self.keyed)
        self.assertEqual(self.send(get, lambda http: http.get("https://api.openalex.org/works")).status, "ok")
        self.assertEqual((len(self.sent), self.waits), (5, [2.0, 1.0]))

    def test_timeout_s_replaces_the_read_timeout_for_that_call_only(self):
        """A POST with timeout_s=90 reads for up to 90 s and connects for 10 s; a call without it keeps 30 s and 10 s."""
        seen = []

        def handle(request: httpx.Request) -> httpx.Response:
            seen.append(request.extensions["timeout"])
            return httpx.Response(200, json={})

        client = net.Client(self.keyed, httpx.MockTransport(handle))

        def call(http):
            http.post(SEARCH, BODY, timeout_s=90)
            http.post(SEARCH, BODY)
            http.get("https://api.openalex.org/works")

        self.send(client, call)
        self.assertEqual([(t["read"], t["connect"]) for t in seen], [(90.0, 10.0), (30.0, 10.0), (30.0, 10.0)])

    def test_get_cache_file_name_is_still_the_sha256_of_the_full_url(self):
        """Caches written before POST existed still hit: a GET with params is stored under sha256 of the URL with its query."""
        client = self.client([httpx.Response(200, json={})])
        self.step(client, "https://api.openalex.org/works")
        self.assertEqual([p.name for p in client.cache.glob("*.json")],
                         ["bc6b1a8f149a05e249eec8b94ccfdaa64aa92fa00ecbd94d6c6761510b9282fc.json"])

    def test_post_is_refused_for_other_schemes_and_for_a_body_over_5_mb(self):
        """A POST follows the GET rules: a non-http URL is refused before any request, and an answer over 5 MB fails the call."""
        self.assertRaises(net.HttpError, self.send, self.client([], self.keyed), lambda http: http.post("file:///etc/passwd", BODY))
        self.assertEqual(self.sent, [])
        big = self.client([httpx.Response(200, content=b"x" * (net.MAX_BYTES + 1))], self.keyed)
        self.assertRaises(net.HttpError, self.send, big, lambda http: http.post(SEARCH, BODY))
        self.assertIn("POST", self.calls(self.store.list_steps(self.search_id)[-1])[0].error)
        self.assertIn("over 5 MB", self.calls(self.store.list_steps(self.search_id)[-1])[0].error)

    def test_from_env_reads_each_vendor_key_from_its_env_var_else_the_keychain(self):
        """The Parallel key and the Apify token come from the env var, else the Keychain.

        Only FN_LINKEDIN=1 switches the LinkedIn lane on.
        """
        keychain = {"APIFY_TOKEN": APIFY_TOKEN}
        for switch, expected in (("1", True), ("0", False), ("true", False), (None, False)):
            env = {"PARALLEL_API_KEY": PARALLEL_KEY} | ({"FN_LINKEDIN": switch} if switch else {})
            with self.subTest(switch=switch), mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch("fn.config.keychain", side_effect=keychain.get):
                settings = config.from_env()
            self.assertEqual(settings.linkedin_live, expected)
        self.assertEqual(settings.parallel_api_key.get_secret_value(), PARALLEL_KEY)
        self.assertEqual(settings.apify_token.get_secret_value(), APIFY_TOKEN)
        self.assertIsNone(settings.openalex_api_key)
        self.assertEqual(sorted(settings.secrets()), sorted([PARALLEL_KEY, APIFY_TOKEN]))


if __name__ == "__main__":
    unittest.main()
