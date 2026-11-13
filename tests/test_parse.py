import json
import unittest
from pathlib import Path

from fn import llm, parse
from fn.contracts import Chip, Chips, Place, Span, WebQuery
from fn.llm import FixtureLLM
from fn.worker import Worker
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

FIXTURES = Path(__file__).parent / "fixtures" / "llm"
EN = ("Who are Flemish experts in telecom and 6G research in the New York and New Jersey area, "
      "for a roundtable at Flanders House with Vint Cerf?")
NL = ("Welke Vlaamse experten in telecom en 6G-onderzoek in de regio New York en New Jersey "
      "kunnen deelnemen aan een rondetafel?")


class ContentWordsTest(unittest.TestCase):
    def test_function_and_generic_words_are_dropped_and_ai_stays(self):
        """Function words, generic words and one-letter words go; a two-letter word stays; a repeat comes back once."""
        self.assertEqual(parse.content_words("AI in health care"), ["ai", "health", "care"])
        self.assertEqual(parse.content_words("Research"), [])
        self.assertEqual(parse.content_words("Who are the Belgian experts in the US?"), [])
        self.assertEqual(parse.content_words("wind and Wind, and solar and wind"), ["wind", "solar"])

    def test_dutch_and_french_questions_lose_their_function_words_and_accents(self):
        """Welke and de/het (Dutch), quelles and les/de (French) are dropped; the rest is folded like a name key."""
        self.assertEqual(parse.content_words("Welke experts in de windenergie en het elektriciteitsnet?"),
                         ["windenergie", "elektriciteitsnet"])
        self.assertEqual(parse.content_words("Quelles études sur l'énergie éolienne dans les Ardennes ?"),
                         ["etudes", "energie", "eolienne", "ardennes"])


def chip(text: str, **fields) -> Chip:
    return Chip(text=text, origin="parsed", **fields)


class RelatedTest(unittest.TestCase):
    def test_related_words_drop_the_chip_itself_generic_words_and_repeats_and_stop_at_six(self):
        """An entry equal to the chip, with only generic words, repeating another or using only the chip's words goes."""
        entries = ["AI", "research", "artificial intelligence", "machine learning", "ML", "deep learning",
                   "neural networks", "robotics", "computer vision"]
        self.assertEqual(parse.clean_related(chip("AI", related=entries)),
                         ["artificial intelligence", "machine learning", "ML", "deep learning", "neural networks",
                          "robotics"])
        messy = ["  oprichter \n", "Oprichter", "fondateur", "chercheur", "specialists", "wind", "wind power", ""]
        self.assertEqual(parse.clean_related(chip("wind", related=messy)), ["oprichter", "fondateur", "wind power"])


