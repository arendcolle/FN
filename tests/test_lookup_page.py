import re
import threading
import unittest
from datetime import UTC, date, datetime, timedelta
from html import unescape
from unittest import mock

from fastapi.testclient import TestClient

from fn import deepen, network, present
from fn.contracts import ClaimDraft, Identifier, Lookup, Search, Source
from fn.present import ADDED, NOT_SURE, NOTHING, STOPPED
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

AT = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)
TODAY = date(2026, 11, 17)
DAY = "17 November 2026"
LOOKUP_JS = '<script src="/static/lookup.js" defer></script>'
REFRESH = '<meta http-equiv="refresh" content="2">'


class LookupPageTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False,
                                 follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.n = 0

    def person(self, name: str, key: str, member: bool = False) -> str:
        found = self.store.resolve_person([Identifier(scheme="seed", value=key)], name).id
        if member:
            network.add(self.store, [found], via="search", now=AT - timedelta(days=2))
        return found

    def found(self, person_id: str, kind: str, value: str, at: datetime = AT - timedelta(milliseconds=5),
              read: bool = True, **fields) -> str:
        """A claim from a page a lookup read (read) or an older page, first stored at at."""
        self.n += 1
        text = f"{value} of {person_id} {self.n}"
        source = Source(id=f"src-{self.n}", kind="page", url=f"https://example.org/{self.n}", title="Example page", text=text,
                        content_hash=f"h-{self.n}", raw_json='{"lookup": {"truncated": false}}' if read else "{}")
        draft = ClaimDraft(person_id=person_id, kind=kind, value=value, quote=text, quote_start=0, quote_end=len(text),
                           source=source, **fields)
        return self.store.upsert_claim(draft, at).id

    def row(self, person_id: str, verdict: str, at: datetime = AT) -> None:
        with self.store.tx():
            self.store.save_lookup(Lookup(person_id=person_id, kind="web_person", verdict=verdict, detail=""), at)

    def job(self, person_id: str, status: str, created: datetime = AT - timedelta(minutes=1)) -> None:
        self.store.create_search(Search(id=f"job-{self.n}-{status}", kind="job", question=deepen.job_question(person_id),
                                        status=status, created_at=created, code_sha=None, dirty=False, llm_mode="replay",
                                        settings_json="{}", boot_id="b"))
        self.n += 1

    def view(self, person_id: str, records: list[str] | None = None):
        return present.lookup_view(self.store, records or [person_id], person_id, TODAY)

    def page(self, person_id: str, **params) -> str:
        response = self.client.get(f"/people/{person_id}", params=params)
        self.assertEqual(response.status_code, 200)
        return unescape(response.text)

    def box(self, html: str) -> str:
        return re.search(r'<div class="[^"]*" id="lookup".*?</div>', html, re.DOTALL).group(0)

    def test_the_state_and_words_follow_the_job_and_the_newest_row(self):
        """Each state of the table holds for its case: the first line that applies decides."""
        cases = [
            ("no row and no job", [], "before", None),
            ("a queued job", [("job", "queued"), ("row", "nothing_new")], "running", None),
            ("a running job", [("job", "running")], "running", None),
            ("a job that failed and no row since", [("job", "failed")], "stopped", STOPPED),
            ("an interrupted job", [("job", "interrupted")], "stopped", STOPPED),
            ("a job that ended and no recording", [("job", "done"), ("old", "nothing_new")], "stopped", STOPPED),
            ("a failed job older than a row", [("job", "failed"), ("row", "nothing_new")], "after",
             NOTHING.format(date=DAY)),
            ("a failed row", [("row", "failed")], "stopped", STOPPED),
            ("nothing new", [("row", "nothing_new")], "after", NOTHING.format(date=DAY)),
            ("not sure", [("row", "not_sure")], "after", NOT_SURE.format(date=DAY)),
            ("an added row without a part", [("row", "added")], "after", NOTHING.format(date=DAY)),
        ]
        for name, steps, state, words in cases:
            with self.subTest(name):
                self.setUp()
                ada = self.person("Ada Voorbeeld", "ada")
                for kind, what in steps:
                    if kind == "job":
                        self.job(ada, what)
                    else:
                        self.row(ada, what, AT - timedelta(days=30) if kind == "old" else AT)
                self.assertEqual((self.view(ada).state, self.view(ada).words), (state, words))

    def test_an_added_row_names_the_parts_its_claims_made_in_the_order_of_the_words(self):
        """Claims first stored 5 ms before the row make parts; older, later, rejected and unread ones make none."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.found(ada, "role", "Professor of physics")
        self.found(ada, "location", "Bethesda, MD", relation="lives_in")
        self.found(ada, "email", "ada@example.org")
        self.found(ada, "phone", "+1 301 555 0100")
        self.found(ada, "email", "old@example.org", at=AT - timedelta(seconds=61))
        self.found(ada, "phone", "+1 301 555 0199", at=AT + timedelta(seconds=1))
        self.found(ada, "location", "Elsewhere", read=False)
        gone = self.found(ada, "location", "Nowhere")
        network.reject_claim(self.store, gone, now=now())
        self.row(ada, "added")
        self.assertEqual(self.view(ada).words,
                         ADDED.format(date=DAY, parts="a current job, a place, an email address and a phone number"))

    def test_recent_facts_are_counted_once_each_and_a_topic_alone_adds_nothing(self):
        """One recent fact reads 'a recent fact', three read '3 recent facts', and an undated topic is no part."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.found(ada, "topic", "Wind energy")
        self.row(ada, "added")
        self.assertEqual(self.view(ada).words, NOTHING.format(date=DAY))
        for n, words in enumerate(["a recent fact", "2 recent facts", "3 recent facts"]):
            self.found(ada, "topic", f"Topic {n}", claim_date="2026", date_precision="year", date_method="stated_in_quote")
            self.assertEqual(self.view(ada).words, ADDED.format(date=DAY, parts=words))

    def test_forty_added_claims_and_a_row_on_a_merged_record_read_as_one_line(self):
        """Forty email claims are one 'an email address'; a row saved on a merged record shows on the canonical person."""
        ada, twin = self.person("Ada Voorbeeld", "ada"), self.person("Ada Voorbeeld", "ada-2")
        network.merge(self.store, [twin], ada, now=now())
        for n in range(40):
            self.found(twin, "email", f"ada{n}@example.org")
        self.row(twin, "added")
        records = [r.id for r in self.store.records_of(ada)]
        self.assertEqual(self.view(ada, records).words, ADDED.format(date=DAY, parts="an email address"))
        self.assertIn(ADDED.format(date=DAY, parts="an email address"), self.page(ada))

    def test_the_person_page_shows_the_state_markup(self):
        """Before: the button alone; after: the words and Look up again; stopped: the note and Try again; running: a
        status line without a button, with a refresh and the script."""
        ada = self.person("Ada Voorbeeld", "ada")
        before = self.page(ada)
        self.assertIn(f'<div class="fn-more text-meta" id="lookup" role="status" tabindex="-1"><form method="post" '
                      f'action="/people/{ada}/lookup">', before)
        self.assertEqual(re.findall(r">(Look up [^<]*)</button>", self.box(before)), ["Look up more"])
        self.assertNotIn(LOOKUP_JS, before)
        self.row(ada, "nothing_new")
        after = self.box(self.page(ada))
        self.assertIn(f"<span>{NOTHING.format(date=DAY)}</span>", after)
        self.assertEqual(re.findall(r">(Look up [^<]*)</button>", after), ["Look up again"])
        self.row(ada, "failed")
        stopped = self.box(self.page(ada))
        self.assertIn('class="fn-status-note" id="lookup"', stopped)
        self.assertIn(f'<p class="text-strong">{STOPPED}</p>', stopped)
        self.assertIn(">Try again</button>", stopped)
        self.job(ada, "running")
        running = self.page(ada)
        self.assertIn('<div class="fn-status text-strong" id="lookup" role="status" tabindex="-1"><span>Looking up more…'
                      '</span><span class="fn-status__bar"></span></div>', running)
        self.assertEqual((REFRESH in running, LOOKUP_JS in running), (True, True))
        self.assertNotIn("Try again", running)
        self.assertEqual(re.findall(r"<form[^>]*lookup", running), [])

    def test_refresh_and_script_come_only_while_a_lookup_runs(self):
        """A page in any other state has neither the meta refresh nor lookup.js."""
        ada = self.person("Ada Voorbeeld", "ada")
        for status in ("done", "failed", "interrupted"):
            self.job(ada, status)
            html = self.page(ada)
            self.assertEqual((REFRESH in html, LOOKUP_JS in html), (False, False), status)

    def test_a_script_fetch_leaves_a_members_new_facts_unseen(self):
        """The poll's fetch does not clear the New marks; the next plain visit shows them and then clears them."""
        ada = self.person("Ada Voorbeeld", "ada", member=True)
        self.found(ada, "topic", "Tidal energy", at=now() - timedelta(hours=1))
        for _ in range(2):
            polled = self.client.get(f"/people/{ada}", headers={"X-Requested-With": "fetch"})
            self.assertIn("fn-new", polled.text)
        self.assertIn("fn-new", self.page(ada))
        self.assertNotIn("fn-new", self.page(ada))

    def test_a_post_starts_one_job_for_the_canonical_person_and_returns_to_the_line(self):
        """Two posts, one also by a merged id, start one job while it runs; a post after it ends starts another."""
        ada, twin = self.person("Ada Voorbeeld", "ada"), self.person("Ada Voorbeeld", "ada-2")
        network.merge(self.store, [twin], ada, now=now())
        release, started = threading.Event(), threading.Event()

        def hold(ctx, job):
            started.set()
            release.wait(10)

        jobs = lambda: self.store.conn.execute("SELECT status FROM searches WHERE kind = 'job' AND question = ?",
                                               (deepen.job_question(ada),)).fetchall()
        with mock.patch("fn.deepen.run_job", hold):
            first = self.client.post(f"/people/{ada}/lookup", data={"next": f"/people/{ada}?search=s1#lookup"})
            self.assertTrue(started.wait(10))
            second = self.client.post(f"/people/{twin}/lookup", data={})
            self.assertEqual((first.status_code, first.headers["location"]), (303, f"/people/{ada}?search=s1#lookup"))
            self.assertEqual((second.status_code, second.headers["location"]), (303, f"/people/{ada}#lookup"))
            self.assertEqual(len(jobs()), 1)
            self.assertIn("Looking up more…", self.page(ada))
            release.set()
            deadline = now() + timedelta(seconds=10)
            while jobs()[0][0] in ("queued", "running") and now() < deadline:
                threading.Event().wait(0.01)
        self.assertEqual(jobs()[0][0], "done")

    def test_a_post_for_an_unknown_person_is_a_404_and_starts_nothing(self):
        """An id nobody has gives a 404 and no job row."""
        self.assertEqual(self.client.post("/people/nobody/lookup", data={}).status_code, 404)
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM searches").fetchone()[0], 0)

    def test_a_job_whose_lookup_fails_ends_with_the_stopped_line(self):
        """The real job, run with a model that fails, stores a failed row, so the page reads that it stopped."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.found(ada, "role", "Professor of physics", read=False)
        self.client.post(f"/people/{ada}/lookup", data={})
        deadline = now() + timedelta(seconds=10)
        while now() < deadline and self.view(ada).state == "running":
            threading.Event().wait(0.01)
        self.assertEqual(self.view(ada).state, "stopped")
        self.assertIn(STOPPED, self.page(ada))


if __name__ == "__main__":
    unittest.main()
