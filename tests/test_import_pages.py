import asyncio
import re
import unittest
from datetime import timedelta
from unittest import mock

from fastapi.testclient import TestClient

from fn import network
from fn.contracts import IMPORT_COLUMNS, ClaimDraft, Identifier, Source
from fn.web.app import create_app
from fn.web.staff import UPLOAD_CAP
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

START = now() - timedelta(days=30)
BOUNDARY = "fnTestBoundary7"
# Five rows: one new, one tied by LinkedIn URL, one with a network name, one without a name, one new.
CONTACTS = ("name,email,organization,role,city,state,country,linkedin_url,notes\n"
            "Bo Newperson,bo@example.org,Example Labs,Engineer,Boston,MA,USA,,x\n"
            "Ann Linked,,,,,,,https://www.linkedin.com/in/ann-linked,\n"
            "Cy Samename,cy@example.org,Other Labs,Lecturer,Cambridge,MA,USA,,\n"
            ",nobody@example.org,,,,,,,\n"
            "Di Fresh,,,,,,,,\n")
# Three rows with one network name: the same job and place, another employer and place with an email, and the name alone.
NAMESAKES = ("name,email,organization,role,city,state,country\n"
             "Cy Samename,,Other Labs,Lecturer,Cambridge,MA,USA\n"
             "Cy Samename,cy@example.org,Elsewhere Inc,Lecturer,Chicago,IL,USA\n"
             "Cy Samename,,,,,,\n")


