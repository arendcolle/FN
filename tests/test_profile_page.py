import re
import unittest
from datetime import UTC, date, datetime, timedelta
from html import unescape
from unittest import mock

from fastapi.testclient import TestClient

from fn import network
from fn.contracts import Candidate, Claim, ClaimDraft, Identifier, Org, ScorePart, Search, Source
from fn.present import debris, group_of, person_views, proof_quote
from fn.web.app import create_app
from fn.web.parts import person_card
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

EARLIER = now() - timedelta(days=2)
GENT_UNI = Org(id="ror:00cv9y106", name="Gent University", country_code="BE", source_id="org-src", fetched_at=EARLIER)
HEADING = re.compile(r'<h2 class="fn-section text-title">([^<]+)</h2>')
TOPIC = ScorePart(feature="topic", rank=1, points=1.0, detail="turbines, grids")
SENTENCE = "Ada Fictief leads the offshore wind turbines group and studies coastal grids for the harbour authority."


def words_of(html: str, stop: str | None = None) -> int:
    """The words in main, without forms and the body of closed proofs, up to the first stop marker."""
    main = re.search(r"<main.*?</main>", html, re.DOTALL).group(0)
    main = re.sub(r"<form.*?</form>", "", main, flags=re.DOTALL)
    main = re.sub(r'<div class="fn-proof__body">.*?</div></details>', "</details>", main, flags=re.DOTALL)
    if stop:
        main = main.split(stop, 1)[0]
    return len(re.sub(r"<[^>]+>", " ", unescape(main)).split())


class ProfilePageTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False,
                                 follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store.upsert_source(Source(id="org-src", kind="page", url="https://example.org/orgs", text="orgs",
                                        content_hash="h-orgs"))
        self.store.upsert_org(GENT_UNI, replace=True)
        self.n = 0

    def claim(self, person_id: str, kind: str, value: str, quote: str | None = None, source_kind: str = "page",
              url: str | None = None, title: str = "Example page", **fields) -> str:
        """A claim from its own source, first seen two days ago; returns the claim id."""
        self.n += 1
        text = quote or f"{value} of {person_id} {self.n}"
        source = Source(id=f"src-{self.n}", kind=source_kind, url=url or f"https://www.example.org/{self.n}", title=title,
                        text=text, content_hash=f"h-{self.n}")
        return self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, value=value, quote=text, quote_start=0,
                                                  quote_end=len(text), source=source, **fields), EARLIER).id

    def person(self, name: str, key: str, member: bool = False) -> str:
        found = self.store.resolve_person([Identifier(scheme="seed", value=key)], name).id
        if member:
            network.add(self.store, [found], via="search", now=EARLIER)
        return found

    def twins(self, name: str, key: str) -> tuple[str, str]:
        """Two unmerged records of one name at one organization, so that adding the card merges them."""
        first, second = self.person(name, key), self.person(name, f"{key}-2")
        for record in (first, second):
            self.claim(record, "affiliation", "Gent University", relation="works_at", org_id=GENT_UNI.id)
        return first, second

    def search(self, cards: list[list[str]]) -> None:
        """A done search s1 whose kept candidates are the cards, each a list of records, with a topic part."""
        self.store.create_search(Search(id="s1", question="Example question", status="done", created_at=now(),
                                        code_sha=None, dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        self.store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=ids[0], person_ids=ids, hit_person_ids=ids[:1], card_person_ids=ids,
                      section="new", rank=n, score=1.0, lane_ranks={"seeds": n}, score_parts=[TOPIC])
            for n, ids in enumerate(cards, 1)], [])

    def raw(self, person_id: str, **params) -> str:
        response = self.client.get(f"/people/{person_id}", params=params)
        self.assertEqual(response.status_code, 200)
        return response.text

    def page(self, person_id: str, **params) -> str:
        return unescape(self.raw(person_id, **params))

    def post(self, path: str, **fields) -> str:
        response = self.client.post(path, data=fields)
        self.assertEqual(response.status_code, 303, response.text[:300])
        return response.headers["location"]

    def section(self, html: str, title: str) -> str | None:
        found = re.search(rf'<section class="fn-profile__section" id="[a-z]+"><h2 class="fn-section text-title">{title}</h2>'
                          r"(.*?)</section>", html, re.DOTALL)
        return found.group(1) if found else None

    def facts(self, html: str, title: str) -> list[str]:
        """The claim ids of the section, in order."""
        return re.findall(r'class="fn-claim[^"]*" id="claim-([^"]+)"', self.section(html, title) or "")

    def test_sections_come_in_order_and_a_long_one_shows_three_and_show_more(self):
        """Headings are h2.text-title in sections in the Profile order; 5 work facts show 3 and Show 2 more."""
        ada = self.person("Ada Fictief", "ada", member=True)
        for n in range(5):
            self.claim(ada, "affiliation", f"Firm {n}", relation="worked_at", claim_date=f"20{10 + n}")
        self.claim(ada, "affiliation", "Gent University", relation="studied_at", org_id=GENT_UNI.id, claim_date="2012")
        self.claim(ada, "affiliation", "Example College", relation="studied_at", claim_date="2008")
        self.claim(ada, "location", "Paris", relation="born_in")
        self.claim(ada, "location", "Gent", relation="lives_in")
        self.claim(ada, "location", "Belgian", relation="origin")
        self.claim(ada, "email", "ada@example.org")
        html = self.page(ada)
        self.assertEqual(HEADING.findall(html), ["Work", "Education", "Ties to Flanders and Belgium", "Places", "Contact"])
        self.assertEqual(len(self.facts(html, "Work")), 3)
        self.assertIn(f'<p class="fn-more text-meta"><a class="fn-link" href="/people/{ada}?all=work#work">Show 2 more</a></p>',
                      html)
        self.assertEqual(len(self.facts(self.page(ada, all="work"), "Work")), 5)
        self.assertNotIn("Not provided", self.section(html, "Places"))

    def test_a_section_whose_only_fact_is_the_studied_row_or_the_head_place_is_left_out(self):
        """One study fact is the tie row, so Education is left out; one place the head shows leaves Places out."""
        ada = self.person("Ada Fictief", "ada")
        self.claim(ada, "affiliation", "Gent University", relation="studied_at", org_id=GENT_UNI.id, claim_date="2012")
        self.claim(ada, "location", "Gent", relation="lives_in")
        self.claim(ada, "topic", "Wind energy")
        html = self.page(ada)
        self.assertEqual(HEADING.findall(html), ["Work"])
        self.assertIn('<dt class="text-label">Tie to Flanders</dt>', html)
        self.assertNotIn('<dt class="text-label">Studied</dt>', html)
        self.assertIn("Gent</p>", html.split('class="fn-profile__role text-body">', 1)[1])

    def test_each_fact_stands_in_one_section_only(self):
        """A Belgian job is Work and a degree Education; a Belgian birthplace, an origin and a list role are Flanders."""
        ada = self.person("Ada Fictief", "ada")
        job = self.claim(ada, "affiliation", "Gent University", relation="works_at", org_id=GENT_UNI.id, claim_date="2020")
        degree = self.claim(ada, "affiliation", "Gent University", relation="studied_at", org_id=GENT_UNI.id, claim_date="2010")
        other = self.claim(ada, "affiliation", "Example College", relation="studied_at", claim_date="2006")
        birth = self.claim(ada, "location", "Antwerp, Belgium", relation="born_in")
        abroad = self.claim(ada, "location", "Paris, France", relation="born_in")
        origin = self.claim(ada, "location", "Belgian", relation="origin")
        listed = self.claim(ada, "role", "Fellow of Example Society", source_kind="seed_page", relation="fellow_of")
        html = self.page(ada)
        for title, ids in (("Work", [job]), ("Education", [degree, other]),
                           ("Ties to Flanders and Belgium", [birth, origin, listed]), ("Places", [abroad])):
            with self.subTest(title=title):
                self.assertCountEqual(self.facts(html, title), ids)
        self.assertEqual(html.count(f'id="claim-{job}"'), 1)

    def test_group_of_orders_its_rules(self):
        """Contact has no section; a study and a job go by relation; a birthplace outside Belgium is a place."""
        src = Source(id="s", kind="page", url="https://example.org/", text="t", content_hash="h")
        seed = src.model_copy(update={"kind": "seed_page"})

        def made(kind: str, relation: str | None, value: str = "x", org_id: str | None = None) -> Claim:
            return Claim(id="c", person_id="p", kind=kind, relation=relation, value=value, quote="q", quote_start=0,
                         quote_end=1, source_id="s", org_id=org_id)

        facts = {GENT_UNI.id: GENT_UNI}
        cases = [(made("email", None), src, None), (made("affiliation", "studied_at"), seed, "Education"),
                 (made("affiliation", "hosted_by"), seed, "Work"),
                 (made("location", "born_in", "Ghent"), src, "Ties to Flanders and Belgium"),
                 (made("location", "born_in", "Paris"), src, "Places"), (made("location", "lives_in"), seed, "Places"),
                 (made("affiliation", "member_of", org_id=GENT_UNI.id), src, "Ties to Flanders and Belgium"),
                 (made("affiliation", "member_of"), src, "Work"), (made("topic", None), seed, "Work"),
                 (made("topic", None), src, "Work")]
        for claim, source, group in cases:
            with self.subTest(claim=claim.kind, relation=claim.relation, source=source.kind):
                self.assertEqual(group_of(claim, facts, source), group)

    def test_the_summary_has_the_newest_study_the_tie_and_the_contact_or_not_found(self):
        """Studied is the newest study with its years unless it is the tie; Contact links or reads Not found."""
        ada = self.person("Ada Fictief", "ada", member=True)
        self.claim(ada, "affiliation", "Example College", relation="studied_at", claim_date="2006")
        self.claim(ada, "affiliation", "Gent University", relation="studied_at", org_id=GENT_UNI.id, claim_date="2012")
        html = self.page(ada)
        self.assertNotIn('<dt class="text-label">Studied</dt>', html)
        self.assertIn('<dt class="text-label">Tie to Flanders</dt><dd class="text-body">Studied at Gent University, '
                      '<span class="text-year">2012</span></dd>', html)
        self.assertIn('<dt class="text-label">Contact</dt><dd class="fn-contact__none text-body">Not found</dd>', html)
        self.claim(ada, "email", "ada@example.org")
        self.claim(ada, "phone", "+32 9 555 01 00")
        self.assertIn('<dd class="text-body"><a href="mailto:ada@example.org">ada@example.org</a> · '
                      '<a href="tel:+32 9 555 01 00">+32 9 555 01 00</a></dd>', self.page(ada))
        bo = self.person("Bo Fictief", "bo")
        self.claim(bo, "topic", "Wind energy")
        self.assertNotIn("Studied", self.page(bo))

    def test_a_found_contact_value_has_its_source_name_and_proof_and_not_correct(self):
        """A non-member's page holds only the kinds FN found, with no summary row; every Email and Phone row has one
        Not correct, nobody has Edit, and an imported value keeps its citation line."""
        long = "a" * 190 + "@health.example.gov"
        ada = self.person("Ada Fictief", "ada")
        self.claim(ada, "email", long, url="https://health.example.gov/staff", title="Staff directory", claim_date="2026-10")
        html = self.page(ada)
        contact = self.section(html, "Contact")
        self.assertEqual(re.findall(r'<dt class="text-label">([^<]+)</dt>', contact), ["Email"])
        self.assertIn(f'<div class="fn-contact__value text-body"><a href="mailto:{long}">{long}</a> <details class="fn-proof">'
                      '<summary class="fn-proof__name text-small" aria-label="Source for the email address: '
                      'health.example.gov">health.example.gov</summary>', contact)
        self.assertIn('>Staff directory</a>, ', contact)
        self.assertNotIn("fn-quote", contact)
        self.assertEqual(contact.count(">Not correct</button>"), 1)
        for gone in (">Edit<", "Not provided", 'class="fn-summary-list'):
            self.assertNotIn(gone, html)
        bo = self.person("Bo Fictief", "bo", member=True)
        self.claim(bo, "email", "bo@health.example.gov", url="https://health.example.gov/staff")
        self.claim(bo, "phone", "+1 301 555 0100", source_kind="import", title="people.csv", url="https://example.org/f")
        shown = self.section(self.page(bo), "Contact")
        self.assertIn('aria-label="Source for the email address: health.example.gov"', shown)
        self.assertEqual(shown.count(">Not correct</button>"), 2)
        self.assertNotIn(">Edit<", shown)
        self.assertNotIn("Source for the phone number", shown)

    def test_a_person_outside_the_network_without_contact_has_no_contact_section(self):
        """A non-member with no email and no phone has no Contact section and no Contact row in the summary."""
        ada = self.person("Ada Fictief", "ada")
        self.claim(ada, "topic", "Wind energy")
        html = self.page(ada)
        self.assertEqual(HEADING.findall(html), ["Work"])
        self.assertNotIn(">Contact<", html)

    def test_a_card_of_two_records_shows_both_and_not_this_person_separates_the_second(self):
        """With search and card the page combines the records; without search a page outside the network lists no possible match."""
        ada, twin = self.twins("Ada Fictief", "ada")
        mine = self.claim(ada, "topic", "Tidal energy")
        theirs = self.claim(twin, "topic", "Wind energy")
        self.search([[ada, twin]])
        html = self.page(ada, search="s1", card=ada)
        self.assertIn('<p class="fn-profile__combined text-small"><a href="#sources">Combined from 2 records</a></p>', html)
        self.assertEqual(self.facts(html, "Work").count(mine) + self.facts(html, "Work").count(theirs), 2)
        self.assertEqual(re.findall(r'name="other" value="([^"]+)"', self.section(html, "Sources")), [twin])
        self.assertIsNone(self.section(html, "Possible matches"))
        alone = self.page(ada)
        self.assertNotIn("Wind energy", alone)
        self.assertNotIn("Combined from", alone)
        self.assertIsNone(self.section(alone, "Possible matches"))
        self.post(f"/people/{ada}/not-same", other=twin, next=f"/people/{ada}?search=s1&card={ada}")
        after = self.page(ada, search="s1", card=ada)
        self.assertNotIn("Combined from", after)
        self.assertNotIn("Wind energy", after)

    def test_possible_matches_are_compare_tables_with_both_buttons(self):
        """One match reads 'the possible match', ten read 'n of 10'; the left Name is text and the right one links.

        After Different person nine tables and the done line are left.
        """
        ada = self.person("Ada Fictief", "ada", member=True)
        twin = self.person("Ada Fictief", "twin")
        self.claim(twin, "affiliation", "Gent University", relation="works_at", org_id=GENT_UNI.id)
        one = self.section(self.page(ada), "Possible matches")
        self.assertEqual(re.findall(r"<caption>(.*?)</caption>", one), ["This person and the possible match"])
        self.assertIn(f'<tr><th scope="row">Name</th><td>Ada Fictief</td><td><a href="/people/{twin}?back=%2Fpeople%2F{ada}%23matches">'
                      "Ada Fictief</a></td></tr>", one)
        self.assertEqual(re.findall(r">(Same person|Different person)</button>", one), ["Same person", "Different person"])
        others = [twin, *[self.person("Ada Fictief", f"twin-{n}") for n in range(9)]]
        ten = self.section(self.page(ada), "Possible matches")
        self.assertEqual(sorted(re.findall(r"<caption>This person and possible match (\d+) of 10</caption>", ten), key=int),
                         [str(n) for n in range(1, 11)])
        self.post(f"/people/{ada}/not-same", other=others[0], next=f"/people/{ada}#matches")
        after = self.section(self.page(ada), "Possible matches")
        self.assertEqual((after.count('<table class="fn-compare">'), "Marked as a different person" in after), (9, True))

    def test_a_page_outside_the_network_runs_no_possible_match_query(self):
        """A person outside the network has no Possible matches section and the query is never run; the same person
        added from a card has the section."""
        ada, twin = self.person("Ada Fictief", "ada"), self.person("Ada Fictief", "twin")
        self.search([[ada]])
        with mock.patch.object(network, "possible_matches", side_effect=AssertionError("no query")):
            html = self.page(ada, search="s1", card=ada)
        self.assertIsNone(self.section(html, "Possible matches"))
        self.post(f"/searches/s1/people/{ada}/add", next="/searches/s1")
        added = self.section(self.page(ada, search="s1", card=ada), "Possible matches")
        self.assertIn(f"/people/{twin}", added)

    def test_a_result_with_a_network_namesake_shows_line_table_and_three_buttons(self):
        """A result with a network namesake has the same-name line, a Compare table with 'This person' and 'In your
        network', then Same person, Add as new and Skip."""
        ada, twin = self.person("Ada Fictief", "ada", member=True), self.person("Ada Fictief", "twin")
        self.claim(ada, "role", "Engineer")
        self.search([[twin]])
        html = self.page(twin, search="s1", card=twin)
        head = html.split('<main class="fn-page">', 1)[1]
        self.assertIn("<caption>This person and Ada Fictief in your network</caption>", head)
        self.assertIn('<th scope="col" class="text-label">This person</th><th scope="col" class="text-label">In your network</th>', head)
        self.assertLess(head.index("Same name as"), head.index('<table class="fn-compare">'))
        self.assertLess(head.index("</table>"), head.index(">Same person<"))
        self.assertEqual(re.findall(r">(Same person|Add as new|Skip)</button>", head), ["Same person", "Add as new", "Skip"])
        self.assertIn(f'<td><a href="/people/{ada}?back=', head)

    def test_a_merged_record_and_an_unknown_card_key_do_not_break_the_page(self):
        """A card whose second record was merged since has one record; a card key of no candidate keeps profile routes."""
        ada, twin = self.twins("Ada Fictief", "ada")
        self.claim(twin, "topic", "Wind energy")
        self.search([[ada, twin]])
        network.merge(self.store, [twin], ada, now=now())
        html = self.page(ada, search="s1", card=ada)
        self.assertIn("Wind energy", html)
        self.assertIn('<section class="fn-profile__section" id="sources">', html)
        self.assertNotIn("Combined from", html)
        lone = self.person("Bo Fictief", "bo")
        html = self.page(lone, search="s1", card="nobody")
        self.assertIn(f'action="/people/{lone}/add"', html)

    def test_head_buttons_post_to_the_cards_route_and_act_on_every_record(self):
        """Add puts both records in the network; Add as new with a same-name network person keeps them apart from it."""
        ada, twin = self.twins("Ada Fictief", "ada")
        self.claim(ada, "topic", "Tidal energy")
        self.claim(twin, "topic", "Wind energy")
        self.search([[ada, twin]])
        here = f"/people/{ada}?search=s1&card={ada}"
        html = self.page(ada, search="s1", card=ada)
        self.assertIn(f'<form method="post" action="/searches/s1/people/{ada}/add"><input type="hidden" name="next" '
                      f'value="{here}">', html)
        self.assertIn(f'action="/searches/s1/people/{ada}/skip"', html)
        self.assertEqual(self.post(f"/searches/s1/people/{ada}/add", next=here), here)
        for record in (ada, twin):
            self.assertEqual(self.store.get_persons([self.store.canonical_ids([record])[record]]).popitem()[1].list_status,
                             "in_list")

    def test_add_as_new_on_a_card_page_leaves_both_records_apart_from_the_network_person(self):
        """The same-name buttons send the network person's id as match and act on the whole card."""
        net = self.person("Ada Fictief", "ada-net", member=True)
        ada, twin = self.twins("Ada Fictief", "ada")
        self.claim(ada, "topic", "Tidal energy")
        self.claim(twin, "topic", "Wind energy")
        self.search([[ada, twin]])
        here = f"/people/{ada}?search=s1&card={ada}"
        html = self.page(ada, search="s1", card=ada)
        for action in ("same", "new"):
            self.assertIn(f'action="/searches/s1/people/{ada}/{action}"><input type="hidden" name="match" value="{net}">', html)
        self.assertEqual(self.post(f"/searches/s1/people/{ada}/new", match=net, next=here), here)
        canonical = self.store.canonical_ids([net, ada, twin])
        self.assertEqual(canonical[ada], canonical[twin])
        self.assertNotEqual(canonical[ada], canonical[net])
        self.assertEqual(self.store.get_persons([canonical[ada]])[canonical[ada]].list_status, "in_list")

    def test_not_correct_on_the_second_records_fact_shows_its_removed_line_with_undo(self):
        """The page of a card undoes a decision on any of its records, in place."""
        ada, twin = self.twins("Ada Fictief", "ada")
        self.claim(ada, "topic", "Tidal energy")
        fact = self.claim(twin, "topic", "Wind energy")
        self.search([[ada, twin]])
        here = f"/people/{ada}?search=s1&card={ada}"
        self.assertEqual(self.post(f"/claims/{fact}/reject", next=f"{here}#claim-{fact}"), f"{here}#claim-{fact}")
        html = self.page(ada, search="s1", card=ada)
        self.assertRegex(html, rf'<div class="fn-claim fn-claim--removed" id="claim-{fact}"><form [^>]*undo[^>]*>'
                               r"<span>Topic: Wind energy</span><span>· Removed</span> .*?>Undo</button>")

    def test_show_more_keeps_the_search_and_card(self):
        """The link adds all=<section> to the page's own query, before the section anchor."""
        ada = self.person("Ada Fictief", "ada")
        for n in range(5):
            self.claim(ada, "topic", f"Topic {n}")
        self.search([[ada]])
        html = self.page(ada, search="s1", card=ada, all="education")
        self.assertIn(f'href="/people/{ada}?search=s1&card={ada}&all=work#work">Show 2 more</a>', html)

    def test_a_removed_fact_keeps_its_place_in_its_section(self):
        """The Removed line stands at the index the fact had."""
        ada = self.person("Ada Fictief", "ada")
        ids = [self.claim(ada, "affiliation", f"Firm {n}", relation="worked_at", claim_date=f"202{n}") for n in range(3)]
        before = self.facts(self.page(ada), "Work")
        self.post(f"/claims/{ids[1]}/reject")
        after = self.facts(self.page(ada), "Work")
        self.assertEqual(before, [ids[2], ids[1], ids[0]])
        self.assertEqual(after, before)

    def test_quotes_that_are_page_debris_are_left_out_and_the_title_link_stays(self):
        """A field label after a list mark and author-list tokens show no quote; a sentence without the name does."""
        ada = self.person("Ada Fictief", "ada")
        for topic, text in (("Wind energy", "* company name: Example Corp, a harbour authority with many staff members"),
                            ("Tidal energy", "Ada Fictief 1, 2 Author Orcid Image"),
                            ("Solar energy", "The offshore wind turbines group studies coastal grids for the harbour authority.")):
            with self.subTest(text=text):
                self.claim(ada, "topic", topic, quote=text, title="Staff page")
        html = self.page(ada)
        self.assertEqual(html.count("<blockquote"), 1)
        self.assertIn("The offshore wind turbines group studies coastal grids", html)
        self.assertEqual(html.count(">Staff page</a>"), 3)

    def test_proof_quote_unescapes_cuts_around_the_match_and_marks_the_cut(self):
        """&amp; reads &; 300 words give at most 25 around the first matched word, with … at each cut end."""
        source = Source(id="s", kind="page", url="https://example.org/", text="t", content_hash="h")
        claim = Claim(id="c", person_id="p", kind="topic", value="x", quote="Ada Fictief studies wind &amp; solar energy for "
                      "coastal grids and harbour towns in Flanders.", quote_start=0, quote_end=1, source_id="s")
        self.assertEqual(proof_quote(claim, source, "Ada Fictief", []),
                         "“Ada Fictief studies wind & solar energy for coastal grids and harbour towns in Flanders.”")
        long = " ".join(["Ada Fictief"] + [f"word{n}" for n in range(150)] + ["turbines"] + [f"more{n}" for n in range(150)])
        cut = proof_quote(claim.model_copy(update={"quote": long}), source, "Ada Fictief", ["grids", "turbines"])
        inner = cut.strip("“”")
        self.assertLessEqual(len(inner.split()), 25)
        self.assertIn("turbines", inner)
        self.assertTrue(inner.startswith("…") and inner.endswith("…"))
        self.assertIsNone(proof_quote(claim, source.model_copy(update={"kind": "record"}), "Ada Fictief", []))

    def test_debris_rules(self):
        """A field label after a list mark, image or author-list tokens, a markup entity and under 4 words are debris."""
        good = "Ada Fictief leads the offshore wind turbines group at the harbour authority"
        self.assertFalse(debris(good))
        self.assertFalse(debris("She leads the lab."))
        self.assertFalse(debris("Name: the group leads the harbour authority"))
        for text in ("- company name: " + good, "* Name: Ada Fictief", "Ann", "Ada Fictief 1, 2 Author Orcid Image",
                     "![Ada Fictief portrait at the harbour authority]", "Ada Fictief&amp;nbsp;leads the group at the harbour"):
            with self.subTest(text=text):
                self.assertTrue(debris(text))

    def test_a_quote_escapes_once_and_the_proof_holds_title_date_and_original_link(self):
        """The raw page has &amp; once; a dated claim cites 'title, date · Original page'; an undated one has no date."""
        ada = self.person("Ada Fictief", "ada")
        dated = self.claim(ada, "topic", "Wind energy", quote="Ada Fictief studies wind & solar energy for coastal grids and "
                           "harbour towns in Flanders.", title="Staff page", claim_date="2024-05", date_precision="month")
        self.claim(ada, "topic", "Solar energy", quote=SENTENCE, title="Lab page")
        raw = self.raw(ada)
        self.assertIn("studies wind &amp; solar energy", raw)
        self.assertNotIn("&amp;amp;", raw)
        html = unescape(raw)
        self.assertRegex(html, r'Staff page</a>, May 2024 · <a href="https://www.example.org/\d+">Original page</a></p>')
        self.assertIn(f'id="claim-{dated}"', html)
        self.assertNotIn("date unknown", html)
        self.assertRegex(html, r'Lab page</a> · <a href="https://www.example.org/\d+">Original page</a>')

    def test_a_record_has_no_quote_and_an_fn_source_has_no_original_page(self):
        """An OpenAlex record's proof is its cite and Original page; an import row's has the date and no link out."""
        ada = self.person("Ada Fictief", "ada")
        self.claim(ada, "topic", "Wind energy", source_kind="record", url="https://openalex.org/A1", title="Ada Fictief",
                   claim_date="2025")
        self.claim(ada, "topic", "Solar energy", source_kind="import", url="fn:import/1#2", title="contacts.csv, row 2",
                   claim_date="2026-11-03", date_precision="day")
        html = self.page(ada)
        self.assertNotIn("<blockquote", html)
        self.assertIn('OpenAlex record</a>, 2025 · <a href="https://openalex.org/A1">Original page</a>', html)
        self.assertIn("Import contacts.csv, row 2</a>, 3 November 2026</p>", html)
        self.assertEqual(html.count("Original page"), 1)

    def test_a_fact_is_one_line_with_the_source_name_and_not_correct_beside_it(self):
        """The what span and details sit in fn-claim__line with a space between; the form is a child of the head."""
        ada = self.person("Ada Fictief", "ada")
        fact = self.claim(ada, "topic", "Wind energy", quote=SENTENCE, title="Lab page")
        html = self.page(ada)
        self.assertRegex(html, rf'<div class="fn-claim__head"><div class="fn-claim__line"><span class="fn-claim__what '
                               rf'text-body">Topic: Wind energy</span> <details class="fn-proof"><summary class="fn-proof__name '
                               rf'text-small" aria-label="Source for Topic: Wind energy: example.org">example.org</summary>'
                               rf'<div class="fn-proof__body"><blockquote class="fn-quote text-quote">'
                               rf'“{SENTENCE}”</blockquote>'
                               rf'.*?</details></div><form method="post" action="/claims/{fact}/reject">')

    def test_the_head_says_remove_from_network_and_each_fact_not_correct(self):
        """No button reads Remove alone."""
        ada = self.person("Ada Fictief", "ada", member=True)
        self.claim(ada, "topic", "Wind energy")
        html = self.page(ada)
        self.assertIn(">Remove from network</button>", html)
        self.assertIn(">Not correct</button>", html)
        self.assertNotIn(">Remove</button>", html)

    def test_a_person_with_only_a_worked_at_claim_has_no_employer_anywhere(self):
        """The role line of the page, a card and a network row leave out a past employer."""
        ada = self.person("Ada Fictief", "ada", member=True)
        self.claim(ada, "affiliation", "Firm Zero", relation="worked_at", claim_date="2015")
        self.assertNotIn("fn-profile__role", self.page(ada))
        view = person_views(self.store, [[ada]], date.today())[0]
        self.assertIsNone(view.employer)
        self.assertNotIn("Firm Zero", person_card(view, "s1"))
        self.assertNotIn("Firm Zero", self.client.get("/people").text)
        self.claim(ada, "affiliation", "Firm One", relation="works_at", claim_date="2016")
        self.assertIn("Firm One", self.page(ada))

    def test_the_first_screen_and_the_whole_page_stay_within_the_word_budget(self):
        """At most 90 words before the first section and 180 in main, on a seed, OpenAlex, web, member and combined page."""
        seed = self.person("Sofie Seed", "seed")
        self.claim(seed, "role", "Fellow of Example Society", source_kind="seed_page", relation="fellow_of")
        alex = self.person("Olav Alex", "alex")
        for n in range(58):
            self.claim(alex, "topic", f"Topic {n}", source_kind="record", url=f"https://openalex.org/W{n}",
                       title=f"OpenAlex work W{n}", claim_date="2024")
        web = self.person("Wim Web", "web")
        self.claim(web, "topic", "Wind energy", quote="Wim Web 1, 2 Author Orcid Image", title="Staff page of the lab")
        member = self.person("Mia Member", "mia", member=True)
        for n in range(5):
            self.claim(member, "affiliation", f"Firm {n}", relation="worked_at", claim_date=f"20{10 + n}", quote=SENTENCE)
        self.claim(member, "affiliation", "Gent University", relation="studied_at", org_id=GENT_UNI.id, claim_date="2012")
        self.claim(member, "affiliation", "Example College", relation="studied_at", claim_date="2008")
        self.claim(member, "location", "Paris", relation="born_in")
        self.claim(member, "email", "mia@example.org")
        ada, twin = self.twins("Ada Fictief", "ada")
        self.claim(ada, "topic", "Tidal energy", quote=SENTENCE)
        self.claim(twin, "topic", "Wind energy", quote=SENTENCE)
        self.search([[ada, twin]])
        pages = {"seed": self.page(seed), "openalex": self.page(alex), "web": self.page(web), "member": self.page(member),
                 "combined": self.page(ada, search="s1", card=ada)}
        for name, html in pages.items():
            with self.subTest(page=name):
                first = words_of(html, '<section class="fn-profile__section"')
                self.assertLessEqual(first, 90, first)
                self.assertLessEqual(words_of(html), 180, words_of(html))

    def sourced(self, person_id: str, kind: str, value: str, source: Source, **fields) -> str:
        """A claim whose source is the given one; returns the claim id."""
        return self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, value=value, quote=source.text, quote_start=0,
                                                  quote_end=len(source.text), source=source, **fields), EARLIER).id

    def imported(self, person_id: str, kind: str, value: str, row: int) -> str:
        """A claim from row `row` of contacts.csv, imported on 3 November 2026."""
        source = Source(id=f"imp-{row}", kind="import", url=f"fn:import/x#row-{row}", title=f"contacts.csv, row {row}",
                        text=f"{kind}: {value}", content_hash=f"h-imp-{row}", fetched_at=datetime(2026, 11, 3, 12, tzinfo=UTC))
        return self.sourced(person_id, kind, value, source, claim_date="2026-11-03", date_precision="day",
                            date_method="sheet_date")

    def linkedin(self, person_id: str, address: str) -> None:
        self.store.add_identifier(person_id, Identifier(scheme="profile_url", value=address))

    def test_not_correct_on_an_email_shows_the_next_one_and_undo_brings_it_back(self):
        """Removing the newest email leaves one Removed line over the older address, which has its own Not correct."""
        ada = self.person("Ada Fictief", "ada", member=True)
        old = self.claim(ada, "email", "ada@old.example.org", claim_date="2024-05")
        new = self.claim(ada, "email", "ada@new.example.org", claim_date="2026-03")
        self.assertIn(">ada@new.example.org</a>", self.section(self.page(ada), "Contact"))
        self.post(f"/claims/{new}/reject", next=f"/people/{ada}#contact")
        contact = self.section(self.page(ada), "Contact")
        self.assertIn("<span>ada@new.example.org</span><span>· Removed</span>", contact)
        self.assertIn(">ada@old.example.org</a>", contact)
        self.assertEqual(re.findall(r'action="/claims/([^/]+)/reject"', contact), [old])
        undo = re.search(r'action="/events/([^"]+)/undo"', contact).group(1)
        self.post(f"/events/{undo}/undo", next=f"/people/{ada}#contact")
        contact = self.section(self.page(ada), "Contact")
        self.assertNotIn("Removed", contact)
        self.assertEqual(re.findall(r'action="/claims/([^/]+)/reject"', contact), [new])

    def test_one_email_from_two_pages_is_one_row_and_one_not_correct_hides_both(self):
        """Two pages naming one address give one Email row; rejecting it hides both and leaves only the Removed line."""
        ada = self.person("Ada Fictief", "ada", member=True)
        long = "a" * 190 + "@health.example.gov"
        first = self.claim(ada, "email", long, claim_date="2025-01")
        self.claim(ada, "email", long, claim_date="2026-02")
        self.assertEqual(self.section(self.page(ada), "Contact").count(">Not correct</button>"), 1)
        self.post(f"/claims/{first}/reject", next=f"/people/{ada}#contact")
        contact = self.section(self.page(ada), "Contact")
        self.assertEqual(contact.count('<dt class="text-label">Email</dt>'), 1)
        self.assertIn(f"<span>{long}</span><span>· Removed</span>", contact)
        self.assertNotIn("mailto:", contact)
        self.assertNotIn(">Not correct</button>", contact)

    def test_an_email_rejected_without_an_event_is_not_shown(self):
        """A rejected email with no decision event behind it is gone, and a network person then gets the import line."""
        ada = self.person("Ada Fictief", "ada", member=True)
        self.store.set_claim_rejected(self.claim(ada, "email", "ada@example.org"), now())
        contact = self.section(self.page(ada), "Contact")
        self.assertNotIn("ada@example.org", contact)
        self.assertIn('<p class="fn-note text-small">FN found no contact details. An <a href="/imports/new">import</a> '
                      "can add them.</p>", contact)

    def test_an_imported_email_and_a_phone_only_each_have_one_row_with_not_correct(self):
        """An imported email cites its file and row; a person with only a phone has one Phone row; outsiders get no summary row."""
        ada = self.person("Ada Fictief", "ada", member=True)
        self.imported(ada, "email", "ada@example.org", 7)
        contact = self.section(self.page(ada), "Contact")
        self.assertIn('>From import contacts.csv, row 7</a>, 3 November 2026</p>', contact)
        self.assertEqual(contact.count(">Not correct</button>"), 1)
        bo = self.person("Bo Fictief", "bo", member=True)
        self.claim(bo, "phone", "+1 301 555 0100", url="https://health.example.gov/staff")
        contact = self.section(self.page(bo), "Contact")
        self.assertEqual(re.findall(r'<dt class="text-label">([^<]+)</dt>', contact), ["Phone"])
        self.assertEqual(contact.count(">Not correct</button>"), 1)
        eli = self.person("Eli Fictief", "eli")
        self.claim(eli, "phone", "+1 301 555 0101", url="https://health.example.gov/staff")
        self.imported(eli, "email", "eli@example.org", 8)
        html = self.page(eli)
        self.assertEqual(self.section(html, "Contact").count(">Not correct</button>"), 2)
        self.assertNotIn(">Contact</dt>", html)

    def test_a_linkedin_row_names_its_record_or_its_import_and_has_no_action(self):
        """The row cites the LinkedIn record or the newest import with its day, has no form, and no source gives no cite line."""
        record, imp, bare = (self.person(n, k, member=True) for n, k in (("Ada Fictief", "ada"), ("Bo Fictief", "bo"), ("Cy Fictief", "cy")))
        address = "https://www.linkedin.com/in/ada-fictief"
        self.linkedin(record, address)
        card = Source(id="li-1", kind="vendor_record", url=address + "/", title="Ada Fictief", text="name: Ada Fictief",
                      content_hash="h-li")
        self.sourced(record, "topic", "Wind energy", card)
        contact = self.section(self.page(record), "Contact")
        self.assertIn(f'<a href="{address}">linkedin.com/in/ada-fictief</a>', contact)
        self.assertIn('>From a LinkedIn record</a></p>', contact)
        self.assertIn('href="/sources/li-1?back=', contact)
        self.linkedin(imp, "https://www.linkedin.com/in/bo-fictief")
        self.imported(imp, "topic", "Wind energy", 3)
        contact = self.section(self.page(imp), "Contact")
        self.assertIn(">From import contacts.csv, row 3</a>, 3 November 2026</p>", contact)
        self.linkedin(bare, "https://www.linkedin.com/in/cy-fictief")
        contact = self.section(self.page(bare), "Contact")
        self.assertIn(">linkedin.com/in/cy-fictief</a>", contact)
        self.assertNotIn("fn-cite", contact)
        for name in (record, imp, bare):
            self.assertNotIn("<form", self.section(self.page(name), "Contact"))

    def test_the_linkedin_row_shows_the_record_merged_last(self):
        """Of three records with an address the one merged last shows, with its host and trailing slash cleaned."""
        ada, first, last = (self.person("Ada Fictief", k, member=True) for k in ("ada", "ada-2", "ada-3"))
        self.linkedin(ada, "https://www.linkedin.com/in/ada-one")
        self.linkedin(first, "https://www.linkedin.com/in/ada-two")
        self.linkedin(last, "https://be.linkedin.com/in/ada-fictief/")
        self.store.set_merged_into(first, ada, now() - timedelta(days=1))
        self.store.set_merged_into(last, ada, now())
        contact = self.section(self.page(ada), "Contact")
        self.assertIn('<a href="https://www.linkedin.com/in/ada-fictief">linkedin.com/in/ada-fictief</a>', contact)
        self.assertNotIn("ada-one", contact)
        self.assertNotIn("ada-two", contact)

    def test_a_network_person_without_contact_gets_the_import_line(self):
        """No contact value gives the line with a link to Import; a LinkedIn address alone is a value, so no line."""
        ada = self.person("Ada Fictief", "ada", member=True)
        self.assertIn('<a href="/imports/new">import</a>', self.section(self.page(ada), "Contact"))
        self.linkedin(ada, "https://www.linkedin.com/in/ada-fictief")
        contact = self.section(self.page(ada), "Contact")
        self.assertNotIn("FN found no contact details", contact)
        self.assertIn("linkedin.com/in/ada-fictief", contact)


if __name__ == "__main__":
    unittest.main()
