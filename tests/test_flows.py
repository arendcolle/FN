import csv
import io
import re
import threading
import time
import unittest
from dataclasses import dataclass, field
from datetime import timedelta
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from fn import network
from fn.contracts import (
    IMPORT_COLUMNS,
    ClaimDraft,
    Identifier,
    LaneHit,
    LaneIn,
    LaneOut,
    Source,
)
from fn.steps import StepContext
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

EARLIER = now() - timedelta(days=30)
WIND = {"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "parsed"}]}
# Five people in Massachusetts, Illinois and Belgium, one Belgian city FN cannot find, and a row without a name.
CONTACTS = ("name;email;organization;role;city;state;country\n"
            "Ann Harbor;ann@example.org;Harbor Labs;Engineer;Boston;MA;USA\n"
            "Ben Quill;;Quill Works;Analyst;Cambridge;MA;USA\n"
            ";nobody@example.org;;;;;\n"
            "Cas Lindqvist;;Lake Systems;Researcher;Chicago;IL;USA\n"
            "Dora Vermeer;dora@example.org;Vermeer Studio;Designer;Leuven;;Belgium\n"
            "Eli Nowhere;;Nowhere Inc;Founder;Nergensdorp;;Belgium\n")
PLACED = ["Ann Harbor", "Ben Quill", "Cas Lindqvist", "Dora Vermeer"]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SCOPES = {"fn-card", "fn-claim", "fn-row", "fn-line", "fn-count"}
# The import column linkedin_url and the LinkedIn record label are staff words; the bare lowercase lane name is not.
FORBIDDEN = re.compile(r"(?i:\bscores?\b)|openalex|seeds|lane:|(?<![\w.])linkedin(?![\w.])|Traceback|href=\"/debug")


@dataclass
class Form:
    action: str
    method: str
    fields: list[tuple[str, str]] = field(default_factory=list)
    boxes: list[tuple[str, str]] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    buttons: list[str] = field(default_factory=list)


@dataclass
class Scope:
    attrs: dict[str, str]
    text: list[str] = field(default_factory=list)
    forms: list[Form] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)

    @property
    def words(self) -> str:
        return " ".join(" ".join(self.text).split())


