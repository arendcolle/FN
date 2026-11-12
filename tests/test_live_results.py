import re
import threading
import time
import unittest
from html import unescape
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from fn.contracts import (
    Candidate,
    Chip,
    Chips,
    Identifier,
    LaneHit,
    LaneIn,
    LaneOut,
    Search,
    StepRun,
)
from fn.steps import StepContext
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

CHIPS = Chips(topics=[Chip(text="wind", origin="edited")])


class LiveResultsTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False,
                                 follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def person(self, name: str) -> str:
        return self.store.resolve_person([Identifier(scheme="seed", value=name)], name).id

    def search(self, search_id: str, status: str, people: list[str], steps: list[tuple[str, str]] = ()) -> str:
        """A search in status with the people as new candidates in rank order and step rows of (step, status)."""
        self.store.create_search(Search(id=search_id, question="Who knows wind?", status=status, created_at=now(),
                                        code_sha=None, dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        for seq, (step, step_status) in enumerate(steps, 1):
            run = StepRun(id=f"{search_id}-{seq}", search_id=search_id, seq=seq, step=step, status="running",
                          started_at=now(), input_model="LaneIn")
            self.store.start_step(run, "{}")
            self.store.finish_step(run.model_copy(update={"status": step_status, "ended_at": now()}), None)
        self.store.save_candidates(search_id, [
            Candidate(search_id=search_id, person_id=p, person_ids=[p], hit_person_ids=[p], section="new", rank=n,
                      score=1.0, lane_ranks={"seeds": n}) for n, p in enumerate(people, 1)], [])
        return search_id

    def text(self, path: str) -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return unescape(response.text)

    def test_the_status_route_returns_status_people_and_version(self):
        """GET /searches/{id}/status is the search's progress as JSON, and 404 for an unknown search."""
        ann = self.person("Ann Example")
        self.search("queued", "queued", [])
        self.search("running", "running", [ann], [("lane:seeds", "ok"), ("publish", "ok")])
        self.search("done", "done", [ann], [("lane:seeds", "ok"), ("publish", "ok"), ("save", "ok")])
        for search_id, expected in (("queued", {"status": "queued", "people": 0, "version": 0}),
                                    ("running", {"status": "running", "people": 1, "version": 1}),
                                    ("done", {"status": "done", "people": 1, "version": 2})):
            with self.subTest(search_id=search_id):
                self.assertEqual(self.client.get(f"/searches/{search_id}/status").json(), expected)
        self.assertEqual(self.client.get("/searches/nope/status").status_code, 404)
        self.assertEqual(self.client.get("/searches/nope/cards").status_code, 404)

    def test_the_fragment_holds_the_page_s_list_and_nothing_else(self):
        """The cards route returns the results list of the page, byte for byte, without the document or header."""
        people = [self.person(f"Person {n} Example") for n in range(3)]
        self.search("s1", "done", people)
        fragment = self.text("/searches/s1/cards?shown=2")
        self.assertTrue(fragment.startswith('<div class="fn-results__list"'))
        self.assertIn(fragment, self.text("/searches/s1?shown=2"))
        self.assertEqual(re.findall(r'id="card-([^"]+)"', fragment), people[:2])
        self.assertIn("Show 1 more", fragment)
        for absent in ("<html", "fn-header", "<head"):
            self.assertNotIn(absent, fragment)

    def test_a_running_page_shows_the_count_and_polls_with_the_refresh_only_without_javascript(self):
        """A running search says how many people so far, loads results.js with the URLs it polls, and reloads only
        inside noscript; it leaves out the count line."""
        self.search("s0", "running", [])
        empty = self.text("/searches/s0")
        self.assertIn("<span>Searching…</span>", empty)
        self.assertIn('src="/static/results.js"', empty)
        self.search("s1", "running", [self.person("Ann Example")], [("lane:seeds", "ok"), ("publish", "ok")])
        page = self.text("/searches/s1")
        self.assertIn("<span>Searching… 1 person so far</span>", page)
        self.assertIn('data-status="/searches/s1/status" data-progress="running 1" data-cards="/searches/s1/cards"', page)
        self.assertIn('<noscript><meta http-equiv="refresh" content="2"></noscript>', page)
        self.assertEqual(page.count('http-equiv="refresh"'), 1)
        self.assertNotIn("fn-count", page)
        self.search("s2", "running", [self.person(f"P{n} Example") for n in range(12)])
        self.assertIn("Searching… 12 people so far", self.text("/searches/s2/map"))
        self.assertIn('data-cards="/searches/s2/cards?view=map"', self.text("/searches/s2/map"))

    def test_a_done_search_with_a_failed_lane_says_the_list_may_be_incomplete(self):
        """The note and Search again, which posts the question, stand above the cards; no poll and no refresh."""
        ann = self.person("Ann Example")
        self.search("s1", "done", [ann], [("lane:seeds", "ok"), ("lane:openalex", "error"), ("save", "ok")])
        page = self.text("/searches/s1")
        note = page.index("Some sources could not be read, so this list may be incomplete.")
        self.assertLess(page.index('<div class="fn-status-note">'), note)
        self.assertLess(note, page.index(">Search again</button>"))
        self.assertLess(page.index(">Search again</button>"), page.index(f'id="card-{ann}"'))
        self.assertIn('<input type="hidden" name="question" value="Who knows wind?">', page)
        for absent in ("data-status", "refresh", "Searching…"):
            self.assertNotIn(absent, page)
        self.search("s2", "done", [ann], [("lane:seeds", "ok"), ("save", "ok")])
        self.assertNotIn("fn-status-note", self.text("/searches/s2"))

    def test_a_stopped_search_shows_the_people_it_found_or_the_notice(self):
        """A failed or interrupted search with people shows them under the stopped note with Run again; one with
        nobody shows the This search stopped notice and no map."""
        ann = self.person("Ann Example")
        for status in ("failed", "interrupted"):
            with self.subTest(status=status):
                self.search(f"{status}-1", status, [ann], [("lane:seeds", "ok"), ("publish", "ok")])
                page = self.text(f"/searches/{status}-1")
                self.assertLess(page.index("This search stopped before it finished."), page.index(">Run again</button>"))
                self.assertLess(page.index(">Run again</button>"), page.index(f'id="card-{ann}"'))
                self.assertNotIn("fn-notice", page)
                self.search(f"{status}-0", status, [])
                nobody = self.text(f"/searches/{status}-0")
                self.assertIn('<h2 class="fn-notice__title text-title">This search stopped</h2>', nobody)
                self.assertIn("FN ran into a problem before it found anyone. Your question is kept, so Try again runs "
                              "it once more.", nobody)
                self.assertIn(">Try again</button>", nobody)
                self.assertIn("fn-results--no-map", nobody)

    def test_a_running_search_s_first_lane_people_are_served_before_the_next_lane_returns(self):
        """While the second lane blocks, the status route says running at version 1 and the fragment holds the first
        lane's card; after it returns the search is done."""
        ann, pat = self.person("Ann Example"), self.person("Pat Example")
        release = threading.Event()

        keys = {p.id: p.name_key for p in self.store.get_persons([ann, pat]).values()}

        def lane(name: str, person_id: str, gate: threading.Event | None = None):
            def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
                if gate:
                    self.assertTrue(gate.wait(10))
                hit = LaneHit(person_id=person_id, name_key=keys[person_id], lane=name, rank=1, score=1.0,
                              matched_on="wind")
                return LaneOut(lane=name, query="wind", total_seen=1, hits=[hit])
            return SimpleNamespace(name=name, run=run)

        worker = self.client.app.state.worker
        with mock.patch("fn.search.LANES", [lane("seeds", ann), lane("web", pat, release)]):
            search_id = worker.pool.submit(worker.create_search, "Who knows wind?", CHIPS, "edited").result(10).id
            future = worker.submit(search_id)
            deadline = time.monotonic() + 10
            while (status := self.client.get(f"/searches/{search_id}/status").json())["version"] < 1:
                self.assertLess(time.monotonic(), deadline, "nothing was published")
                time.sleep(0.01)
            self.assertEqual(status, {"status": "running", "people": 1, "version": 1})
            fragment = self.text(f"/searches/{search_id}/cards")
            self.assertEqual(re.findall(r'id="card-([^"]+)"', fragment), [ann])
            self.assertIn("Searching… 1 person so far", fragment)
            release.set()
            future.result(timeout=10)
        self.assertEqual(self.client.get(f"/searches/{search_id}/status").json(),
                         {"status": "done", "people": 2, "version": 2})
        self.assertNotIn("data-status", self.text(f"/searches/{search_id}/cards"))

    def test_the_status_route_logs_version_and_people(self):
        """The request log line of a status request carries the version and the people count."""
        self.search("s1", "running", [self.person("Ann Example")], [("publish", "ok")])
        with self.assertLogs("fn.request", "INFO") as logs:
            self.client.get("/searches/s1/status")
        self.assertRegex(logs.output[-1], r"GET /searches/s1/status 200 \d+ms version=1 people=1$")


if __name__ == "__main__":
    unittest.main()
