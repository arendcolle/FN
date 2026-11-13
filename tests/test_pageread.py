import logging
import unittest
from unittest import mock

import httpx

from fn import net, pageread
from fn.contracts import ParseIn, ParseOut
from fn.pageread import Read, allowed, html_text, page_date, read, read_all, windows
from fn.steps import StepContext, run_step
from fn.worker import Worker, new_id, now
from tests.helpers import StubLLM, make_db, make_settings

LONG = "Ada Example leads the Example Labs team on quiet measurement. " * 8


def page(body: str, title: str = "Example page") -> str:
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


class PageReadTest(unittest.TestCase):
    def setUp(self):
        pageread.ROBOTS.clear()
        looked_up = mock.patch.object(pageread, "addresses", side_effect=lambda host: ["10.0.0.7"] if host == "inside.example" else ["93.184.216.34"])
        looked_up.start()
        self.addCleanup(looked_up.stop)
        self.settings = make_settings(self).model_copy(update={"http_mode": "live"})
        self.store = make_db(self, self.settings)
        self.sent: list[httpx.Request] = []
        self.routes: dict[str, httpx.Response | Exception] = {}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        answer = self.routes.get(str(request.url), httpx.Response(404))
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def run_in_step(self, settings, fn):
        """Run fn(ctx) inside one step over a client with this test's routes; returns what fn returned."""
        worker = Worker(self.store, settings, llm=StubLLM())
        self.addCleanup(worker.shutdown)
        search = worker.create_search("question")
        client = net.Client(settings, httpx.MockTransport(self.handle))
        ctx = StepContext(search_id=search.id, store=self.store, llm=None, http=client, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        out = []
        run_step(ctx, "read", lambda c, i: (out.append(fn(c)), ParseOut(chips={}))[1], ParseIn(question="q"))
        return out[0]

    def reading(self, *urls: str, settings=None) -> list[Read]:
        return self.run_in_step(settings or self.settings, lambda ctx: read_all(ctx, list(urls)))

    def serve(self, url: str, body: str | bytes, robots: str = "User-agent: *\nAllow: /", status: int = 200, **headers):
        host = "/".join(url.split("/")[:3])
        self.routes.setdefault(f"{host}/robots.txt", httpx.Response(200, text=robots))
        content = body.encode() if isinstance(body, str) else body
        self.routes[url] = httpx.Response(status, content=content, headers=headers)

    def test_a_page_gives_its_title_and_main_text_without_navigation_script_or_footer(self):
        """Text in nav, script, header, footer and form is absent; main wins when it holds 300 characters."""
        self.serve("https://a.example/p", page(
            f"<header>Site banner</header><nav>Menu entry</nav><div>Outside noise</div>"
            f"<main><h1>Team</h1><p>{LONG}</p></main><script>var hidden = 1;</script><footer>Copyright line</footer>"))
        [got] = self.reading("https://a.example/p")
        self.assertEqual((got.title, got.failed, got.truncated), ("Example page", None, False))
        self.assertTrue(got.text.startswith("Team\nAda Example leads"))
        for absent in ("Site banner", "Menu entry", "Outside noise", "hidden", "Copyright"):
            self.assertNotIn(absent, got.text)

    def test_the_body_is_used_when_main_is_short_and_a_nested_article_stays_in_main(self):
        """A main of 50 characters falls back to the whole body; an article inside main counts once."""
        self.serve("https://a.example/short", page(f"<main>Only a short line here, fifty characters or so.</main><div>{LONG}</div>"))
        self.serve("https://a.example/nested", page(f"<div>Outside</div><main><article><p>{LONG}</p></article></main>"))
        short, nested = self.reading("https://a.example/short", "https://a.example/nested")
        self.assertIn("Only a short line", short.text)
        self.assertIn("Ada Example leads", short.text)
        self.assertEqual(nested.text, " ".join(LONG.split()))

    def test_every_failure_gives_its_reason_word_for_word(self):
        """A 403, a 999, a 404, a PDF, a script-only page and four redirects each fail with their reason."""
        self.serve("https://a.example/403", "no", status=403)
        self.serve("https://a.example/999", "no", status=999)
        self.serve("https://a.example/404", "no", status=404)
        self.serve("https://a.example/pdf", b"%PDF-1.7 binary")
        self.serve("https://a.example/js", page("<div id=app></div><script>render()</script>"))
        for n in range(4):
            self.serve(f"https://a.example/r{n}", "", status=302, location=f"/r{n + 1}")
        got = {r.url.rsplit("/", 1)[1]: r for r in self.reading(*(f"https://a.example/{p}" for p in
                                                                   ("403", "999", "404", "pdf", "js", "r0")))}
        self.assertEqual(got["403"].failed, "GET https://a.example/403 returned 403: no")
        self.assertEqual(got["999"].failed, "GET https://a.example/999 returned 999: no")
        self.assertIn("returned 404", got["404"].failed)
        self.assertEqual(got["pdf"].failed, "a PDF, not a web page")
        self.assertEqual(got["js"].failed, "0 characters of text, under 300")
        self.assertEqual(got["r0"].failed, "GET https://a.example/r0 redirected more than 3 times")
        self.assertTrue(all(r.text is None for r in got.values()))

    def test_robots_txt_decides_before_the_page_is_asked_for(self):
        """A disallow, a 403 and a timeout stop the read; a 404 allows it; the page is never requested when stopped."""
        self.serve("https://deny.example/x", page(LONG), robots="User-agent: *\nDisallow: /x")
        self.routes["https://locked.example/robots.txt"] = httpx.Response(403)
        self.routes["https://locked.example/x"] = httpx.Response(200, text=page(LONG))
        self.routes["https://slow.example/robots.txt"] = httpx.ConnectTimeout("timed out")
        self.routes["https://slow.example/x"] = httpx.Response(200, text=page(LONG))
        self.routes["https://open.example/x"] = httpx.Response(200, text=page(LONG))
        deny, locked, slow, opened = self.reading("https://deny.example/x", "https://locked.example/x",
                                                  "https://slow.example/x", "https://open.example/x")
        self.assertEqual(deny.failed, "robots.txt disallows it")
        self.assertEqual(locked.failed, "robots.txt disallows it")
        self.assertTrue(slow.failed.startswith("robots.txt could not be read: "))
        self.assertIn("timed out", slow.failed)
        self.assertIsNone(opened.failed)
        asked = {str(r.url) for r in self.sent}
        self.assertFalse(asked & {"https://deny.example/x", "https://locked.example/x", "https://slow.example/x"})

    def test_two_pages_on_one_host_fetch_robots_txt_once(self):
        """The parsed robots.txt is kept per host for the process, so the second page costs no second fetch."""
        self.serve("https://a.example/one", page(LONG))
        self.serve("https://a.example/two", page(LONG))
        self.reading("https://a.example/one", "https://a.example/two")
        self.assertEqual([str(r.url) for r in self.sent].count("https://a.example/robots.txt"), 1)

    def test_text_over_40000_characters_is_cut_and_marked(self):
        """A page of 60,000 characters gives its first 40,000 and truncated; 40,000 exactly is not truncated."""
        self.serve("https://a.example/big", page("<p>" + "x" * 60_000 + "</p>"))
        self.serve("https://a.example/exact", page("<p>" + "y" * 40_000 + "</p>"))
        big, exact = self.reading("https://a.example/big", "https://a.example/exact")
        self.assertEqual((len(big.text), big.truncated), (40_000, True))
        self.assertEqual((len(exact.text), exact.truncated), (40_000, False))

    def test_a_page_in_cp1252_is_decoded_with_its_accents(self):
        """A body that is not UTF-8 is read as cp1252, so a name with an accent survives."""
        text = page(f"<p>Zoë Voorbeeld werkt bij Voorbeeld Labs. {LONG}</p>").encode("cp1252")
        self.serve("https://a.example/old", text)
        [got] = self.reading("https://a.example/old")
        self.assertIn("Zoë Voorbeeld", got.text)

    def test_a_redirect_chain_is_followed_and_replay_serves_it_under_the_first_url(self):
        """A 301 to https then a 200 reads the final body; replay mode then needs no network for the first url."""
        self.routes["http://a.example/old"] = httpx.Response(301, headers={"location": "https://a.example/new"})
        self.serve("https://a.example/new", page(LONG))
        self.routes["http://a.example/robots.txt"] = httpx.Response(200, text="User-agent: *\nAllow: /")
        [got] = self.reading("http://a.example/old")
        self.assertIsNone(got.failed)
        sent = len(self.sent)
        pageread.ROBOTS.clear()
        [again] = self.reading("http://a.example/old", settings=self.settings.model_copy(update={"http_mode": "replay"}))
        self.assertEqual(again.text, got.text)
        self.assertEqual(len(self.sent), sent)

    def test_a_replay_reads_a_cached_page_whose_host_had_no_robots_txt(self):
        """A 404 robots.txt is never cached; a replay then treats it as allowing, and serves the cached page."""
        self.routes["https://a.example/p"] = httpx.Response(200, content=page(LONG).encode())
        [live] = self.reading("https://a.example/p")
        self.assertIsNone(live.failed)
        pageread.ROBOTS.clear()
        [again] = self.reading("https://a.example/p", settings=self.settings.model_copy(update={"http_mode": "replay"}))
        self.assertEqual((again.failed, again.text), (None, live.text))

    def test_a_local_or_private_address_is_never_fetched(self):
        """Loopback, localhost, a private or link-local IP and a name that resolves to one are refused before any call."""
        urls = ["http://127.0.0.1:8765/people", "http://localhost/x", "http://10.0.0.5/x", "http://169.254.169.254/latest",
                "http://[::1]/x", "http://intranet/x", "https://inside.example/x"]
        got = self.reading(*urls)
        self.assertEqual({r.failed for r in got}, {"a local or private address"})
        self.assertEqual(self.sent, [])

    def test_a_redirect_to_a_private_address_or_a_disallowed_page_is_not_followed(self):
        """Each hop passes the same checks as a first address: no private host, and the new host's robots.txt."""
        self.serve("https://a.example/start", "x")
        self.routes["https://a.example/start"] = httpx.Response(302, headers={"location": "http://10.0.0.5/admin"})
        self.serve("https://b.example/start", "x")
        self.routes["https://b.example/start"] = httpx.Response(302, headers={"location": "https://c.example/private/page"})
        self.routes["https://c.example/robots.txt"] = httpx.Response(200, text="User-agent: *\nDisallow: /private/")
        self.routes["https://c.example/private/page"] = httpx.Response(200, content=page(LONG).encode())
        with mock.patch("fn.pageread.time.sleep"):
            first, second = self.reading("https://a.example/start", "https://b.example/start")
        self.assertIn("a local or private address", first.failed)
        self.assertIn("robots.txt disallows it", second.failed)
        self.assertNotIn("https://c.example/private/page", [str(r.url) for r in self.sent])
        self.assertNotIn("http://10.0.0.5/admin", [str(r.url) for r in self.sent])

    def test_a_read_page_carries_its_own_date(self):
        """read passes the date of the page's meta tags on with the text; a page without one has none."""
        dated = f'<html><head><meta property="article:published_time" content="2024-05-17"></head><body><p>{LONG}</p></body></html>'
        self.serve("https://a.example/dated", dated)
        self.serve("https://a.example/plain", page(LONG))
        with mock.patch("fn.pageread.time.sleep"):
            got = self.reading("https://a.example/dated", "https://a.example/plain")
        self.assertEqual([r.published for r in got], ["2024-05-17", None])

    def test_pages_of_one_host_are_read_one_after_another_with_a_pause(self):
        """Two pages of one host and one of another: one pause, between the two pages that share a host."""
        for url in ("https://a.example/1", "https://a.example/2", "https://b.example/1"):
            self.serve(url, page(LONG))
        with mock.patch("fn.pageread.time.sleep") as slept:
            got = self.reading("https://a.example/1", "https://b.example/1", "https://a.example/2")
        self.assertEqual([r.url for r in got], ["https://a.example/1", "https://b.example/1", "https://a.example/2"])
        self.assertEqual(slept.call_args_list, [mock.call(pageread.PAUSE_S)])
        asked = [str(r.url) for r in self.sent if "a.example" in str(r.url) and "robots" not in str(r.url)]
        self.assertEqual(asked, ["https://a.example/1", "https://a.example/2"])

    def test_the_page_and_its_robots_txt_are_asked_for_as_fn_alone(self):
        """Both requests carry exactly FN/0.1 as User-Agent, without the repository address."""
        self.serve("https://a.example/p", page(LONG))
        self.reading("https://a.example/p")
        self.assertEqual({str(r.url): r.headers["user-agent"] for r in self.sent},
                         {"https://a.example/robots.txt": "FN/0.1", "https://a.example/p": "FN/0.1"})

    def test_allowed_is_none_for_a_permitted_url(self):
        """allowed returns None when robots.txt permits the path and names the reason when it does not."""
        self.serve("https://a.example/ok", "", robots="User-agent: *\nDisallow: /private")
        self.assertEqual(self.run_in_step(self.settings, lambda c: (allowed(c, "https://a.example/ok"),
                                                                    allowed(c, "https://a.example/private/x"))),
                         (None, "robots.txt disallows it"))


class HtmlTextTest(unittest.TestCase):
    def test_blocks_start_lines_and_whitespace_collapses(self):
        """Each block tag starts a line, inline text stays on one line and empty lines go."""
        title, text = html_text("<title> A \n title </title><p>One   two</p><p></p><div>Three <b>four</b></div>")
        self.assertEqual((title, text), ("A title", "One two\nThree four"))

    def test_a_page_without_a_title_gives_none(self):
        self.assertEqual(html_text("<p>text</p>"), (None, "text"))


class PageDateTest(unittest.TestCase):
    def test_a_changed_date_wins_over_a_published_one_and_a_page_without_one_has_none(self):
        """The meta tags a page carries about itself give its date; a malformed value and other tags are ignored."""
        both = ('<meta property="article:published_time" content="2023-04-01T08:00:00Z">'
                '<meta content="2024-05-17" itemprop="dateModified">')
        self.assertEqual(page_date(both), "2024-05-17")
        self.assertEqual(page_date('<meta name="date" content="2022-11-03">'), "2022-11-03")
        self.assertIsNone(page_date('<meta name="date" content="last week"><meta name="author" content="2024-05-17">'))
        self.assertIsNone(page_date('<meta name="date" content="2024-13-05">'))
        self.assertIsNone(page_date("<p>Published 2024-05-17</p>"))


class WindowsTest(unittest.TestCase):
    def lines(self, n: int, marks: dict[int, str]) -> str:
        return "\n".join(marks.get(i, f"filler line number {i} " + "x" * 80) for i in range(n))

    def test_a_short_text_and_a_text_without_a_name_come_back_whole_or_cut(self):
        """Up to the limit nothing changes; with no name or no names the first limit characters come back."""
        self.assertEqual(windows("short text", ["Ada Example"]), "short text")
        text = self.lines(400, {})
        self.assertEqual(windows(text, ["Ada Example"]), text[:12_000])
        self.assertEqual(windows(text, []), text[:12_000])

    def test_one_name_keeps_its_surroundings_as_copied_lines(self):
        """The part around a last word starts and ends at line ends and every line is a line of the page."""
        text = self.lines(400, {200: "Our speaker Ada Example arrived."})
        got = windows(text, ["Ada Example"], around=500, limit=5_000)
        self.assertIn("Our speaker Ada Example arrived.", got)
        self.assertLessEqual(len(got), 5_000)
        self.assertTrue(set(got.split("\n")) <= set(text.split("\n")))
        self.assertNotIn("filler line number 0 ", got)

    def test_far_apart_names_give_two_parts_joined_by_a_line_with_the_ellipsis(self):
        """Two names far apart give two parts in page order, split by a line holding only the ellipsis."""
        text = self.lines(600, {50: "Bea Voorbeeld spoke.", 500: "Carl Sample answered."})
        got = windows(text, ["Carl Sample", "Bea Voorbeeld"], around=300, limit=8_000)
        parts = got.split("\n…\n")
        self.assertEqual(len(parts), 2)
        self.assertIn("Voorbeeld", parts[0])
        self.assertIn("Sample", parts[1])

    def test_overlapping_parts_merge_and_thirty_hits_stay_inside_the_limit(self):
        """Names close together give one part; thirty hits still give at most limit characters at a line end."""
        near = windows(self.lines(600, {50: "Bea Voorbeeld one", 52: "Bea Voorbeeld two"}), ["Bea Voorbeeld"], around=300)
        self.assertNotIn("…", near)
        many = windows(self.lines(900, {i: f"Bea Voorbeeld again {i}" for i in range(10, 900, 30)}), ["Bea Voorbeeld"],
                       around=200, limit=3_000)
        self.assertLessEqual(len(many), 3_000)
        self.assertTrue(many.rsplit("\n", 1)[-1].startswith(("filler", "Bea", "…")))

    def test_a_name_on_one_very_long_line_stays_in_its_part(self):
        """A line of 40,000 characters is cut inside the line around the name, and the part is a copy of the page."""
        text = "x " * 15_000 + "Ada Example leads the team. " + "y " * 5_000
        got = windows(text, ["Ada Example"])
        self.assertIn("Ada Example leads the team.", got)
        self.assertLessEqual(len(got), 12_000)
        self.assertIn(got, text)

    def test_a_name_lost_to_the_cut_leaves_the_first_characters(self):
        """A name at character 50,000 of a text cut at 40,000 is not there, so the first 12,000 characters come back."""
        text = ("a" * 99 + "\n") * 500 + "Ada Example\n" + ("b" * 99 + "\n") * 100
        cut = text[:40_000]
        self.assertEqual(windows(cut, ["Ada Example"]), cut[:12_000])


if __name__ == "__main__":
    unittest.main()
