import logging
import unittest
from unittest import mock

import httpx

from fn import net, usindex
from fn.contracts import IndexIn
from fn.lanes import openalex
from fn.steps import StepContext, run_step
from fn.worker import Worker, new_id, now
from tests.helpers import make_db, make_settings

LEUVEN = {"id": "https://openalex.org/I9000001", "ror": "https://ror.org/00fict001",
          "display_name": "Fictional University", "country_code": "BE"}
BOSTON = {"id": "https://openalex.org/I9000002", "ror": "https://ror.org/00fict002",
          "display_name": "Elsewhere Institute", "country_code": "US"}
GEO = {BOSTON["id"]: {"city": "Boston", "region": "Massachusetts", "country": "United States",
                      "latitude": 42.36, "longitude": -71.06}}


def author(number: int, name: str | None = "Test Author", be_years=(2015, 2018), **fields) -> dict:
    """A made-up OpenAlex author in the documented shape: Belgian years, a US last known institution, topics."""
    record = {"id": f"https://openalex.org/A90000{number:02d}", "display_name": name, "orcid": None,
              "updated_date": "2026-11-01", "last_known_institutions": [BOSTON], "works_count": 40,
              "affiliations": [{"institution": LEUVEN, "years": list(be_years)},
                               {"institution": BOSTON, "years": [2019, 2024]}],
              "topics": [{"id": f"https://openalex.org/T{i}", "display_name": f"Topic {i}", "count": 9 - i}
                         for i in range(7)],
              "counts_by_year": [{"year": 2024, "works_count": 3, "cited_by_count": 5},
                                 {"year": 2016, "works_count": 2, "cited_by_count": 1},
                                 {"year": 2020, "works_count": 0, "cited_by_count": 4}]}
    return {k: v for k, v in (record | fields).items() if v is not None or k == "orcid"}


def page(*results: dict, next_cursor: str | None = None) -> dict:
    return {"meta": {"count": len(results), "next_cursor": next_cursor}, "results": list(results)}


class Served:
    """Serves made-up author pages by cursor and institution records; logs requests; credits left go in a header."""

    def __init__(self, pages: dict[str, dict | int], left: dict[str, int] | None = None):
        self.pages, self.left, self.requests = pages, left or {}, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/institutions":
            ids = request.url.params["filter"].split(":", 1)[1].split("|")
            results = [{"id": f"https://openalex.org/{i}", "display_name": i, "geo": GEO[f"https://openalex.org/{i}"]}
                       for i in ids if f"https://openalex.org/{i}" in GEO]
            return httpx.Response(200, json=page(*results))
        cursor = request.url.params["cursor"]
        served = self.pages[cursor]
        if isinstance(served, int):
            return httpx.Response(served, json={"error": "made-up refusal"})
        headers = {"X-RateLimit-Remaining": str(self.left[cursor])} if cursor in self.left else {}
        return httpx.Response(200, json=served, headers=headers)

    def paths(self, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == path]


class UsIndexTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self).model_copy(update={"http_mode": "live"})
        self.store = make_db(self, self.settings)

    def index(self, served: Served, settings=None, http=None):
        """Run the index step against served pages (or http); returns its output, or raises what it raised."""
        settings = settings or self.settings
        http = http or net.Client(self.settings, httpx.MockTransport(served), sleep=lambda _: None)
        worker = Worker(self.store, settings, llm=None, http=http)
        self.addCleanup(worker.shutdown)
        ctx = StepContext(search_id=worker.create_search("fn-index", kind="job").id, store=self.store, llm=None,
                          http=http, now=now, new_id=new_id, log=logging.getLogger("fn.step"), settings=settings)
        return run_step(ctx, "index", usindex.run, IndexIn())

    def counts(self) -> tuple[int, int, int]:
        return tuple(self.store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("persons", "sources", "claims"))

    def claims_of(self, author_id: str) -> list:
        (person,) = self.store.person_ids_by_identifier("openalex", [author_id]).values()
        return self.store.claims_of([person])

    def test_an_author_is_stored_once_with_affiliations_a_location_and_dated_topics(self):
        """A stored author has an affiliation claim per affiliation, a location and five topics dated by the last year with works.

        A second author with no topics or counts is stored with its affiliations and no topic claims.
        """
        bare = author(2, "Test Bare", topics=None, counts_by_year=None)
        out = self.index(Served({"*": page(author(1), bare)}))
        self.assertEqual((out.pages, out.authors, out.new, out.skipped, out.malformed), (1, 2, 2, 0, 0))
        claims = self.claims_of("A9000001")
        kinds = sorted(c.kind for c in claims)
        self.assertEqual(kinds, ["affiliation"] * 2 + ["location"] + ["topic"] * 5)
        topics = [c for c in claims if c.kind == "topic"]
        self.assertEqual(sorted(c.value for c in topics), [f"Topic {i}" for i in range(5)])
        self.assertEqual({(c.claim_date, c.date_precision, tuple(c.years)) for c in topics}, {("2024", "year", ())})
        self.assertEqual(sorted(c.kind for c in self.claims_of("A9000002")), ["affiliation"] * 2 + ["location"])

    def test_a_rerun_adds_no_person_source_or_claim(self):
        """The same pages run twice leave the persons, sources and claims as the first run made them."""
        served = Served({"*": page(author(1), author(2, "Test Other"))})
        self.index(served)
        before = self.counts()
        out = self.index(served)
        self.assertEqual((self.counts(), out.new, out.authors), (before, 0, 2))

    def test_institutions_are_fetched_once_across_pages(self):
        """Two pages with the same last known institution make one institution call."""
        served = Served({"*": page(author(1), next_cursor="c2"), "c2": page(author(2, "Test Other"))})
        out = self.index(served)
        self.assertEqual((out.pages, out.authors, len(served.paths("/institutions"))), (2, 2, 1))

    def test_credits_under_the_reserve_stop_the_job_after_the_page(self):
        """2,999 credits left after page one store its authors and stop before page two."""
        served = Served({"*": page(author(1), next_cursor="c2"), "c2": page(author(2, "Test Other"))}, left={"*": 2999})
        out = self.index(served)
        self.assertEqual((out.pages, out.authors, out.stopped), (1, 1, "2999 credits left, under the reserve of 3000"))
        self.assertEqual(len(served.paths("/authors")), 1)

    def test_the_reserve_is_the_one_in_the_openalex_module(self):
        """The credit reserve fn-index stops at is openalex.RESERVE, the one fn-enrich shares."""
        served = Served({"*": page(author(1), next_cursor="c2"), "c2": page(author(2, "Test Other"))}, left={"*": 9000})
        with mock.patch.object(openalex, "RESERVE", 9500):
            out = self.index(served)
        self.assertEqual((out.pages, len(served.paths("/authors"))), (1, 1))

    def test_a_429_stops_the_job_and_keeps_the_authors_stored_before_it(self):
        """A refusal on page two ends the run with its message; page one's author stays stored."""
        served = Served({"*": page(author(1), next_cursor="c2"), "c2": 429}, left={"*": 9000})
        out = self.index(served)
        self.assertEqual((out.pages, out.authors), (1, 1))
        self.assertIn("429", out.stopped)
        self.assertEqual(len(self.claims_of("A9000001")), 8)

    def test_another_error_raises(self):
        """A 500 on page two is not a stop; the step raises it."""
        with self.assertRaises(net.HttpError):
            self.index(Served({"*": page(author(1), next_cursor="c2"), "c2": 500}))

    def test_too_many_works_a_missing_name_and_a_repeated_id_are_counted_and_not_stored(self):
        """An author with 1,001 works or a repeated id is skipped, a result without a name is malformed."""
        served = Served({"*": page(author(1), author(2, "Test Merged", works_count=1001), author(3, None),
                                   {"display_name": "No Id"}, next_cursor="c2"),
                         "c2": page(author(1))})
        out = self.index(served)
        self.assertEqual((out.authors, out.new, out.skipped, out.malformed), (1, 1, 2, 2))
        self.assertEqual(self.store.person_ids_by_identifier("openalex", ["A9000002", "A9000003"]), {})

    def test_an_author_with_one_belgian_year_is_skipped_and_one_with_two_is_stored(self):
        """Belgian affiliations that cover one year are left out and counted; two distinct years are stored."""
        one = author(1, "Test One", be_years=(2017,))
        two = author(2, "Test Two", be_years=(2017, 2018))
        split = author(3, "Test Split", be_years=(2017,), affiliations=[
            {"institution": LEUVEN, "years": [2017]}, {"institution": {**LEUVEN, "id": "https://openalex.org/I9000009"},
                                                       "years": [2017, 2018]}])
        out = self.index(Served({"*": page(one, two, split)}))
        self.assertEqual((out.authors, out.skipped), (2, 1))
        self.assertEqual(self.store.person_ids_by_identifier("openalex", ["A9000001"]), {})

    def test_an_empty_first_page_gives_zeros(self):
        out = self.index(Served({"*": page()}))
        self.assertEqual((out.pages, out.authors, out.new, out.skipped, out.malformed, out.stopped), (0, 0, 0, 0, 0, ""))

    def test_live_mode_without_a_key_or_prefer_mode_raises_before_any_call(self):
        """A missing key in live mode, prefer mode and a missing client each raise with no request sent."""
        served = Served({"*": page(author(1))})
        keyless = self.settings.model_copy(update={"openalex_api_key": None})
        prefer = self.settings.model_copy(update={"http_mode": "prefer"})
        for settings in (keyless, prefer):
            with self.subTest(mode=settings.http_mode), self.assertRaises(RuntimeError):
                self.index(served, settings)
        self.assertEqual(served.requests, [])

    def test_a_replay_answer_without_the_header_runs_to_the_end(self):
        """In replay mode no key is needed, and pages without the rate-limit header are all read."""
        served = Served({"*": page(author(1), next_cursor="c2"), "c2": page(author(2, "Test Other"))})
        replay = self.settings.model_copy(update={"http_mode": "replay", "openalex_api_key": None})
        out = self.index(served, replay)
        self.assertEqual((out.pages, out.authors, out.stopped), (2, 2, ""))


if __name__ == "__main__":
    unittest.main()
