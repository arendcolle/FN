import re
import unittest
from datetime import timedelta
from html import unescape

from fastapi.testclient import TestClient

from fn import evidence, network, present
from fn.contracts import (
    Candidate,
    CardFit,
    Claim,
    ClaimDraft,
    Identifier,
    Org,
    Search,
    Source,
)
from fn.web.app import create_app
from fn.worker import now
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

EARLIER = now() - timedelta(days=2)
YEAR = now().astimezone().date().year
HEALTH_TEXT = "Chief scientist at Example Health"
TOPIC = "Matches: wind"


def org(org_id: str, name: str, country: str, **fields) -> Org:
    return Org(id=org_id, name=name, country_code=country, source_id="org-src", fetched_at=EARLIER, **fields)


CHALMERS = org("openalex:I1", "Chalmers University of Technology", "SE", city="Gothenburg")
GHENT = org("ror:00cv9y106", "Ghent University", "BE", city="Gent")
MIT = org("ror:042nb2s44", "Massachusetts Institute of Technology", "US")
HEALTH = org("openalex:I2", "Example Health", "US")
BAEF = org("ror:03q6ab901", "Belgian American Educational Foundation", "BE", region="BRU", city="Brussels")
UCLOUVAIN = org("ror:02495e989", "UCLouvain", "BE", region="WAL", city="Louvain-la-Neuve")
TIES = "Ties to Flanders and Belgium"
LEUVEN = org("ror:05f950310", "KU Leuven", "BE", city="Leuven")