class Page(HTMLParser):
    """A staff page read as a browser would: its forms, its links by text, its tag attributes and scoped parts.

    A scope is a card, a fact, a network row, a line or the count line; forms and links inside one belong to it.
    """

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.html, self.text, self.forms, self.links, self.tags, self.scopes = html, [], [], [], [], []
        self._open: list[tuple[str, Scope | None]] = []
        self._form = self._link = self._button = self._area = None
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        self.tags.append((tag, a))
        scope = Scope(a) if tag == "article" or SCOPES & set(a.get("class", "").split()) else None
        if scope:
            self.scopes.append(scope)
        if tag not in VOID:
            self._open.append((tag, scope))
        if tag == "form":
            self._form = Form(a.get("action", ""), a.get("method", "get").lower())
            self.forms.append(self._form)
            if inner := self.inner():
                inner.forms.append(self._form)
        elif tag == "a":
            self._link = (a.get("href", ""), [])
        elif tag == "button":
            self._button = []
        elif tag == "textarea":
            self._area = (a.get("name", ""), [])
        elif tag == "input" and self._form and a.get("name"):
            kind = a.get("type", "text")
            if kind == "checkbox":
                self._form.boxes.append((a["name"], a.get("value", "on")))
            elif kind == "file":
                self._form.files.append(a["name"])
            else:
                self._form.fields.append((a["name"], a.get("value", "")))

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "a" and self._link:
            link = (" ".join("".join(self._link[1]).split()), self._link[0])
            self.links.append(link)
            if inner := self.inner():
                inner.links.append(link)
            self._link = None
        elif tag == "button" and self._button is not None:
            if self._form:
                self._form.buttons.append(" ".join("".join(self._button).split()))
            self._button = None
        elif tag == "textarea" and self._area:
            if self._form:
                self._form.fields.append((self._area[0], "".join(self._area[1])))
            self._area = None
        names = [t for t, _ in self._open]
        if tag in names:
            del self._open[len(names) - 1 - names[::-1].index(tag):]

    def handle_data(self, data):
        self.text.append(data)
        for _, scope in self._open:
            if scope:
                scope.text.append(data)
        for parts in (self._link and self._link[1], self._button, self._area and self._area[1]):
            if parts is not None:
                parts.append(data)

    def inner(self) -> Scope | None:
        return next((s for _, s in reversed(self._open) if s), None)

    @property
    def words(self) -> str:
        return " ".join(" ".join(self.text).split())

    def attr(self, name: str) -> str | None:
        """The first value of the attribute name on any tag."""
        return next((a[name] for _, a in self.tags if name in a), None)

    def link(self, text: str, within: Scope | None = None) -> str:
        """The href of the first link whose text is text."""
        found = [href for words, href in (within or self).links if words == text]
        if not found:
            raise AssertionError(f"no link {text!r} in {[w for w, _ in (within or self).links]}")
        return found[0]

    def form(self, button: str, within: Scope | None = None) -> Form:
        """The first form with a button labelled button."""
        found = [f for f in (within or self).forms if button in f.buttons]
        if not found:
            raise AssertionError(f"no form with {button!r} in {[f.buttons for f in (within or self).forms]}")
        return found[0]

    def scope(self, text: str, css: str) -> Scope:
        """The first part with class css (or the card article) whose words hold text."""
        for scope in self.scopes:
            if (css in scope.attrs.get("class", "").split()) and text in scope.words:
                return scope
        raise AssertionError(f"no {css} holding {text!r}")

    def has_scope(self, text: str, css: str) -> bool:
        return any(css in s.attrs.get("class", "").split() and text in s.words for s in self.scopes)


def found(name: str, key: str, fact: str, scheme: str = "seed") -> SimpleNamespace:
    """A made-up person a fake lane finds: name, identifier and one topic it reads on a page."""
    return SimpleNamespace(name=name, scheme=scheme, key=key, fact=fact)


def write_claim(store, person_id: str, fact: str, at=None) -> str:
    """A topic claim from its own made-up web page; returns the claim id."""
    text = f"{fact} is what this page is about."
    source = Source(id=f"src-{person_id}-{abs(hash(fact))}", kind="page", url=f"https://example.org/{abs(hash(fact))}",
                    title="Example page", text=text, content_hash=f"h-{person_id}-{fact}")
    return store.upsert_claim(ClaimDraft(person_id=person_id, kind="topic", value=fact, quote=text, quote_start=0,
                                         quote_end=len(text), source=source), at or now()).id


