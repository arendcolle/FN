import logging
import unittest
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from fn import extract, llm, rank
from fn.contracts import (
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
from tests.helpers import make_db, make_settings

URL = "https://events.example.org/belgium-6g-roundtable"
READ = datetime(2026, 11, 3, tzinfo=UTC)
SPEAKERS = ("Speakers\n\nJan Peeters, PhD, KU Leuven\nEls Janssens, PhD, KU Leuven\n\n"
            "Moderator: Wim Doe was born in Ghent and studied at Ghent University from 1990 to 1994.")


def relation(kind: str, org: str, quote: str, year_from: int | None = None, year_to: int | None = None) -> dict:
    return {"relation": kind, "org": org, "quote": quote, "year_from": year_from, "year_to": year_to}


def mention(name: str, quote: str, role: str | None = None, *relations: dict) -> dict:
    return {"name": name, "quote": quote, "role": role, "relations": list(relations)}


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
        pages = self.llm.pages
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


class NamesTest(unittest.TestCase):
    def test_clean_name_drops_titles_and_credentials(self):
        """Leading titles and trailing credentials go, in any number and case of title.

        The name itself stays as written, also when it starts with the letters of a title.
        """
        for given, cleaned in (("Prof. Dr. Jan Peeters, PhD", "Jan Peeters"),
                               ("prof. dr. Els  Janssens", "Els Janssens"), ("Prof.Dr. Jan Peeters", "Jan Peeters"),
                               ("Mr Wim Doe, Ph.D.", "Wim Doe"), ("Ms. Anja Voorbeeld MBA, MD", "Anja Voorbeeld"),
                               ("Drew Mdala", "Drew Mdala"), ("Dr. Doe", "Doe"),
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
