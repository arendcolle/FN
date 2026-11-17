import logging
import unittest
from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx
from pydantic import BaseModel

from fn import extract, geo, llm, rank
from fn.contracts import (
    ClaimDraft,
    DeathsOut,
    Identifier,
    LLMResult,
    Located,
    PageRelation,
    Source,
    Span,
    clean_name,
    page_source,
)
from fn.steps import StepContext
from fn.worker import new_id, now
from tests.helpers import cities_zip, make_db, make_settings

URL = "https://events.example.org/belgium-6g-roundtable"
READ = datetime(2026, 11, 3, tzinfo=UTC)
SPEAKERS = ("Speakers\n\nJan Peeters, PhD, KU Leuven\nEls Janssens, PhD, KU Leuven\n\n"
            "Moderator: Wim Doe was born in Ghent and studied at Ghent University from 1990 to 1994.")


def relation(kind: str, org: str, quote: str, year_from: int | None = None, year_to: int | None = None) -> dict:
    return {"relation": kind, "org": org, "quote": quote, "year_from": year_from, "year_to": year_to}


def mention(name: str, quote: str, role: str | None = None, *relations: dict, topics: list[dict] | None = None) -> dict:
    found = {"name": name, "quote": quote, "role": role, "relations": list(relations)}
    return found | {"topics": topics} if topics is not None else found


def by_marker(answers: dict[str, list[dict]]) -> Callable[[str], list[dict]]:
    """The people of the first marker the chunk holds, else nobody."""
    return lambda page: next((people for marker, people in answers.items() if marker in page), [])


class PageLLM:
    """Keeps each chunk, renders the user turn as ClaudeCli and FixtureLLM do, then answers {"people": answer(chunk)}.

    A chunk holding a marker of errors raises that marker's error instead.
    """

    def __init__(self, answer: Callable[[str], object] = lambda page: [], errors: dict[str, Exception] | None = None):
        self.answer, self.errors, self.pages = answer, errors or {}, []

    def structured[T: BaseModel](self, task: str, data: dict[str, str], schema: type[T]) -> LLMResult[T]:
        self.pages.append(data["page"])
        llm.user_turn(data)
        for marker, error in self.errors.items():
            if marker in data["page"]:
                raise error
        return LLMResult[schema](value=schema.model_validate({"people": self.answer(data["page"])}), model="stub",
                                 cost_usd=0.0, tokens_in=0, tokens_out=0, billing="stub")


