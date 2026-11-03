import hashlib
import json
import logging
import unittest
from datetime import UTC, datetime
from unittest import mock

import httpx
from pydantic import SecretStr

from fn import llm, net
from fn.contracts import Chip, Chips, LaneIn, LaneOut, Place, page_source
from fn.lanes import web
from fn.steps import StepContext, run_step
from fn.worker import Worker, new_id, now
from tests.helpers import FIXTURES, make_db, make_settings
from tests.test_extract import PageLLM, by_marker, mention, relation

RECORDED = FIXTURES / "http" / "web"
KEY = "px-parallel-0123456789"
EVENT = "https://events.example.org/belgium-6g-roundtable"
FACULTY = "https://example.edu/faculty/telecom"
NEWS = "https://news.example.org/flemish-researchers"
PLACE = Place(text="New York and New Jersey area", origin="edited", kind="metro")
NEW_YORK = Chips(topics=[Chip(text="telecom", origin="edited"), Chip(text="6G research", origin="edited")], place=PLACE)
FIELDS = json.loads((RECORDED / "v1_fields.json").read_text())
# What the stub model reads on each recorded page, by a marker of that page's text.
PEOPLE = {
    "Belgium 6G roundtable": [
        mention("Wim Doe", "Speakers include Wim Doe, professor of wireless networks at KU Leuven.",
                "professor of wireless networks",
                relation("works_at", "KU Leuven", "professor of wireless networks at KU Leuven")),
        mention("Anja Voorbeeld", "Moderator: Anja Voorbeeld, PhD, imec.", "Moderator",
                relation("works_at", "imec", "Anja Voorbeeld, PhD, imec")),
    ],
    "telecom group": [
        mention("Anja Voorbeeld", "Anja Voorbeeld leads the telecom group.", None,
                relation("studied_at", "Ghent University", "She studied at Ghent University.")),
        mention("Jan Peeters", "Jan Peeters leads the telecom group."),
    ],
    "Karel Proef": [mention("Dr. Karel Proef", "Karel Proef was born in Ghent.", None,
                            relation("born_in", "Ghent", "Karel Proef was born in Ghent."))],
}
# The schema each nested object of a request must follow, by parent schema and key.
NESTED = {
    "V1SearchRequest": {"advanced_settings": "AdvancedSearchSettings"},
    "V1ExtractRequest": {"advanced_settings": "AdvancedExtractSettings"},
    "AdvancedSearchSettings": {"fetch_policy": "FetchPolicy"},
    "AdvancedExtractSettings": {"fetch_policy": "FetchPolicy", "full_content": "FullContentSettings"},
}


def recorded(name: str) -> dict:
    return json.loads((RECORDED / f"{name}.json").read_text())


def chips(topics: list[str] = (), institutions: list[str] = (), place: Place | None = None) -> Chips:
    return Chips(topics=[Chip(text=t, origin="edited") for t in topics],
                 institutions=[Chip(text=i, origin="edited") for i in institutions], place=place)


def unknown(body: dict, schema: str, path: str = "") -> list[str]:
    """The dotted paths in body that the saved v1 schema does not name; a nested object checks against its own schema."""
    found = []
    for key, value in body.items():
        if key not in FIELDS[schema]:
            found.append(path + key)
        elif isinstance(value, dict):
            found += unknown(value, NESTED[schema][key], f"{path}{key}.")
    return found