def multipart(filename: str, raw: bytes) -> tuple[bytes, dict[str, str]]:
    """A multipart/form-data body with one file field, as a browser sends it, and its Content-Type header."""
    head = (f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: text/csv\r\n\r\n").encode()
    return head + raw + f"\r\n--{BOUNDARY}--\r\n".encode(), {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"}


class ImportPagesTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(self.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def member(self, name: str, *idents: tuple[str, str]) -> str:
        """A made-up person in the network, with the given identifiers, else a seed identifier of the name."""
        person_id = self.store.resolve_person([Identifier(scheme=s, value=v) for s, v in idents or [("seed", name)]],
                                              name).id
        network.add(self.store, [person_id], via="search", now=START)
        return person_id

    def claim(self, person_id: str, kind: str, value: str, **fields) -> None:
        """A claim of the person from its own made-up source."""
        text = f"{kind}: {value}"
        source = Source(id=f"src-{person_id}-{kind}", kind="page", url=f"https://example.org/{person_id}/{kind}",
                        title="Lab", text=text, content_hash=f"h-{person_id}-{kind}")
        self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, value=value, quote=text, quote_start=0,
                                           quote_end=len(text), source=source, **fields), START)

    def tables(self, html: str) -> list[str]:
        return re.findall(r'<table class="fn-compare">.*?</table>', html, re.DOTALL)

    def post_file(self, filename: str, text: str | bytes):
        body, headers = multipart(filename, text if isinstance(text, bytes) else text.encode())
        return self.client.post("/imports", content=body, headers=headers, follow_redirects=False)

    def upload(self, text: str, filename: str = "contacts.csv") -> str:
        response = self.post_file(filename, text)
        self.assertEqual(response.status_code, 303, response.text)
        return response.headers["location"].rsplit("/", 1)[-1]

    def network_size(self) -> int:
        return sum(len(ids) for ids in self.store.network_by_group_key().values())

    def names(self, html: str) -> list[str]:
        return re.findall(r'<h3 class="fn-row__name text-name"><a href="/people/[^"]+">([^<]+)</a>', html)


class UploadTest(ImportPagesTest):
    def test_the_upload_page_lists_every_import_column(self):
        """The upload page has the file field and one table row per column FN reads, name the only required one."""
        html = self.client.get("/imports/new").text
        self.assertIn('<input class="fn-input text-body" id="file" name="file" type="file"', html)
        self.assertIn('enctype="multipart/form-data"', html)
        rows = re.findall(r'<tr><td class="text-meta">(\w+)</td><td class="text-meta">(Yes|No)</td>', html)
        self.assertEqual(rows, [(c, "Yes" if c == "name" else "No") for c in (*IMPORT_COLUMNS, "profile")])

    def test_the_upload_page_explains_the_profile_column(self):
        """The upload page says what the profile column is and that FN recognizes the person by it."""
        html = self.client.get("/imports/new").text
        self.assertIn("The address of the person&#x27;s page in FN, as an FN export writes it. FN recognizes the person by it.",
                      html)

    def test_a_posted_csv_redirects_to_a_preview_with_counts_matches_and_rows(self):
        """The preview counts the rows in words, offers each name match unticked and lists every row's outcome."""
        self.member("Ann Linked", ("profile_url", "https://www.linkedin.com/in/ann-linked"))
        cy = self.member("Cy Samename")
        import_id = self.upload(CONTACTS)
        html = self.client.get(f"/imports/{import_id}").text
        self.assertIn('<h1 class="fn-page__title text-title">Check contacts.csv</h1>', html)
        self.assertIn("Nothing is imported until you press Import 4 people.", html)
        self.assertIn('<ul class="fn-summary__counts text-body"><li>2 new people</li><li>1 already in your network</li>'
                      "<li>1 with the same name as someone in your network</li><li>1 row skipped</li></ul>", html)
        self.assertIn("FN adds what is new in the 1 row already in your network to their profiles. "
                      "Row 5 has no name, so FN skips it. FN ignores 1 column: notes.", html)
        self.assertIn('<input type="checkbox" id="m4" name="merge" value="4">'
                      f'<label class="text-body" for="m4">Row 4. Same as <a href="/people/{cy}">Cy Samename</a>?</label>',
                      html)
        self.assertIn("<caption>Row 4 of contacts.csv and Cy Samename in your network</caption>", html)
        self.assertIn('<tr><th scope="row">Employer</th><td>Other Labs</td><td class="fn-compare__none">Not known</td></tr>', html)
        self.assertIn('<input type="checkbox" id="all" name="same_all" value="1">', html)
        self.assertIn('<button class="fn-btn fn-btn--dark text-control">Import 4 people</button>', html)
        self.assertEqual(re.findall(r'<tr><td class="text-meta">(\d+)</td><td class="([^"]+)">([^<]+)</td>', html), [
            ("2", "text-meta", "New"), ("3", "text-meta", "In your network"), ("4", "text-meta", "Same name"),
            ("5", "text-meta fn-table__failed", "Skipped: no name"), ("6", "text-meta", "New")])

    def test_no_file_an_xlsx_no_name_column_and_an_oversized_file_give_400_under_the_field(self):
        """Each refusal re-renders the upload page with status 400 and its one sentence under the field."""
        cases = [
            ("", b"", "Choose a CSV file to upload."),
            ("people.xlsx", b"PK\x03\x04\x14\x00\x06\x00rest",
             "people.xlsx is not a CSV file. In Excel, use Save as and pick CSV."),
            ("emails.csv", b"email\nann@example.org\n",
             "emails.csv has no name column. Rename the column that holds names to name and upload it again."),
            ("big.csv", b"name\n" + b"Ann Example\n" * 600_000,
             "big.csv is larger than 5 MB. Split it into smaller files and upload them one by one."),
        ]
        for filename, raw, sentence in cases:
            with self.subTest(sentence=sentence):
                response = self.post_file(filename, raw)
                self.assertEqual(response.status_code, 400)
                self.assertIn('aria-describedby="file-hint file-error" aria-invalid="true"', response.text)
                self.assertIn(f'<p class="fn-error text-small" id="file-error">{sentence}</p>', response.text)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0], 0)

    def test_an_oversized_body_is_not_read_past_the_cap(self):
        """The upload route stops pulling body chunks once it holds more than the cap, and answers 400."""
        body, headers = multipart("big.csv", b"name\n" + b"x" * (3 * UPLOAD_CAP))
        chunks, pulled, sent = [body[i:i + 65536] for i in range(0, len(body), 65536)], [], []

        async def receive():
            if len(pulled) == len(chunks):
                return {"type": "http.disconnect"}
            pulled.append(chunks[len(pulled)])
            return {"type": "http.request", "body": pulled[-1], "more_body": len(pulled) < len(chunks)}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
                 "path": "/imports", "raw_path": b"/imports", "query_string": b"", "root_path": "",
                 "server": ("127.0.0.1", 80), "client": ("127.0.0.1", 5000),
                 "headers": [(b"host", b"127.0.0.1"), (b"content-type", headers["Content-Type"].encode()),
                             (b"content-length", str(len(body)).encode())]}
        asyncio.run(self.app(scope, receive, send))
        self.assertEqual(next(m["status"] for m in sent if m["type"] == "http.response.start"), 400)
        self.assertLessEqual(sum(map(len, pulled)), UPLOAD_CAP + 65536)

    def test_each_name_match_shows_both_records_and_differs_where_they_disagree(self):
        """Of two rows, only the second differs, on Employer and Place; an email on one side reads Not known, a
        name-only row reads Not in the file and two network namesakes show the first."""
        both = [self.member("Cy Samename"), self.member("Cy Samename", ("seed", "second"))]
        (first,) = [ids[0] for ids in self.store.network_by_group_key().values()]
        (other,) = [p for p in both if p != first]
        self.claim(first, "role", "Lecturer")
        self.claim(first, "affiliation", "Other Labs", relation="works_at")
        self.claim(first, "location", "Cambridge, MA, USA", relation="lives_in", lat=42.37, lon=-71.11)
        html = self.client.get(f"/imports/{self.upload(NAMESAKES)}").text
        rows = self.tables(html)
        self.assertEqual(len(rows), 3)
        marked = [re.findall(r'<th scope="row">(\w+) <span class="fn-compare__differs text-label">Differs</span>', t) for t in rows]
        self.assertEqual(marked, [[], ["Employer", "Place"], []])
        self.assertIn('<tr><th scope="row">Email</th><td><a href="mailto:cy@example.org">cy@example.org</a></td>'
                      '<td class="fn-compare__none">Not known</td></tr>', rows[1])
        self.assertIn('<tr><th scope="row">Job</th><td class="fn-compare__none">Not in the file</td><td>Lecturer</td></tr>', rows[2])
        self.assertEqual({re.search(r'<td><a href="/people/([^"]+)">', t).group(1) for t in rows}, {first})
        self.assertNotIn(other, html)

    def test_long_values_and_bad_links_render_whole_and_as_text(self):
        """A 200 character employer shows whole; a javascript: LinkedIn cell and an ORCID of n/a are plain text."""
        self.member("Cy Samename")
        long = "Institute of " + "Very Long Names " * 12
        html = self.client.get("/imports/" + self.upload(
            "name,organization,linkedin_url,orcid\n" f"Cy Samename,{long.strip()},javascript:alert(1),n/a\n")).text
        (table,) = self.tables(html)
        self.assertIn(f"<td>{long.strip()}</td>", table)
        self.assertGreaterEqual(len(long.strip()), 190)
        self.assertIn('<tr><th scope="row">LinkedIn</th><td>javascript:alert(1)</td>', table)
        self.assertIn('<tr><th scope="row">ORCID</th><td>n/a</td>', table)
        self.assertNotIn("href=\"javascript", table)

    def test_three_hundred_name_matches_read_the_claims_once(self):
        """The page reads claims in two calls, one for the views and one for the compares, however many rows match."""
        rows = [f"Person{chr(65 + n // 26)}{chr(65 + n % 26)} Samename" for n in range(300)]
        for name in rows:
            self.member(name)
        import_id = self.upload("name,organization\n" + "\n".join(f"{n},Labs" for n in rows))
        calls = []
        real = self.store.claims_of
        with mock.patch.object(type(self.store), "claims_of", autospec=True,
                               side_effect=lambda store, *a, **k: calls.append(1) or real(*a, **k)):
            html = self.client.get(f"/imports/{import_id}").text
        self.assertEqual((len(calls), len(self.tables(html))), (2, 300))


