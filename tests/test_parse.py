import unittest
from pathlib import Path

from fn import parse
from fn.contracts import Chip, Chips, Place, Span
from fn.llm import FixtureLLM
from fn.worker import Worker
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

FIXTURES = Path(__file__).parent / "fixtures" / "llm"
EN = ("Who are Flemish experts in telecom and 6G research in the New York and New Jersey area, "
      "for a roundtable at Flanders House with Vint Cerf?")
NL = ("Welke Vlaamse experten in telecom en 6G-onderzoek in de regio New York en New Jersey "
      "kunnen deelnemen aan een rondetafel?")


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)

    def search_with(self, llm, question: str):
        worker = Worker(self.store, self.settings, llm=llm, http=StubHttp())
        self.addCleanup(worker.shutdown)
        return worker.execute(worker.create_search(question).id)

    def test_span_not_in_the_question_is_rejected(self):
        """A span whose slice differs from the chip text, or lies outside the question, raises SpanError."""
        for span in (Span(start=0, end=4), Span(start=5, end=500), Span(start=6, end=3)):
            chips = Chips(topics=[Chip(text="wind", span=span, origin="parsed")])
            with self.assertRaises(parse.SpanError):
                parse.check_spans("Who knows wind?", chips)
        place = Chips(place=Place(text="Boston", span=Span(start=0, end=6), origin="parsed"))
        with self.assertRaises(parse.SpanError):
            parse.check_spans("Who knows wind?", place)
        with self.assertRaises(parse.SpanError):
            parse.check_spans("Who knows wind?", Chips(topics=[Chip(text="wind", origin="parsed")]))

    def test_edited_chips_without_spans_are_kept(self):
        """A chip with no span, as the form sends it after an edit, passes the check unchanged."""
        chips = Chips(topics=[Chip(text="offshore wind", origin="edited"), Chip(text="wind", span=Span(start=10, end=14), origin="parsed")],
                      place=Place(text="Gent", origin="edited"))
        self.assertIs(parse.check_spans("Who knows wind?", chips), chips)

    def test_span_off_by_up_to_two_characters_is_moved_onto_the_text(self):
        """A span at most two characters from its chip's text is moved onto it; three or more is rejected."""
        question = "Who knows AI search in San Diego?"
        chips = Chips(topics=[Chip(text="AI search", span=Span(start=11, end=20), origin="parsed")],
                      place=Place(text="San Diego", span=Span(start=22, end=31), origin="parsed"))
        fixed = parse.check_spans(question, chips)
        for chip in (fixed.topics[0], fixed.place):
            self.assertEqual(question[chip.span.start:chip.span.end], chip.text)
        far = Chips(topics=[Chip(text="AI search", span=Span(start=13, end=22), origin="parsed")])
        with self.assertRaises(parse.SpanError):
            parse.check_spans(question, far)

    def test_bad_span_from_the_llm_fails_the_step(self):
        """A model answer with a wrong span stops the search at the parse step with a SpanError."""
        llm = StubLLM({"topics": [{"text": "wind", "span": {"start": 0, "end": 4}, "origin": "parsed"}]})
        with self.assertLogs("fn.worker", "ERROR"):
            search = self.search_with(llm, "Who knows wind?")
        (step,) = self.store.list_steps(search.id)
        self.assertEqual((search.status, step.status, step.error_type), ("failed", "error", "SpanError"))

    def test_model_answer_claiming_an_edited_chip_fails_the_step(self):
        """A model answer whose chip says origin edited is rejected, even with a correct span."""
        llm = StubLLM({"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "edited"}]})
        with self.assertLogs("fn.worker", "ERROR"):
            search = self.search_with(llm, "Who knows wind?")
        self.assertEqual(search.status, "failed")

    def test_refs_come_from_the_alias_file_only(self):
        """A ref the model sends is dropped; a known institution gets its ROR ref from the alias file, others none."""
        llm = StubLLM({"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "parsed", "ref": "x"}],
                       "institutions": [{"text": "MIT", "span": {"start": 18, "end": 21}, "origin": "parsed", "ref": "y"},
                                        {"text": "Acme", "span": {"start": 26, "end": 30}, "origin": "parsed", "ref": "z"}]})
        chips = self.search_with(llm, "Who knows wind at MIT and Acme?").chips
        self.assertEqual([c.ref for c in [*chips.topics, *chips.institutions]],
                         [None, "ror:042nb2s44", None])

    def test_recorded_english_and_dutch_questions_parse_with_checked_spans(self):
        """Replayed parses of an English and a Dutch question give chips in the question's own language."""
        llm = FixtureLLM(FIXTURES, "replay")
        english = self.search_with(llm, EN).chips
        dutch = self.search_with(llm, NL).chips
        self.assertEqual([c.text for c in english.topics], ["telecom", "6G research"])
        self.assertEqual([c.text for c in dutch.topics], ["telecom", "6G-onderzoek"])
        self.assertEqual(dutch.place.text, "New York en New Jersey")
        for question, chips in ((EN, english), (NL, dutch)):
            for chip in [*chips.topics, chips.place]:
                self.assertEqual(question[chip.span.start:chip.span.end], chip.text)


if __name__ == "__main__":
    unittest.main()
