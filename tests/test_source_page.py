import re
import unittest
from html import unescape

from fastapi.testclient import TestClient

from fn.contracts import ClaimDraft, Identifier, Org, Source
from fn.present import passage
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

LEUVEN = Org(id="ror:05f950310", name="KU Leuven", country_code="BE", source_id="org-src", fetched_at=now())
SENTENCE = "The lab measures radio links across the harbour district every spring. "


def words_outside_details(html: str) -> int:
    body = re.sub(r"<details.*?</details>", "", html, flags=re.S)
    body = re.sub(r"<header.*?</header>|<[^>]+>", " ", body, flags=re.S)
    return len(unescape(body).split())


class SourcePageTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store.upsert_source(Source(id="org-src", kind="page", url="https://example.org/orgs", text="orgs",
                                        content_hash="h-orgs"))
        self.store.upsert_org(LEUVEN, replace=True)
        self.person = self.store.resolve_person([Identifier(scheme="seed", value="ada")], "Ada Example").id
        self.n = 0

    def add(self, kind: str, text: str, quote: str, url: str = "https://example.org/lab", title: str | None = "Lab",
            start: int | None = None, claim_kind: str = "role", value: str = "Engineer", **fields) -> tuple[str, str]:
        """A source with text and a claim quoting quote in it; returns (source id, claim id)."""
        self.n += 1
        source = Source(id=f"src-{self.n}", kind=kind, url=url, title=title, text=text, content_hash=f"h-{self.n}")
        start = text.index(quote) if start is None else start
        draft = ClaimDraft(person_id=self.person, kind=claim_kind, value=value, quote=quote, quote_start=start,
                           quote_end=start + len(quote), source=source, **fields)
        return source.id, self.store.upsert_claim(draft, now()).id

    def open(self, source_id: str, claim_id: str = "") -> str:
        response = self.client.get(f"/sources/{source_id}", params={"claim": claim_id} if claim_id else {})
        self.assertEqual(response.status_code, 200)
        return response.text

    def test_a_page_source_names_the_person_says_the_fact_and_holds_the_text_in_a_closed_record(self):
        """The h1 is the person, the sentence is built from the fact, the passage has at most 60 words per side."""
        quote = "Ada Example works at Example Labs since 2019"
        text = SENTENCE * 20 + quote + ". " + SENTENCE * 20
        source_id, claim_id = self.add("page", text, quote, claim_kind="affiliation", relation="works_at", value="Example Labs",
                                       years=[2019, 2020, 2021, 2022, 2023, 2024])
        html = self.open(source_id, claim_id)
        self.assertIn('<h1 class="fn-source__title text-title">Ada Example</h1>', html)
        self.assertIn('<p class="fn-source__lead text-body">The page says: Works at Example Labs, 2019–2024.</p>', html)
        before, marked, after = re.search(r'<p class="fn-source__passage text-body">(.*?)<mark id="quote">(.*?)</mark>(.*?)</p>',
                                          html, re.S).groups()
        self.assertEqual(marked, quote)
        self.assertLessEqual(len(before.replace("…", "").split()), 60)
        self.assertLessEqual(len(after.replace("…", "").split()), 60)
        self.assertTrue(before.startswith("…") and after.endswith("…"))
        stored = re.search(r'<details class="fn-source__stored"><summary class="text-meta">Show the stored record</summary>'
                           r'<pre class="fn-source__text text-body">(.*?)</pre></details>', html, re.S)
        self.assertIn(text.split(quote)[0], stored.group(1))
        self.assertEqual(html.count('id="quote"'), 1)

    def test_a_record_source_has_no_passage_and_the_sentence_is_the_quote_target(self):
        """A record's lines are never a passage; #quote stays on the sentence so the stored record stays closed."""
        text = "name: Ada Example\nstudied at KU Leuven 2012-2017"
        source_id, claim_id = self.add("record", text, "studied at KU Leuven 2012-2017", title="Record",
                                       claim_kind="affiliation", relation="studied_at", org_id=LEUVEN.id, value="KU Leuven",
                                       years=[2012, 2013, 2014, 2015, 2016, 2017])
        html = self.open(source_id, claim_id)
        self.assertIn("The record lists: Studied at KU Leuven, 2012–2017.", html)
        self.assertNotIn("fn-source__passage", html)
        self.assertRegex(html, r'<p id="quote" class="fn-source__lead text-body">')
        self.assertEqual(html.count('id="quote"'), 1)

    def test_the_original_page_link_is_left_out_for_an_fn_url(self):
        """Import and staff sources have an fn: url and no original page; a page source links to its own."""
        source_id, claim_id = self.add("import", "name: Ada Example", "name: Ada Example", url="fn:import:1", title="x.csv, row 2")
        self.assertNotIn("Open the original page", self.open(source_id, claim_id))
        page_id, page_claim = self.add("page", "Ada Example is an engineer", "Ada Example is an engineer", claim_kind="role",
                                       value="Engineer")
        self.assertIn('<p class="fn-source__url text-small"><a href="https://example.org/lab">Open the original page</a></p>',
                      self.open(page_id, page_claim))

    def test_without_a_claim_the_title_is_the_source_label_and_there_is_no_sentence(self):
        """Opened without a fact the page names the source and says nothing about a fact."""
        source_id, _ = self.add("record", "name: Ada Example", "Ada Example", title="Lab people")
        html = self.open(source_id)
        self.assertIn('<h1 class="fn-source__title text-title">OpenAlex record</h1>', html)
        self.assertNotIn("fn-source__lead", html)
        self.assertNotIn("fn-source__passage", html)

    def test_a_very_long_source_shows_at_most_200_words_outside_the_stored_record(self):
        """Seventeen thousand words of text put the passage and the record behind a window of the text."""
        quote = "Ada Example works at Example Labs"
        text = SENTENCE * 1000 + quote + ". " + SENTENCE * 1000
        self.assertGreater(len(text.split()), 17000)
        source_id, claim_id = self.add("page", text, quote)
        self.assertLessEqual(words_outside_details(self.open(source_id, claim_id)), 200)

    def test_a_quote_at_the_start_or_end_has_no_cut_mark_on_that_side(self):
        """No leading ellipsis at offset 0 and no trailing one at the end of the text."""
        text = "Ada Example works here. " + SENTENCE * 30 + "Ada Example left."
        source_id, claim_id = self.add("page", text, "Ada Example works here", start=0)
        source = self.store.get_sources([source_id])[source_id]
        before, _, after = passage(source, self.store.get_claim(claim_id))
        self.assertEqual(before, "")
        self.assertTrue(after.endswith("…"))
        end_id, end_claim = self.add("page", text, "Ada Example left.")
        before, _, after = passage(self.store.get_sources([end_id])[end_id], self.store.get_claim(end_claim))
        self.assertTrue(before.startswith("…"))
        self.assertEqual(after, "")

    def test_text_without_spaces_is_cut_at_400_characters(self):
        """A side with no space near the quote is cut by characters, not kept whole."""
        text = "x" * 2000 + " Ada Example " + "y" * 2000
        source_id, claim_id = self.add("page", text, "Ada Example")
        before, quote, after = passage(self.store.get_sources([source_id])[source_id], self.store.get_claim(claim_id))
        self.assertEqual((before, quote, after), ("… " + "x" * 400 + " ", "Ada Example", " " + "y" * 400 + " …"))

    def test_hostile_title_url_and_text_are_escaped(self):
        """Markup in the title, the passage and the url is text; a quote in the url cannot close the attribute."""
        quote = "Ada <b>Example</b> is an engineer"
        source_id, claim_id = self.add("page", "<script>x</script> " + quote, quote, url='https://example.org/?q="><b>',
                                       title="<i>t</i>")
        html = self.open(source_id, claim_id)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>", html)
        self.assertNotIn("<i>", html)
        self.assertNotIn('q="><b>', html)

    def test_a_claim_of_another_source_is_a_404(self):
        """The claim must belong to the source in the url."""
        _, claim_id = self.add("page", "Ada Example", "Ada Example")
        other, _ = self.add("page", "Other", "Other")
        self.assertEqual(self.client.get(f"/sources/{other}", params={"claim": claim_id}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