class ConfirmTest(ImportPagesTest):
    def test_confirm_adds_the_people_once_and_the_import_filter_lists_every_row_person(self):
        """Confirm redirects to the Network page with the Banner; import=<id> lists new, tied and merged rows' people.

        A second confirm adds nobody and redirects the same way.
        """
        ann = self.member("Ann Linked", ("profile_url", "https://www.linkedin.com/in/ann-linked"))
        cy = self.member("Cy Samename")
        self.member("Ed Bystander")
        import_id = self.upload(CONTACTS)
        response = self.client.post(f"/imports/{import_id}/confirm", data={"merge": "4"}, follow_redirects=False)
        self.assertEqual((response.status_code, response.headers["location"]), (303, f"/people?imported={import_id}"))
        html = self.client.get(response.headers["location"]).text
        self.assertIn('<p class="fn-banner text-body" role="status"><span>4 people imported from contacts.csv.</span>'
                      f'<a href="/people?import={import_id}">Show them</a></p>', html)
        self.assertEqual(self.network_size(), 5)
        shown = self.client.get("/people", params={"import": import_id}).text
        self.assertEqual(sorted(self.names(shown)), ["Ann Linked", "Bo Newperson", "Cy Samename", "Di Fresh"])
        self.assertIn(f'data-person="{ann}"', shown)
        self.assertIn(f'data-person="{cy}"', shown)
        again = self.client.post(f"/imports/{import_id}/confirm", data={"merge": "4"}, follow_redirects=False)
        self.assertEqual(again.headers["location"], f"/people?imported={import_id}")
        self.assertEqual(self.network_size(), 5)

    def test_discard_changes_nothing_and_shows_its_banner(self):
        """Discard leaves the network as it was and the Network page says the file was discarded."""
        import_id = self.upload(CONTACTS)
        response = self.client.post(f"/imports/{import_id}/discard", follow_redirects=False)
        self.assertEqual((response.status_code, response.headers["location"]), (303, f"/people?discarded={import_id}"))
        html = self.client.get(response.headers["location"]).text
        self.assertIn('<p class="fn-banner text-body" role="status"><span>contacts.csv discarded. Nothing was imported.'
                      "</span></p>", html)
        self.assertEqual(self.network_size(), 0)
        self.assertEqual(self.client.post(f"/imports/{import_id}/confirm", follow_redirects=False).headers["location"],
                         f"/imports/{import_id}")
        self.assertEqual(self.network_size(), 0)

    def test_a_ticked_match_merges_an_unticked_one_is_new_and_the_header_box_merges_all(self):
        """Only ticked name matches merge into the network person; the header box ticks every one."""
        text = "name,city\nAnn Twin,Boston\nBo Twin,Boston\n"
        for form, merged in (({"merge": "2"}, 1), ({}, 0), ({"same_all": "1"}, 2)):
            with self.subTest(form=form):
                self.store.conn.execute("DELETE FROM events")
                self.store.conn.execute("UPDATE persons SET list_status = 'candidate', merged_into = NULL")
                self.member("Ann Twin")
                self.member("Bo Twin")
                import_id = self.upload(text)
                self.client.post(f"/imports/{import_id}/confirm", data=form)
                self.assertEqual(self.network_size(), 2 + 2 - merged)

    def test_a_confirmed_preview_has_no_buttons_and_an_unknown_import_is_404(self):
        """After confirm the preview says what happened without a form; an unknown id answers 404 on every route."""
        import_id = self.upload(CONTACTS)
        self.client.post(f"/imports/{import_id}/confirm")
        html = self.client.get(f"/imports/{import_id}").text
        self.assertIn("4 people imported from contacts.csv. ", html)
        self.assertNotIn("<button", html)
        self.assertNotIn("<form", html.split("</header>", 1)[1])
        for method, url in (("get", "/imports/nope"), ("post", "/imports/nope/confirm"), ("post", "/imports/nope/discard")):
            with self.subTest(url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 404)