class ChipsPredicateTest(unittest.TestCase):
    def chips(self, **fields) -> Chips:
        return Chips(**fields)

    def test_version_1_chips_cut_nobody_for_a_tie_and_count_research_as_asked(self):
        """Chips stored before this round: no tie is a must, researchers are asked for, even with a tie chip saying must."""
        for extra in ({}, {"tie": chip("Flemish", need="must")}):
            old = self.chips(**extra)
            self.assertEqual((parse.tie_must(old), parse.asks_researchers(old), parse.wants_research(old)),
                             (False, True, True))

    def test_version_2_reads_the_role_and_tie_chips(self):
        """Research is asked for only by a research role; a role question without one does not want research."""
        founders, faculty = chip("founders", research=False), chip("faculty", research=True)
        cases = [
            (self.chips(version=2), (False, False, True)),
            (self.chips(version=2, roles=[founders]), (False, False, False)),
            (self.chips(version=2, roles=[founders, faculty]), (False, True, True)),
            (self.chips(version=2, tie=chip("ideally Flemish", need="nice")), (False, False, True)),
            (self.chips(version=2, tie=chip("Flemish", need="must")), (True, False, True)),
        ]
        for chips, (tie, asked, wants) in cases:
            with self.subTest(chips=chips):
                self.assertEqual((parse.tie_must(chips), parse.asks_researchers(chips), parse.wants_research(chips)),
                                 (tie, asked, wants))


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)

    def search_with(self, llm, question: str):
        worker = Worker(self.store, self.settings, llm=llm, http=StubHttp())
        self.addCleanup(worker.shutdown)
        return worker.execute(worker.create_search(question).id)

    def test_span_on_the_wrong_word_or_outside_the_question_is_repaired(self):
        """A wrong, reversed, out-of-range or missing span is replaced by the position of the chip's text."""
        question = "Who knows wind?"
        for span in (Span(start=0, end=4), Span(start=5, end=500), Span(start=6, end=3), None):
            chips = Chips(topics=[Chip(text="wind", span=span, origin="parsed")],
                          place=Place(text="knows", span=Span(start=0, end=5), origin="parsed"))
            fixed = parse.check_spans(question, chips)
            self.assertEqual((fixed.topics[0].span, fixed.place.span), (Span(start=10, end=14), Span(start=4, end=9)))

    def test_edited_chips_without_spans_are_kept(self):
        """A chip with no span, as the form sends it after an edit, passes the check unchanged."""
        chips = Chips(topics=[Chip(text="offshore wind", origin="edited"), Chip(text="wind", span=Span(start=10, end=14), origin="parsed")],
                      place=Place(text="Gent", origin="edited"))
        self.assertIs(parse.check_spans("Who knows wind?", chips), chips)

    def test_span_five_characters_off_is_moved_and_the_search_ends_done(self):
        """A topic span five characters off comes back on its text, and the search does not fail."""
        question = "Which business development people in Boston life sciences studied at a Flemish university?"
        llm = StubLLM({"topics": [{"text": "life sciences", "span": {"start": 62, "end": 75}, "origin": "parsed"}]})
        search = self.search_with(llm, question)
        (topic,) = search.chips.topics
        self.assertEqual((search.status, question[topic.span.start:topic.span.end]), ("done", "life sciences"))

    def test_text_that_stands_twice_gets_the_nearest_occurrence(self):
        """The occurrence whose start is nearest to the claimed start wins; the first one without a claim."""
        question = "wind and solar and wind"
        self.assertEqual(parse.locate(question, "wind", 15), Span(start=19, end=23))
        self.assertEqual(parse.locate(question, "wind", 3), Span(start=0, end=4))
        self.assertEqual(parse.locate(question, "wind", None), Span(start=0, end=4))
        self.assertIsNone(parse.locate(question, "", 0))

    def test_text_in_another_case_becomes_the_questions_own_slice(self):
        """A casefolded match keeps the question's spelling as the chip text, with an exact span."""
        question = "Who knows AI and AI in Évora \U0001F600?"
        chips = Chips(topics=[Chip(text="ai", span=Span(start=9, end=11), origin="parsed")],
                      place=Place(text="évora", span=Span(start=0, end=5), origin="parsed"))
        fixed = parse.check_spans(question, chips)
        self.assertEqual((fixed.topics[0].text, fixed.topics[0].span), ("AI", Span(start=10, end=12)))
        self.assertEqual((fixed.place.text, question[fixed.place.span.start:fixed.place.span.end]), ("Évora", "Évora"))

    def test_text_the_question_does_not_hold_is_dropped_with_a_warning(self):
        """A parsed chip whose text stands nowhere is dropped and logged; the other chips stay; the search ends done."""
        llm = StubLLM({"topics": [{"text": "machine learning", "span": {"start": 10, "end": 26}, "origin": "parsed"},
                                  {"text": "AI", "span": {"start": 10, "end": 12}, "origin": "parsed"}]})
        with self.assertLogs("fn.parse", "WARNING") as logs:
            search = self.search_with(llm, "Who knows AI?")
        self.assertEqual((search.status, [c.text for c in search.chips.topics]), ("done", ["AI"]))
        self.assertIn("chip 'machine learning' is not in the question; dropped", logs.output[0])

    def test_place_and_tie_that_stand_nowhere_become_none(self):
        """A dropped place or tie chip is None, and a search whose every chip is dropped still ends done."""
        llm = StubLLM({"topics": [{"text": "solar", "origin": "parsed"}],
                       "tie": {"text": "Flemish", "span": {"start": 0, "end": 7}, "origin": "parsed"},
                       "place": {"text": "Boston", "span": {"start": 0, "end": 6}, "origin": "parsed"}})
        with self.assertLogs("fn.parse", "WARNING"):
            search = self.search_with(llm, "Who knows wind?")
        self.assertEqual((search.status, search.chips.topics, search.chips.tie, search.chips.place), ("done", [], None, None))

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

    def rekeyed(self) -> Path:
        """A temp folder with the recorded answers to EN and NL under the keys FixtureLLM computes for today's prompt."""
        directory = self.settings.var_dir / "rekeyed"
        directory.mkdir()
        for question in (EN, NL):
            user = llm.user_turn({"question": question})
            (old,) = [f for f in FIXTURES.glob("parse-*.json") if json.loads(f.read_text())["prompt"] == user]
            sha = llm.prompt_sha(llm.system_prompt("parse"), user, llm.schema_json(Chips), llm.MODEL)
            (directory / f"parse-{sha[:16]}.json").write_text(json.dumps(json.loads(old.read_text())))
        return directory

    def test_roles_and_tie_come_back_as_version_2_chips_with_checked_spans_and_queries(self):
        """A model answer with a role, a tie and queries gives version 2; spans are checked, research is role-only."""
        question = "Which Flemish founders know wind at MIT?"
        llm = StubLLM({
            "topics": [{"text": "wind", "span": {"start": 29, "end": 33}, "origin": "parsed", "research": True,
                        "related": ["wind", "offshore", "wind energy", "windenergie"]}],
            "institutions": [{"text": "MIT", "span": {"start": 37, "end": 40}, "origin": "parsed", "related": ["x"]}],
            "roles": [{"text": "founders", "span": {"start": 15, "end": 23}, "origin": "parsed", "research": 1,
                       "related": ["oprichter", "CEO"]}],
            "tie": {"text": "Flemish", "span": {"start": 6, "end": 13}, "origin": "parsed", "need": "must",
                    "related": ["belgian"], "research": True},
            "queries": [{"text": "Flemish founders wind", "lang": "en"}, {"text": "Vlaamse oprichters wind", "lang": "nl"}],
            "version": 5,
        })
        chips = self.search_with(llm, question).chips
        self.assertEqual(chips.version, 2)
        self.assertEqual([(q.text, q.lang) for q in chips.queries],
                         [("Flemish founders wind", "en"), ("Vlaamse oprichters wind", "nl")])
        for found in (*chips.topics, *chips.roles, chips.tie):
            self.assertEqual(question[found.span.start:found.span.end], found.text)
        (topic,), (role,) = chips.topics, chips.roles
        self.assertEqual((topic.research, topic.related), (None, ["offshore", "wind energy", "windenergie"]))
        self.assertEqual((role.research, role.related, chips.tie.need), (True, ["oprichter", "CEO"], "must"))
        self.assertEqual((chips.tie.research, chips.tie.related, chips.institutions[0].related), (None, [], []))

    def test_an_answer_with_no_roles_tie_or_queries_is_still_version_2(self):
        """The new fields are optional in the answer; the chips are marked version 2 anyway."""
        llm = StubLLM({"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "parsed"}]})
        chips = self.search_with(llm, "Who knows wind?").chips
        self.assertEqual((chips.version, chips.roles, chips.tie, chips.queries), (2, [], None, []))

    def test_a_role_span_five_characters_off_is_moved_onto_the_role(self):
        """A role chip's span is repaired like a topic's, so a position five characters off ends done."""
        llm = StubLLM({"roles": [{"text": "founders", "span": {"start": 19, "end": 27}, "origin": "parsed"}]})
        search = self.search_with(llm, "Which Flemish founders know wind?")
        self.assertEqual((search.status, search.chips.roles[0].span), ("done", Span(start=14, end=22)))

    def test_a_role_and_tie_span_off_are_moved_onto_their_text(self):
        """A role and a tie span that miss their text are moved onto it."""
        question = "Which Flemish founders know wind?"
        chips = Chips(roles=[chip("founders", span=Span(start=16, end=24))], tie=chip("Flemish", span=Span(start=6, end=13)))
        fixed = parse.check_spans(question, chips)
        self.assertEqual(question[fixed.roles[0].span.start:fixed.roles[0].span.end], "founders")

    def test_queries_are_kept_as_written_and_a_language_other_than_en_or_nl_fails(self):
        """The parse step keeps an empty query text for websearch.queries to judge; a lang outside en and nl fails."""
        llm = StubLLM({"queries": [{"text": "", "lang": "en"}]})
        chips = self.search_with(llm, "Who knows wind?").chips
        self.assertEqual(chips.queries, [WebQuery(text="", lang="en")])
        seven = StubLLM({"queries": [{"text": f"wind {i}", "lang": "nl"} for i in range(7)]})
        self.assertEqual(len(self.search_with(seven, "Who knows wind?").chips.queries), 7)
        bad = StubLLM({"queries": [{"text": "wind", "lang": "fr"}]})
        with self.assertLogs("fn.worker", "ERROR"):
            self.assertEqual(self.search_with(bad, "Who knows wind?").status, "failed")

    def test_recorded_english_and_dutch_questions_parse_with_checked_spans(self):
        """Replayed parses of an English and a Dutch question give chips in the question's own language."""
        llm = FixtureLLM(self.rekeyed(), "replay")
        english = self.search_with(llm, EN).chips
        dutch = self.search_with(llm, NL).chips
        self.assertEqual([c.text for c in english.topics], ["telecom", "6G research"])
        self.assertEqual([c.text for c in dutch.topics], ["telecom", "6G-onderzoek"])
        self.assertEqual(dutch.place.text, "New York en New Jersey")
        self.assertEqual((english.version, dutch.version), (2, 2))
        for question, chips in ((EN, english), (NL, dutch)):
            for chip in [*chips.topics, chips.place]:
                self.assertEqual(question[chip.span.start:chip.span.end], chip.text)


if __name__ == "__main__":
    unittest.main()