class BodyTest(unittest.TestCase):
    def test_request_and_extract_body_name_only_fields_the_v1_schemas_define(self):
        """Parallel's v1 schema refuses unknown fields with a 422, so every key sent, nested ones too, must be saved.

        The helper itself must flag a stray key, at the top and inside advanced_settings.
        """
        extract = web.extract_body([EVENT], "objective")
        for body, schema in ((web.request(NEW_YORK), "V1SearchRequest"), (extract, "V1ExtractRequest")):
            self.assertEqual(unknown(body, schema), [])
        self.assertEqual(unknown({**web.request(NEW_YORK), "max_results": 5}, "V1SearchRequest"), ["max_results"])
        stray = {**extract, "advanced_settings": {**extract["advanced_settings"], "full_content": {"max_chars": 9}}}
        self.assertEqual(unknown(stray, "V1ExtractRequest"), ["advanced_settings.full_content.max_chars"])

    def test_request_gives_an_objective_sentence_and_a_query_per_topic_with_the_place_then_one_per_institution(self):
        """The topics' queries carry the place text, the institutions' do not, and at most 5 queries go out."""
        sentence = "People with a connection to Belgium"
        for given, objective, queries in (
            (NEW_YORK, f"{sentence} who work on telecom, 6G research in New York and New Jersey area",
             ["telecom New York and New Jersey area", "6G research New York and New Jersey area"]),
            (chips(institutions=["KU Leuven", "imec"]), f"{sentence} who have a link to KU Leuven, imec",
             ["KU Leuven", "imec"]),
            (chips(["6G"], ["KU Leuven"], PLACE),
             f"{sentence} who work on 6G and have a link to KU Leuven in New York and New Jersey area",
             ["6G New York and New Jersey area", "KU Leuven"]),
            (chips(place=PLACE), f"{sentence} in New York and New Jersey area", []),
            (chips([f"topic {i}" for i in range(4)], ["KU Leuven", "imec"]),
             f"{sentence} who work on topic 0, topic 1, topic 2, topic 3 and have a link to KU Leuven, imec",
             ["topic 0", "topic 1", "topic 2", "topic 3", "KU Leuven"]),
        ):
            with self.subTest(objective=objective):
                self.assertEqual(web.request(given), {"objective": objective, "search_queries": queries, "mode": "fast"})

    def test_extract_body_asks_for_12000_characters_of_full_content_and_a_20s_fetch(self):
        """Extract gets the URLs in the order given, the search objective, full content up to 12,000 characters and 20 s."""
        self.assertEqual(web.extract_body([EVENT, NEWS], "who"), {
            "urls": [EVENT, NEWS], "objective": "who",
            "advanced_settings": {"full_content": {"max_chars_per_result": 12000},
                                  "fetch_policy": {"timeout_seconds": 20}}})


class PageSourceTest(unittest.TestCase):
    def source(self, markdown: str, **kw):
        return page_source(kw.get("url", EVENT), "Title", markdown, kw.get("raw", {}), datetime(2026, 11, 3, tzinfo=UTC),
                           kw.get("date"))

    def test_page_source_turns_markdown_into_the_plain_text_a_reader_sees(self):
        """Link text stays and its URL goes; emphasis, heading markers and backslash escapes go; other text is kept."""
        for markdown, text in (
            ("[Wim Doe](https://x) is **professor**", "Wim Doe is professor"),
            ("# Roundtable\n\n## Speakers\nAnja *Voorbeeld* and _Karel Proef_",
             "Roundtable\n\nSpeakers\nAnja Voorbeeld and Karel Proef"),
            ("![a logo](logo.png) [page](https://en.example.org/wiki/Foo_(bar) \"title\") end", "a logo page end"),
            (r"price \*5\* snake\_case \# not a heading", "price *5* snake_case # not a heading"),
            ("**[Bold link](u)** and __strong__ and nested [a **b**](u)", "Bold link and strong and nested a b"),
            ("[![Wim Doe](https://events.example.org/wim.jpg)](https://events.example.org/speakers/wim-doe)", "Wim Doe"),
            ("***Wim Doe*** and **a *b*** and ___c___", "Wim Doe and a b and c"),
            ("snake_case_name, 2 * 3 * 4 and\n* a bullet", "snake_case_name, 2 * 3 * 4 and\n* a bullet"),
            ("Wim Doe’s  “lab”", "Wim Doe's \"lab\""),
        ):
            with self.subTest(markdown=markdown):
                self.assertEqual(self.source(markdown).text, text)

    def test_page_source_fills_a_vendor_page_source_and_its_id_follows_the_text(self):
        """The id hashes kind, URL and the plain text, so equal text is one source and changed text is a new one."""
        first = self.source("Wim **Doe**", raw={"k": 1}, date="2026-05-12")
        digest = hashlib.sha256(b"Wim Doe").hexdigest()
        self.assertEqual(
            (first.kind, first.url, first.title, first.text, first.content_hash, first.source_date, first.date_method,
             first.fetched_at, first.raw_json),
            ("vendor_page", EVENT, "Title", "Wim Doe", digest, "2026-05-12", "record_field",
             datetime(2026, 11, 3, tzinfo=UTC), '{"k": 1}'))
        self.assertEqual(first.id, hashlib.sha1(f"vendor_page\0{EVENT}\0{digest}".encode()).hexdigest())
        self.assertEqual(self.source("Wim *Doe*").id, first.id)
        self.assertNotEqual(self.source("Wim Doe, PhD").id, first.id)
        self.assertNotEqual(self.source("Wim Doe", url=FACULTY).id, first.id)
        undated = self.source("Wim Doe")
        self.assertEqual((undated.source_date, undated.date_method), (None, None))

    def test_page_source_puts_a_vendor_title_on_one_line(self):
        """A title keeps its words on one line with single spaces; an empty or blank title is None."""
        multi = page_source(EVENT, "\n   Blueprint for 6G\n   -  VUB", "Wim Doe", {}, datetime(2026, 11, 3, tzinfo=UTC), None)
        self.assertEqual(multi.title, "Blueprint for 6G - VUB")
        for blank in (None, "", " \n "):
            self.assertIsNone(page_source(EVENT, blank, "Wim Doe", {}, datetime(2026, 11, 3, tzinfo=UTC), None).title)


class WebLaneTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live", "parallel_api_key": SecretStr(KEY)})
        self.store = make_db(self, self.settings)
        self.search, self.extract = recorded("search"), recorded("extract")
        self.sent: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        return httpx.Response(200, json={"/v1/search": self.search, "/v1/extract": self.extract}[request.url.path])

    def run_lane(self, given: Chips = NEW_YORK, settings=None, handler=None) -> LaneOut:
        """Run lane:web as a step of a new search with the chips, over a mock transport; raises what the step raises."""
        settings = settings or self.settings
        http = net.Client(settings, httpx.MockTransport(handler or self.handle))
        worker = Worker(self.store, settings, llm=PageLLM(), http=http)
        self.addCleanup(worker.shutdown)
        self.search_id = worker.create_search("question", given, "edited").id
        ctx = StepContext(search_id=self.search_id, store=self.store, llm=PageLLM(), http=http, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        return run_step(ctx, "lane:web", web.run, LaneIn(search_id=self.search_id, chips=given))

    def step(self):
        return self.store.list_steps(self.search_id)[-1]

    def stored(self) -> dict[str, dict]:
        """The stored sources by URL, each as a dict; one URL stored twice keeps the later row."""
        rows = self.store.conn.execute("SELECT * FROM sources ORDER BY rowid").fetchall()
        return {r["url"]: dict(r) for r in rows}

    def pages(self, out: LaneOut, kept: bool = True) -> dict[str, str]:
        """The reason of each page row of the lane's output that was stored (kept) or dropped, by URL."""
        return {c.person_key: c.reason for c in out.considered if c.stage == "page" and c.kept == kept}

    def test_the_lane_posts_one_search_then_one_extract_for_each_unique_url_and_stores_one_source_each(self):
        """Search and Extract go out once each, signed, with the lane's bodies; the repeated URL is asked for once."""
        out = self.run_lane()
        search, extract = self.sent
        self.assertEqual([r.url.path for r in self.sent], ["/v1/search", "/v1/extract"])
        self.assertEqual(json.loads(search.content), web.request(NEW_YORK))
        objective = web.request(NEW_YORK)["objective"]
        self.assertEqual(json.loads(extract.content), web.extract_body([EVENT, FACULTY, NEWS], objective))
        self.assertEqual({r.headers["x-api-key"] for r in self.sent}, {KEY})
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM sources").fetchone()[0], 3)
        self.assertEqual({r["kind"] for r in self.stored().values()}, {"vendor_page"})
        self.assertEqual((out.lane, out.hits, out.total_seen, out.query),
                         ("web", [], 3, "telecom New York and New Jersey area; 6G research New York and New Jersey area"))
        self.assertEqual(self.step().status, "ok")

    def test_extract_gets_a_90s_read_timeout_and_search_the_default(self):
        """Extract fetches live pages, so its read timeout is 90 s; Search keeps net.py's 30 s."""
        self.run_lane()
        search, extract = self.sent
        self.assertEqual((search.extensions["timeout"]["read"], extract.extensions["timeout"]["read"]), (30.0, 90.0))

    def test_a_page_takes_its_text_from_extract_content_then_extract_excerpts_then_search_excerpts(self):
        """The text is the first of those with text, excerpts joined by blank lines, stored as plain text.

        The page Extract could not read falls back to its Search excerpts, and the considered row says so.
        """
        out = self.run_lane()
        sources = self.stored()
        event = ("Belgium 6G roundtable\n\nSpeakers include Wim Doe, professor of wireless networks at KU Leuven."
                 "\n\nModerator: Anja Voorbeeld, PhD, imec.")
        self.assertEqual(sources[EVENT]["text"], event)
        faculty = "Anja Voorbeeld leads the telecom group.\n\nShe studied at Ghent University."
        self.assertEqual(sources[FACULTY]["text"], faculty)
        self.assertEqual(sources[NEWS]["text"], "Karel Proef was born in Ghent.\n\nHe now works on 6G in Princeton.")
        self.assertEqual(self.pages(out), {
            EVENT: "rank 1, Belgium 6G roundtable: 132 characters from Extract full content",
            FACULTY: "rank 2, Telecom faculty: 73 characters from Extract excerpts",
            NEWS: "rank 3, Flemish researchers in New Jersey: 64 characters from Search excerpts; "
                  "Extract could not read it (fetch_failed)",
        })

    def test_a_full_content_with_no_plain_text_falls_back_to_the_next_candidate(self):
        """Markdown that strips to nothing, such as an image alone, does not win: the next source with text does.

        The same holds one step down, when the Extract excerpts are an image too.
        """
        banner = "![](https://events.example.org/banner.jpg)"
        self.extract["results"][0]["full_content"] = banner
        out = self.run_lane()
        speakers = "Speakers include Wim Doe, professor of wireless networks at KU Leuven."
        self.assertEqual(self.stored()[EVENT]["text"], speakers)
        self.assertEqual(self.pages(out)[EVENT],
                         f"rank 1, Belgium 6G roundtable: {len(speakers)} characters from Extract excerpts")
        self.extract["results"][0]["excerpts"] = [banner]
        searched = "Search says Wim Doe teaches at KU Leuven."
        self.search["results"][0]["excerpts"] = [searched]
        out = self.run_lane()
        self.assertEqual(self.stored()[EVENT]["text"], searched)
        self.assertEqual(self.pages(out)[EVENT],
                         f"rank 1, Belgium 6G roundtable: {len(searched)} characters from Search excerpts")
        self.assertEqual(self.step().status, "ok")

    def test_a_page_is_stored_with_its_title_its_publish_date_and_both_vendor_results(self):
        """The Extract title and date win over Search's; a page Extract failed on keeps Search's. raw_json keeps both."""
        self.search["results"][1]["publish_date"] = "2026-01-01"
        self.extract["results"][0]["title"] = "Roundtable on Belgium and 6G"
        self.run_lane()
        sources = self.stored()
        found = [(sources[u]["title"], sources[u]["source_date"], sources[u]["date_method"]) for u in (EVENT, FACULTY, NEWS)]
        self.assertEqual(found, [("Roundtable on Belgium and 6G", "2026-05-12", "record_field"),
                                 ("Telecom faculty", "2026-01-01", "record_field"),
                                 ("Flemish researchers in New Jersey", "2026-03-02", "record_field")])
        raw = json.loads(sources[EVENT]["raw_json"])
        self.assertEqual((raw["search"]["title"], raw["extract"]["title"]),
                         ("Belgium 6G roundtable", "Roundtable on Belgium and 6G"))
        self.assertEqual(json.loads(sources[NEWS]["raw_json"])["extract"]["error_type"], "fetch_failed")
        self.assertEqual(json.loads(sources[NEWS]["raw_json"])["search"]["publish_date"], "2026-03-02")

    def test_a_repeated_url_is_one_source_at_its_first_rank_with_a_dropped_row(self):
        """The fourth result repeats the first URL: one source, no second Extract URL, and a row naming the first rank."""
        out = self.run_lane()
        self.assertEqual(json.loads(self.sent[1].content)["urls"].count(EVENT), 1)
        dropped = [c for c in out.considered if not c.kept]
        self.assertEqual([(c.person_key, c.reason) for c in dropped], [(EVENT, "rank 4: same URL as rank 1")])
        self.assertTrue(self.pages(out)[EVENT].startswith("rank 1, "))

    def test_a_page_with_no_text_anywhere_is_skipped_with_a_note_and_the_others_are_stored(self):
        """No Extract content or excerpts and no Search excerpts: nothing stored for that page, one dropped row."""
        self.search["results"][2]["excerpts"] = []
        self.extract["results"][1] |= {"excerpts": [], "full_content": ""}
        self.search["results"][1]["excerpts"] = []
        out = self.run_lane()
        self.assertEqual(list(self.stored()), [EVENT])
        self.assertEqual(self.pages(out, kept=False), {
            NEWS: "rank 3: no text in Extract or Search; skipped; Extract could not read it (fetch_failed)",
            FACULTY: "rank 2: no text in Extract or Search; skipped",
            EVENT: "rank 4: same URL as rank 1",
        })
        self.assertEqual(self.step().status, "ok")

    def test_the_same_url_with_the_same_text_adds_no_source_and_with_changed_text_adds_one(self):
        """A rerun stores nothing new; a page whose text changed is a second source for the URL and raises nothing."""
        self.run_lane()
        self.run_lane()
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM sources").fetchone()[0], 3)
        self.extract["results"][0]["full_content"] += "\n\nA new paragraph."
        self.run_lane()
        rows = self.store.conn.execute("SELECT id, content_hash, text FROM sources WHERE url = ?", (EVENT,)).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r["id"] for r in rows}), 2)
        self.assertEqual(sum(r["text"].endswith("A new paragraph.") for r in rows), 1)
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM sources").fetchone()[0], 4)
        self.assertEqual(self.step().status, "ok")

    def test_a_full_content_of_12000_characters_may_be_truncated_and_a_shorter_one_is_not(self):
        """Extract does not say a page was cut, so a full_content that reaches the 12,000 limit gets a note."""
        text = ("Wim Doe teaches at KU Leuven. " * 500)[:12000]
        for length, noted in ((12000, True), (11999, False)):
            with self.subTest(length=length):
                self.extract["results"][0]["full_content"] = text[:length]
                reason = self.pages(self.run_lane())[EVENT]
                self.assertEqual("may be truncated at 12,000 characters" in reason, noted, reason)

    def test_without_a_parallel_key_the_lane_notes_it_and_warns_and_sends_nothing(self):
        """Live mode with no key: MissingKey gives one note and a warning in the step log, no hit, no call, step ok."""
        keyless = make_settings(self).model_copy(update={"http_mode": "live"})
        out = self.run_lane(settings=keyless)
        self.assertEqual(self.sent, [])
        self.assertEqual((out.hits, out.total_seen, len(out.considered)), ([], 0, 1))
        self.assertIn("PARALLEL_API_KEY", out.considered[0].reason)
        self.assertRegex(self.step().log, r"WARNING .*web lane skipped: no key for api\.parallel\.ai")
        self.assertEqual(self.step().status, "ok")
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM sources").fetchone()[0], 0)

    def test_without_a_topic_or_institution_chip_the_lane_notes_it_and_makes_no_call(self):
        """A place alone, or no chip at all, gives one query note and no call."""
        for given in (chips(place=PLACE), Chips()):
            with self.subTest(place=given.place):
                out = self.run_lane(given)
                self.assertEqual(self.sent, [])
                self.assertEqual((out.query, out.hits, [(c.stage, c.reason) for c in out.considered]),
                                 ("", [], [("query", web.NO_QUERY)]))
                self.assertEqual(self.step().status, "ok")

    def test_a_search_with_no_results_is_noted_and_extract_is_not_called(self):
        """An empty result list ends the lane after one call, with one note and no source."""
        self.search["results"] = []
        out = self.run_lane()
        self.assertEqual([r.url.path for r in self.sent], ["/v1/search"])
        self.assertEqual([c.reason for c in out.considered], ["Parallel Search returned no results; Extract not called"])
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM sources").fetchone()[0], 0)

    def test_a_refused_search_or_a_failed_extract_fails_the_step_with_the_vendor_message(self):
        """A 402 puts the response body in the error; an Extract that times out fails too; neither becomes a note."""
        def refuse(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={"error": {"message": "credit exhausted"}})

        def slow(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/search":
                return httpx.Response(200, json=self.search)
            raise httpx.ReadTimeout("read timed out")

        with self.assertRaises(net.HttpError) as refused:
            self.run_lane(handler=refuse)
        self.assertIn("credit exhausted", str(refused.exception))
        self.assertEqual(self.step().status, "error")
        with self.assertRaises(net.HttpError) as timed_out:
            self.run_lane(handler=slow)
        self.assertIn("ReadTimeout", str(timed_out.exception))
        self.assertEqual(self.step().status, "error")
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM sources").fetchone()[0], 0)

    def test_the_cost_function_prices_the_search_usage_and_an_unknown_sku_gives_none_and_a_warning(self):
        """sku_search costs $0.001 a count; Extract's SKU is not in the table, so its call has no cost and a warning.

        The step cost is then the Search call's alone, and the warning is in the step log.
        """
        self.run_lane()
        step = self.step()
        self.assertEqual([c.cost_usd for c in self.store.list_calls(step.id)], [0.001, None])
        self.assertEqual(step.cost_usd, 0.001)
        self.assertIn("sku_extract_invented", step.log)
        with self.assertLogs("fn.lanes.web", "WARNING") as logged:
            self.assertIsNone(web.usage_cost(json.dumps(self.extract).encode()))
        self.assertIn("sku_extract_invented", logged.output[0])
        self.assertEqual(web.usage_cost(json.dumps(self.search).encode()), 0.001)

    def test_a_priced_sku_costs_its_price_times_its_count_and_no_usage_has_no_cost(self):
        """Each SKU adds price times count; one unknown SKU among known ones still gives None; no usage gives None."""
        with mock.patch.dict(web.PRICES, {"sku_extract_invented": 0.002}):
            self.run_lane()
            step = self.step()
            costs = [c.cost_usd for c in self.store.list_calls(step.id)]
            self.assertAlmostEqual(costs[1], 0.006)
            self.assertAlmostEqual(step.cost_usd, 0.007)
            mixed = {"usage": [{"name": "sku_search", "count": 2}, {"name": "sku_other", "count": 1}]}
            with self.assertLogs("fn.lanes.web", "WARNING"):
                self.assertIsNone(web.usage_cost(json.dumps(mixed).encode()))
            for body in ({"usage": []}, {"usage": None}, {}):
                self.assertIsNone(web.usage_cost(json.dumps(body).encode()))


class WebPeopleTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live", "parallel_api_key": SecretStr(KEY)})
        self.store = make_db(self, self.settings)
        self.search, self.extract = recorded("search"), recorded("extract")
        self.llm = PageLLM(by_marker(PEOPLE))

    def handle(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"/v1/search": self.search, "/v1/extract": self.extract}[request.url.path])

    def run_lane(self) -> LaneOut:
        """Run lane:web with self.llm as a step of a new search with the New York chips; keeps the step as self.step."""
        http = net.Client(self.settings, httpx.MockTransport(self.handle))
        worker = Worker(self.store, self.settings, llm=self.llm, http=http)
        self.addCleanup(worker.shutdown)
        search_id = worker.create_search("question", NEW_YORK, "edited").id
        ctx = StepContext(search_id=search_id, store=self.store, llm=self.llm, http=http, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        out = run_step(ctx, "lane:web", web.run, LaneIn(search_id=search_id, chips=NEW_YORK))
        self.step = self.store.list_steps(search_id)[-1]
        return out

    def claims(self) -> set[tuple]:
        """Every stored claim as (person, page URL, kind, relation, org id, value, offsets, date, latitude)."""
        rows = self.store.conn.execute(
            "SELECT p.display_name, s.url, c.kind, c.relation, c.org_id, c.value, c.quote_start, c.quote_end, "
            "c.claim_date, c.lat FROM claims c JOIN persons p ON p.id = c.person_id "
            "JOIN sources s ON s.id = c.source_id")
        return {tuple(r) for r in rows}

    def count(self, table: str) -> int:
        return self.store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def names(self, out: LaneOut) -> list[str]:
        persons = self.store.get_persons([h.person_id for h in out.hits])
        return [persons[h.person_id].display_name for h in out.hits]

    def test_every_person_a_page_names_is_a_hit_with_the_exact_claims_its_quotes_give(self):
        """Each kept mention is a person with a role claim and a claim per kept relation, at offsets in the stored text.

        The event page's markdown link and bold are gone from the stored text, so its quotes match. Hits run in page
        order, then mention order; every mention, kept or dropped, has a row.
        """
        out = self.run_lane()
        self.assertEqual(self.claims(), {
            ("Wim Doe", EVENT, "role", None, None, "professor of wireless networks", 23, 93, None, None),
            ("Wim Doe", EVENT, "affiliation", "works_at", "ror:05f950310", "KU Leuven", 49, 92, None, None),
            ("Anja Voorbeeld", EVENT, "role", None, None, "Moderator", 95, 132, None, None),
            ("Anja Voorbeeld", EVENT, "affiliation", "works_at", "ror:02kcbn207", "imec", 106, 131, None, None),
            ("Anja Voorbeeld", FACULTY, "role", None, None, "Telecom faculty", 0, 39, None, None),
            ("Anja Voorbeeld", FACULTY, "affiliation", "studied_at", "ror:00cv9y106", "Ghent University", 41, 73, None,
             None),
            ("Karel Proef", NEWS, "role", None, None, "Flemish researchers in New Jersey", 0, 30, None, None),
            ("Karel Proef", NEWS, "location", "born_in", None, "Ghent", 0, 30, None, None),
        })
        self.assertEqual(self.count("persons"), 4)
        event, faculty, news = (f"page 1, Belgium 6G roundtable, {EVENT}", f"page 2, Telecom faculty, {FACULTY}",
                                f"page 3, Flemish researchers in New Jersey, {NEWS}")
        self.assertEqual([(h.rank, h.lane, h.matched_on) for h in out.hits],
                         [(1, "web", event), (2, "web", event), (3, "web", faculty), (4, "web", news)])
        self.assertEqual(self.names(out), ["Wim Doe", "Anja Voorbeeld", "Anja Voorbeeld", "Karel Proef"])
        for hit in out.hits:
            self.assertCountEqual(hit.claim_ids, [c.id for c in self.store.claims_of([hit.person_id])])
        self.assertEqual([(c.person_key, c.kept, c.reason) for c in out.considered if c.stage == "mention"], [
            (f"{EVENT}#wim doe", True,
             f"{event}: role 'professor of wireless networks'; works_at 'KU Leuven' ror:05f950310"),
            (f"{EVENT}#anja voorbeeld", True, f"{event}: role 'Moderator'; works_at 'imec' ror:02kcbn207"),
            (f"{FACULTY}#jan peeters", False, "quote not found: 'Jan Peeters leads the telecom group.'"),
            (f"{FACULTY}#anja voorbeeld", True,
             f"{faculty}: role 'Telecom faculty'; studied_at 'Ghent University' ror:00cv9y106"),
            (f"{NEWS}#karel proef", True, f"{news}: role 'Flemish researchers in New Jersey'; born_in 'Ghent'"),
        ])
        self.assertEqual(len(self.llm.pages), 3)
        self.assertEqual(self.step.status, "ok")

    def test_a_rerun_of_the_lane_adds_no_person_source_or_claim(self):
        """Running the lane again over the same pages adds no row.

        The same pages and answers give the same sources, mention identities and claim ids.
        """
        first = self.run_lane()
        tables = ("persons", "person_identifiers", "sources", "claims")
        before = [self.count(t) for t in tables]
        second = self.run_lane()
        self.assertEqual([self.count(t) for t in tables], before)
        self.assertEqual([(h.person_id, h.claim_ids) for h in second.hits],
                         [(h.person_id, h.claim_ids) for h in first.hits])

    def test_changed_page_text_is_a_new_source_and_the_same_mention_person(self):
        """A page whose text changed is a new source, and its people stay the same persons.

        The persons then hold claims on both versions of the page.
        """
        first = self.run_lane()
        self.extract["results"][0]["full_content"] += "\n\nA new paragraph."
        second = self.run_lane()
        self.assertEqual((self.count("persons"), self.count("sources")), (4, 4))
        self.assertEqual(second.hits[0].person_id, first.hits[0].person_id)
        wim = self.store.claims_of([first.hits[0].person_id])
        self.assertEqual(len({c.source_id for c in wim}), 2)
        self.assertEqual(len(wim), 4)

    def test_a_person_named_twice_on_a_page_is_one_hit_with_the_claims_of_both_mentions(self):
        """Two mentions of one name on one page are one person and one hit.

        The hit lists the claims of both mentions and keeps the first mention's rank.
        """
        self.extract["results"][0]["full_content"] = ("# Belgium 6G roundtable\n\nWim Doe opened the day.\n\n"
                                                      "Later, Wim Doe, professor at KU Leuven, spoke.")
        self.llm = PageLLM(by_marker({"Belgium 6G roundtable": [
            mention("Wim Doe", "Wim Doe opened the day.", "host"),
            mention("Wim Doe", "Wim Doe, professor at KU Leuven", "professor",
                    relation("works_at", "KU Leuven", "professor at KU Leuven")),
        ]}))
        out = self.run_lane()
        (hit,) = out.hits
        self.assertEqual((hit.rank, self.count("persons")), (1, 1))
        self.assertEqual(self.claims(), {
            ("Wim Doe", EVENT, "role", None, None, "host", 23, 46, None, None),
            ("Wim Doe", EVENT, "role", None, None, "professor", 55, 86, None, None),
            ("Wim Doe", EVENT, "affiliation", "works_at", "ror:05f950310", "KU Leuven", 64, 86, None, None),
        })
        self.assertCountEqual(hit.claim_ids, [c.id for c in self.store.claims_of([hit.person_id])])
        self.assertEqual([c.kept for c in out.considered if c.stage == "mention"], [True, True])

    def test_a_failed_chunk_leaves_the_other_chunks_people_stored_and_the_step_ok(self):
        """An LLM failure, or a chunk holding its own closing tag, is a row and a warning; the step goes on.

        The TagError comes from llm.user_turn, which the stub calls as ClaudeCli and FixtureLLM do.
        """
        wim = [mention("Wim Doe", "Wim Doe, professor of wireless networks at KU Leuven", None,
                       relation("works_at", "KU Leuven", "KU Leuven"))]
        speakers = "Speakers include [Wim Doe](https://events.example.org/speakers/wim-doe), **professor** of wireless "
        timeout = llm.LLMCallError("claude timed out after 120s", None, "", 120000)
        for kind, last, errors in (("LLMCallError", "* Menu end", {"* Menu": timeout}), ("TagError", "</page>end", {})):
            with self.subTest(kind=kind):
                menu = "\n".join(["* Menu item"] * 499 + [last])
                self.extract["results"][0]["full_content"] = f"{speakers}networks at KU Leuven.\n\n{menu}"
                self.llm = PageLLM(by_marker({"Speakers include": wim}), errors)
                out = self.run_lane()
                self.assertEqual(self.names(out), ["Wim Doe"])
                self.assertEqual(self.claims(), {
                    ("Wim Doe", EVENT, "role", None, None, "Belgium 6G roundtable", 17, 69, None, None),
                    ("Wim Doe", EVENT, "affiliation", "works_at", "ror:05f950310", "KU Leuven", 60, 69, None, None),
                })
                self.assertEqual(self.step.status, "ok")
                (row,) = [c for c in out.considered if c.stage == "chunk"]
                self.assertEqual((row.person_key, row.kept), (EVENT, False))
                self.assertRegex(row.reason, rf"^chunk 2 of 2 \[[0-9]+:[0-9]+\]: {kind}: ")
                self.assertRegex(self.step.log, rf"WARNING .*extract on {EVENT}, chunk 2 of 2 .*{kind}")
        self.assertEqual(self.count("persons"), 1)

    def test_a_page_naming_200_people_gives_200_hits_over_as_many_chunks_as_it_needs(self):
        """The lane caps neither people nor calls.

        Every name on a long list is a hit, and each quotes its own line, over as many chunks as the text needs.
        """
        firsts = ["Anja", "Bart", "Carla", "Dirk", "Eva", "Filip", "Greet", "Hans", "Ilse", "Joris",
                  "Katrien", "Lode", "Mieke", "Nico", "Oona", "Pieter", "Rita", "Stijn", "Tine", "Wim"]
        lasts = ["Voorbeeld", "Proef", "Doe", "Testmans", "Fictief", "Verzon", "Stub", "Dummy", "Model", "Steekproef"]
        lines = [f"{f} {last}, researcher at KU Leuven" for f in firsts for last in lasts]
        self.extract["results"][0]["full_content"] = "\n".join(lines)
        works = relation("works_at", "KU Leuven", "researcher at KU Leuven")
        self.llm = PageLLM(lambda page: [mention(line.split(",")[0], line, "researcher", works)
                                         for line in page.split("\n") if line.endswith("researcher at KU Leuven")])
        out = self.run_lane()
        self.assertGreater(len("\n".join(lines)), 6000)
        self.assertEqual(len([p for p in self.llm.pages if "researcher" in p]), 2)
        self.assertEqual(self.names(out), [line.split(",")[0] for line in lines])
        claims = self.store.claims_of([h.person_id for h in out.hits])
        self.assertEqual(len({c.quote_start for c in claims if c.kind == "affiliation"}), 200)

    def test_without_an_llm_the_lane_fails_before_any_call(self):
        """A lane that cannot read people fails its step at once, like the parse step, and sends nothing."""
        self.llm, sent = None, []
        self.handle = lambda request: sent.append(request) or httpx.Response(500)
        with self.assertRaisesRegex(RuntimeError, "needs an HTTP client and an LLM"):
            self.run_lane()
        self.assertEqual(sent, [])

if __name__ == "__main__":
    unittest.main()
