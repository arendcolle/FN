import logging
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

from fn import deepen, extract, llm, pageread
from fn.contracts import (
    Candidate,
    CardFit,
    Chip,
    Chips,
    ClaimDraft,
    DeepenIn,
    Identifier,
    Lookup,
    LookupAnswer,
    LookupIn,
    LookupPage,
    Place,
    Search,
    Source,
)
from fn.llm import FixtureMissing
from fn.steps import StepContext, run_step
from fn.worker import new_id, now
from tests.helpers import StubHttp, make_db, make_settings

V2 = Chips(topics=[Chip(text="physics", origin="edited")], version=2)
PLACED = V2.model_copy(update={"place": Place(text="Boston", origin="edited", kind="metro")})
V1 = Chips(topics=[Chip(text="physics", origin="edited")])
CREATED = datetime(2026, 11, 1, tzinfo=UTC)
EMPLOYER = "Example University"
URL = "https://example.edu/people/{}"


def page_text(name: str, extra: str = "") -> str:
    return f"Faculty\n{name} is professor of physics at {EMPLOYER}.{extra}\nMore about the department."


class LookupLLM:
    """Answers lookup by the person's name (a LookupAnswer, a page list or an exception) and extract_person by the
    page's text; renders the user turn as FixtureLLM does and records each task with its data."""

    def __init__(self, answers: dict, people=None):
        self.answers, self.people, self.calls = answers, people or (lambda page, person: []), []

    def structured(self, task, data, schema):
        llm.user_turn(data)
        self.calls.append((task, dict(data)))
        if task == "lookup":
            name = data["person"].splitlines()[0]
            given = self.answers.get(name, LookupAnswer())
            if isinstance(given, Exception):
                raise given
            value = given if isinstance(given, LookupAnswer) else LookupAnswer.model_validate({"pages": given})
        else:
            found = self.people(data["page"], data["person"])
            if isinstance(found, Exception):
                raise found
            value = schema.model_validate({"people": found})
        return type("Result", (), {"value": value})()


def page(url: str, kind: str = "employer") -> dict:
    return {"url": url, "kind": kind, "why": "the employer"}


def named(name: str, role: str | None = "professor of physics") -> dict:
    return {"name": name, "quote": f"{name} is professor of physics at {EMPLOYER}.", "role": role,
            "relations": [{"relation": "works_at", "org": EMPLOYER, "quote": f"professor of physics at {EMPLOYER}"}]}


class DeepenTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.searches, self.people = 0, []
        self.pages: dict[str, pageread.Read] = {}
        self.read_urls: list[list[str]] = []

    def claim(self, person_id: str, kind: str, value: str, relation: str | None = None, year: str | None = None) -> None:
        text = f"{value} {year or ''}".strip()
        self.store.upsert_claim(ClaimDraft(
            person_id=person_id, kind=kind, relation=relation, value=value, quote=text, quote_start=0,
            quote_end=len(text), claim_date=year, date_precision="year" if year else None,
            date_method="stated_in_quote" if year else None, source=Source(
                id=f"src-{person_id}-{kind}-{value}", kind="record", url="https://example.org/r", text=text,
                content_hash=f"h-{person_id}-{kind}-{value}")))

    def person(self, name: str, *, complete: bool = False, employer: bool = True, contact: bool = False,
               tier: int = 1, tie: str = "strong", place: str = "none", section: str = "new", cut: str | None = None,
               aside: str | None = None, claims: bool = True) -> str:
        """A stored person and the kept candidate for them, next in rank; complete holds a role, an employer and a
        recent dated fact."""
        found = self.store.resolve_person([Identifier(scheme="seed", value=name)], name)
        if claims and employer:
            self.claim(found.id, "affiliation", EMPLOYER, "works_at")
        if claims and complete:
            self.claim(found.id, "role", "Professor of physics")
            self.claim(found.id, "topic", "Quantum dots", year="2025")
        if contact:
            self.claim(found.id, "email", "someone@example.edu")
        self.people.append(Candidate(
            search_id="", person_id=found.id, person_ids=[found.id], section=section, rank=len(self.people) + 1,
            score=1.0, lane_ranks={"seeds": 1}, hit_person_ids=[found.id], cut_reason=cut, tier=tier,
            fit=CardFit(tie_grade=tie, place=place), aside=aside))
        return found.id

    def read_all(self, ctx, urls):
        self.read_urls.append(list(urls))
        return [self.pages.get(u) or pageread.Read(u, None, None, "a 404", retry=True) for u in urls]

    def serve(self, url: str, text: str | None, failed: str | None = None, retry: bool = False) -> None:
        self.pages[url] = pageread.Read(url, "Faculty", text, failed, retry=retry)

    def deepen(self, answers: dict | None = None, people=None, chips: Chips = V2, order=None,
               skip: list[str] | None = None, used: int = 0):
        """Save the people as a new search's candidates (in order when given) and run the deepen step on them, leaving
        out the records in skip after used lookups with a gap."""
        self.searches += 1
        search_id = f"s{self.searches}"
        self.store.create_search(Search(id=search_id, question="Who knows physics?", chips=chips, status="done",
                                        code_sha="abc", dirty=False, llm_mode="replay", settings_json="{}",
                                        boot_id="boot", created_at=CREATED))
        ranked = [c.model_copy(update={"search_id": search_id, "rank": at}) for at, c in
                  enumerate(order or self.people, 1)]
        self.store.save_candidates(search_id, ranked, [])
        self.llm = LookupLLM(answers or {}, people)
        ctx = StepContext(search_id=search_id, store=self.store, llm=self.llm, http=StubHttp(), now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        with mock.patch("fn.pageread.read_all", self.read_all):
            out = run_step(ctx, "deepen", deepen.run, DeepenIn(chips=chips, skip=skip or [], used=used))
        self.step = self.store.list_steps(search_id)[-1]
        return out

    def looked_up(self) -> list[str]:
        return [data["person"].splitlines()[0] for task, data in self.llm.calls if task == "lookup"]

    def verdicts(self, out) -> dict[str, str]:
        return {lookup.person_id: lookup.verdict for lookup in out.lookups}

    def held(self, person_id: str, kind: str | None = None) -> list:
        return [c for c in self.store.claims_of([person_id]) if kind in (None, c.kind)]

    def test_the_first_twelve_qualifying_people_by_rank_are_looked_up(self):
        """Of 25 people who miss a fact, the lookups are those of the first MAX_LOOKUPS (12) by rank, in rank order."""
        ids = [self.person(f"Ann Person{chr(97 + n)}") for n in range(25)]
        order = list(reversed(self.people))
        out = self.deepen(order=order)
        self.assertEqual(deepen.MAX_LOOKUPS, 12)
        self.assertEqual([lookup.person_id for lookup in out.lookups], [c.person_id for c in order][:12])
        self.assertEqual(len(self.looked_up()), 12)
        self.assertNotIn(ids[0], {lookup.person_id for lookup in out.lookups})

    def test_nobody_qualifying_gives_a_note_and_no_call(self):
        """People with a role, an employer, a recent fact and contact details are not looked up."""
        self.person("Ann Example", complete=True, contact=True)
        out = self.deepen()
        self.assertEqual((out.lookups, out.note, self.llm.calls), ([], "nobody to look up", []))

    def test_aside_cut_network_heading_four_and_complete_people_are_skipped(self):
        """Only kept people of the new section without an aside under headings 1 to 3 who miss a fact are looked up."""
        self.person("Ann Aside", aside="unfit")
        self.person("Bob Cut", cut="no_tie")
        self.person("Cy Network", section="network")
        self.person("Di Low", tier=6, tie="none")
        self.person("Ed Done", complete=True, contact=True)
        self.person("Flo Open", tier=5)
        self.deepen()
        self.assertEqual(self.looked_up(), ["Flo Open"])

    def test_an_unknown_place_counts_only_when_a_place_was_asked(self):
        """A complete card with an unknown place is looked up under a place chip and not without one."""
        self.person("Ann Example", complete=True, contact=True, place="unknown")
        self.deepen(chips=V2)
        self.assertEqual(self.looked_up(), [])
        self.deepen(chips=PLACED)
        self.assertEqual(self.looked_up(), ["Ann Example"])

    def test_a_complete_person_without_contact_is_looked_up_only_in_the_first_ten(self):
        """Contact details are looked for among the first CONTACT_TOP people only."""
        for n in range(11):
            self.person(f"Ann Person{chr(97 + n)}", complete=True)
        self.deepen()
        self.assertCountEqual(self.looked_up(), [f"Ann Person{chr(97 + n)}" for n in range(10)])

    def test_a_lookup_holds_ninety_days_unless_it_failed(self):
        """A lookup 89 days old stops a new one; one 91 days old or a failed one does not."""
        cases = [(89, "nothing_new", []), (91, "nothing_new", ["Ann Example"]), (1, "failed", ["Ann Example"])]
        person_id = self.person("Ann Example")
        for days, verdict, expected in cases:
            with self.subTest(days=days, verdict=verdict):
                with self.store.tx():
                    self.store.save_lookup(Lookup(person_id=person_id, kind="web_person", verdict=verdict, detail=""),
                                           datetime.now(UTC) - timedelta(days=days))
                self.deepen()
                self.assertEqual(self.looked_up(), expected)

    def test_a_page_stating_a_held_employer_attaches_its_claims(self):
        """The page names the person and their stored employer, so its role is stored and the outcome is added."""
        person_id = self.person("Jan Peeters")
        self.serve(URL.format("jan"), page_text("Jan Peeters"))
        out = self.deepen({"Jan Peeters": [page(URL.format("jan"))]}, lambda text, who: [named("Jan Peeters")])
        self.assertEqual(self.verdicts(out), {person_id: "added"})
        roles = [c for c in self.held(person_id, "role")]
        self.assertEqual([c.value for c in roles], ["professor of physics"])
        self.assertIn(roles[0].id, out.claim_ids)
        self.assertIn("works at Example University", out.lookups[0].detail)
        self.assertEqual([task for task, _ in self.llm.calls], ["lookup", "extract_person"])
        self.assertEqual(self.llm.calls[1][1]["person"], "Jan Peeters")

    def test_a_namesake_page_and_a_claimless_card_give_not_sure_and_nothing(self):
        """A page that names the person but no fact FN holds attaches nothing, as does any page for a card without claims."""
        other = self.person("Jan Peeters")
        bare = self.person("Eva Maes", claims=False)
        self.serve(URL.format("jan"), "Faculty\nJan Peeters is a chef at Cafe Test.\nMore text.")
        self.serve(URL.format("eva"), page_text("Eva Maes"))
        answer = {"name": "Jan Peeters", "quote": "Jan Peeters is a chef at Cafe Test.", "role": "chef"}
        out = self.deepen({"Jan Peeters": [page(URL.format("jan"))], "Eva Maes": [page(URL.format("eva"))]},
                       lambda text, who: [answer] if who == "Jan Peeters" else [named("Eva Maes")])
        self.assertEqual(self.verdicts(out), {other: "not_sure", bare: "not_sure"})
        self.assertEqual((self.held(other, "role"), self.held(bare), out.claim_ids), ([], [], []))

    def test_a_page_without_a_role_adds_no_role_claim(self):
        """A mention without a role stores its relations but no role taken from the page title."""
        person_id = self.person("Jan Peeters")
        self.serve(URL.format("jan"), page_text("Jan Peeters"))
        self.deepen({"Jan Peeters": [page(URL.format("jan"))]}, lambda text, who: [named("Jan Peeters", role=None)])
        self.assertEqual(self.held(person_id, "role"), [])

    def test_an_email_is_stored_from_a_confirmed_employer_or_own_page_for_any_looked_up_person(self):
        """The email a confirmed page prints is stored for a person beyond the first ten and from an own page, not
        from an other page or a page that prints a stranger's address."""
        for n in range(10):
            self.person(f"Ann Person{chr(97 + n)}", complete=True, contact=True)
        late = self.person("Lou Late")
        self.serve(URL.format("late"), page_text("Lou Late", " Mail lou@example.edu"))
        self.deepen({"Lou Late": [page(URL.format("late"))]}, lambda text, who: [named(who)])
        self.assertEqual([c.value for c in self.held(late, "email")], ["lou@example.edu"])
        cases = [("employer", " Mail jan@example.edu", ["jan@example.edu"]), ("own", " Mail jan@example.edu", ["jan@example.edu"]),
                 ("other", " Mail jan@example.edu", []), ("employer", "", [])]
        for kind, extra, stored in cases:
            with self.subTest(kind=kind, extra=extra):
                self.store = make_db(self)
                self.people, self.searches = [], 0
                person_id = self.person("Jan Peeters", complete=True)
                self.serve(URL.format("jan"), page_text("Jan Peeters", extra))
                self.deepen({"Jan Peeters": [page(URL.format("jan"), kind)]}, lambda text, who: [named(who)])
                self.assertEqual([c.value for c in self.held(person_id, "email")], stored)

    def test_the_email_is_stored_once_when_the_reading_returns_the_person_twice(self):
        person_id = self.person("Jan Peeters", complete=True)
        self.serve(URL.format("jan"), page_text("Jan Peeters", " Mail jan@example.edu"))
        out = self.deepen({"Jan Peeters": [page(URL.format("jan"))]}, lambda text, who: [named(who), named(who)])
        self.assertEqual([c.value for c in self.held(person_id, "email")], ["jan@example.edu"])
        self.assertEqual(len(out.claim_ids), len(set(out.claim_ids)))

    def test_blocked_and_refused_pages_store_no_source_and_are_named(self):
        """A LinkedIn, javascript: or private address is not read; each is named in the detail and stores nothing."""
        person_id = self.person("Jan Peeters")
        local = "http://10.0.0.1/jan"
        self.serve(local, None, "a local or private address")
        out = self.deepen({"Jan Peeters": [page("https://www.linkedin.com/in/jan"), page("javascript:alert(1)"),
                                        page(local)]})
        detail = out.lookups[0].detail
        self.assertIn("https://www.linkedin.com/in/jan: not fetchable", detail)
        self.assertIn("a javascript address: not fetchable", detail)
        self.assertIn(f"{local}: a local or private address", detail)
        self.assertEqual(self.read_urls, [[local]])
        self.assertEqual(self.verdicts(out), {person_id: "nothing_new"})
        count = self.store.conn.execute("SELECT count(*) FROM sources WHERE kind = 'page'").fetchone()[0]
        self.assertEqual(count, 0)

    def test_a_raising_call_beside_two_good_ones_fails_alone(self):
        """One lookup that raises gives failed; the two others still add their claims."""
        ids = [self.person(name) for name in ("Ann Ash", "Jan Peeters", "Eva Maes")]
        self.serve(URL.format("jan"), page_text("Jan Peeters"))
        self.serve(URL.format("eva"), page_text("Eva Maes"))
        out = self.deepen({"Ann Ash": RuntimeError("timed out"), "Jan Peeters": [page(URL.format("jan"))],
                        "Eva Maes": [page(URL.format("eva"))]}, lambda text, who: [named(who)])
        self.assertEqual([self.verdicts(out)[i] for i in ids], ["failed", "added", "added"])

    def test_a_503_is_tried_again_next_search_and_a_robots_refusal_is_not(self):
        """A read that may pass later fails the lookup and is retried; a robots.txt refusal holds as nothing new."""
        for failed, retry, verdict, again in (("HTTP 503", True, "failed", ["Jan Peeters"]),
                                              ("robots.txt disallows it", False, "nothing_new", [])):
            with self.subTest(failed=failed):
                self.store = make_db(self)
                self.people, self.searches = [], 0
                person_id = self.person("Jan Peeters")
                self.serve(URL.format("jan"), None, failed, retry)
                out = self.deepen({"Jan Peeters": [page(URL.format("jan"))]})
                self.assertEqual(self.verdicts(out), {person_id: verdict})
                self.deepen({"Jan Peeters": [page(URL.format("jan"))]})
                self.assertEqual(self.looked_up(), again)

    def test_two_of_five_pages_are_read_and_a_page_twice_is_read_once(self):
        """Only the first PAGES distinct pages of an answer are read; one address given twice is read once."""
        self.person("Jan Peeters")
        self.person("Eva Maes")
        five = [page(URL.format(n)) for n in "abcde"]
        twice = [page(URL.format("a")), page(URL.format("a") + "/#bio")]
        self.deepen({"Jan Peeters": five, "Eva Maes": twice})
        self.assertEqual(self.read_urls, [[URL.format("a"), URL.format("b")]])

    def test_missing_recordings_give_a_note_no_rows_and_nothing_in_the_step_log(self):
        """A replay without a single recorded lookup ends with a note, no lookup row and no FixtureMissing in its log."""
        self.person("Jan Peeters")
        out = self.deepen({"Jan Peeters": FixtureMissing("no LLM fixture lookup-0123")})
        self.assertEqual((out.lookups, out.note), ([], "no recorded lookup"))
        self.assertEqual(self.store.conn.execute("SELECT count(*) FROM lookups").fetchone()[0], 0)
        self.assertNotIn("FixtureMissing", self.step.log or "")

    def test_a_middle_name_on_one_side_is_the_same_person_and_another_first_name_is_not(self):
        """The page may write a middle name the stored name lacks, or the reverse; the first and last word must agree."""
        same = [("Jan Peeters", "Jan Willem Peeters"), ("Jan Willem Peeters", "Jan Peeters"), ("Jan Peeters", "J. Peeters")]
        other = [("Jan Peeters", "Piet Peeters"), ("Jan Peeters", "Jan Willem Maes"), ("Peeters", "Jan Peeters")]
        self.assertEqual([deepen.named_as(a, b) for a, b in same + other], [True] * 3 + [False] * 3)

    def test_an_address_that_is_no_web_page_is_named_by_its_kind_only(self):
        """A mail or phone address the model gives as a page never reaches the stored note; a blocked web page is named."""
        answer = LookupAnswer(pages=[LookupPage(url="mailto:jan@example.org", kind="own", why="x"),
                                     LookupPage(url="https://www.linkedin.com/in/jan", kind="other", why="x")])
        pages, notes = deepen.chosen_pages(answer)
        self.assertEqual((pages, notes), ([], ["a mailto address: not fetchable", "https://www.linkedin.com/in/jan: not fetchable"]))

    def test_a_long_page_is_cut_around_the_name_so_one_call_reads_it(self):
        """A page of 20,000 characters reaches the page reading as one part of at most PAGE_CHARS characters plus its
        title line, so the model is asked once for it."""
        text = ("Staff of the department. " * 400) + "Jan Peeters is professor of physics at Example University. " + ("More staff. " * 800)
        cut = deepen.titled("Staff", pageread.windows(text, ["Jan Peeters"], limit=deepen.PAGE_CHARS))
        self.assertIn("Jan Peeters is professor", cut)
        self.assertEqual(len(extract.chunks(cut)), 1)

    def test_version_one_chips_make_no_call(self):
        """Chips stored before this round give a note and no lookup."""
        self.person("Jan Peeters")
        out = self.deepen(chips=V1)
        self.assertEqual((out.lookups, self.llm.calls), ([], []))
        self.assertTrue(out.note)

    def lookup_ctx(self, search_id: str, http=True) -> StepContext:
        return StepContext(search_id=search_id, store=self.store, llm=self.llm, http=StubHttp() if http else None, now=now,
                           new_id=new_id, log=logging.getLogger("fn.step"), settings=self.settings)

    def test_one_looks_a_person_up_within_ninety_days_and_run_job_reads_the_id_from_the_question(self):
        """A lookup of 1 day ago does not stop a staff lookup; the job's question names the person it looks up."""
        person_id = self.person("Jan Peeters")
        with self.store.tx():
            self.store.save_lookup(Lookup(person_id=person_id, kind="web_person", verdict="nothing_new", detail=""),
                                   datetime.now(UTC) - timedelta(days=1))
        self.serve(URL.format("jan"), page_text("Jan Peeters"))
        self.llm = LookupLLM({"Jan Peeters": [page(URL.format("jan"))]}, lambda text, who: [named("Jan Peeters")])
        job = Search(id="j1", kind="job", question=deepen.job_question(person_id), status="running", code_sha="abc",
                     dirty=False, llm_mode="replay", settings_json="{}", boot_id="boot", created_at=CREATED)
        self.store.create_search(job)
        with mock.patch("fn.pageread.read_all", self.read_all):
            deepen.run_job(self.lookup_ctx("j1"), job)
        self.assertEqual(self.looked_up(), ["Jan Peeters"])
        self.assertEqual([(s.step, s.status) for s in self.store.list_steps("j1")], [(deepen.STEP, "ok")])
        self.assertEqual(self.store.last_lookup([person_id], "web_person")[0].verdict, "added")

    def test_one_makes_no_call_without_a_client_or_for_an_unknown_id(self):
        """Without an HTTP client, or for an id no person has, the output is a note and the model is never called."""
        person_id = self.person("Jan Peeters")
        self.llm = LookupLLM({})
        self.assertEqual(deepen.one(self.lookup_ctx("j1", http=False), LookupIn(person_id=person_id)).note, deepen.NO_CLIENT)
        self.assertEqual(deepen.one(self.lookup_ctx("j1"), LookupIn(person_id="nobody")).note, "no such person")
        self.assertEqual(self.llm.calls, [])

    def test_a_name_that_closes_the_person_block_fails(self):
        """A name holding </person> cannot be sent, so its lookup fails."""
        person_id = self.person("Jan </person> Peeters")
        out = self.deepen()
        self.assertEqual(self.verdicts(out), {person_id: "failed"})

    def test_a_store_error_for_one_person_fails_that_person_alone(self):
        """When storing one person's claims raises, that person gets failed and the others' claims are stored."""
        broken, fine = self.person("Jan Peeters"), self.person("Eva Maes")
        self.serve(URL.format("jan"), page_text("Jan Peeters"))
        self.serve(URL.format("eva"), page_text("Eva Maes"))
        upsert = self.store.upsert_claim

        def flaky(draft, at=None):
            if draft.person_id == broken:
                raise ValueError("disk full")
            return upsert(draft, at)

        with mock.patch.object(self.store, "upsert_claim", flaky):
            out = self.deepen({"Jan Peeters": [page(URL.format("jan"))], "Eva Maes": [page(URL.format("eva"))]},
                           lambda text, who: [named(who)])
        self.assertEqual(self.verdicts(out), {broken: "failed", fine: "added"})
        self.assertEqual(len(self.held(fine, "role")), 1)
        self.assertEqual(self.store.conn.execute("SELECT verdict FROM lookups WHERE person_id = ?", (broken,)).fetchone()[0],
                         "failed")

    def test_past_the_used_lookups_only_the_rest_of_the_limit_is_looked_up_and_no_gap_gets_contact_alone(self):
        """With used lookups the step looks up at most MAX_LOOKUPS minus used people with a gap; past that cap a top-10
        person with a gap gets no contact-only lookup, while a top-10 person without a gap still gets one."""
        for n in range(300):
            self.person(f"Ann Person{n:03}", complete=n < 10 and n % 2 == 0)
        top = [c.person_id for c in self.people[:10]]
        out = self.deepen(used=deepen.MAX_LOOKUPS)
        self.assertEqual(out.picked, top[::2])
        self.assertEqual((out.gaps, sorted(self.looked_up())), (0, [f"Ann Person{n:03}" for n in range(0, 10, 2)]))
        out = self.deepen(used=deepen.MAX_LOOKUPS - 5)
        self.assertEqual((out.picked, out.gaps), (top[1::2], 5))

    def test_a_person_in_skip_is_not_looked_up_even_after_a_failed_lookup_or_as_a_card_s_second_record(self):
        """A record in skip keeps its person out of the step, whatever lookup row it has and wherever it sits on a
        card."""
        failed = self.person("Ann Failed")
        with self.store.tx():
            self.store.save_lookup(Lookup(person_id=failed, kind="web_person", verdict="failed", detail=""),
                                   datetime.now(UTC) - timedelta(days=1))
        main = self.person("Bob Card")
        second = self.store.resolve_person([Identifier(scheme="seed", value="Bob Second")], "Bob Second").id
        self.people[-1] = self.people[-1].model_copy(update={"card_person_ids": [main, second]})
        out = self.deepen(skip=[failed, second])
        self.assertEqual((out.picked, out.note, self.llm.calls), ([], "nobody to look up", []))

    def test_missing_recordings_still_name_the_picked_people_and_count_their_gaps(self):
        """A replay without recordings returns the picks and how many had a gap, so a second pass leaves them out."""
        gap, contact = self.person("Jan Peeters"), self.person("Eva Maes", complete=True)
        missing = FixtureMissing("no LLM fixture lookup-0123")
        out = self.deepen({"Jan Peeters": missing, "Eva Maes": missing})
        self.assertEqual((out.note, out.picked, out.gaps), ("no recorded lookup", [gap, contact], 1))

    def test_version_one_chips_pick_nobody(self):
        """Chips stored before this round give no picks, no gaps and no call."""
        self.person("Jan Peeters")
        out = self.deepen(chips=V1)
        self.assertEqual((out.picked, out.gaps, self.llm.calls), ([], 0, []))

    def test_a_stored_input_without_skip_or_used_reads_as_a_first_pass(self):
        """A deepen input stored with chips only reads back with nobody to skip and no lookups used."""
        found = DeepenIn.model_validate_json(f'{{"chips": {V2.model_dump_json()}}}')
        self.assertEqual((found.skip, found.used), ([], 0))


if __name__ == "__main__":
    unittest.main()
