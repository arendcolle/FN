import json
import logging
import os
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from fn import db, orgs
from fn.contracts import (
    Chip,
    Chips,
    ClaimDraft,
    Identifier,
    OrgFacts,
    ParseIn,
    ParseOut,
    Place,
    Search,
    Source,
    StepRun,
)
from fn.steps import StepContext, run_step, setup_logging
from fn.store import Store
from fn.web.app import create_app, serve
from fn.web.html import h, safe_url
from fn.worker import new_id, now
from tests.helpers import (
    SECRET,
    StubHttp,
    StubLLM,
    make_db,
    make_seeded_db,
    make_settings,
)

HOSTILE = '"><script>alert(1)</script>'
QUESTION = f"{HOSTILE} javascript:alert(1) <b>"
HOSTILE_CHIPS = {
    "topics": [{"text": HOSTILE, "span": {"start": 0, "end": len(HOSTILE)}, "origin": "parsed"}],
    "institutions": [{"text": "javascript:alert(1)", "span": {"start": len(HOSTILE) + 1, "end": len(HOSTILE) + 20},
                      "origin": "parsed"}],
    "place": {"text": "<b>", "span": {"start": len(QUESTION) - 3, "end": len(QUESTION)}, "origin": "parsed"},
}


class WebTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)

    def client(self, llm: StubLLM | None = None) -> TestClient:
        app = create_app(self.settings, llm or StubLLM(error=AssertionError("the LLM must not be called")), StubHttp())
        client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def create_search(self, client: TestClient, question: str, chips: Chips | None = None) -> str:
        """Create a queued search on the worker thread, so the test thread opens no connection of the app's store."""
        worker = client.app.state.worker
        return worker.pool.submit(worker.create_search, question, chips, "parsed" if chips else None).result(timeout=10).id

    def run_search(self, client: TestClient, question: str, chips: Chips | None = None) -> str:
        search_id = self.create_search(client, question, chips)
        client.app.state.worker.submit(search_id).result(timeout=10)
        return search_id

    def wait_ended(self, search_id: str) -> None:
        deadline = time.monotonic() + 10
        while self.store.get_search(search_id).status in ("queued", "running"):
            self.assertLess(time.monotonic(), deadline, "the search did not end")
            time.sleep(0.01)

    def test_pages_render_hostile_text_escaped(self):
        """Script tags, quotes and javascript: in every stored text field show as text on every page."""
        good = self.client(StubLLM(answer=HOSTILE_CHIPS))
        bad = self.client(StubLLM(error=ValueError(HOSTILE)))
        good_id = self.run_search(good, QUESTION)
        with self.assertLogs("fn.worker", "ERROR"):
            bad_id = self.run_search(bad, QUESTION)
        self.store.add_request_error("e1", f"GET /{HOSTILE}", f"Traceback {HOSTILE}", now())
        steps = [s for s in self.store.list_steps(good_id) + self.store.list_steps(bad_id) if s.step == "parse"]
        urls = ["/", f"/searches/{good_id}", f"/searches/{bad_id}", f"/debug/searches/{good_id}",
                f"/debug/searches/{bad_id}", "/debug/errors", *(f"/debug/steps/{s.id}/calls" for s in steps)]
        responses = {url: good.get(url) for url in urls}
        responses["POST /searches"] = good.post("/searches", data={"question": HOSTILE + "q" * 1001})
        responses["POST rerun"] = good.post(f"/searches/{good_id}/rerun", data={"ask": HOSTILE})
        for url, response in responses.items():
            with self.subTest(url=url):
                self.assertEqual(response.status_code, 400 if url.startswith("POST") else 200)
                self.assertNotIn("<script", response.text)
                self.assertNotIn('href="javascript:', response.text)
                self.assertNotIn("<b>", response.text)
                self.assertIn("&lt;script&gt;", response.text)

    def test_cards_source_and_trace_pages_escape_hostile_text(self):
        """A hostile name, claim, quote, source title and URL show as text on the card, source and trace pages."""
        text = f"{HOSTILE} works at javascript:alert(1) <b>"
        source = Source(id="src", kind="page", url=f"https://example.org/{HOSTILE}", title=HOSTILE, text=text,
                        content_hash="h")
        person = self.store.resolve_person([Identifier(scheme="seed", value="x")], HOSTILE)
        claim = self.store.upsert_claim(ClaimDraft(
            person_id=person.id, kind="topic", value=HOSTILE, quote=text, quote_start=0, quote_end=len(text),
            source=source, claim_date="2020", date_precision="year", date_method="record_field"))
        client = self.client()
        search_id = self.run_search(client, QUESTION, Chips(topics=[Chip(text="script alert", origin="edited")]))
        self.assertEqual(len(self.store.list_candidates(search_id)), 1)
        for url in (f"/searches/{search_id}", f"/sources/src?claim={claim.id}",
                    f"/debug/searches/{search_id}/trace?name={HOSTILE}"):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("<script", response.text)
                self.assertNotIn('href="javascript:', response.text)
                self.assertNotIn("<b>", response.text)
                self.assertIn("&lt;script&gt;", response.text)
        self.assertEqual(client.get("/sources/src?claim=nope").status_code, 404)
        self.assertEqual(client.get("/sources/nope").status_code, 404)

    def test_a_claim_at_an_org_without_stored_facts_is_named_not_counted_as_not_belgian(self):
        """A KVAB claim with no orgs row (fn-orgs not run) shows 'org facts not stored for' its id, never the absence line."""
        text = "Anne Example, member of KVAB"
        source = Source(id="src", kind="page", url="https://example.org/kvab", title="KVAB members", text=text,
                        content_hash="h")
        person = self.store.resolve_person([Identifier(scheme="seed", value="anne")], "Anne Example")
        self.store.upsert_claim(ClaimDraft(
            person_id=person.id, kind="role", relation="member_of", org_id="wikidata:Q1301699", value="KVAB",
            quote=text, quote_start=0, quote_end=len(text), source=source))
        client = self.client()
        search_id = self.run_search(client, "q", Chips(topics=[Chip(text="KVAB", origin="edited")]))
        page = client.get(f"/debug/searches/{search_id}").text
        self.assertIn("org facts not stored for wikidata:Q1301699", page)
        self.assertNotIn("No Belgian organization found", page)

    def test_card_writes_a_spanned_claims_years_and_shows_the_belgian_years_part(self):
        """The Years column writes a 2013 to 2018 claim as '2013-2018', and Score parts has its belgian_years row."""
        text = "Anne Example, ULB 2013-2018"
        source = Source(id="src", kind="page", url="https://example.org/ulb", title="ULB staff", text=text,
                        content_hash="h")
        record = Source(id="org", kind="record", url="https://ror.org/01r9htc13", text="id: ror", content_hash="h2",
                        fetched_at=now())
        orgs.save(self.store, [OrgFacts(id="ror:01r9htc13", name="ULB", country_code="BE")], record, replace=True)
        person = self.store.resolve_person([Identifier(scheme="seed", value="anne")], "Anne Example")
        self.store.upsert_claim(ClaimDraft(
            person_id=person.id, kind="affiliation", relation="worked_at", org_id="ror:01r9htc13", value="ULB",
            quote=text, quote_start=0, quote_end=len(text), source=source, claim_date="2018", valid_from="2013",
            valid_to="2018"))
        client = self.client()
        search_id = self.run_search(client, "q", Chips(topics=[Chip(text="ULB", origin="edited")]))
        page = client.get(f"/debug/searches/{search_id}").text
        belgian = page[page.index("Claims at Belgian organizations"):page.index("Record 1:")]
        self.assertIn("<th>Years</th>", belgian)
        self.assertIn("<td>2013-2018</td>", belgian)
        self.assertIn("<td>belgian_years</td><td>1</td><td>0.0164</td>"
                      "<td>6 years at Belgian organizations; 1 / (60 + 1)</td><td>ULB</td>", page)

    def anne_card(self, records: list[tuple[str, str, dict]]) -> str:
        """Anne Example's card from a ULB topic search; each (key, quote, dates) is one record with one ULB claim."""
        facts = Source(id="org", kind="record", url="https://ror.org/01r9htc13", text="id: ror", content_hash="h0",
                       fetched_at=now())
        orgs.save(self.store, [OrgFacts(id="ror:01r9htc13", name="ULB", country_code="BE")], facts, replace=True)
        for key, text, dates in records:
            source = Source(id=f"src-{key}", kind="page", url=f"https://example.org/{key}", title=f"{key} page",
                            text=text, content_hash=f"h-{key}")
            person = self.store.resolve_person([Identifier(scheme="seed", value=key)], "Anne Example")
            self.store.upsert_claim(ClaimDraft(
                person_id=person.id, kind="affiliation", relation="worked_at", org_id="ror:01r9htc13",
                value=text.split(", ")[1], quote=text, quote_start=0, quote_end=len(text), source=source, **dates))
        client = self.client()
        page = client.get(f"/debug/searches/{self.run_search(client, 'q', Chips(topics=[Chip(text='ULB', origin='edited')]))}").text
        start = page.index("Anne Example</legend>")
        return page[start:page.index("</fieldset>", start)]

    def test_card_writes_only_the_years_a_source_lists(self):
        """A claim valid 2012 to 2023 whose source lists 2012 and 2023 shows '2012, 2023' and counts 2 years."""
        card = self.anne_card([("anne", "Anne Example, ULB", {"claim_date": "2023", "valid_from": "2012",
                                                               "valid_to": "2023", "years": [2012, 2023]})])
        self.assertIn("<td>2012, 2023</td>", card[card.index("Claims at Belgian organizations"):])
        self.assertIn("2 years at Belgian organizations", card)

    def test_card_marks_the_claims_that_scored(self):
        """The hit record's Belgian claim is marked scored; a same-name record's Belgian claim is shown unmarked."""
        card = self.anne_card([("anne", "Anne Example, ULB", {"claim_date": "2020"}),
                               ("anne-2", "Anne Example, Brussels university", {"claim_date": "2001"})])
        belgian = card[card.index("Claims at Belgian organizations"):card.index("Record 1:")]
        self.assertIn("<th>Scored</th>", belgian)
        self.assertIn("<td>2020</td><td>yes</td>", belgian)
        self.assertIn("<td>2001</td><td></td>", belgian)

    def test_card_score_line_names_every_part(self):
        """The score line names each part with its rank, the belgian_years part too."""
        card = self.anne_card([("anne", "Anne Example, ULB", {"claim_date": "2020"})])
        self.assertIn("Score 0.0328 from seeds #1, belgian_years #1. ", card)

    def test_the_results_page_names_people_and_shows_no_debug_content(self):
        """Staff see each person's name, never a score, chip, trace, record table, source fact or /debug link.

        The /debug page links to the search's debug page, which keeps that content and links to the source facts.
        """
        text = "Anne Example, ULB"
        source = Source(id="src", kind="page", url="https://example.org/ulb", title="ULB staff", text=text,
                        content_hash="h")
        person = self.store.resolve_person([Identifier(scheme="seed", value="anne")], "Anne Example")
        claim = self.store.upsert_claim(ClaimDraft(
            person_id=person.id, kind="affiliation", relation="worked_at", value="ULB", quote=text, quote_start=0,
            quote_end=len(text), source=source, claim_date="2018"))
        client = self.client()
        search_id = self.run_search(client, "q", Chips(topics=[Chip(text="ULB", origin="edited")]))
        staff = client.get(f"/searches/{search_id}").text
        self.assertIn("Anne Example", staff)
        for hidden in ("/debug", "Score", "Chips", "trace", "Record 1", "Request errors"):
            self.assertNotIn(hidden, staff)
        self.assertIn(f'href="/debug/searches/{search_id}"', client.get("/debug").text)
        debug = client.get(f"/debug/searches/{search_id}").text
        self.assertIn("Score 0.0164 from seeds #1", debug)
        self.assertIn(f'href="/debug/sources/src?claim={claim.id}"', debug)
        self.assertNotIn("content hash", client.get(f"/sources/src?claim={claim.id}").text)
        self.assertIn("content hash", client.get(f"/debug/sources/src?claim={claim.id}").text)
        self.assertEqual(client.get("/debug/sources/src?claim=nope").status_code, 404)

    def test_security_headers_on_every_response(self):
        """Pages, error pages and refusals carry the CSP and Referrer-Policy headers."""
        client = self.client()
        for response in (client.get("/"), client.get("/searches/nope"), client.post("/searches", data={"question": ""}),
                         client.get("/", headers={"host": "evil.example"}),
                         client.post("/searches", data={"question": "q"}, headers={"Origin": "http://evil.example"})):
            with self.subTest(status=response.status_code):
                self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(client.get("/static/fn.css").status_code, 200)

    def test_foreign_host_is_refused(self):
        client = self.client()
        self.assertEqual(client.get("/", headers={"host": "evil.example"}).status_code, 400)
        self.assertEqual(client.get("/", headers={"host": "localhost:8765"}).status_code, 200)
        self.assertEqual(client.get("/", headers={"host": "[::1]:8760"}).status_code, 200)

    def test_debug_page_shows_a_steps_log_lines(self):
        """A line logged inside a step is stored with the step and shown on the search's debug page."""
        client = self.client()
        search_id = self.create_search(client, "q")
        worker = client.app.state.worker

        def noisy(ctx: StepContext, inp: ParseIn) -> ParseOut:
            ctx.log.info("matched %s", "needle")
            return ParseOut(chips={})

        def run() -> None:
            ctx = StepContext(search_id=search_id, store=worker.store, llm=None, http=None, now=now, new_id=new_id,
                              log=logging.getLogger("fn.step"), settings=self.settings)
            run_step(ctx, "parse", noisy, ParseIn(question="q"))

        worker.pool.submit(run).result(timeout=10)
        self.assertIn("matched needle", client.get(f"/debug/searches/{search_id}").text)

    def test_cross_site_post_is_refused(self):
        """A POST from another origin or site creates no search; the browser's own form post (Origin null, same-origin) does."""
        client = self.client(StubLLM())
        refused = ({"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}, {"Origin": "http://evil.example"},
                   {"Origin": "null"}, {"Origin": "null", "Sec-Fetch-Site": "cross-site"},
                   {"Origin": "http://evil.example", "Sec-Fetch-Site": "same-origin"})
        for headers in refused:
            with self.subTest(headers=headers):
                response = client.post("/searches", data={"question": "q"}, headers=headers, follow_redirects=False)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.store.list_searches(10), [])
        browser_form = {"Origin": "null", "Sec-Fetch-Site": "same-origin"}
        for headers in ({"Origin": "http://127.0.0.1"}, browser_form, {}):
            with self.subTest(allowed=headers):
                response = client.post("/searches", data={"question": "q"}, headers=headers, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
        self.assertEqual(len(self.store.list_searches(10)), 3)

    def test_bad_questions_are_refused_and_create_no_search(self):
        """An empty, blank or 1,001-character question gets a message; 1,000 characters is accepted."""
        client = self.client(StubLLM())
        for question, message in (("", "Type a question"), ("  \n ", "Type a question"), ("q" * 1001, "1,000 characters")):
            with self.subTest(question=question[:5]):
                response = client.post("/searches", data={"question": question}, follow_redirects=False)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.text)
        self.assertEqual(self.store.list_searches(10), [])
        self.assertEqual(client.post("/searches", data={"question": "q" * 1000}, follow_redirects=False).status_code, 303)

    def test_question_runs_and_page_shows_chips_and_refresh_while_active(self):
        """POST /searches redirects to a page that refreshes while the search is active and shows its chips when done."""
        client = self.client(StubLLM(answer={"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "parsed"}]}))
        response = client.post("/searches", data={"question": "Who knows wind?"}, follow_redirects=False)
        search_id = response.headers["location"].rsplit("/", 1)[1]
        self.wait_ended(search_id)
        done = client.get(f"/debug/searches/{search_id}").text
        self.assertIn('value="wind"', done)
        self.assertNotIn("refresh", done)
        queued_id = self.create_search(client, "waiting")
        self.assertIn('http-equiv="refresh"', client.get(f"/searches/{queued_id}").text)

    def test_unhandled_error_is_stored_and_shows_its_traceback(self):
        """An exception in a route gives a 500 page with the redacted traceback, stored and listed on /debug/errors."""
        client = self.client()
        with mock.patch.object(Store, "list_searches", side_effect=RuntimeError(f"boom {SECRET}")), \
                self.assertLogs("fn.web", "ERROR"):
            response = client.get("/")
        self.assertEqual(response.status_code, 500)
        self.assertIn("Traceback (most recent call last)", response.text)
        self.assertIn("RuntimeError: boom ***", response.text)
        self.assertNotIn(SECRET, response.text)
        self.assertIn("frame-ancestors", response.headers["content-security-policy"])
        (stored,) = self.store.list_request_errors()
        self.assertEqual(stored.route, "GET /")
        self.assertIn("RuntimeError: boom ***", stored.traceback)
        self.assertIn("RuntimeError: boom ***", client.get("/debug/errors").text)

    def test_debug_page_lists_failed_step_traceback_and_payload_links(self):
        """The debug page shows a failed step's error and traceback, its call count and links to its payloads."""
        client = self.client(StubLLM(error=ValueError("model said no")))
        with self.assertLogs("fn.worker", "ERROR"):
            search_id = self.run_search(client, "Who knows wind?")
        (step,) = self.store.list_steps(search_id)
        page = client.get(f"/debug/searches/{search_id}").text
        for text in ("ValueError: model said no", "Traceback (most recent call last)", "1 calls", "failed",
                     f"/debug/steps/{step.id}/input.json", f"/debug/steps/{step.id}/calls"):
            self.assertIn(text, page)
        self.assertNotIn(f"/debug/steps/{step.id}/output.json", page)
        self.assertIn("Who knows wind?", client.get(f"/debug/steps/{step.id}/calls").text)
        self.assertEqual(client.get(f"/debug/steps/{step.id}/output.json").status_code, 404)
        self.assertEqual(client.get("/debug/steps/nope/input.json").status_code, 404)

    def test_payload_routes_return_the_stored_json(self):
        client = self.client(StubLLM(answer={"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "parsed"}]}))
        search_id = self.run_search(client, "Who knows wind?")
        step = self.store.list_steps(search_id)[0]
        inp, out = (client.get(f"/debug/steps/{step.id}/{name}.json") for name in ("input", "output"))
        self.assertEqual(inp.headers["content-type"], "application/json")
        self.assertEqual(inp.json(), {"question": "Who knows wind?"})
        self.assertEqual(out.json()["chips"]["topics"][0]["text"], "wind")
        self.assertIn("debug", client.get("/debug").text)
        self.assertIn(f"/debug/steps/{step.id}/output.json", client.get(f"/debug/searches/{search_id}").text)

    def test_rerun_with_edited_chips_skips_parse_and_links_back(self):
        """Edited chips start a new search with rerun_of, origin edited, no spans and a skipped parse step."""
        client = self.client()
        source_id = self.run_search(client, "Who knows wind?", Chips(topics=[Chip(text="wind", origin="parsed")]))
        response = client.post(f"/searches/{source_id}/rerun", follow_redirects=False, data={
            "topics": ["wind", " ", "offshore  wind", "wind"], "institutions": [""], "place": "Boston", "ask": "talk"})
        self.assertEqual(response.status_code, 303)
        new_id = response.headers["location"].rsplit("/", 1)[1]
        self.wait_ended(new_id)
        found = self.store.get_search(new_id)
        self.assertEqual((found.status, found.rerun_of, found.chips_origin), ("done", source_id, "edited"))
        self.assertEqual([(c.text, c.origin, c.span) for c in found.chips.topics],
                         [("wind", "edited", None), ("offshore wind", "edited", None)])
        self.assertEqual((found.chips.place.text, found.chips.place.origin, found.chips.ask), ("Boston", "edited", "talk"))
        self.assertEqual([(s.step, s.status) for s in self.store.list_steps(new_id)],
                         [("parse", "skipped"), ("lane:seeds", "ok"), ("lane:openalex", "ok"), ("resolve", "ok"),
                          ("rank", "ok"), ("save", "ok")])
        self.assertIn(source_id, client.get(f"/debug/searches/{new_id}").text)

    def test_rerun_accepts_no_chips_and_refuses_bad_ones(self):
        """Removing every chip is a valid rerun; an oversized chip, too many chips or an unknown ask is refused."""
        client = self.client()
        source_id = self.run_search(client, "Who knows wind?", Chips(topics=[Chip(text="wind", origin="parsed")]))
        url = f"/searches/{source_id}/rerun"
        empty = client.post(url, data={"topics": [""], "institutions": [""], "place": "", "ask": ""}, follow_redirects=False)
        self.assertEqual(empty.status_code, 303)
        self.wait_ended(empty.headers["location"].rsplit("/", 1)[1])
        self.assertEqual(self.store.get_search(empty.headers["location"].rsplit("/", 1)[1]).chips, Chips())
        before = len(self.store.list_searches(100))
        for data in ({"topics": ["x" * 201]}, {"institutions": [f"chip {i}" for i in range(21)]},
                     {"place": "p" * 201}, {"ask": "bogus"}):
            with self.subTest(data=list(data)):
                self.assertEqual(client.post(url, data=data, follow_redirects=False).status_code, 400)
        self.assertEqual(len(self.store.list_searches(100)), before)
        self.assertEqual(client.post("/searches/nope/rerun", data={}, follow_redirects=False).status_code, 404)

    def test_rerun_keeps_ref_and_kind_of_unedited_chips(self):
        """A chip or place the user did not change keeps its ref or kind on rerun; an edited one loses it."""
        client = self.client()
        chips = Chips(topics=[Chip(text="wind", origin="parsed", ref="oa:1")],
                      institutions=[Chip(text="MIT", origin="parsed", ref="ror:2")],
                      place=Place(text="Boston", origin="parsed", kind="metro"))
        source_id = self.run_search(client, "Who knows wind?", chips)
        url = f"/searches/{source_id}/rerun"
        data = {"topics": ["wind", "tides"], "institutions": ["MIT"], "place": "Boston", "ask": ""}
        for post, place_kind in ((data, "metro"), ({**data, "place": "Paris"}, None)):
            response = client.post(url, data=post, follow_redirects=False)
            rerun_id = response.headers["location"].rsplit("/", 1)[1]
            self.wait_ended(rerun_id)
            found = self.store.get_search(rerun_id).chips
            self.assertEqual([(c.text, c.ref) for c in found.topics], [("wind", "oa:1"), ("tides", None)])
            self.assertEqual([(c.text, c.ref) for c in found.institutions], [("MIT", "ror:2")])
            self.assertEqual(found.place.kind, place_kind)

    def test_serve_refuses_a_host_that_is_not_loopback(self):
        with mock.patch.dict(os.environ, {"FN_HOST": "0.0.0.0"}), mock.patch("fn.config.keychain", return_value=None), \
                mock.patch("uvicorn.run") as run, self.assertRaises(SystemExit):
            serve()
        run.assert_not_called()


class SeedCardsTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_seeded_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("the LLM must not be called")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        worker = app.state.worker
        chips = Chips(institutions=[Chip(text="MIT", origin="edited")])
        self.search_id = worker.pool.submit(worker.create_search, "Belgian faculty at MIT?", chips, "edited").result(10).id
        worker.submit(self.search_id).result(timeout=10)

    def test_card_lists_each_record_with_quote_source_date_and_the_belgian_claims(self):
        """Goemans' card holds his Francqui and BAEF records with quotes, source links, dates and score parts.

        Its Belgian section lists the claims at orgs with country code BE, each with the org's region and name language.
        """
        page = self.client.get(f"/debug/searches/{self.search_id}").text
        start = page.index("Michel Goemans</legend>")
        card = page[start:page.index("</fieldset>", start)]
        for text in ("Same name in 2 records, not merged", "Record 1: Michel Goemans, in Complete list of Francqui",
                     "Record 2: Michel Goemans, in BAEF Belgian Fellows", "Michel GOEMANS", "GOEMANS, Michel",
                     "Massachusetts Institute of Technology (matched)", "1987 (year, record_field)",
                     'href="https://www.francquifoundation.be/', "/trace?name=Michel+Goemans",
                     "<td>seeds</td><td>", "<td>1 / (60 + "):
            self.assertIn(text, card)
        belgian = card[card.index("Claims at Belgian organizations"):card.index("Record 1:")]
        for text in ("<td>UCLouvain</td><td>WAL</td><td>fr</td><td>affiliation affiliated_with</td>",
                     "<td>Fondation Francqui</td><td>BRU</td><td>fr</td><td>role fellow_of</td>",
                     "<td>Belgian American Educational Foundation</td><td>BRU</td><td>en</td><td>role fellow_of</td>"):
            self.assertIn(text, belgian)
        self.assertEqual(belgian.count("<tr>"), 4)
        link = card[card.index('href="/sources/') + 6:]
        response = self.client.get(link[:link.index('"')].replace("&amp;", "&"))
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.text, r'<mark id="quote">Michel GOEMANS[^<]*Massachusetts Institute of Technology')

    def test_trace_shows_where_a_name_went_in_every_step(self):
        """The trace lists the seed lane's verdict, the entry and the rank, and says where a name is absent."""
        page = self.client.get(f"/debug/searches/{self.search_id}/trace", params={"name": "michel GOEMANS"}).text
        for text in ("<td>fts</td><td>kept</td><td>fts rank", "<td>entry</td><td>kept</td><td>2 records",
                     "<td>rank</td><td>kept</td><td>new #"):
            self.assertIn(text, page)
        missing = self.client.get(f"/debug/searches/{self.search_id}/trace", params={"name": "Anne Deconinck"}).text
        self.assertIn('not present; query "MIT" OR "M.I.T." OR', missing.replace("&quot;", '"'))
        self.assertIn("Trace a person", self.client.get(f"/debug/searches/{self.search_id}/trace").text)


class ContractsV1Test(unittest.TestCase):
    def setUp(self):
        """A search stored by the code before migration 004: v1 step payloads and a candidate row with its old column."""
        self.settings = make_settings(self)
        old = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, old)
        for path in sorted(db.MIGRATIONS.glob("00[1-3]_*.sql")):
            shutil.copy(path, old / path.name)
        self.store = Store(self.settings.db_path)
        self.addCleanup(self.store.close)
        with mock.patch.object(db, "MIGRATIONS", old):
            self.store.migrate()
        self.store.create_search(Search(id="old", question="Who knows wind?", status="done", created_at=now(),
                                        code_sha=None, dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        person = self.store.resolve_person([Identifier(scheme="seed", value="anne")], "Anne Example")
        hit = {"person_id": person.id, "name_key": person.name_key, "lane": "seeds", "rank": 1, "score": 1.0,
               "matched_on": "wind", "claim_ids": []}
        label = {"tie": "belgian", "claim_ids": [], "checked": [], "rules_version": "2"}
        candidate = {"search_id": "old", "person_id": person.id, "person_ids": [person.id], "section": "new", "rank": 1,
                     "score": 1 / 61, "lane_ranks": {"seeds": 1}, "reason_claim_ids": [], "tie": label}
        outputs = [("lane:seeds", "LaneOut", {"lane": "seeds", "query": '"wind"', "total_seen": 1, "hits": [hit],
                                               "considered": []}),
                   ("rank", "RankOut", {"candidates": [candidate]})]
        for seq, (step, model, output) in enumerate(outputs, 1):
            run = StepRun(id=f"st{seq}", search_id="old", seq=seq, step=step, status="ok", started_at=now(),
                          ended_at=now(), input_model="LaneIn", output_model=model, contracts_version="1")
            self.store.start_step(run, "{}")
            self.store.finish_step(run, json.dumps(output))
        self.store.conn.execute("INSERT INTO candidates VALUES ('old', ?, ?, 'new', 1, ?, ?, '[]', ?)",
                                (person.id, json.dumps([person.id]), 1 / 61, '{"seeds": 1}', json.dumps(label)))
        self.assertEqual(self.store.migrate(), [4, 5])
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_an_old_candidate_row_gets_empty_score_parts_and_its_card_renders(self):
        """Migration 004 swaps the old column for score_parts_json, '[]' on old rows, and the results page shows the card."""
        columns = [r[1] for r in self.store.conn.execute("PRAGMA table_info(candidates)")]
        self.assertEqual(columns, ["search_id", "person_id", "person_ids_json", "section", "rank", "score",
                                   "lane_ranks_json", "reason_claim_ids_json", "score_parts_json"])
        (candidate,) = self.store.list_candidates("old")
        self.assertEqual(candidate.score_parts, [])
        response = self.client.get("/debug/searches/old")
        self.assertEqual(response.status_code, 200)
        for text in ("new #1 Anne Example", "Score 0.0164 from seeds #1", "No Belgian organization found in no source"):
            self.assertIn(text, response.text)
        self.assertNotIn("Score parts", response.text)
        self.assertIn("score parts not stored (contracts v1)", response.text)

    def test_the_trace_notes_v1_payloads_instead_of_parsing_them(self):
        """Each traced step stored under contracts v1 shows one note row; the page does not fail on the old rank payload."""
        response = self.client.get("/debug/searches/old/trace", params={"name": "Anne Example"})
        self.assertEqual(response.status_code, 200)
        for seq, step in ((1, "lane:seeds"), (2, "rank")):
            self.assertIn(f"<td>{seq}</td><td>{step}</td><td>-</td><td>-</td>"
                          "<td>stored under contracts v1, not shown</td>", response.text)
        self.assertEqual(self.store.list_request_errors(), [])


class LoggingTest(unittest.TestCase):
    def test_setup_logging_creates_var_dir_private(self):
        """On a fresh path, var and var/log are both 0700, before anything else creates them."""
        settings = make_settings(self)
        settings = settings.model_copy(update={"var_dir": settings.var_dir / "var"})
        root = logging.getLogger()
        saved, level = root.handlers[:], root.level

        def restore():
            for handler in root.handlers[:]:
                root.removeHandler(handler)
                handler.close()
            root.handlers[:], root.level = saved, level

        self.addCleanup(restore)
        setup_logging(settings)
        for path in (settings.var_dir, settings.var_dir / "log"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700, path)


class HtmlTest(unittest.TestCase):
    def test_text_and_attributes_are_escaped(self):
        out = h.p("<script>", h.a("x", href="javascript:alert(1)"), h.input(value='"><b>'), None, ["<i>", h.b("ok")])
        self.assertEqual(
            out, '<p>&lt;script&gt;<a href="#">x</a><input value="&quot;&gt;&lt;b&gt;">&lt;i&gt;<b>ok</b></p>')

    def test_urls_allow_http_https_and_relative_only(self):
        for url in ("javascript:alert(1)", " JaVaScRiPt:x", "java\tscript:x", "data:text/html,x", "vbscript:x", "http://[bad"):
            with self.subTest(url=url):
                self.assertEqual(safe_url(url), "#")
        for url in ("/a/b", "https://x.org/a", "http://x.org", "page.html", "#frag", "?q=1"):
            with self.subTest(url=url):
                self.assertEqual(safe_url(url), url)

    def test_protocol_relative_urls_are_refused(self):
        for url in ("//evil.example", " //evil.example/x", "/\\evil.example", "\\\\evil.example", "/\t/evil.example"):
            with self.subTest(url=url):
                self.assertEqual(safe_url(url), "#")

    def test_attribute_and_tag_names_are_checked(self):
        with self.assertRaises(ValueError):
            h.p(**{"onclick=x y": "1"})
        with self.assertRaises(ValueError):
            h.__getattr__("p onclick=x")()


if __name__ == "__main__":
    unittest.main()