class RecordingLLM(PageLLM):
    """PageLLM that also keeps each call's (task, data)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data = []

    def structured(self, task, data, schema):
        self.data.append((task, dict(data)))
        return super().structured(task, data, schema)


def topic(topic_: str, quote: str) -> dict:
    return {"topic": topic_, "quote": quote}


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)

    def source(self, text: str = SPEAKERS, title: str | None = "Belgium 6G roundtable", url: str = URL) -> Source:
        return page_source(url, title, text, {}, READ, None)

    def mentions(self, people: list[dict], source: Source | None = None, page_llm: PageLLM | None = None):
        """extract.mentions over the source with a stub that answers people for every chunk."""
        self.llm = page_llm or PageLLM(lambda page: people)
        ctx = StepContext(search_id="s", store=self.store, llm=self.llm, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        return extract.mentions(ctx, source or self.source())

    def drafted(self, people: list[dict], source: Source | None = None) -> list[tuple]:
        """The claim drafts of every located mention as (kind, relation, org_id, value, quote, dates, lat, lon)."""
        source = source or self.source()
        found, _ = self.mentions(people, source)
        return [(d.kind, d.relation, d.org_id, d.value, d.quote, d.valid_from, d.valid_to, d.claim_date,
                 d.date_precision, d.date_method, d.lat, d.lon)
                for located in found for d in extract.drafts("p", source, located)]

    def test_a_page_fn_read_dates_its_claims_and_stated_years_still_win(self):
        """A claim without stated years takes the read page's date and method; a vendor page leaves it undated."""
        text = "Jan Peeters, PhD, KU Leuven, studied at Ghent University from 1990 to 1994"
        people = [mention("Jan Peeters", text, "PhD", relation("works_at", "KU Leuven", "PhD, KU Leuven"),
                          relation("studied_at", "Ghent University", "studied at Ghent University from 1990 to 1994", 1990, 1994))]
        read = page_source(URL, "Team", text, {}, READ, "2026-11-13", kind="page", plain=True, date_method="read_date")
        dates = [(d.relation, d.claim_date, d.date_precision, d.date_method) for d in
                 (row for row in self.dated(people, read))]
        self.assertEqual(dates, [(None, "2026-11-13", "day", "read_date"), ("works_at", "2026-11-13", "day", "read_date"),
                                 ("studied_at", "1994", "year", "stated_in_quote")])
        self.assertEqual({d.claim_date for d in self.dated(people, self.source(text, "Team"))}, {None, "1994"})

    def dated(self, people: list[dict], source: Source) -> list:
        found, _ = self.mentions(people, source)
        return [d for located in found for d in extract.drafts("p", source, located)]

    def test_locate_finds_exact_text_across_line_breaks_with_curly_apostrophes_and_only_inside_its_range(self):
        """Offsets point into the text, so text[start:end] is the quote as stored, whatever spacing the model used.

        A quote outside text[start:end] is not found, and neither is text the page does not hold.
        """
        text = "Wim Doe's lab\nis at KU Leuven.\n\nJan Peeters,\nPhD, KU Leuven"
        self.assertEqual(extract.locate(text, "is at KU Leuven"), (14, 29))
        start, end = extract.locate(text, "Jan Peeters, PhD")
        self.assertEqual(text[start:end], "Jan Peeters,\nPhD")
        self.assertEqual(extract.locate(text, "Wim Doe’s  lab is"), (0, 16))
        self.assertIsNone(extract.locate(text, "Jan Peters"))
        self.assertIsNone(extract.locate(text, " \n"))
        self.assertEqual(extract.locate(text, "KU Leuven", 30), (50, 59))
        self.assertIsNone(extract.locate(text, "KU Leuven", 0, 28))
        self.assertIsNone(extract.locate(text, "Jan Peeters, PhD", 0, 44))
        self.assertEqual(extract.locate(text, "Jan Peeters, PhD", 0, 49), (32, 48))

    def test_two_speakers_sharing_a_phrase_each_get_the_phrase_after_their_own_name(self):
        """A relation quote is looked for from the start of its mention quote, so equal lines keep their own offsets.

        Each speaker's relation lies after their own name, never on the line of the speaker before.
        """
        jan, els = SPEAKERS.index("Jan Peeters"), SPEAKERS.index("Els Janssens")
        works = relation("works_at", "KU Leuven", "PhD, KU Leuven")
        found, considered = self.mentions([mention("Jan Peeters", "Jan Peeters, PhD, KU Leuven", None, works),
                                           mention("Els Janssens", "Els Janssens, PhD, KU Leuven", None, works)])
        rel = PageRelation.model_validate(works)
        self.assertEqual(found, [
            Located(name="Jan Peeters", span=Span(start=jan, end=jan + 27),
                    relations=[(rel, Span(start=jan + 13, end=jan + 27))]),
            Located(name="Els Janssens", span=Span(start=els, end=els + 28),
                    relations=[(rel, Span(start=els + 14, end=els + 28))]),
        ])
        self.assertEqual(considered, [])

    def test_a_relation_whose_org_the_quote_does_not_name_is_dropped_and_an_alias_spelling_counts(self):
        """The org must stand in its quote, as written or as a spelling the alias file gives its org id.

        A relation whose quote does not name its org is dropped with a row; the others on the mention stay.
        """
        found, considered = self.mentions([mention(
            "Jan Peeters", "Jan Peeters, PhD, KU Leuven", None, relation("works_at", "imec", "PhD, KU Leuven"),
            relation("studied_at", "Katholieke Universiteit Leuven", "PhD, KU Leuven"))])
        (located,) = found
        self.assertEqual([(r.org, r.relation) for r, _ in located.relations],
                         [("Katholieke Universiteit Leuven", "studied_at")])
        self.assertEqual([(c.person_key, c.name, c.stage, c.kept, c.reason) for c in considered], [
            (f"{URL}#jan peeters", "Jan Peeters", "relation", False,
             "org not in quote: works_at 'imec', quote 'PhD, KU Leuven'")])

    def test_a_mention_whose_name_or_quote_fails_is_dropped_with_its_reason(self):
        """A mention is kept only when its quote is in the chunk, holds the cleaned name, and the name has two words.

        Whitespace the model changed still matches; each dropped mention has a row with its reason.
        """
        found, considered = self.mentions([
            mention("Jan Peeters", "Els Janssens, PhD, KU Leuven"),
            mention("Els Janssens", "Els Janssens, Ph.D., University of Leuven"),
            mention("Prof. Peeters", "Jan Peeters, PhD, KU Leuven"),
            mention("Els Janssens", "Els  Janssens, PhD"),
        ])
        self.assertEqual([(f.name, SPEAKERS[f.span.start:f.span.end]) for f in found],
                         [("Els Janssens", "Els Janssens, PhD")])
        self.assertEqual([(c.name, c.stage, c.reason) for c in considered], [
            ("Jan Peeters", "mention", "name not in quote: 'Els Janssens, PhD, KU Leuven'"),
            ("Els Janssens", "mention", "quote not found: 'Els Janssens, Ph.D., University of Leuven'"),
            ("Peeters", "mention", "name has fewer than two words: 'Prof. Peeters'"),
        ])

    def test_a_relation_quote_before_the_mention_beyond_1500_characters_or_in_another_chunk_is_dropped(self):
        """A relation quote counts only in the 1,500 characters from the mention quote's start, inside its own chunk.

        Text before the mention, further away or in the next chunk drops the relation with its reason.
        """
        moved = relation("worked_at", "KU Leuven", "moved to KU Leuven")
        not_near = "relation quote not near the mention: worked_at 'KU Leuven', quote 'moved to KU Leuven'"
        jan = mention("Jan Peeters", "Jan Peeters works at imec.", None, relation("works_at", "imec", "works at imec"),
                      moved)
        far = "Jan Peeters works at imec.\n\n" + "Filler line.\n" * 125 + "Later: Jan Peeters moved to KU Leuven."
        near = "f" * 5960 + "\nJan Peeters works at imec.\n\nLater: Jan Peeters moved to KU Leuven."
        self.assertGreater(far.index("moved to KU Leuven"), 1500)
        for text in (far, near):
            with self.subTest(text=text[:20]):
                stub = PageLLM(by_marker({"works at imec": [jan]}))
                found, considered = self.mentions([], self.source(text), stub)
                self.assertEqual([r.org for r, _ in found[0].relations], ["imec"])
                self.assertEqual([c.reason for c in considered], [not_near])
        self.assertEqual(len(stub.pages), 2)
        els = mention("Els Janssens", "Els Janssens, PhD, KU Leuven", None,
                      relation("works_at", "KU Leuven", "Jan Peeters, PhD, KU Leuven"))
        found, considered = self.mentions([els])
        self.assertEqual((found[0].relations, [c.reason for c in considered]), ([], [
            "relation quote not near the mention: works_at 'KU Leuven', quote 'Jan Peeters, PhD, KU Leuven'"]))

    def test_two_relations_that_would_be_one_claim_keep_the_first_and_every_draft_is_stored(self):
        """Relations of one mention with the same claim kind, org and quote start would share one stored claim.

        The first is kept and each later one dropped with a row naming it, so every draft is its own claim.
        """
        text = "Wim Doe was born and lives in Ghent, and studied and works at KU Leuven."
        source = self.source(text)
        found, considered = self.mentions([mention(
            "Wim Doe", text, None, relation("born_in", "Ghent", "born and lives in Ghent"),
            relation("lives_in", "Ghent", "born and lives in Ghent"),
            relation("studied_at", "KU Leuven", "studied and works at KU Leuven"),
            relation("works_at", "KU Leuven", "studied and works at KU Leuven"),
            relation("works_at", "KU Leuven", "works at KU Leuven"))], source)
        (located,) = found
        self.assertEqual([(r.relation, s.start) for r, s in located.relations],
                         [("born_in", 12), ("studied_at", 41), ("works_at", 53)])
        self.assertEqual([c.reason for c in considered], ["same claim as born_in 'Ghent': lives_in 'Ghent'",
                                                          "same claim as studied_at 'KU Leuven': works_at 'KU Leuven'"])
        person = self.store.resolve_person([extract.identifier(URL, "Wim Doe")], "Wim Doe")
        drafts = extract.drafts(person.id, source, located)
        for draft in drafts:
            self.store.upsert_claim(draft)
        self.assertCountEqual([(c.kind, c.relation, c.value, c.quote_start) for c in self.store.claims_of([person.id])],
                              [(d.kind, d.relation, d.value, d.quote_start) for d in drafts])

    def test_a_name_or_org_inside_a_longer_word_or_a_year_inside_a_longer_number_does_not_count(self):
        """Names and orgs count only as whole words of their quote, and a year only as four digits on their own.

        Otherwise the mention or relation is dropped with its reason, and the year leaves the claim undated.
        """
        text = "Jan Peetersen, PhD, KU Leuven\nWim Doe works at Smith Labs, room 19901, KU Leuven."
        wim = "Wim Doe works at Smith Labs, room 19901, KU Leuven."
        for case, people, dates, reasons in (
            ("name", [mention("Jan Peeters", "Jan Peetersen, PhD, KU Leuven")], [],
             ["name not in quote: 'Jan Peetersen, PhD, KU Leuven'"]),
            ("org", [mention("Wim Doe", wim, None, relation("works_at", "MIT", "works at Smith Labs"))], [[]],
             ["org not in quote: works_at 'MIT', quote 'works at Smith Labs'"]),
            ("year", [mention("Wim Doe", wim, None, relation("works_at", "KU Leuven", "room 19901, KU Leuven", 1990))],
             [[None]], []),
        ):
            with self.subTest(case=case):
                source = self.source(text)
                found, considered = self.mentions(people, source)
                self.assertEqual([[d.claim_date for d in extract.drafts("p", source, f)[1:]] for f in found], dates)
                self.assertEqual([c.reason for c in considered], reasons)

    def test_drafts_give_a_role_claim_then_an_affiliation_or_location_claim_per_relation(self):
        """KU Leuven and Ghent University get their alias-file ids; born_in is a location claim with no coordinates.

        Only years whose digits stand in the relation's quote date a claim, with the later one as its date.
        """
        moderator = "Moderator: Wim Doe was born in Ghent and studied at Ghent University from 1990 to 1994."
        studied = "studied at Ghent University from 1990 to 1994"
        undated = (None,) * 7
        self.assertEqual(self.drafted([
            mention("Wim Doe", moderator, "Moderator", relation("born_in", "Ghent", "Wim Doe was born in Ghent"),
                    relation("studied_at", "Ghent University", studied, 1990, 1994)),
            mention("Jan Peeters", "Jan Peeters, PhD, KU Leuven", "  ",
                    relation("works_at", "KU Leuven", "PhD, KU Leuven")),
        ]), [
            ("role", None, None, "Moderator", moderator, *undated),
            ("location", "born_in", None, "Ghent", "Wim Doe was born in Ghent", *undated),
            ("affiliation", "studied_at", "ror:00cv9y106", "Ghent University", studied,
             "1990", "1994", "1994", "year", "stated_in_quote", None, None),
            ("role", None, None, "Belgium 6G roundtable", "Jan Peeters, PhD, KU Leuven", *undated),
            ("affiliation", "works_at", "ror:05f950310", "KU Leuven", "PhD, KU Leuven", *undated),
        ])

    def test_an_origin_relation_is_a_location_claim_without_coordinates_that_locate_stored_leaves(self):
        """Belgian in 'Belgian chocolatier Ann Example' is a location claim with relation origin and no place to find."""
        text = "Belgian chocolatier Ann Example opened a shop."
        source = self.source(text)
        found, considered = self.mentions([mention("Ann Example", text, "chocolatier",
                                                   relation("origin", "Belgian", "Belgian chocolatier"))], source)
        (draft,) = [d for d in extract.drafts("p", source, found[0]) if d.kind == "location"]
        self.assertEqual((draft.relation, draft.value, draft.lat, draft.lon, draft.quote_start, considered),
                         ("origin", "Belgian", None, None, 0, []))
        person = self.store.resolve_person([Identifier(scheme="mention", value="m1")], "Ann Example")
        claim = self.store.upsert_claim(draft.model_copy(update={"person_id": person.id}))
        self.assertEqual(extract.locate_stored(self.store, geo.from_zip(cities_zip())), 0)
        self.assertIsNone(self.store.get_claim(claim.id).lat)

    def test_a_kept_topic_is_an_undated_topic_claim_at_its_quote(self):
        """A topic found in its quote near the mention gives a topic claim with the quote's own offsets."""
        text = "Intro line.\nProf. Jan Peeters, professor of wireless networks at KU Leuven"
        source = self.source(text)
        found, considered = self.mentions([mention("Jan Peeters", "Jan Peeters, professor of wireless networks", None,
                                                   topics=[topic("Wireless Networks", "professor of wireless networks")])],
                                          source)
        (draft,) = [d for d in extract.drafts("p", source, found[0]) if d.kind == "topic"]
        start = text.index("professor of")
        self.assertEqual((draft.value, draft.quote, draft.quote_start, draft.claim_date, draft.valid_from, considered),
                         ("Wireless Networks", "professor of wireless networks", start, None, None, []))

    def test_a_topic_is_dropped_with_its_reason_when_the_quote_is_far_missing_or_lacks_it_or_repeats(self):
        """A quote past NEAR_CHARS, absent from the chunk, without the topic words or the same twice leaves one row each."""
        far = "x" * (extract.NEAR_CHARS + 500)
        text = f"Jan Peeters, professor of wireless networks\n{far}\nHe also studies optics and photonics."
        quote = "professor of wireless networks"
        cases = [
            (topic("optics", "studies optics and photonics"),
             "topic quote not near the mention: 'optics', quote 'studies optics and photonics'"),
            (topic("optics", "invented quote"), "topic quote not near the mention: 'optics', quote 'invented quote'"),
            (topic("antennas", quote), f"topic not in quote: 'antennas', quote {quote!r}"),
            (topic("wireless", quote), None),
            (topic("Wireless", quote), "same topic as before: 'Wireless'"),
            (topic("   ", quote), f"topic not in quote: '   ', quote {quote!r}"),
        ]
        found, considered = self.mentions([mention("Jan Peeters", "Jan Peeters, professor of wireless networks", None,
                                                   topics=[t for t, _ in cases])], self.source(text))
        self.assertEqual([c.reason for c in considered], [r for _, r in cases if r])
        self.assertTrue(all(c.stage == "topic" and not c.kept for c in considered))
        self.assertEqual([t for t, _ in found[0].topics], ["wireless"])

    def test_a_mention_with_no_topics_gives_no_topic_claim(self):
        """A page with no topics, as an answer from before this round, gives the role claim and nothing else."""
        source = self.source()
        found, _ = self.mentions([mention("Jan Peeters", "Jan Peeters, PhD, KU Leuven")], source)
        self.assertEqual([d.kind for d in extract.drafts("p", source, found[0])], ["role"])

    def test_a_year_the_quote_does_not_state_leaves_the_claim_undated(self):
        """A year whose digits are not in the relation's quote does not date the claim.

        With no stated year left the claim has no date and counts as one undated unit; a stated one stays.
        """
        source = self.source()
        person = self.store.resolve_person([Identifier(scheme="mention", value="x")], "Wim Doe")
        found, _ = self.mentions([mention(
            "Wim Doe", "Wim Doe was born in Ghent and studied at Ghent University from 1990 to 1994.", None,
            relation("studied_at", "Ghent University", "studied at Ghent University", 1990, 1994),
            relation("studied_at", "Ghent University", "Ghent University from 1990", 1990, 1995))], source)
        claims = [self.store.upsert_claim(d) for d in extract.drafts(person.id, source, found[0])][1:]
        self.assertEqual([(c.valid_from, c.valid_to, c.claim_date, c.date_method) for c in claims],
                         [(None, None, None, None), ("1990", None, "1990", "stated_in_quote")])
        self.assertEqual([rank.units(c) for c in claims], [frozenset({rank.UNDATED}), frozenset({"1990"})])

    def test_a_lives_in_claim_gets_the_coordinates_geo_finds_and_a_born_in_claim_none(self):
        """Only lives_in is placed on the map; a place geo cannot resolve stays without coordinates and is logged."""
        class Http:
            def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
                return httpx.Response(200, content=cities_zip())

        text = "Wim Doe was born in Boston and lives in Cambridge, Massachusetts. Jan Peeters lives in Nowhereville."
        source = self.source(text)
        found, _ = self.mentions([
            mention("Wim Doe", "Wim Doe was born in Boston and lives in Cambridge, Massachusetts", None,
                    relation("born_in", "Boston", "was born in Boston"),
                    relation("lives_in", "Cambridge, Massachusetts", "lives in Cambridge, Massachusetts")),
            mention("Jan Peeters", "Jan Peeters lives in Nowhereville", None,
                    relation("lives_in", "Nowhereville", "lives in Nowhereville"))], source)
        ctx = StepContext(search_id="s", store=self.store, llm=self.llm, http=Http(), now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        with self.assertLogs("fn.step", "INFO") as logs:
            places = [(d.relation, d.lat is not None) for f in found for d in extract.drafts("p", source, f, ctx)
                      if d.kind == "location"]
        self.assertEqual(places, [("born_in", False), ("lives_in", True), ("lives_in", False)])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Nowhereville", logs.output[0])
        (cambridge,) = [d for d in extract.drafts("p", source, found[0], ctx) if d.relation == "lives_in"]
        self.assertAlmostEqual(cambridge.lat, 42.38, places=1)
        self.assertAlmostEqual(cambridge.lon, -71.11, places=1)

    def test_stored_place_claims_without_coordinates_get_the_ones_geo_finds(self):
        """A city is located with or without a relation; a place that names no city and a birthplace are left.

        A second run fills none.
        """
        source = self.source("Wim Doe lives in Cambridge, Massachusetts, was born in Boston, stays in Nowhereville, "
                             "and his list row says Leuven.")
        person = self.store.resolve_person([Identifier(scheme="mention", value="m1")], "Wim Doe")
        ids = {}
        for relation_, place in (("lives_in", "Cambridge, Massachusetts"), ("lives_in", "Nowhereville"), ("born_in", "Boston"),
                                 (None, "Leuven")):
            start = source.text.index(place)
            ids[place] = self.store.upsert_claim(ClaimDraft(
                person_id=person.id, kind="location", relation=relation_, value=place, quote=place, quote_start=start,
                quote_end=start + len(place), source=source)).id
        self.assertEqual(extract.locate_stored(self.store, geo.from_zip(cities_zip())), 2)
        placed = {place: self.store.get_claim(i).lat for place, i in ids.items()}
        self.assertAlmostEqual(placed.pop("Cambridge, Massachusetts"), 42.38, places=1)
        self.assertAlmostEqual(placed.pop("Leuven"), 50.88, places=1)
        self.assertEqual(placed, {"Nowhereville": None, "Boston": None})
        self.assertEqual(extract.locate_stored(self.store, geo.from_zip(cities_zip())), 0)

    def test_a_role_falls_back_to_the_page_title_then_the_host(self):
        """Every mention gives a role claim, even without a role.

        Its value is then the page title, or the page's host when the page has no title.
        """
        found, _ = self.mentions([mention("Jan Peeters", "Jan Peeters, PhD, KU Leuven")])
        untitled = self.source(title=None)
        self.assertEqual([d.value for d in extract.drafts("p", self.source(), found[0])], ["Belgium 6G roundtable"])
        self.assertEqual([d.value for d in extract.drafts("p", untitled, found[0])], ["events.example.org"])

    def test_a_page_of_13000_characters_takes_three_calls_of_whole_lines_and_a_long_paragraph_splits_at_a_line(self):
        """Chunks hold at most 6,000 characters, pack whole paragraphs, and cut a longer paragraph at a line break.

        Long runs of short lines, such as menus, pack into few calls; together the chunks hold all of the text.
        """
        menu = "\n".join(f"* Menu item {i:03d}" for i in range(200))
        table = "\n".join(f"{i:02d} " + "x" * 96 for i in range(70))
        footer = "\n".join(f"* Footer {i:05d}" for i in range(190))
        text = f"{menu}\n\n{table}\n\n{footer}"
        self.assertGreaterEqual(len(text), 13000)
        self.assertGreater(len(table), 6000)
        self.mentions([], self.source(text))
        pages = sorted(self.llm.pages, key=text.index)
        self.assertEqual(len(pages), 3)
        self.assertTrue(all(len(p) <= 6000 for p in pages), [len(p) for p in pages])
        for page in pages:
            at = text.index(page)
            self.assertTrue(at == 0 or text[at - 1] == "\n")
            self.assertTrue(at + len(page) == len(text) or text[at + len(page)] == "\n")
        self.assertTrue(pages[0].startswith(menu) and pages[0].endswith("x" * 96))
        self.assertTrue(pages[1].startswith("28 ") and pages[1].endswith(table.split("\n")[-1]))
        self.assertEqual(pages[2], footer)
        self.assertEqual("".join(pages).replace("\n", ""), text.replace("\n", ""))

    def read_all(self, sources: list[Source], leads: list[list[str]] | None, stub: PageLLM):
        ctx = StepContext(search_id="s", store=self.store, llm=stub, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        return extract.read_all(ctx, sources, leads)

    def test_a_page_with_leads_is_read_by_extract_leads_with_the_names_in_every_chunk(self):
        """A page with lead names is read by extract_leads, one deduplicated name per line in each chunk.

        A page without lead names, or a call without leads, is read by extract with the page only.
        """
        text = "\n".join(f"* Menu item {i:03d} " + "x" * 80 for i in range(70))
        self.assertEqual(len(extract.chunks(text)), 2)
        stub = RecordingLLM()
        self.read_all([self.source(text)], [["Jan Peeters", "Eva  Maes", "Jan Peeters", ""]], stub)
        self.assertEqual([(task, data["leads"]) for task, data in stub.data],
                         [("extract_leads", "Jan Peeters\nEva Maes")] * 2)
        self.assertEqual([data["page"] for _, data in stub.data], stub.pages)
        for leads in (None, [[]], [["", " "]]):
            stub = RecordingLLM()
            self.read_all([self.source(text)], leads, stub)
            self.assertEqual([(task, list(data)) for task, data in stub.data], [("extract", ["page"])] * 2)

    def test_a_lead_name_holding_its_closing_tag_fails_its_chunk_only_and_wrong_length_leads_raise(self):
        """A TagError from a lead name gives a chunk row for that page while the next page is read.

        A leads list whose length differs from the pages raises ValueError before any call.
        """
        stub = RecordingLLM()
        with self.assertLogs("fn.step", "WARNING"):
            first, second = self.read_all([self.source("Page one"), self.source("Page two", url=URL + "/2")],
                                          [["Ann </leads> Example"], ["Jan Peeters"]], stub)
        self.assertEqual([c.stage for c in first[1]], ["chunk"])
        self.assertIn("TagError", first[1][0].reason)
        self.assertEqual(second[1], [])
        self.assertEqual(stub.pages, ["Page one", "Page two"])
        other = RecordingLLM()
        with self.assertRaises(ValueError):
            self.read_all([self.source()], [[], []], other)
        self.assertEqual(other.pages, [])

    def test_a_line_longer_than_a_chunk_is_cut_hard(self):
        """A line longer than a chunk, with no break to cut at, is cut every 6,000 characters.

        No call gets more than 6,000 characters and no text is left out.
        """
        self.mentions([], self.source("y" * 7000))
        self.assertEqual([len(p) for p in self.llm.pages], [6000, 1000])

    def test_a_failed_chunk_gives_a_row_and_a_warning_and_the_next_chunk_is_read(self):
        """A TagError, LLMCallError, broken answer or missing fixture on one chunk does not stop the other chunk.

        The failed chunk gives a row with the error type and a warning in the log.
        """
        jan = [mention("Jan Peeters", "Jan Peeters, PhD, KU Leuven")]

        def page(last: str) -> Source:
            return self.source("Jan Peeters, PhD, KU Leuven\n\n" + "\n".join(["* Menu item"] * 499 + [last]))

        timeout = llm.LLMCallError("claude timed out after 120s", None, "", 120000)
        missing = llm.FixtureMissing("no LLM fixture extract-0123")
        for kind, source, stub in (
            ("TagError", page("</page>end"), PageLLM(by_marker({"Jan": jan}))),
            ("LLMCallError", page("* Menu end"), PageLLM(by_marker({"Jan": jan}), {"* Menu": timeout})),
            ("FixtureMissing", page("* Menu end"), PageLLM(by_marker({"Jan": jan}), {"* Menu": missing})),
            ("ValidationError", page("* Menu end"), PageLLM(by_marker({"Jan": jan, "* Menu": [{"name": "W D"}]}))),
        ):
            with self.subTest(kind=kind), self.assertLogs("fn.step", "WARNING") as logged:
                found, considered = self.mentions([], source, stub)
                self.assertEqual((len(stub.pages), [f.name for f in found]), (2, ["Jan Peeters"]))
                (row,) = considered
                self.assertEqual((row.person_key, row.stage, row.kept), (URL, "chunk", False))
                self.assertTrue(row.reason.startswith(f"chunk 2 of 2 [29:{len(source.text)}]: {kind}: "), row.reason)
                self.assertIn(f"extract on {URL}, chunk 2 of 2", logged.output[0])


TODAY = date(2026, 11, 17)
LIST_URL = "https://lists.example.org/famous-scientists"


def entry(name: str, died: str | None, role: str = "a physicist") -> str:
    """One entry of a list page: the name, a birth date, a Died line when died is set, then the name sentence."""
    return f"{name}\nBirthdate: March 3, 1901\n" + (f"Died: {died}\n" if died else "") + f"{name} was {role}.\n\n"


def sentence(text: str, name: str, after: int = 0) -> Span:
    """The span of the name sentence, the quote extract keeps for the person."""
    start = text.index(f"{name} was", after)
    end = text.find("\n", start)
    return Span(start=start, end=len(text) if end < 0 else end)


def died(text: str, *names: str, stored: tuple[str, ...] | None = None) -> dict[str, str]:
    """extract.deaths over a list page with each name's sentence as its quote; the year found by name."""
    source = page_source(LIST_URL, "Famous scientists", text, {}, READ, None, plain=True)
    people = {name: (name, [sentence(source.text, name)]) for name in (stored or names)}
    return {d.person_id: d.value for d in extract.deaths(source, people, TODAY)}


class DeathsTest(unittest.TestCase):
    def test_a_living_entry_between_two_dead_ones_gets_no_death_and_each_dead_one_its_own_year(self):
        """A death line counts only inside the person's own entry, which starts after the previous person's quote."""
        text = entry("Pieter Vanacker", "June 20, 1966") + entry("Lotte Verbist", None) + entry("Marc Dewulf", "May 26, 1922")
        self.assertEqual(died(text, "Pieter Vanacker", "Lotte Verbist", "Marc Dewulf"),
                         {"Pieter Vanacker": "1966", "Marc Dewulf": "1922"})

    def test_an_unknown_neighbour_s_death_line_within_600_characters_is_kept_out_by_the_surname_alone(self):
        """With no other quote on the page the entry is the 600 characters before the quote, and the surname must
        stand before the death line in it."""
        text = entry("Pieter Vanacker", "June 20, 1966") + entry("Lotte Verbist", None)
        self.assertLess(sentence(text, "Lotte Verbist").start - text.index("Died:"), extract.ENTRY_CHARS)
        self.assertEqual(died(text, stored=("Lotte Verbist",)), {})

    def test_an_unstored_dead_neighbour_keyed_by_its_mention_bounds_the_entry_and_gets_its_own_year(self):
        """A located person who is not stored still ends the entry of the person after them, even when both share
        a surname."""
        text = entry("Pieter Vanacker", "June 20, 1966") + entry("Lotte Vanacker", None)
        source = page_source(LIST_URL, None, text, {}, READ, None, plain=True)
        key = extract.identifier(LIST_URL, "Pieter Vanacker").value
        people = {key: ("Pieter Vanacker", [sentence(text, "Pieter Vanacker")]),
                  "p-lotte": ("Lotte Vanacker", [sentence(text, "Lotte Vanacker")])}
        self.assertEqual([(d.person_id, d.value) for d in extract.deaths(source, people, TODAY)], [(key, "1966")])

    def test_a_death_line_inside_another_person_s_quote_is_not_taken(self):
        """A line another person's quote covers belongs to that quote, not to the entry before it."""
        text = "Bert Aerts\nDied: 1950\nBert Aerts was a chemist, as was Carla Mertens.\n"
        source = page_source(LIST_URL, None, text, {}, READ, None, plain=True)
        carla = Span(start=text.index("Died:"), end=text.index(".\n") + 1)
        people = {"bert": ("Bert Aerts", [sentence(text, "Bert Aerts")]), "carla": ("Carla Mertens", [carla])}
        self.assertEqual(extract.deaths(source, people, TODAY), [])

    def test_a_death_line_without_a_year_or_with_a_future_year_and_died_in_prose_give_nothing(self):
        """Only a Died line whose first year has passed counts; a sentence saying died is no death line."""
        for text in (entry("Bert Aerts", "unknown"), entry("Bert Aerts", "January 1, 2031"),
                     "Bert Aerts\nHis brother died in 1966.\nBert Aerts was a chemist.\n"):
            with self.subTest(text=text):
                self.assertEqual(died(text, "Bert Aerts"), {})

    def test_an_infobox_row_counts_and_its_line_is_the_quote(self):
        """A table row '| Died | ... |' is a death line; the claim is dated by its year and quotes the row."""
        text = "Bert Aerts\n| Born | 4 May 1922 |\n| Died | 27 November 1977 (aged 55) |\nBert Aerts was a painter.\n"
        source = page_source(LIST_URL, None, text, {}, READ, None, plain=True)
        (draft,) = extract.deaths(source, {"bert": ("Bert Aerts", [sentence(text, "Bert Aerts")])}, TODAY)
        self.assertEqual((draft.kind, draft.value, draft.quote, draft.claim_date, draft.date_precision, draft.date_method),
                         ("death", "1977", "| Died | 27 November 1977 (aged 55) |", "1977", "year", "stated_in_quote"))

    def test_a_lifespan_after_the_surname_counts(self):
        """'(1894–1966)' after the surname, in the entry before the quote or inside it, gives the second year."""
        for text in ("Bert Aerts (1894–1966)\nBert Aerts was a physicist.\n",
                     "Bert Aerts was a physicist. Aerts (1894 — 1966) taught in Ghent.\n"):
            with self.subTest(text=text):
                self.assertEqual(died(text, "Bert Aerts"), {"Bert Aerts": "1966"})

    def test_an_org_s_dates_a_birth_year_and_a_tenure_are_no_lifespan(self):
        """Years after another name, a single year, two years less than 25 apart or without a dash between them, and
        three years are not a life."""
        for text in ("Bert Aerts was a member of the Example Society (1830-1930).\n",
                     "Bert Aerts was born in Ghent. Bert Aerts (born 1959) is a designer.\n",
                     "Bert Aerts was chair. Bert Aerts (2010–2015) led the board.\n",
                     "Bert Aerts was a painter. Bert Aerts (born 1894, moved 1950) lived in Ghent.\n",
                     "Bert Aerts was a painter. Bert Aerts (1894–1966, 1970) lived in Ghent.\n"):
            with self.subTest(text=text):
                self.assertEqual(died(text, "Bert Aerts"), {})

    def test_a_death_line_wins_over_a_lifespan(self):
        """With both in the entry the Died line gives the year."""
        text = "Bert Aerts (1894–1970)\nDied: June 20, 1966\nBert Aerts was a physicist.\n"
        self.assertEqual(died(text, "Bert Aerts"), {"Bert Aerts": "1966"})

    def test_an_empty_page_gives_nothing(self):
        """A page without people gives no claim."""
        source = page_source(LIST_URL, None, "Nothing here.", {}, READ, None, plain=True)
        self.assertEqual(extract.deaths(source, {}, TODAY), [])

    def test_200_entries_each_get_their_own_death_or_none(self):
        """On a long list every second person died, and each takes only their own line."""
        names = [f"Person{n:03d} Surname{n:03d}" for n in range(200)]
        text = "".join(entry(name, f"May 1, {1900 + n % 100}" if n % 2 else None) for n, name in enumerate(names))
        self.assertEqual(died(text, *names), {name: str(1900 + n % 100) for n, name in enumerate(names) if n % 2})

    def test_a_rerun_over_stored_pages_finds_the_same_claims_and_adds_no_row(self):
        """deaths_stored reads every page's people without their death claims, so a rerun stores nothing new."""
        settings = make_settings(self)
        store = make_db(self, settings)
        source = page_source(LIST_URL, None, entry("Pieter Vanacker", "June 20, 1966") + entry("Lotte Verbist", None),
                             {}, READ, None, kind="page", plain=True)
        for name in ("Pieter Vanacker", "Lotte Verbist"):
            person = store.resolve_person([extract.identifier(LIST_URL, name)], name)
            span = sentence(source.text, name)
            store.upsert_claim(ClaimDraft(person_id=person.id, kind="role", value="physicist", quote=source.text[span.start:span.end],
                                          quote_start=span.start, quote_end=span.end, source=source))
        first = extract.deaths_stored(store, TODAY)
        rows = store.conn.execute("SELECT count(*) FROM claims").fetchone()[0]
        self.assertEqual((first, extract.deaths_stored(store, TODAY)), (DeathsOut(pages=1, deaths=1),) * 2)
        self.assertEqual(store.conn.execute("SELECT count(*) FROM claims").fetchone()[0], rows)


class PersonTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.text = "Faculty\nJan Peeters is professor of physics. Mail jan@example.org, phone +1 (617) 555-0100.\nOffice"

    def source(self, text: str) -> Source:
        return page_source(URL, "Faculty", text, {}, READ, "2026-10-01", kind="page", plain=True, date_method="page_date")

    def test_read_person_sends_the_person_with_every_chunk_and_keeps_each_mention(self):
        """Each chunk goes to extract_person with the person's name; a checked mention keeps its death year."""
        text = "\n".join(f"* Menu item {i:03d} " + "x" * 80 for i in range(70)) + "\n" + self.text
        jan = mention("Jan Peeters", "Jan Peeters is professor of physics.") | {"died": 2020}
        stub = RecordingLLM(by_marker({"Jan Peeters is": [jan]}))
        ctx = StepContext(search_id="s", store=None, llm=stub, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        [(found, considered)] = extract.read_person(ctx, [(self.source(text), "Jan Peeters")])
        self.assertEqual([(task, data["person"]) for task, data in stub.data], [("extract_person", "Jan Peeters")] * 2)
        self.assertEqual([(located.name, m.died) for located, m in found], [("Jan Peeters", 2020)])
        self.assertEqual(considered, [])

    def contacts(self, text: str, name: str = "Jan Peeters") -> list[tuple]:
        return [(d.kind, d.value) for d in extract.contacts("p1", self.source(text), name)]

    def test_contacts_keep_the_printed_email_and_phone_with_their_line_and_the_page_date(self):
        """The email and phone near the name become claims quoting their line, dated by the page."""
        found = extract.contacts("p1", self.source(self.text), "Jan Peeters")
        line = "Jan Peeters is professor of physics. Mail jan@example.org, phone +1 (617) 555-0100."
        self.assertEqual([(d.kind, d.value, d.quote, d.claim_date) for d in found],
                         [("email", "jan@example.org", line, "2026-10-01"),
                          ("phone", "+1 (617) 555-0100", line, "2026-10-01")])

    def test_an_address_with_the_surname_is_taken_however_far_the_name_is(self):
        far = "Jan Peeters is professor.\n" + "x " * 2000 + "\nMail jan.peeters@example.org."
        self.assertEqual(self.contacts(far), [("email", "jan.peeters@example.org")])

    def test_an_address_without_the_surname_is_taken_near_the_name_and_not_far_from_it(self):
        self.assertEqual(self.contacts("Jan Peeters, physics. Mail office@example.org"), [("email", "office@example.org")])
        self.assertEqual(self.contacts("Jan Peeters, physics.\n" + "x " * 400 + "\nMail office@example.org"), [])

    def test_a_department_address_near_another_persons_name_is_not_taken(self):
        self.assertEqual(self.contacts("Eva Claes, chair. Mail physics@example.org\nMore pages."), [])
        both = "Jan Peeters, professor.\nEva Claes, chair. Mail physics@example.org"
        self.assertEqual(self.contacts(both), [])
        self.assertEqual(self.contacts(both.replace("chair. Mail physics", "professor. eva.claes")), [])

    def test_the_address_with_the_surname_wins_over_one_that_only_stands_near_the_name(self):
        text = "Jan Peeters. Office office@example.org and jan.peeters@example.org and peeters.team@example.org"
        self.assertEqual(self.contacts(text), [("email", "jan.peeters@example.org")])
        self.assertEqual(self.contacts("Jan Peeters. Office office@example.org then other@example.org"),
                         [("email", "office@example.org")])

    def test_a_surname_of_two_letters_does_not_match_a_local_part(self):
        far = "Wei Li is professor.\n" + "x " * 2000 + "\nMail li@example.org."
        self.assertEqual(self.contacts(far, "Wei Li"), [])
        self.assertEqual(self.contacts("Wei Li is professor. Mail li@example.org.", "Wei Li"), [("email", "li@example.org")])

    def test_a_name_written_with_a_middle_name_still_places_the_address(self):
        self.assertEqual(self.contacts("Jan Pieter Peeters, physics. Mail office@example.org"), [("email", "office@example.org")])

    def test_a_page_without_an_address_gives_nothing_and_words_are_no_address(self):
        self.assertEqual(self.contacts("Jan Peeters is professor of physics."), [])
        self.assertEqual(self.contacts("Jan Peeters: jan peeters at example dot org"), [])

    def test_an_address_followed_by_a_full_stop_is_kept_without_it(self):
        self.assertEqual(self.contacts("Jan Peeters: jan@example.org."), [("email", "jan@example.org")])

    def test_a_phone_beside_the_email_counts_when_the_name_is_far(self):
        far = "Jan Peeters is professor.\n" + "x " * 2000 + "\nMail jan.peeters@example.org, phone 617-555-0100."
        self.assertEqual(self.contacts(far), [("email", "jan.peeters@example.org"), ("phone", "617-555-0100")])

    def test_a_fax_a_year_range_and_a_short_run_are_no_phone(self):
        text = "Jan Peeters, 2019-2024, since 2010 / 2012. Fax 617-555-0199. Room 4021. Updated 2026-10-01."
        self.assertEqual(self.contacts(text), [])
        self.assertEqual(self.contacts("Jan Peeters (1950-2020) was a physicist."), [])
        self.assertEqual(self.contacts(text + " Tel 617-555-0100"), [("phone", "617-555-0100")])


class NamesTest(unittest.TestCase):
    def test_clean_name_drops_titles_and_credentials(self):
        """Leading titles and trailing credentials go, in any number and case, with or without a final period.

        The name itself stays as written, also when it starts with the letters of a title.
        """
        for given, cleaned in (("Prof. Dr. Jan Peeters, PhD", "Jan Peeters"),
                               ("prof. dr. Els  Janssens", "Els Janssens"), ("Prof.Dr. Jan Peeters", "Jan Peeters"),
                               ("Mr Wim Doe, Ph.D.", "Wim Doe"), ("Ms. Anja Voorbeeld MBA, MD", "Anja Voorbeeld"),
                               ("Jan Peeters, PhD.", "Jan Peeters"), ("Jan Peeters, phd", "Jan Peeters"),
                               ("Ann Doe, mba.", "Ann Doe"), ("Ann Doe, ph.d", "Ann Doe"),
                               ("Drew Mdala", "Drew Mdala"), ("Dr. Doe", "Doe"),
                               ("Ngozi Mba", "Ngozi Mba"), ("Rahman Md", "Rahman Md"),
                               ("Prof. dr. ir. Jan Peeters", "Jan Peeters"), ("Irene Smet", "Irene Smet")):
            with self.subTest(name=given):
                self.assertEqual(clean_name(given), cleaned)

    def test_identifier_is_the_url_and_the_cleaned_folded_name(self):
        """A mention's identity is the page URL and the cleaned, folded name.

        The same person on the same page gets one identity, however the model wrote titles, accents or case.
        """
        self.assertEqual(extract.identifier(URL, "Prof. Jan Péeters, PhD"),
                         Identifier(scheme="mention", value=f"{URL}#jan peeters"))
        self.assertEqual(extract.identifier(URL, "Jan Peeters"), extract.identifier(URL, "Dr. JAN PEETERS"))


if __name__ == "__main__":
    unittest.main()