def lane(name: str, people: list[SimpleNamespace], gate: threading.Event | None = None) -> SimpleNamespace:
    """A fake lane that stores each person with their fact, as a real lane does, and hits them in order."""

    def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
        if gate and not gate.wait(10):
            raise TimeoutError("the gate was never opened")
        hits = []
        for rank, who in enumerate(people, 1):
            person = ctx.store.resolve_person([Identifier(scheme=who.scheme, value=who.key)], who.name)
            claim = write_claim(ctx.store, person.id, who.fact, ctx.now())
            hits.append(LaneHit(person_id=person.id, name_key=person.name_key, lane=name, rank=rank, score=1.0,
                                matched_on="wind", claim_ids=[claim]))
        return LaneOut(lane=name, query="wind", total_seen=len(people), hits=hits)

    return SimpleNamespace(name=name, run=run)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.pages: dict[str, str] = {}
        self.start()

    def start(self):
        """A fresh store and app, with a stub LLM that parses every question to the topic wind."""
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(answer=WIND), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def keep(self, response) -> Page:
        """Check the response is a 200 page, remember it for the never-see check and read it."""
        self.assertEqual(response.status_code, 200, f"{response.url}: {response.text[:300]}")
        self.pages[str(response.url)] = response.text
        page = Page(response.text)
        page.url = response.url
        return page

    def get(self, url: str) -> Page:
        return self.keep(self.client.get(url))

    def submit(self, form: Form, ticked: list[str] = (), files: dict | None = None, **values: str) -> Page:
        """Send the form as a browser does: its fields with values changed, the ticked boxes and files."""
        data: dict[str, list[str]] = {}
        for name, value in form.fields:
            data.setdefault(name, []).append(values.pop(name, value))
        for name, value in form.boxes:
            if name in ticked:
                data.setdefault(name, []).append(value)
        self.assertEqual(values, {}, "a value for a field the form does not have")
        if form.method == "get":
            return self.keep(self.client.get(form.action, params=data))
        return self.keep(self.client.post(form.action, data=data, files=files))

    def member(self, name: str, key: str, fact: str, scheme: str = "seed") -> str:
        """A made-up person in the network since EARLIER, with one fact seen before then."""
        person_id = self.store.resolve_person([Identifier(scheme=scheme, value=key)], name).id
        write_claim(self.store, person_id, fact, EARLIER - timedelta(days=1))
        network.add(self.store, [person_id], via="search", now=EARLIER)
        return person_id

    def wait(self, page: Page, until=lambda s: s["status"] not in ("queued", "running")) -> dict:
        """Poll the status route a running results page names until until holds; the last status."""
        deadline = time.monotonic() + 10
        while True:
            status = self.client.get(page.attr("data-status")).json()
            if until(status):
                return status
            self.assertLess(time.monotonic(), deadline, f"the search never got past {status}")
            time.sleep(0.01)

    def ask(self, question: str) -> Page:
        """Type the question in the box on Home, wait for the search to end and return its results page."""
        page = self.submit(self.get("/").form("Search"), question=question)
        if page.attr("data-status"):
            self.wait(page)
        return self.get(str(page.url))

    def row_names(self, page: Page) -> list[str]:
        """The names on the page's network rows, sorted; each row's first link is the name."""
        return sorted(s.links[0][0] for s in page.scopes if "fn-row" in s.attrs.get("class", "").split())

    def network_names(self) -> list[str]:
        return self.row_names(self.get(self.get("/").link("Network")))

    def import_file(self, filename: str, text: str, ticked: list[str] = ()) -> tuple[Page, Page]:
        """Follow Import from the Network page, upload the file and confirm; the preview and the page after."""
        upload = self.get(self.get(self.get("/").link("Network")).link("Import"))
        form = upload.form("Upload")
        preview = self.submit(form, files={form.files[0]: (filename, text.encode(), "text/csv")})
        confirm = next(f for f in preview.forms if any(b.startswith("Import ") for b in f.buttons))
        return preview, self.submit(confirm, ticked)

    def card(self, page: Page, name: str) -> Scope:
        return page.scope(name, "fn-card")

    def walk_import(self) -> None:
        home = self.get("/")
        self.assertIn("Your network is empty", home.words)
        upload = self.get(home.link("Import"))
        form = upload.form("Upload")
        preview = self.submit(form, files={form.files[0]: ("contacts.csv", CONTACTS.encode(), "text/csv")})
        self.assertIn("Check contacts.csv", preview.words)
        self.assertIn("5 new people 1 row skipped", preview.words)
        self.assertIn("Row 4 has no name, so FN skips it.", preview.words)
        self.assertIn("Row 7. FN cannot find Nergensdorp, Belgium on the map, so this person will not be on the map.",
                      preview.words)
        after = self.submit(preview.form("Import 5 people"))
        self.assertIn("5 people imported from contacts.csv.", after.words)
        shown = self.get(after.link("Show them"))
        self.assertEqual(self.row_names(shown), [*PLACED, "Eli Nowhere"])
        self.assertEqual(shown.scope("", "fn-count").words, "5 people · 1 not on the map · Export these 5 Clear all")
        points = self.client.get(shown.attr("data-geo")).json()["features"]
        self.assertEqual(sorted(p["properties"]["name"] for p in points), PLACED)

    def walk_search(self) -> None:
        self.member("Nora Network", "nora", "Offshore wind")
        gate = threading.Event()
        self.addCleanup(gate.set)
        lanes = [lane("seeds", [found("Nora Network", "nora", "Wind farms")]),
                 lane("web", [found("Pim Newcomer", "pim", "Wind turbines")], gate)]
        with mock.patch("fn.search.LANES", lanes):
            running = self.submit(self.get("/").form("Search"), question="Who knows wind?")
            self.assertIn("Searching…", running.words)
            self.assertEqual(self.wait(running, lambda s: s["version"] >= 1),
                             {"status": "running", "people": 1, "version": 1})
            gate.set()
            self.assertEqual(self.wait(running)["status"], "done")
        page = self.get(str(running.url))
        words = page.words
        self.assertLess(words.index("In your network 1"), words.index("Nora Network"))
        self.assertLess(words.index("Nora Network"), words.index("New 1"))
        self.assertLess(words.index("New 1"), words.index("Pim Newcomer"))
        self.assertEqual(self.card(page, "Nora Network").forms, [])
        self.assertEqual([f.buttons for f in self.card(page, "Pim Newcomer").forms], [["Add"], ["Skip"]])

    def walk_decide(self) -> None:
        self.member("Ada Example", "ada", "Wind policy")
        people = [found("Bo Adder", "bo", "Wind tunnels"), found("Ada Example", "ada-2", "Wind law"),
                  found("Cy Skipper", "cy", "Wind maps")]
        with mock.patch("fn.search.LANES", [lane("seeds", people)]):
            first = self.ask("Who knows wind?")
            other_url = str(self.ask("Who knows wind power?").url)
        added = self.submit(first.form("Add", self.card(first, "Bo Adder")))
        self.assertIn("Added to your network", self.card(added, "Bo Adder").words)
        self.assertIn("Bo Adder", self.network_names())
        twin = self.card(added, "Ada Example")
        self.assertIn("Same name as Ada Example in your network", twin.words)
        merged = self.submit(added.form("Same person", twin))
        self.assertIn("same person as Ada Example", self.card(merged, "Ada Example").words)
        self.assertEqual(self.network_names().count("Ada Example"), 1)
        profile = self.get(merged.link("Ada Example", self.card(merged, "Ada Example")))
        self.assertIn("Wind policy", profile.words)
        self.assertIn("Wind law", profile.words)
        self.assertIn("Sources", profile.words)
        self.assertEqual(sum(1 for s in profile.scopes if "fn-line" in s.attrs.get("class", "").split()
                             and "· 1 fact" in s.words), 2)
        skipped = self.submit(merged.form("Skip", self.card(merged, "Cy Skipper")))
        self.assertEqual(self.card(skipped, "Cy Skipper").words, "Skipped Cy Skipper Undo")
        other = self.get(other_url)
        self.assertFalse(other.has_scope("Cy Skipper", "fn-card"))
        self.assertIn("1 skipped person hidden Show", other.words)
        undone = self.submit(skipped.form("Undo", self.card(skipped, "Cy Skipper")))
        self.assertEqual([f.buttons for f in self.card(undone, "Cy Skipper").forms], [["Add"], ["Skip"]])
        again = self.get(other_url)
        self.assertTrue(again.has_scope("Cy Skipper", "fn-card"))
        self.assertNotIn("skipped person hidden", again.words)

    def walk_new_facts(self) -> None:
        orcid = "0000-0002-1825-0097"
        self.member("Nell Known", orcid, "Tidal power", scheme="orcid")
        with mock.patch("fn.search.LANES", [lane("seeds", [found("Nell Known", orcid, "Wind leases", "orcid")])]):
            self.ask("Who knows wind?")
        people = self.get(self.get("/").link("Network"))
        row = people.scope("Nell Known", "fn-row")
        self.assertIn("1 new fact", row.words)
        profile = self.get(people.link("Nell Known", row))
        self.assertEqual(profile.scope("Wind leases", "fn-claim").words.split()[0], "New")
        self.assertNotEqual(profile.scope("Tidal power", "fn-claim").words.split()[0], "New")
        again = self.get(str(profile.url))
        fact = again.scope("Wind leases", "fn-claim")
        self.assertNotEqual(fact.words.split()[0], "New")
        removed = self.submit(again.form("Not correct", fact))
        line = removed.scope("", "fn-claim--removed")
        self.assertIn("Undo", line.words)
        self.assertFalse(removed.has_scope("Wind leases is what", "fn-claim"))
        restored = self.submit(removed.form("Undo", line))
        self.assertEqual(restored.form("Not correct", restored.scope("Wind leases", "fn-claim")).buttons, ["Not correct"])

    def walk_browse(self) -> None:
        self.import_file("contacts.csv", CONTACTS)
        everyone = self.get(self.get("/").link("Network"))
        self.assertEqual(len(self.client.get(everyone.attr("data-geo")).json()["features"]), 4)
        boston = self.submit(everyone.form("Filter"), q="Boston")
        self.assertEqual(self.row_names(boston), ["Ann Harbor"])
        (point,) = self.client.get(boston.attr("data-geo")).json()["features"]
        profile = self.get(point["properties"]["href"])
        self.assertIn("Ann Harbor", profile.words)
        facts = [s for s in profile.scopes if "fn-claim" in s.attrs.get("class", "").split()]
        self.assertGreaterEqual(len(facts), 2)
        for fact in facts:
            with self.subTest(fact=fact.words):
                (label, href), = fact.links
                self.assertTrue(label.startswith("Import contacts.csv"), label)
                source = self.get(href)
                self.assertIn('<p id="quote" class="fn-source__lead text-body">', source.html)
                self.assertIn('<h1 class="fn-source__title text-title">Ann Harbor</h1>', source.html)

    def walk_reopen(self) -> None:
        people = [found("Gus Alpha", "gus", "Wind cables"), found("Hal Beta", "hal", "Wind ports"),
                  found("Ivo Gamma", "ivo", "Wind ships")]
        with mock.patch("fn.search.LANES", [lane("seeds", people)]):
            for question in ("Who knows wind energy?", "Who knows wind farms?", "Who knows wind parks?"):
                self.ask(question)
            last = self.ask("Who knows wind power?")
        for name in ("Gus Alpha", "Hal Beta"):
            last = self.submit(last.form("Add", self.card(last, name)))
        self.submit(last.form("Skip", self.card(last, "Ivo Gamma")))
        searches = self.get(self.get("/").link("All searches"))
        old = self.get(searches.link("Who knows wind energy?"))
        for name in ("Gus Alpha", "Hal Beta"):
            self.assertIn("Added to your network", self.card(old, name).words)
        self.assertFalse(old.has_scope("Ivo Gamma", "fn-card"))
        self.assertIn("1 skipped person hidden Show", old.words)

    def export(self, href: str) -> list[list[str]]:
        response = self.client.get(href)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/csv"))
        return list(csv.reader(io.StringIO(response.text.removeprefix("﻿"))))

    def walk_export(self) -> None:
        self.import_file("contacts.csv", CONTACTS)
        everyone = self.get(self.get("/").link("Network"))
        header, *rows = self.export(everyone.link("Export"))
        self.assertEqual(header[:len(IMPORT_COLUMNS)], list(IMPORT_COLUMNS))
        self.assertEqual(len(rows), 5)
        ann = dict(zip(header, next(r for r in rows if r[0] == "Ann Harbor")))
        self.assertEqual([ann[c] for c in ("email", "organization", "role", "city", "state", "country")],
                         ["ann@example.org", "Harbor Labs", "Engineer", "Boston", "MA", "USA"])
        usa = self.submit(everyone.form("Filter"), q="USA")
        count = int(re.match(r"(\d+) (?:person|people)", usa.scope("", "fn-count").words).group(1))
        self.assertEqual(count, 3)
        self.assertEqual(len(self.export(usa.link(f"Export these {count}"))[1:]), count)
        text = self.client.get(everyone.link("Export")).text
        before = self.network_names()
        self.import_file("fn-network.csv", text, ticked=["merge", "same_all"])
        self.assertEqual(self.network_names(), before)


