import logging
import unittest
from datetime import UTC, datetime

from fn import fitcheck
from fn.contracts import Candidate, Chip, Chips, ClaimDraft, FitAnswer, FitIn, FitRow, Identifier, Org, Search, Source
from fn.llm import FixtureMissing
from fn.steps import StepContext
from fn.worker import new_id, now
from tests.helpers import make_db, make_settings

V2 = Chips(topics=[Chip(text="midterms", origin="edited")], version=2)
V1 = Chips(topics=[Chip(text="midterms", origin="edited")])
QUESTION = "Who could speak about the US midterms?"
FETCHED = datetime(2026, 11, 3, tzinfo=UTC)
ULB = Org(id="ror:01r9htc13", name="Example University", country_code="BE", source_id="s", fetched_at=FETCHED)


class BatchLLM:
    """Answers the fit task with `fit` for every numbered line, or what `answer` makes of the call's data; records
    each call's data."""

    def __init__(self, fit: str = "yes", answer=None):
        self.fit, self.answer, self.calls = fit, answer, []

    def structured(self, task, data, schema):
        self.calls.append((task, data))
        given = self.answer(data) if self.answer else FitAnswer(
            people=[FitRow(n=n, fit=self.fit) for n in range(1, len(data["people"].splitlines()) + 1)])
        if isinstance(given, Exception):
            raise given
        return type("Result", (), {"value": given})()


class FitCheckTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.store.upsert_source(Source(id="s", kind="record", url="https://example.org/s", text="x", content_hash="s",
                                        fetched_at=FETCHED))
        self.store.upsert_org(ULB, False)
        self.store.create_search(Search(id="s1", question=QUESTION, status="done", code_sha="abc", dirty=False,
                                        llm_mode="replay", settings_json="{}", boot_id="boot", created_at=FETCHED))
        self.people, self.n = [], 0

    def claim(self, person_id: str, kind: str, value: str, relation: str | None = None, org_id: str | None = None,
              year: str | None = None) -> None:
        text = f"{value} {year or ''}"
        self.store.upsert_claim(ClaimDraft(
            person_id=person_id, kind=kind, relation=relation, org_id=org_id, value=value, quote=text, quote_start=0,
            quote_end=len(text), claim_date=year, source=Source(
                id=f"src-{person_id}-{kind}-{value}"[:80], kind="record", url="https://example.org/p", text=text,
                content_hash=f"h-{person_id}-{kind}-{value}")))

    def person(self, name: str, role: str | None = "Professor of politics", topics=(), tier: int = 1,
               lanes: dict | None = None, section: str = "new", cut: str | None = None) -> Candidate:
        """A stored person with a role, an employer and topic claims, and the kept candidate that stands for them."""
        found = self.store.resolve_person([Identifier(scheme="seed", value=name)], name)
        if role:
            self.claim(found.id, "role", role)
        self.claim(found.id, "affiliation", ULB.name, "works_at", ULB.id)
        for value, year in topics:
            self.claim(found.id, "topic", value, year=year)
        self.n += 1
        c = Candidate(search_id="s1", person_id=found.id, person_ids=[found.id], section=section, rank=self.n, score=1.0,
                      lane_ranks=lanes or {"openalex": 1}, hit_person_ids=[found.id], cut_reason=cut, tier=tier)
        self.people.append(c)
        return c

    def check(self, llm: BatchLLM, chips: Chips = V2):
        self.store.save_candidates("s1", self.people, [])
        ctx = StepContext(search_id="s1", store=self.store, llm=llm, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        return fitcheck.run(ctx, FitIn(question=QUESTION, chips=chips))

    def test_the_line_holds_roles_employers_and_topics_newest_first_and_no_name_or_tie(self):
        """The model reads the role, the employer and the topic claims, newest first; no name, place or tie claim."""
        c = self.person("Ann Example", topics=[("Old paper on polling", "2015"), ("New paper on turnout", "2024")])
        self.claim(c.person_id, "affiliation", "Ghent University", "studied_at")
        self.claim(c.person_id, "location", "Ghent, Belgium")
        llm = BatchLLM()
        out = self.check(llm)
        ((task, data),) = llm.calls
        self.assertEqual(task, "fit")
        self.assertEqual(data["question"], QUESTION)
        self.assertEqual(data["people"], "1. Professor of politics; Example University; New paper on turnout; "
                                         "Old paper on polling")
        self.assertEqual(out.verdicts, {c.person_id: "yes"})

    def test_a_person_with_no_role_and_no_topic_has_the_employer_alone_and_a_long_line_is_cut(self):
        """The line of a bare person is the employer; a line of 200 words keeps its first 40."""
        self.person("Bo Bare", role=None)
        self.person("Cy Long", topics=[(" ".join(f"w{i}" for i in range(200)), "2020")])
        llm = BatchLLM()
        self.check(llm)
        first, second = llm.calls[0][1]["people"].splitlines()
        self.assertEqual(first, "1. Example University")
        self.assertEqual(len(second.split(". ", 1)[1].split()), fitcheck.LINE_WORDS)

    def test_scout_people_cut_people_the_network_and_tiers_5_to_7_are_not_sent(self):
        """Only kept new-section people of tiers 1 to 4 that the web researcher did not find are sent."""
        keep = [self.person(f"Tier {t} Person", tier=t) for t in (1, 2, 3, 4)]
        self.person("Scout Person", lanes={"scout": 1})
        self.person("Cut Person", cut="no_tie")
        self.person("Network Person", section="network")
        for t in (5, 6, 7):
            self.person(f"Tier {t} Person", tier=t)
        llm = BatchLLM()
        out = self.check(llm)
        self.assertEqual(len(llm.calls[0][1]["people"].splitlines()), 4)
        self.assertEqual(set(out.verdicts), {c.person_id for c in keep})

    def test_75_candidates_give_three_calls_of_20_and_15_are_not_checked(self):
        """The first 60 in rank order go out in batches of 20, each numbered from 1."""
        for i in range(75):
            self.person(f"Person {i:02d}")
        llm = BatchLLM()
        out = self.check(llm)
        self.assertEqual([len(d["people"].splitlines()) for _, d in llm.calls], [20, 20, 20])
        self.assertTrue(all(d["people"].startswith("1. ") for _, d in llm.calls))
        self.assertEqual(set(out.verdicts), {c.person_id for c in self.people[:60]})

    def test_a_wrong_number_is_ignored_and_a_missing_person_gets_no_verdict(self):
        """A row for a line the batch does not have changes nothing; a duplicate number keeps its first row."""
        a, b, c = (self.person(name) for name in ("Ann Example", "Bo Example", "Cy Example"))
        rows = [FitRow(n=1, fit="no"), FitRow(n=1, fit="yes"), FitRow(n=0, fit="yes"), FitRow(n=9, fit="yes"),
                FitRow(n=3, fit="partly")]
        out = self.check(BatchLLM(answer=lambda data: FitAnswer(people=rows)))
        self.assertEqual(out.verdicts, {a.person_id: "no", c.person_id: "partly"})
        self.assertNotIn(b.person_id, out.verdicts)

    def test_one_failed_batch_keeps_the_verdicts_of_the_others_and_is_named_in_the_note(self):
        """Batch 2 raises: batches 1 and 3 give their verdicts and the note names batch 2 and its error."""
        for i in range(60):
            self.person(f"Person {i:02d}")

        seen = []

        def by_call(data):
            seen.append(data)
            return ConnectionError("model is down") if len(seen) == 2 else FitAnswer(
                people=[FitRow(n=n, fit="yes") for n in range(1, 21)])

        llm = BatchLLM(answer=by_call)
        self.settings = self.settings.model_copy(update={"llm_workers": 1})
        out = self.check(llm)
        self.assertEqual(len(out.verdicts), 40)
        self.assertEqual(out.note, "batch 2 failed: ConnectionError: model is down")
        self.assertEqual(set(out.verdicts), {c.person_id for c in self.people[:20] + self.people[40:]})

    def test_every_batch_missing_its_recording_gives_a_note_and_other_errors_raise(self):
        """In replay with no recording the step ends ok with a note; any other error in every batch is raised."""
        self.person("Ann Example")
        out = self.check(BatchLLM(answer=lambda data: FixtureMissing("no LLM fixture")))
        self.assertEqual((out.verdicts, out.note), ({}, "no recorded fit check for this question"))
        with self.assertRaisesRegex(ConnectionError, "down"):
            self.check(BatchLLM(answer=lambda data: ConnectionError("down")))

    def test_version_1_chips_and_an_empty_candidate_list_make_no_call(self):
        """Chips stored before this round and a search with nobody in tiers 1 to 4 each give a note and no call."""
        llm = BatchLLM()
        self.person("Ann Example")
        self.assertEqual(self.check(llm, V1).note, "chips stored before this round, so no fit check")
        self.people.clear()
        self.person("Scout Person", lanes={"scout": 1})
        self.assertEqual(self.check(llm).note, "nobody to check")
        self.assertEqual(llm.calls, [])


if __name__ == "__main__":
    unittest.main()