class PersonContentCase(unittest.TestCase):
    """A person page built from made-up people, one rule of the person page content at a time."""

    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        app = create_app(self.settings, StubLLM(error=AssertionError("no LLM")), StubHttp())
        self.client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False, follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.store.upsert_source(Source(id="org-src", kind="page", url="https://example.org/orgs", text="orgs",
                                        content_hash="h-orgs"))
        for found in (CHALMERS, GHENT, MIT, HEALTH, BAEF, UCLOUVAIN, LEUVEN):
            self.store.upsert_org(found, replace=True)
        self.n = 0

    def source(self, text: str = "", kind: str = "page", url: str | None = None, title: str | None = "Example page",
               **fields) -> Source:
        self.n += 1
        return Source(id=f"src-{self.n}", kind=kind, url=url or f"https://www.example.org/{self.n}", title=title,
                      text=text or f"Page {self.n}", content_hash=f"h-{self.n}", **fields)

    def claim(self, person_id: str, kind: str, value: str, quote: str | None = None, src: Source | None = None,
              **fields) -> str:
        """A claim quoting the whole of its source, or the quote in it; returns the claim id."""
        src = src or self.source(quote or f"{value} of {person_id}")
        quote = quote or src.text
        start = src.text.index(quote)
        draft = ClaimDraft(person_id=person_id, kind=kind, value=value, quote=quote, quote_start=start,
                           quote_end=start + len(quote), source=src, **fields)
        return self.store.upsert_claim(draft, EARLIER).id

    def person(self, name: str, key: str, scheme: str = "seed", member: bool = False) -> str:
        found = self.store.resolve_person([Identifier(scheme=scheme, value=key)], name).id
        if member:
            network.add(self.store, [found], via="search", now=EARLIER)
        return found

    def raw(self, path: str, **params) -> str:
        response = self.client.get(path, params=params)
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response.text

    def page(self, person_id: str, **params) -> str:
        return unescape(self.raw(f"/people/{person_id}", **params))

    def section(self, html: str, title: str) -> str:
        found = re.search(rf'<section class="fn-profile__section" id="[a-z]+"><h2 class="fn-section text-title">{title}</h2>'
                          r"(.*?)</section>", html, re.DOTALL)
        return found.group(1) if found else ""

    def lines(self, html: str, title: str = "Work") -> list[str]:
        """The fact lines of a section as the page words them, years included."""
        found = re.findall(r'<span class="fn-claim__what text-body">(.*?)</span> <details', self.section(html, title))
        return [re.sub(r"<[^>]+>", "", x) for x in found]

    def summary(self, html: str) -> dict[str, str]:
        rows = re.findall(r'<dt class="text-label">([^<]+)</dt><dd class="[^"]*">(.*?)</dd>',
                          re.search(r'<dl class="fn-summary-list">.*?</dl>', html, re.DOTALL).group(0))
        return {key: re.sub(r"<[^>]+>", "", value) for key, value in rows}

    def role_line(self, html: str) -> str | None:
        found = re.search(r'<p class="fn-profile__role text-body">(.*?)</p>', html)
        return found.group(1) if found else None

    def search_with(self, cards: list[list[str]], fits: list[CardFit | None] | None = None, search_id: str = "s1") -> None:
        self.store.create_search(Search(id=search_id, question="Example question", status="done", created_at=now(),
                                        code_sha=None, dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        self.store.save_candidates(search_id, [
            Candidate(search_id=search_id, person_id=ids[0], person_ids=ids, hit_person_ids=ids[:1], card_person_ids=ids,
                      section="new", rank=n, score=1.0, lane_ranks={"seeds": n}, fit=(fits or [None] * len(cards))[n - 1])
            for n, ids in enumerate(cards, 1)], [])


    def elke(self, others: int = 30) -> str:
        """A professor at Chalmers since 2009 with a joined role, Ghent and MIT years, and one-year affiliations."""
        elke = self.person("Elke Voorbeeld", "elke", "openalex")
        text = "Elke Voorbeeld is professor of wireless communication at Chalmers University of Technology."
        here = self.source(text, title="Staff, Chalmers", url="https://www.chalmers.example/staff")
        self.claim(elke, "role", "professor", src=here)
        self.claim(elke, "affiliation", CHALMERS.name, src=here, relation="affiliated_with", org_id=CHALMERS.id,
                   years=list(range(2009, YEAR + 1)))
        record = self.source("OpenAlex record", kind="record", url="https://openalex.org/A1", title="Elke Voorbeeld")
        self.claim(elke, "affiliation", GHENT.name, src=record, relation="affiliated_with", org_id=GHENT.id,
                   years=list(range(2003, 2009)))
        self.claim(elke, "affiliation", MIT.name, src=record, relation="affiliated_with", org_id=MIT.id,
                   years=list(range(2006, 2013)))
        for n in range(others):
            other = org(f"openalex:I{100 + n}", f"Institute {n:02d}", "FR")
            self.store.upsert_org(other, replace=True)
            self.claim(elke, "affiliation", other.name, src=self.source(f"Record {n}", kind="record",
                       url=f"https://openalex.org/W{n}", title=f"OpenAlex work W{n}"), relation="affiliated_with",
                       org_id=other.id, years=[2010 + n % 14])
        return elke

    def twin_card(self, sources: int = 3) -> tuple[str, str]:
        """Two OpenAlex records of one name at different employers, the second with several sources."""
        first, second = self.person("Elke Voorbeeld", "oa-1", "openalex"), self.person("Elke Voorbeeld", "oa-2", "openalex")
        record = self.source("OpenAlex record", kind="record", url="https://openalex.org/A1", title="Elke Voorbeeld")
        self.claim(first, "affiliation", CHALMERS.name, src=record, relation="affiliated_with", org_id=CHALMERS.id, years=[2020])
        for n in range(sources):
            work = self.source(f"Work {n}", kind="record", url=f"https://openalex.org/W{n}", title=f"OpenAlex author Elke {n}")
            self.claim(second, "affiliation", MIT.name, src=work, relation="affiliated_with", org_id=MIT.id, years=[2010 + n])
        self.search_with([[first, second]])
        return first, second


class WorkOrderTest(PersonContentCase):
    def test_work_opens_with_the_current_job_then_ghent_and_mit_and_the_one_year_affiliations_fold(self):
        """The long current affiliation with its role heads Work; one-year affiliations fold into the last line."""
        elke = self.elke()
        html = self.page(elke, all="work")
        self.assertEqual(self.role_line(html), "Professor, Chalmers University of Technology")
        self.assertEqual(self.lines(html), [
            f"Professor, Chalmers University of Technology, 2009–{YEAR}", "Named at Ghent University, 2003–2008",
            "Named at Massachusetts Institute of Technology, 2006–2012", "Also named at 30 other organizations"])
        self.assertIn('id="work-fold"', html)
        self.assertEqual(len(self.lines(self.page(elke), "Work")), 3)
        self.assertIn(">Show 1 more</a>", self.page(elke))

    def test_of_two_equal_spans_the_joined_role_comes_first(self):
        """Two works_at lines of 2015–2020, one with a joined role: the joined line heads Work and the page."""
        ada = self.person("Ada Voorbeeld", "ada")
        plain = self.source("Ada Voorbeeld works at Alpha Labs.")
        self.claim(ada, "affiliation", "Alpha Labs", src=plain, relation="works_at", valid_from="2015", valid_to="2020")
        text = "Ada Voorbeeld, engineer at Beta Works."
        both = self.source(text)
        self.claim(ada, "role", "engineer", src=both)
        self.claim(ada, "affiliation", "Beta Works", src=both, relation="works_at", valid_from="2015", valid_to="2020")
        html = self.page(ada)
        self.assertEqual(self.lines(html)[:2], ["Engineer, Beta Works, 2015–2020", "Works at Alpha Labs, 2015–2020"])
        self.assertEqual(self.role_line(html), "Engineer, Beta Works")

    def test_a_works_at_job_is_current_at_any_year_and_an_old_affiliation_is_not(self):
        """works_at heads Work whatever its years; an affiliation needs years that reach the last two."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.claim(ada, "affiliation", "Old Affiliation", relation="affiliated_with", years=list(range(1990, 2010)))
        self.claim(ada, "affiliation", "Stated Job", relation="works_at", claim_date="2012")
        html = self.page(ada)
        self.assertEqual(self.lines(html)[0], "Works at Stated Job, 2012")
        self.assertEqual(self.role_line(html), "Stated Job")
        bo = self.person("Bo Voorbeeld", "bo")
        self.claim(bo, "affiliation", "Old Affiliation", relation="affiliated_with", years=list(range(1990, 2010)))
        self.assertIsNone(self.role_line(self.page(bo)))

    def test_a_topic_a_past_job_and_a_list_entry_never_name_the_head(self):
        """Only the current job or a stated role is the head line."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.claim(ada, "topic", "Wind energy")
        self.claim(ada, "affiliation", "Past Firm", relation="worked_at", claim_date="2015")
        self.claim(ada, "affiliation", "Old University", relation="affiliated_with", years=[1990, 1991, 1992])
        self.claim(ada, "affiliation", "Example Society", relation="member_of", claim_date="2020")
        view = present.person_views(self.store, [[ada]], now().date())[0]
        self.assertIsNone(self.role_line(self.page(ada)))
        self.assertEqual((view.role, view.employer), (None, None))

    def test_one_year_affiliations_at_a_belgian_organization_never_fold(self):
        """A one-year Belgian affiliation stands as a line while the others fold."""
        elke = self.elke(others=3)
        record = self.source("OpenAlex record", kind="record", url="https://openalex.org/A9", title="Elke Voorbeeld")
        self.claim(elke, "affiliation", LEUVEN.name, src=record, relation="affiliated_with", org_id=LEUVEN.id, years=[2014])
        found = self.lines(self.page(elke, all="work"))
        self.assertEqual(found[-1], "Also named at 3 other organizations")
        self.assertIn("Named at KU Leuven, 2014", found)

    def test_no_dated_fact_orders_work_by_words_and_76_affiliations_fold_to_one_line(self):
        """Undated lines go A to Z; 76 one-year affiliations make one folded line and a short first screen."""
        ada = self.person("Ada Voorbeeld", "ada")
        for name in ("Gamma Firm", "Alpha Firm", "Beta Firm"):
            self.claim(ada, "affiliation", name, relation="worked_at")
        self.assertEqual(self.lines(self.page(ada)), ["Worked at Alpha Firm", "Worked at Beta Firm", "Worked at Gamma Firm"])
        html = self.page(self.elke(others=76), all="work")
        self.assertEqual(self.lines(html)[-1], "Also named at 76 other organizations")
        self.assertEqual(len(self.lines(html)), 4)

    def test_the_head_place_and_the_organization_in_its_city_break_a_tie_between_equal_jobs(self):
        """Two works_at lines of equal span: the one whose organization is in the person's city heads Work."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.claim(ada, "location", "Gothenburg", relation="lives_in", lat=57.7, lon=11.97)
        self.claim(ada, "affiliation", "Zeta Firm", relation="works_at", claim_date="2015")
        self.claim(ada, "affiliation", CHALMERS.name, relation="works_at", org_id=CHALMERS.id, claim_date="2015")
        self.assertEqual(self.lines(self.page(ada))[0], "Works at Chalmers University of Technology, 2015")


class YearsAndWordsTest(PersonContentCase):
    def test_the_day_a_record_was_read_is_not_a_year_on_the_line(self):
        """A Wikidata row without a year of its own reads 'Works at Example Health' with no year."""
        ada = self.person("Ada Voorbeeld", "ada")
        row = self.source("Example Health employs Ada Voorbeeld", kind="seed_page", title="Wikidata", url="https://www.wikidata.org/Q1",
                          source_date="2026-11-04", date_method="record_field")
        self.claim(ada, "affiliation", "Example Health", src=row, relation="works_at", org_id=HEALTH.id,
                   claim_date="2026-11-04", date_method="record_field")
        html = self.page(ada)
        self.assertEqual(self.lines(html), ["Works at Example Health"])
        self.assertNotIn("text-year", self.section(html, "Work"))

    def test_years_with_gaps_show_one_span_and_the_full_list_in_the_proof(self):
        """[2009, 2011, 2012, 2019] reads 2009–2019 on the line and 'Years: 2009, 2011–2012, 2019' in the proof."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.claim(ada, "affiliation", "Example Health", relation="works_at", years=[2009, 2011, 2012, 2019])
        html = self.page(ada)
        self.assertEqual(self.lines(html), ["Works at Example Health, 2009–2019"])
        self.assertIn('<p class="fn-cite text-small">Years: 2009, 2011–2012, 2019</p>', html)
        self.claim(ada, "affiliation", "Other Health", relation="worked_at", years=[2005, 2006])
        self.assertEqual(self.page(ada).count("Years:"), 1)

    def test_a_page_title_is_not_a_job(self):
        """A role equal to the page title is no line, no head, no Work section; Sources names the page with no facts."""
        jonas = self.person("Jonas Testman", "jonas")
        board = self.source("Jonas Testman, board secretary of the society", title="Board page",
                            url="https://www.example-society.example/board")
        fact = self.claim(jonas, "role", "Board page", src=board)
        html = self.page(jonas)
        self.assertEqual(self.section(html, "Work"), "")
        self.assertIsNone(self.role_line(html))
        self.assertIsNone(present.person_views(self.store, [[jonas]], now().date())[0].role)
        self.assertRegex(self.section(html, "Sources"), r"example-society\.example</a> <span[^>]*>· no facts</span>")
        source = unescape(self.raw(f"/sources/{board.id}", claim=fact))
        self.assertIn('<p class="fn-source__lead text-body">The page names Jonas Testman.</p>'
                      '<p class="fn-source__cite text-small">example-society.example</p>', source)

    def test_a_list_entry_reads_as_its_relation_and_the_organization_not_the_list(self):
        """A BAEF row reads 'Fellow of Belgian American Educational Foundation, 2015' under Ties, and cites the list."""
        mira = self.person("Mira Proef", "mira")
        row = self.source("BAEF fellows 2015: Mira Proef", kind="seed_page", title="BAEF Belgian Fellows",
                          url="https://www.baef.example/fellows")
        fact = self.claim(mira, "role", "BAEF Belgian Fellows", src=row, relation="fellow_of", org_id=BAEF.id, claim_date="2015")
        self.claim(mira, "location", "Belgian", relation="origin")
        self.search_with([[mira]], [CardFit(tie_grade="strong", tie_claim_ids=[fact])])
        html = self.page(mira, search="s1", card=mira)
        self.assertIn("Fellow of Belgian American Educational Foundation, 2015", self.lines(html, TIES))
        source = unescape(self.raw(f"/sources/{row.id}", claim=fact))
        self.assertIn('<p class="fn-source__cite text-small">BAEF Belgian Fellows, 2015</p>', source)
        self.assertRegex(source, r'The (record|page) (lists|says): Fellow of Belgian American Educational Foundation, 2015\.')

    def test_a_role_whose_organization_comes_from_another_source_stands_alone(self):
        """'Chief scientist' on one page and 'Works at Example Health' on another are two lines."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.claim(ada, "role", "Chief scientist", quote=HEALTH_TEXT, claim_date="2024")
        self.claim(ada, "affiliation", "Example Health", relation="works_at", org_id=HEALTH.id, claim_date="2024")
        self.assertCountEqual(self.lines(self.page(ada)), ["Chief scientist, 2024", "Works at Example Health, 2024"])
        self.assertEqual(self.role_line(self.page(ada)), "Example Health")

    def test_a_role_joins_the_employer_of_its_source_when_the_quotes_overlap_or_it_is_the_only_pair(self):
        """Overlapping quotes join; two roles and a works_at and a worked_at join by overlap, and a worked_at never joins."""
        ada = self.person("Ada Voorbeeld", "ada")
        text = "Engineer at Alpha Labs. Earlier, director at Beta Works."
        src = self.source(text)
        self.claim(ada, "role", "director", quote="director at Beta Works", src=src)
        self.claim(ada, "role", "engineer", quote="Engineer at Alpha Labs", src=src)
        self.claim(ada, "affiliation", "Alpha Labs", quote="Alpha Labs", src=src, relation="works_at")
        self.claim(ada, "affiliation", "Beta Works", quote="Beta Works", src=src, relation="worked_at")
        self.assertCountEqual(self.lines(self.page(ada)), ["Engineer, Alpha Labs", "Director", "Worked at Beta Works"])

    def test_a_role_never_joins_a_past_job_of_its_source(self):
        """'Partner' and a worked_at on one page are two lines, and the head names no employer."""
        pia = self.person("Pia Voorbeeld", "pia")
        src = self.source("Pia Voorbeeld, partner. Earlier, at Beta Works.")
        self.claim(pia, "role", "Partner", quote="Pia Voorbeeld, partner", src=src, claim_date="2024")
        self.claim(pia, "affiliation", "Beta Works", quote="Beta Works", src=src, relation="worked_at", valid_from="2006",
                   valid_to="2009", claim_date="2009")
        html = self.page(pia)
        self.assertCountEqual(self.lines(html), ["Partner, 2024", "Worked at Beta Works, 2006–2009"])
        self.assertEqual(self.role_line(html), "Partner")

    def test_a_role_that_names_its_organization_is_not_followed_by_it(self):
        """'Managing Director at BGR Group' joined to BGR Group reads as the role alone, on the line and the head."""
        bo = self.person("Bo Voorbeeld", "bo")
        src = self.source("Bo Voorbeeld, Managing Director at BGR Group.")
        self.claim(bo, "role", "Managing Director at BGR Group", quote="Managing Director at BGR Group", src=src,
                   claim_date="2024")
        self.claim(bo, "affiliation", "BGR Group", quote="BGR Group", src=src, relation="works_at", claim_date="2024")
        html = self.page(bo)
        self.assertEqual(self.lines(html), ["Managing Director at BGR Group, 2024"])
        self.assertEqual(self.role_line(html), "Managing Director at BGR Group")

    def test_a_consul_post_reads_consul_for_the_country(self):
        """A consul_for claim reads 'Consul for Belgium', never 'Honorary consul for'."""
        cy = self.person("Cy Voorbeeld", "cy")
        src = self.source("Cy Voorbeeld, consul", kind="seed_page", title="Consuls")
        fact = self.claim(cy, "role", "Consul", relation="consul_for", org_id=BAEF.id, claim_date="2020", src=src)
        self.assertRegex(unescape(self.raw(f"/sources/{src.id}", claim=fact)),
                         rf"The (record|page) (lists|says): Consul for {BAEF.name}, 2020\.")

    def test_a_card_with_two_ways_to_say_one_job_reads_the_role_with_a_capital(self):
        """A lower-case stated role reads with a capital letter on the line."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.claim(ada, "role", "head of gynecology", claim_date="2021")
        self.assertEqual(self.lines(self.page(ada)), ["Head of gynecology, 2021"])
        self.assertEqual(self.role_line(self.page(ada)), "Head of gynecology")


class PlacesAndTieRowTest(PersonContentCase):
    def test_a_place_a_record_gives_for_an_institution_is_no_fact_but_the_head_still_uses_it(self):
        """A location without a relation from a record is no line; a stated place from a page is 'Lives in'."""
        ada = self.person("Ada Voorbeeld", "ada")
        record = self.source("OpenAlex record", kind="record", url="https://openalex.org/A3", title="Ada Voorbeeld")
        self.claim(ada, "location", "Gothenburg", src=record, lat=57.7, lon=11.97)
        html = self.page(ada)
        self.assertEqual(self.section(html, "Places"), "")
        self.assertIn("Gothenburg", html)
        self.claim(ada, "location", "Boston, MA", claim_date="2024")
        self.assertEqual(self.lines(self.page(ada), "Places"), ["Lives in Boston, MA, 2024"])

    def test_the_tie_row_follows_the_ranker_fit_and_reads_belgium_for_a_brussels_foundation(self):
        """With a strong fit whose first claim is the fellowship the row is 'Tie to Belgium: Fellow of …'."""
        mira = self.person("Mira Proef", "mira")
        row = self.source("BAEF fellows 2015: Mira Proef", kind="seed_page", title="BAEF Belgian Fellows")
        fellow = self.claim(mira, "role", "BAEF Belgian Fellows", src=row, relation="fellow_of", org_id=BAEF.id, claim_date="2015")
        degree = self.claim(mira, "affiliation", "UCLouvain", relation="studied_at", org_id=UCLOUVAIN.id, claim_date="2012")
        self.search_with([[mira]], [CardFit(tie_grade="strong", tie_claim_ids=[fellow, degree])])
        html = self.page(mira, search="s1", card=mira)
        self.assertEqual(self.summary(html)["Tie to Belgium"], "Fellow of Belgian American Educational Foundation, 2015")
        self.assertIn("Studied", self.summary(html))
        weak = self.person("Wim Proef", "wim")
        self.search_with([[weak]], [CardFit(tie_grade="weak", tie_claim_ids=[degree])], "s2")
        self.assertFalse({"Tie to Belgium", "Tie to Flanders"} & set(self.summary(self.page(weak, search="s2", card=weak))))

    def test_without_a_search_the_degree_is_the_tie_and_the_studied_row_goes(self):
        """A degree at UCLouvain (Wallonia) reads 'Tie to Belgium' and leaves out Studied and the Education section."""
        luc = self.person("Luc Exemple", "luc")
        self.claim(luc, "affiliation", "UCLouvain", relation="studied_at", org_id=UCLOUVAIN.id, claim_date="2012")
        html = self.page(luc)
        self.assertEqual(self.summary(html)["Tie to Belgium"], "Studied at UCLouvain, 2012")
        self.assertNotIn("Studied", self.summary(html))
        self.assertEqual(self.section(html, "Education"), "")

    def test_a_birthplace_in_brussels_is_belgium_and_one_in_antwerp_is_flanders(self):
        """The row key follows the place: Brussels is not in the Flemish Region."""
        for place, key in (("Brussels, Belgium", "Tie to Belgium"), ("Antwerp, Belgium", "Tie to Flanders")):
            with self.subTest(place=place):
                person = self.person(f"Pia {key[-3:]}", f"pia-{key}")
                self.claim(person, "location", place, relation="born_in")
                self.claim(person, "location", "Belgian", relation="origin")
                html = self.page(person)
                self.assertEqual(list(self.summary(html))[:1], [key])
                self.assertIn(f"Born in {place}", self.lines(html, TIES))

    def test_the_flemish_region_check_reads_the_region_first_then_words_in_city_and_name(self):
        """A region decides; without one Flemish words in the city or name do; without an organization the value does."""
        def claim(value: str) -> Claim:
            return Claim(id="c", person_id="p", kind="affiliation", value=value, quote="q", quote_start=0, quote_end=1,
                         source_id="s")

        self.assertFalse(evidence.in_flanders(claim("x"), BAEF))
        self.assertFalse(evidence.in_flanders(claim("x"), UCLOUVAIN))
        self.assertTrue(evidence.in_flanders(claim("x"), org("ror:0aaaaaa01", "KU Leuven", "BE")))
        self.assertTrue(evidence.in_flanders(claim("x"), org("ror:0aaaaaa02", "Imec", "BE", city="Leuven")))
        self.assertTrue(evidence.in_flanders(claim("x"), org("ror:0aaaaaa03", "Imec", "BE", region="VLG")))
        self.assertFalse(evidence.in_flanders(claim("x"), org("ror:0aaaaaa04", "Leuven Instruments", "BE", region="BRU")))
        self.assertTrue(evidence.in_flanders(claim("Antwerp, Belgium"), None))
        self.assertFalse(evidence.in_flanders(claim("Brussels, Belgium"), None))

    def test_a_bare_role_and_a_topic_show_no_tie(self):
        """Only a Belgian organization or a tie relation with Belgian words shows a tie."""
        def claim(kind: str, relation: str | None, value: str, org_id: str | None = None) -> Claim:
            return Claim(id="c", person_id="p", kind=kind, relation=relation, value=value, quote="q", quote_start=0,
                         quote_end=1, source_id="s", org_id=org_id)

        facts = {GHENT.id: GHENT, HEALTH.id: HEALTH}
        self.assertTrue(evidence.shows_tie(claim("affiliation", "works_at", "x", GHENT.id), facts))
        self.assertFalse(evidence.shows_tie(claim("affiliation", "works_at", "x", HEALTH.id), facts))
        self.assertTrue(evidence.shows_tie(claim("location", "origin", "Belgian"), facts))
        self.assertFalse(evidence.shows_tie(claim("topic", None, "Belgian chocolate"), facts))
        self.assertFalse(evidence.shows_tie(claim("role", None, "Belgian consul", GHENT.id), facts))
        self.assertFalse(evidence.shows_tie(claim("affiliation", "works_at", "Belgian Firm"), facts))


class QuotesAndSourcesTest(PersonContentCase):
    def test_debris_is_a_label_after_a_list_mark_tokens_an_entity_or_under_four_words(self):
        """Four words stay; a list-mark label, a one-word quote and an entity go."""
        self.assertFalse(present.debris("She leads the lab."))
        self.assertTrue(present.debris("* Name: Mira Proef"))
        self.assertTrue(present.debris("Ann"))
        self.assertTrue(present.debris("Mira Proef&amp;nbsp;leads the lab at the harbour"))
        self.assertFalse(present.debris("Name: she leads the lab at the harbour"))

    def test_a_quote_of_three_words_and_one_that_says_she_on_a_page(self):
        """The four-word sentence shows in the proof; the three-word one leaves the title and links."""
        ada = self.person("Ada Voorbeeld", "ada")
        self.claim(ada, "topic", "Wind energy", quote="She leads the lab.")
        self.claim(ada, "topic", "Solar energy", quote="Leads the lab.")
        html = self.page(ada)
        self.assertEqual(re.findall(r"<blockquote[^>]*>(.*?)</blockquote>", html), ["“She leads the lab.”"])
        self.assertEqual(html.count("Original page"), 2)

    def test_a_linkedin_profile_is_a_record_with_no_quote(self):
        """A vendor_page on linkedin.com shows 'LinkedIn record' as source name and cite, and 'The record lists'."""
        ada = self.person("Ada Voorbeeld", "ada")
        fact = self.claim(ada, "affiliation", "Example Health", relation="works_at", org_id=HEALTH.id, claim_date="2025",
                          quote="Ada Voorbeeld has worked at Example Health since 2019 and leads the lab",
                          src=self.source("Ada Voorbeeld has worked at Example Health since 2019 and leads the lab",
                                          kind="vendor_page", url="https://www.linkedin.com/in/ada-voorbeeld", title="Ada Voorbeeld"))
        html = self.page(ada)
        self.assertNotIn("<blockquote", html)
        self.assertIn(">LinkedIn record</summary>", html)
        self.assertIn(">LinkedIn record</a>, 2025", html)
        source = unescape(self.raw(f"/sources/src-{self.n}", claim=fact))
        self.assertIn("The record lists: Works at Example Health", source)
        self.assertNotIn("fn-source__passage", source)
        self.assertIn('<p class="fn-source__cite text-small">LinkedIn record, 2025</p>', source)


class RecordsAndUndoTest(PersonContentCase):
    def test_a_card_of_two_records_has_two_rows_named_by_their_first_employer(self):
        """A record with three sources is one row; both rows read 'OpenAlex record, {organization}'."""
        first, _ = self.twin_card()
        html = self.page(first, search="s1", card=first)
        self.assertIn('<a href="#sources">Combined from 2 records</a>', html)
        rows = re.findall(r'<div class="fn-line__main"><p class="text-body"><a href="[^"]*">([^<]+)</a> <span[^>]*>([^<]+)</span>',
                          self.section(html, "Sources"))
        self.assertEqual(rows, [("OpenAlex record, Chalmers University of Technology", "· 1 fact"),
                                ("OpenAlex record, Massachusetts Institute of Technology", "· 3 facts")])
        self.assertEqual(self.section(html, "Sources").count("Not this person</button>"), 1)

    def test_a_record_with_five_sources_is_one_row_with_its_facts_counted_once(self):
        """Five sources of one record make one row; its fact count is the five claims."""
        first, _ = self.twin_card(sources=5)
        html = self.page(first, search="s1", card=first)
        self.assertEqual(len(re.findall(r'class="fn-line"', self.section(html, "Sources"))), 2)
        self.assertIn("· 5 facts", self.section(html, "Sources"))
        self.assertIn("Combined from 2 records", html)

    def test_same_person_different_person_and_their_undo_return_to_the_matches_section(self):
        """The forms of a possible match post next with #matches; Not this person posts #sources."""
        ada, twin = self.person("Ada Voorbeeld", "ada", member=True), self.person("Ada Voorbeeld", "ada-2")
        self.claim(ada, "topic", "Wind energy")
        self.claim(twin, "topic", "Solar energy")
        html = self.page(ada)
        nexts = re.findall(r'name="next" value="([^"]+)"', self.section(html, "Possible matches"))
        self.assertEqual(nexts, [f"/people/{ada}#matches"] * 2)
        response = self.client.post(f"/people/{ada}/not-same", data={"other": twin, "next": nexts[0]})
        self.assertTrue(response.headers["location"].endswith("#matches"))
        done = self.section(self.page(ada), "Possible matches")
        self.assertIn(f'name="next" value="/people/{ada}#matches"', done)

    def test_not_correct_on_a_joined_line_hides_the_role_and_the_employer_and_undo_restores_both(self):
        """One post removes both claims; the page shows one removed line; Undo brings the joined line back."""
        ada = self.person("Ada Voorbeeld", "ada", member=True)
        text = "Ada Voorbeeld, engineer at Alpha Labs."
        src = self.source(text)
        role = self.claim(ada, "role", "engineer", src=src, quote="Ada Voorbeeld, engineer")
        job = self.claim(ada, "affiliation", "Alpha Labs", src=src, quote="engineer at Alpha Labs", relation="works_at")
        html = self.page(ada)
        self.assertEqual(self.lines(html), ["Engineer, Alpha Labs"])
        form = re.search(rf'action="/claims/{job}/reject">(.*?)</form>', html).group(1)
        self.assertIn(f'name="also" value="{role}"', form)
        self.client.post(f"/claims/{job}/reject", data={"also": role, "next": f"/people/{ada}"})
        after = self.page(ada)
        self.assertEqual(re.findall(r"<span>([^<]+)</span><span>· Removed</span>", after), ["Engineer, Alpha Labs"])
        self.assertIsNone(self.role_line(after))
        self.assertEqual({c.id for c in self.store.claims_of([ada])}, set())
        undo = re.search(r'action="/events/([^"]+)/undo"', after).group(1)
        self.client.post(f"/events/{undo}/undo", data={"next": f"/people/{ada}"})
        self.assertEqual({c.id for c in self.store.claims_of([ada])}, {role, job})
        self.assertEqual(self.lines(self.page(ada)), ["Engineer, Alpha Labs"])

    def test_a_reject_leaves_alone_an_also_claim_of_another_person(self):
        """The also field names only claims of the same person."""
        ada, bo = self.person("Ada Voorbeeld", "ada"), self.person("Bo Voorbeeld", "bo")
        mine = self.claim(ada, "topic", "Wind energy")
        theirs = self.claim(bo, "topic", "Solar energy")
        self.client.post(f"/claims/{mine}/reject", data={"also": theirs, "next": f"/people/{ada}"})
        self.assertEqual([c.value for c in self.store.claims_of([bo])], ["Solar energy"])
        self.assertEqual(self.store.claims_of([ada]), [])


class FirstScreenBudgetTest(PersonContentCase):
    def test_head_why_and_summary_stay_within_90_words_on_six_pages(self):
        """Seed, OpenAlex, web, member, combined and a 76-affiliation page: head, why and summary at most 90 words."""
        seed = self.person("Sofie Seed", "seed")
        self.claim(seed, "role", "Fellow of Example Society", src=self.source("Fellow", kind="seed_page", title="Example list"),
                   relation="fellow_of")
        web = self.person("Wim Web", "web")
        self.claim(web, "topic", "Wind energy", quote="Wim Web 1, 2 Author Orcid Image")
        member = self.person("Mia Member", "mia", member=True)
        for n in range(5):
            self.claim(member, "affiliation", f"Firm {n}", relation="worked_at", claim_date=f"20{10 + n}")
        self.claim(member, "affiliation", "UCLouvain", relation="studied_at", org_id=UCLOUVAIN.id, claim_date="2012")
        self.claim(member, "email", "mia@example.org")
        first, _ = self.twin_card()
        elke = self.elke(others=76)
        pages = {"seed": self.page(seed), "web": self.page(web), "member": self.page(member),
                 "combined": self.page(first, search="s1", card=first), "elke": self.page(elke)}
        for name, html in pages.items():
            with self.subTest(page=name):
                main = re.search(r"<main.*?</main>", html, re.DOTALL).group(0)
                main = re.sub(r"<form.*?</form>", "", main, flags=re.DOTALL)
                parts = re.findall(r'<div class="fn-profile__head">.*?</div>|<section class="fn-why">.*?</section>|'
                                   r'<dl class="fn-summary-list">.*?</dl>', main, re.DOTALL)
                words = len(re.sub(r"<[^>]+>", " ", " ".join(parts)).split())
                self.assertLessEqual(words, 90, words)


if __name__ == "__main__":
    unittest.main()
