import json
import logging
import unittest

import httpx
from pydantic import SecretStr

from fn import net
from fn.contracts import Chip, Chips, LaneIn, LaneOut, Place
from fn.lanes import web, web_topic
from fn.steps import StepContext, run_step
from fn.worker import Worker, new_id, now
from tests.helpers import make_db, make_settings
from tests.test_extract import PageLLM, by_marker
from tests.test_web_lane import KEY, PEOPLE, recorded

PLACE = Place(text="New York", origin="edited")


def chips(version: int = 2, tie: str | None = None, need: str = "nice") -> Chips:
    return Chips(topics=[Chip(text="nanotech", origin="edited")], roles=[Chip(text="founders", origin="edited")],
                 place=PLACE, tie=Chip(text=tie, origin="edited", need=need) if tie else None, version=version)


class WebTopicTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live", "parallel_api_key": SecretStr(KEY)})
        self.store = make_db(self, self.settings)
        self.sent: list[httpx.Request] = []
        self.responses = {"/v1/search": recorded("search"), "/v1/extract": recorded("extract")}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        return httpx.Response(200, json=self.responses[request.url.path])

    def run_lane(self, given: Chips, first_heading: int | None = None) -> LaneOut:
        """Run lane:web_topic as a step of a new search over a mock transport."""
        llm = PageLLM(by_marker(PEOPLE))
        http = net.Client(self.settings, httpx.MockTransport(self.handle))
        worker = Worker(self.store, self.settings, llm=llm, http=http)
        self.addCleanup(worker.shutdown)
        search_id = worker.create_search("question", given, "edited").id
        ctx = StepContext(search_id=search_id, store=self.store, llm=llm, http=http, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        return run_step(ctx, "lane:web_topic", web_topic.run,
                        LaneIn(search_id=search_id, chips=given, first_heading=first_heading))

    def test_each_gate_gives_one_note_and_makes_no_call(self):
        """No chip, version 1 chips, a must tie and a full first heading each note their reason and post nothing."""
        for given, heading, reason in (
            (Chips(place=PLACE, version=2), 0, web.NO_QUERY),
            (chips(version=1), 0, "chips stored before this round, so no search without a tie"),
            (chips(tie="Flemish", need="must"), 0, "the tie is a must, so no search without it"),
            (chips(), 20, "20 people under the first heading, so no search without a tie"),
            (chips(), 35, "35 people under the first heading, so no search without a tie"),
        ):
            with self.subTest(reason=reason):
                out = self.run_lane(given, heading)
                self.assertEqual(self.sent, [])
                self.assertEqual(([c.reason for c in out.considered], out.hits, out.lane), ([reason], [], "web_topic"))

    def test_under_the_gate_one_search_without_belgium_and_hits_carry_the_lane(self):
        """With 19 or no count under the first heading, the Search objective has no Belgium and every hit is web_topic."""
        for heading in (None, 0, 19):
            with self.subTest(first_heading=heading):
                self.sent.clear()
                out = self.run_lane(chips(), heading)
                search = json.loads(self.sent[0].content)
                self.assertEqual(self.sent[0].url.path, "/v1/search")
                self.assertNotIn("Belgium", search["objective"])
                self.assertEqual(search["objective"], "People who are founders and work on nanotech in New York")
                self.assertEqual(out.lane, "web_topic")
                self.assertTrue(out.hits)
                self.assertEqual({h.lane for h in out.hits}, {"web_topic"})

    def test_a_missing_key_is_a_note_and_the_step_is_ok(self):
        """Without a Parallel key the lane returns a note that names the lane and makes no call."""
        self.settings = self.settings.model_copy(update={"parallel_api_key": None})
        out = self.run_lane(chips(), 0)
        self.assertEqual(self.sent, [])
        self.assertTrue(out.considered[0].reason.startswith("web_topic lane skipped"))


if __name__ == "__main__":
    unittest.main()