class NetworkLinksTest(ImportPagesTest):
    def count_line(self, html: str) -> str:
        return re.search(r'<p class="fn-count text-meta">(.*?)</p>', html).group(1)

    def test_the_heading_notice_and_count_line_link_import_export_and_new_facts(self):
        """Import sits on the heading and in the empty notice; the count line links new facts and the export."""
        for url in ("/", "/people"):
            with self.subTest(url=url):
                html = self.client.get(url).text
                self.assertIn('<p class="fn-sectionbar__acts text-meta"><a href="/imports/new">Import</a></p>', html)
                self.assertIn('<div class="fn-notice__acts"><a class="fn-btn fn-btn--quiet text-control" '
                              'href="/imports/new">Import</a></div>', html)
        ann = self.member("Ann Example")
        self.member("Bo Example")
        text = "Tidal energy"
        source = Source(id="src-ann", kind="page", url="https://example.org/ann", title="Example page", text=text,
                        content_hash="h-ann")
        self.store.upsert_claim(ClaimDraft(person_id=ann, kind="topic", value=text, quote=text, quote_start=0,
                                           quote_end=len(text), source=source), now())
        self.assertEqual(self.count_line(self.client.get("/people").text),
                         '<span>2 people · 2 not on the map · <a href="/people?new=1">1 with new facts</a> · '
                         '<a href="/people/export.csv">Export</a></span>')
        self.assertEqual(self.count_line(self.client.get("/people", params={"q": "ann"}).text),
                         '<span>1 person · 1 not on the map · <a href="/people?q=ann&amp;new=1">1 with new facts</a>'
                         ' · <a href="/people/export.csv?q=ann">Export these 1</a></span><a href="/people">Clear all</a>')
        self.assertEqual(self.count_line(self.client.get("/people", params={"q": "zzz"}).text),
                         '<span>0 people</span><a href="/people">Clear all</a>')


if __name__ == "__main__":
    unittest.main()