class ImportFlowTest(FlowTest):
    def test_an_imported_csv_lists_its_people_and_puts_each_found_city_on_the_map(self):
        """From an empty Home, Import leads to a preview that counts the rows and skips the nameless one.

        Confirm adds the five people, Show them lists exactly them, and their map data has a point per known city.
        """
        self.walk_import()


class SearchFlowTest(FlowTest):
    def test_a_search_shows_progress_then_network_people_first_and_new_people_with_add_and_skip(self):
        """While a lane still runs, the status the page names reports the first lane's people.

        At the end the network person stands under In your network without buttons, the new one has Add and Skip.
        """
        self.walk_search()


class DecideFlowTest(FlowTest):
    def test_add_same_person_skip_and_undo_from_a_search_change_the_network_and_other_searches(self):
        """Add puts the person on the Network page, Same person makes one person of both records.

        Skip hides the person on another search behind the skipped line, and Undo brings the card back.
        """
        self.walk_decide()


class NewFactsFlowTest(FlowTest):
    def test_a_fact_a_later_search_finds_is_marked_new_once_and_can_be_removed_and_restored(self):
        """A lane's claim on a network person's identifier counts as a new fact on the Network row.

        The profile marks it New on the first visit only, and Remove with Undo hides and restores it.
        """
        self.walk_new_facts()


