import logging
import unittest
from unittest import mock

from fn import config, scout
from fn.contracts import Chip, Chips, ScoutLead, ScoutLeads
from fn.llm import FixtureMissing
from fn.steps import StepContext
from fn.worker import new_id, now
from tests.helpers import make_db, make_settings

MUST = Chips(tie=Chip(text="Belgian", origin="edited", need="must"), version=2)
WISH = Chips(tie=Chip(text="Belgian", origin="edited", need="nice"), version=2)
NO_TIE = Chips(version=2)
QUESTION = "Which Belgian-born chefs work in Chicago?"


class AngleLLM:
    """Answers the scout task per angle text: a ScoutLeads, or an exception to raise; records each call's data."""

    def __init__(self, by_angle: dict[str, ScoutLeads | Exception]):
        self.by_angle, self.calls = by_angle, []

    def structured(self, task, data, schema):
        self.calls.append((task, data))
        answer = self.by_angle[next(k for k, text in scout.ANGLES.items() if text == data["angle"])]
        if isinstance(answer, Exception):
            raise answer
        return type("Result", (), {"value": answer})()


def lead(name: str, *pages: str, role: str = "Chef", place: str = "") -> ScoutLead:
    return ScoutLead(name=name, role=role, employer="Cafe Test", place=place, pages=list(pages))


class ScoutTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)

    def find(self, chips: Chips, by_angle: dict[str, ScoutLeads | Exception]):
        self.llm = AngleLLM(by_angle)
        ctx = StepContext(search_id="s", store=self.store, llm=self.llm, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        return scout.find(ctx, QUESTION, chips)

    def every(self, chips: Chips, answer: ScoutLeads | Exception) -> dict:
        return {k: answer for k in scout.angles(chips)}

    def test_the_angles_depend_on_the_tie_chip(self):
        """A must tie gives four angles, a wished tie six, no tie chip four."""
        self.assertEqual(scout.angles(MUST), ["press", "lists", "born", "place_tied"])
        self.assertEqual(scout.angles(WISH), ["press", "lists", "born", "place", "speakers", "boards"])
        self.assertEqual(scout.angles(NO_TIE), ["place", "speakers", "boards", "lists"])

    def test_one_call_per_angle_carries_the_question_and_the_angle_text(self):
        """Each angle makes one scout call whose data holds the question and that angle's text, and a row says what came back."""
        answers = {k: ScoutLeads(searches=["a", "b"], people=[lead("Jan Peeters", "https://example.org/jan")])
                   for k in scout.angles(WISH)}
        leads, rows = self.find(WISH, answers)
        self.assertEqual(sorted(d["angle"] for _, d in self.llm.calls), sorted(scout.ANGLES[k] for k in answers))
        self.assertTrue(all(t == "scout" and d["question"] == QUESTION for t, d in self.llm.calls))
        self.assertEqual([r.reason for r in rows if r.stage == "query"],
                         [f"angle {k}: 1 people; searches: a | b" for k in answers])
        self.assertEqual(len(leads), 1)

    def test_leads_merge_by_cleaned_name_and_pages_join_without_repeats(self):
        """Dr. Jan Peeters joins Jan Peeters, the first role stands, and a slash or a fragment is not a second page."""
        answers = self.every(WISH, ScoutLeads())
        answers["press"] = ScoutLeads(people=[lead("Dr. Jan Peeters", "https://example.org/a", role="Head chef")])
        answers["lists"] = ScoutLeads(people=[lead("Jan Peeters PhD", "https://example.org/a/", "https://example.org/b#top"),
                                              lead("Eva Maes", "https://example.org/c")])
        answers["born"] = ScoutLeads(people=[lead("Jan Peeters", "https://example.org/b", "https://example.org/d")])
        leads, _ = self.find(WISH, answers)
        self.assertEqual([(x.name, x.role, x.pages) for x in leads],
                         [("Jan Peeters", "Head chef", ["https://example.org/a", "https://example.org/b#top",
                                                        "https://example.org/d"]),
                          ("Eva Maes", "Chef", ["https://example.org/c"])])

    def test_blocked_hosts_subdomains_and_other_schemes_are_dropped_and_a_lead_without_pages_has_its_row(self):
        """A LinkedIn page, a subdomain of a blocked host and an ftp address are dropped; their lead is dropped with a row."""
        blocked = ["https://www.linkedin.com/in/jan", "http://nl.linkedin.com/in/x", "ftp://example.org/jan",
                   "https://x.com/jan", "https://notlinkedin.com.example.org/ok"]
        answers = self.every(WISH, ScoutLeads(people=[lead("Jan Peeters", *blocked[:4]), lead("Eva Maes", blocked[4])]))
        leads, rows = self.find(WISH, answers)
        self.assertEqual([(x.name, x.pages) for x in leads], [("Eva Maes", [blocked[4]])])
        (dropped,) = [r for r in rows if r.stage == "mention"]
        self.assertEqual((dropped.kept, dropped.name, dropped.reason), (False, "Jan Peeters", "Jan Peeters: no page FN may read"))

    def test_a_lead_without_a_name_is_dropped_with_a_row(self):
        """An empty name and a name of only a title give the row; the name stays empty."""
        answers = self.every(WISH, ScoutLeads(people=[lead("", "https://example.org/a"), lead("Dr.", "https://example.org/b")]))
        leads, rows = self.find(WISH, answers)
        self.assertEqual(leads, [])
        self.assertEqual({(r.name, r.reason) for r in rows if r.stage == "mention"}, {("", "a lead without a name")})

    def test_one_failed_angle_gives_a_failed_row_and_the_others_leads_stay(self):
        """A timeout on one angle is a row with the error type and message; the three answers are used."""
        answers = self.every(WISH, ScoutLeads(people=[lead("Jan Peeters", "https://example.org/a")]))
        answers["born"] = TimeoutError("took too long")
        leads, rows = self.find(WISH, answers)
        self.assertEqual(len(leads), 1)
        failed = [r for r in rows if not r.kept]
        self.assertEqual([r.reason for r in failed], ["angle born failed: TimeoutError: took too long"])

    def test_every_angle_failing_raises_the_first_error(self):
        """When no angle answered, the first angle's error is raised so the step ends in error."""
        with self.assertRaises(TimeoutError) as raised:
            self.find(MUST, {"press": TimeoutError("first"), "lists": ValueError("second"), "born": ValueError("third"),
                             "place_tied": ValueError("fourth")})
        self.assertEqual(str(raised.exception), "first")

    def test_every_angle_missing_its_recording_gives_a_note_and_no_error(self):
        """A replay of a search recorded before this lane has no fixture for any angle: no leads, one note, no error."""
        leads, rows = self.find(WISH, self.every(WISH, FixtureMissing("no LLM fixture")))
        self.assertEqual(leads, [])
        self.assertEqual(rows[-1].reason, "no recorded web research for this question")
        self.assertEqual(sum(not r.kept for r in rows), len(scout.angles(WISH)) + 1)

    def test_a_mix_of_missing_recordings_and_another_error_raises(self):
        """The note is only for all-missing recordings; a mix with a real error still raises."""
        with self.assertRaises(FixtureMissing):
            self.find(MUST, {"press": FixtureMissing("x"), "lists": RuntimeError("y"), "born": RuntimeError("y"),
                             "place_tied": RuntimeError("y")})

    def test_fn_scout_turns_the_setting_off_only_for_0_or_false(self):
        """FN_SCOUT unset keeps the lane on; 0 and false turn it off; any other text keeps it on."""
        for value, expected in ((None, True), ("0", False), ("false", False), ("False", False), ("1", True)):
            with self.subTest(value=value):
                env = {} if value is None else {"FN_SCOUT": value}
                with mock.patch.dict("os.environ", env, clear=True), mock.patch("fn.config.keychain", return_value=None):
                    self.assertEqual(config.from_env().scout, expected)