class BrowseFlowTest(FlowTest):
    def test_a_place_filter_narrows_the_map_and_a_point_opens_a_profile_with_its_sources(self):
        """The filter narrows the rows and the map data alike, and a point's link opens that person's profile.

        Every fact on the profile names its source and links to a Source page that marks the quote.
        """
        self.walk_browse()


class ReopenFlowTest(FlowTest):
    def test_an_old_search_from_all_searches_shows_who_was_added_or_skipped_since(self):
        """All searches leads back to an old search, whose cards show today's decisions.

        People added from a later search read Added to your network, and a skipped one is hidden and counted.
        """
        self.walk_reopen()


class ExportFlowTest(FlowTest):
    def test_the_export_holds_the_listed_people_and_imports_again_into_the_same_network(self):
        """Export writes the import columns first and one row per person; a filtered export matches its count line.

        Importing the export with every name match ticked leaves the network with the same people.
        """
        self.walk_export()


class NeverShownTest(FlowTest):
    def test_no_page_a_flow_visits_shows_a_score_a_lane_a_traceback_or_a_debug_link(self):
        """Every staff page the seven flows open is free of scores, lane names, tracebacks and links to /debug.

        Each flow runs on its own fresh network.
        """
        walks = [self.walk_import, self.walk_search, self.walk_decide, self.walk_new_facts, self.walk_browse,
                 self.walk_reopen, self.walk_export]
        for walk in walks:
            with self.subTest(flow=walk.__name__):
                self.start()
                walk()
        self.assertGreater(len(self.pages), 30)
        for url, html in self.pages.items():
            with self.subTest(url=url):
                self.assertIsNone(FORBIDDEN.search(html))


if __name__ == "__main__":
    unittest.main()
