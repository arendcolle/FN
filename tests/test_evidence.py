import unittest
from datetime import UTC, datetime

from fn import evidence, geo
from fn.contracts import Chip, Chips, Claim, GeoArea, Identifier, Org, Place, Question
from tests.helpers import cities_zip

TODAY = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
FETCHED = datetime(2026, 11, 3, tzinfo=UTC)
BOSTON = GeoArea(place="Boston", city="Boston, US", lat=42.35843, lon=-71.05977, radius_km=geo.METRO_RADIUS_KM)
MIT = Org(id="ror:042nb2s44", name="MIT", country_code="US", city="Cambridge", lat=42.3751, lon=-71.10561,
          source_id="s", fetched_at=FETCHED)
LEUVEN = Org(id="ror:05f950310", name="KU Leuven", country_code="BE", city="Leuven", lat=50.87959, lon=4.70093,
             source_id="s", fetched_at=FETCHED)
NO_CITY = Org(id="ror:0abc12399", name="Other Lab", country_code="US", source_id="s", fetched_at=FETCHED)
FACTS = {o.id: o for o in (MIT, LEUVEN, NO_CITY)}
NAMES = geo.from_zip(cities_zip())


def claim(claim_id: str, person_id: str = "p1", kind: str = "affiliation", relation: str | None = None,
          value: str = "x", quote: str = "q", **fields) -> Claim:
    return Claim(id=claim_id, person_id=person_id, kind=kind, relation=relation, value=value, quote=quote,
                 quote_start=0, quote_end=1, source_id=f"src-{claim_id}", **fields)


def lives(claim_id: str, city: str, lat: float, lon: float, relation: str = "lives_in", person_id: str = "p1") -> Claim:
    return claim(claim_id, person_id, "location", relation, city, f"Based in {city}", lat=lat, lon=lon)


def job(claim_id: str, org: Org, stamp: str, person_id: str = "p1", relation: str = "works_at") -> Claim:
    return claim(claim_id, person_id, "affiliation", relation, org.name, f"Works at {org.name}", org_id=org.id,
                 claim_date=stamp)


def question(*topics: str, area: GeoArea | None = None, country: str | None = None, institutions=()) -> Question:
    chips = Chips(topics=[Chip(text=t, origin="edited") for t in topics],
                  institutions=[Chip(text=t, origin="edited") for t in institutions])
    return Question(chips=chips, area=area, country=country)


def of(claims: list[Claim], ask: Question | None = None, card: dict | None = None) -> evidence.Evidence:
    card = card or {"p1": frozenset({"openalex"})}
    return evidence.of(card, claims, FACTS, ask or question(), TODAY, NAMES)


class PlacesTest(unittest.TestCase):
    def test_a_stated_place_has_its_coordinates_text_country_basis_claim_and_year(self):
        """A located lives_in claim of any date is a stated place, with the country of its nearest city."""
        (found,) = evidence.places([lives("c1", "Leuven", 50.88, 4.7).model_copy(update={"claim_date": "1999"})],
                                   FACTS, TODAY, NAMES)
        self.assertEqual(found, evidence.Place(50.88, 4.7, "Leuven", "BE", "stated", "c1", 1999))

    def test_a_recent_employer_gives_its_city_and_a_six_year_old_one_does_not(self):
        """An employer fact of 2021 is within five years of 2026-11-12 and places the person; one of 2020 does not."""
        (found,) = evidence.places([job("c1", MIT, "2021")], FACTS, TODAY)
        self.assertEqual(found, evidence.Place(MIT.lat, MIT.lon, "Cambridge", "US", "employer", "c1", 2021))
        self.assertEqual(evidence.places([job("c1", MIT, "2020")], FACTS, TODAY), [])
        self.assertEqual(evidence.places([job("c1", MIT, "2021-11-11")], FACTS, TODAY), [])

    def test_valid_to_wins_over_the_claim_date_and_an_organization_without_a_city_gives_nothing(self):
        """A fact stated in 2025 that ended in 2019 is old; an employer without a city places no one."""
        old = job("c1", MIT, "2025").model_copy(update={"valid_to": "2019"})
        self.assertEqual(evidence.places([old, job("c2", NO_CITY, "2025")], FACTS, TODAY), [])

    def test_a_birthplace_is_never_a_place(self):
        """A born_in claim with coordinates is left out."""
        self.assertEqual(evidence.places([lives("c1", "Boston", 42.36, -71.06, "born_in")], FACTS, TODAY), [])

    def test_an_origin_is_never_a_place(self):
        """An origin claim with coordinates is left out, as a birthplace is."""
        self.assertEqual(evidence.places([lives("c1", "Belgian", 50.5, 4.4, "origin")], FACTS, TODAY), [])


class TopicTest(unittest.TestCase):
    def test_every_word_of_a_chip_in_one_claim_is_a_match(self):
        """'health care' matches a claim holding both words, with the final s of 'designers' dropped too."""
        found = of([claim("c1", value="Health and care designer"), claim("c2", value="Dentist")],
                   question("health care", "designers"))
        self.assertEqual((found.topic.match, found.topic.words, found.topic.claim_ids),
                         (True, ("health", "care", "designer"), ("c1",)))

    def test_the_words_spread_over_two_claims_are_no_match(self):
        """Health in one claim and care in another are both found words, but no chip is whole in one claim."""
        found = of([claim("c1", value="Health"), claim("c2", value="Care and care home")], question("health care"))
        self.assertEqual((found.topic.match, set(found.topic.words)), (False, {"health", "care"}))

    def test_a_word_must_stand_at_a_word_start(self):
        """'care' does not match 'scared'."""
        found = of([claim("c1", value="A scared cat")], question("care"))
        self.assertEqual((found.topic.match, found.topic.words), (False, ()))

    def test_a_short_word_must_be_the_whole_word(self):
        """'ai' finds the word 'AI' and not 'aircraft' or 'aid'."""
        self.assertEqual(of([claim("c1", value="Aircraft noise and aid programmes")], question("AI")).topic.words, ())
        self.assertEqual(of([claim("c1", value="AI for imaging")], question("AI")).topic.words, ("ai",))

    def test_a_chip_of_generic_words_never_matches(self):
        """'Belgian research' has no content word, so nothing can match it."""
        self.assertFalse(of([claim("c1", value="Belgian research")], question("Belgian research")).topic.match)


class BelgianTest(unittest.TestCase):
    def test_each_kind_of_tie_names_its_claims_and_the_years_count_as_the_ranker_counts_them(self):
        """Seed list, Belgian degree, Belgian organization, Belgian text and Belgian place each name their claims."""
        claims = [claim("seed", "p2", value="Fellow"), claim("org", relation="studied_at", org_id=LEUVEN.id, claim_date="2018"),
                  claim("text", value="Grew up in Ghent"), lives("place", "Home", 50.85, 4.35), job("mit", MIT, "2024")]
        card = {"p1": frozenset({"openalex"}), "p2": frozenset({"seed"})}
        found = of(claims, question(institutions=["MIT"]), card)
        self.assertEqual(found.belgian.kinds, {"seed_list": ("seed",), "belgian_degree": ("org",), "belgian_org": ("org",),
                                               "belgian_text": ("text",), "belgian_place": ("place",)})
        self.assertEqual(found.belgian.grade, "strong")
        self.assertEqual((found.belgian.years, found.belgian.last), (1, 2018))

    def test_a_card_without_any_tie_has_no_kind(self):
        """A US employer and a US place are no tie."""
        found = of([job("c1", MIT, "2024"), lives("c2", "Boston", 42.36, -71.06)])
        self.assertEqual((found.belgian.kinds, found.belgian.years), ({}, 0))

    def test_only_openalex_needs_every_record_to_hold_only_openalex_or_orcid(self):
        """An OpenAlex record with an ORCID is OpenAlex-only; a seed record or a web mention on the card is not."""
        oa = frozenset({"openalex", "orcid"})
        self.assertTrue(of([], card={"p1": oa}).only_openalex)
        self.assertFalse(of([], card={"p1": oa, "p2": frozenset({"seed"})}).only_openalex)
        self.assertFalse(of([], card={"p1": oa, "p2": frozenset({"mention"})}).only_openalex)
        self.assertFalse(of([], card={"p2": frozenset({"mention"})}).only_openalex)


class WhereTest(unittest.TestCase):
    def test_inside_outside_and_unknown(self):
        """A place within 100 km is inside; places none of which is near are outside; no place or no area is unknown."""
        cambridge, leuven = job("c1", MIT, "2024"), lives("c2", "Leuven", 50.88, 4.7)
        inside = of([cambridge], question(area=BOSTON)).place
        self.assertEqual((inside.fit, inside.nearest.claim_id, inside.nearest.basis), ("inside", "c1", "employer"))
        self.assertLess(inside.km, 10)
        self.assertEqual(of([leuven], question(area=BOSTON)).place.fit, "outside")
        self.assertEqual(of([], question(area=BOSTON)).place.fit, "unknown")
        self.assertEqual(of([leuven], question()).place.fit, "unknown")

    def test_a_stated_place_decides_and_an_employers_city_only_counts_without_one(self):
        """Stated in Leuven with a recent employer in Cambridge is outside Boston; stated in Boston is inside."""
        cambridge, leuven = job("c1", MIT, "2024"), lives("c2", "Leuven", 50.88, 4.7)
        away = of([cambridge, leuven], question(area=BOSTON)).place
        self.assertEqual((away.fit, away.nearest.claim_id, away.nearest.basis), ("outside", "c2", "stated"))
        home = of([job("c3", LEUVEN, "2024"), lives("c4", "Boston", 42.36, -71.06)], question(area=BOSTON)).place
        self.assertEqual((home.fit, home.nearest.claim_id), ("inside", "c4"))

    def test_the_countries_of_a_person_with_a_belgian_and_a_us_place(self):
        """A stated place in Leuven and a recent employer in Cambridge give BE and US."""
        found = of([lives("c1", "Leuven", 50.88, 4.7), job("c2", MIT, "2024")])
        self.assertEqual(found.place.countries, {"BE", "US"})


class CountryTest(unittest.TestCase):
    def test_the_country_of_a_point_is_that_of_the_nearest_city_within_100_km(self):
        """Near Leuven is BE, near Boston is US, 113 km from Leuven and the middle of the Atlantic are none."""
        self.assertEqual(geo.country_at(NAMES, 50.9, 4.6), "BE")
        self.assertIsNone(geo.country_at(NAMES, 51.9, 4.7))
        self.assertEqual(geo.country_at(NAMES, 42.3, -71.2), "US")
        self.assertIsNone(geo.country_at(NAMES, 40.0, -40.0))

    def test_the_country_a_question_asks_about(self):
        """The area's city for a metro, US for anywhere_us, none for abroad, no place or a city not located."""
        boston = Place(text="Boston", origin="edited", kind="metro")
        self.assertEqual(geo.question_country(NAMES, boston, BOSTON), "US")
        self.assertEqual(geo.question_country(NAMES, Place(text="the US", origin="edited", kind="anywhere_us"), None), "US")
        self.assertIsNone(geo.question_country(NAMES, Place(text="Europe", origin="edited", kind="abroad"), None))
        self.assertIsNone(geo.question_country(NAMES, None, None))
        self.assertIsNone(geo.question_country(NAMES, Place(text="Atlantis", origin="edited", kind="metro"), None))


SEED = frozenset({"seed"})
MENTION = {"p1": frozenset({"mention"})}
AI = Chip(text="AI", origin="edited", related=["machine learning"])
FOUNDERS = Chip(text="founders", origin="edited", research=False, related=["co-founder", "ceo"])


def seeded(name: str) -> dict:
    return {"p1": frozenset({"seed", f"seed:{name}"})}


def kinds_grade(claims, card=None):
    found = of(claims, card=card).belgian
    return found.kinds, found.grade


def asked(topics=(), roles=()) -> Question:
    return Question(chips=Chips(topics=list(topics), roles=list(roles), version=2))


def topic_of(claims, ask, card=None):
    return evidence.of(card or {"p1": frozenset({"openalex"})}, claims, FACTS, ask, TODAY, NAMES).topic


def role_of(claims, roles, card=None):
    return evidence.of(card or {"p1": frozenset({"openalex"})}, claims, FACTS, asked(roles=roles), TODAY, NAMES).role


def role_claim(value, quote=None, claim_id="c1"):
    return claim(claim_id, kind="role", value=value, quote=quote or value)


class TieGradeTest(unittest.TestCase):
    def test_a_seed_list_is_strong_for_a_strong_list_and_for_no_marker_else_medium(self):
        """baef and a record without a marker are strong; kvab, chambers and an unknown list are medium."""
        self.assertEqual(kinds_grade([], seeded("baef")), ({"seed_list": ()}, "strong"))
        self.assertEqual(kinds_grade([], {"p1": SEED})[1], "strong")
        for name in ("kvab", "chambers", "belcham"):
            self.assertEqual(kinds_grade([], seeded(name)), ({"seed_list": ()}, "medium"))

    def test_card_of_adds_the_list_name_of_each_seed_identifier(self):
        """A seed value kvab|ann-example adds seed:kvab; a record without identifiers has no schemes."""
        ids = {"p1": [Identifier(scheme="seed", value="kvab|ann-example"), Identifier(scheme="openalex", value="A1")]}
        self.assertEqual(evidence.card_of(ids, ["p1", "p2"]),
                         {"p1": frozenset({"seed", "seed:kvab", "openalex"}), "p2": frozenset()})

    def test_a_medium_list_with_a_one_year_job_stays_medium_and_a_degree_makes_it_strong(self):
        """A wikidata record with a Belgian job of 2020 is medium; with a Leuven degree it is strong."""
        card = seeded("wikidata")
        self.assertEqual(kinds_grade([job("c1", LEUVEN, "2020")], card)[1], "medium")
        degree = job("c1", LEUVEN, "2020", relation="studied_at")
        self.assertEqual(kinds_grade([degree], card)[1], "strong")

    def test_degree_birth_and_origin_are_strong_and_an_american_origin_is_no_kind(self):
        """studied_at Leuven, born_in Ghent, Belgium and origin Belgian are strong; origin American gives nothing."""
        degree = job("c1", LEUVEN, "1995", relation="studied_at")
        self.assertEqual(kinds_grade([degree]), ({"belgian_degree": ("c1",), "belgian_org": ("c1",), "belgian_text": ("c1",)}, "strong"))
        born = claim("c1", kind="location", relation="born_in", value="Ghent, Belgium")
        self.assertEqual(kinds_grade([born])[0]["born_in_belgium"], ("c1",))

        def origin(value):
            return claim("c1", kind="location", relation="origin", value=value)
        self.assertEqual(kinds_grade([origin("Belgian")]), ({"belgian_origin": ("c1",), "belgian_text": ("c1",)}, "strong"))
        self.assertEqual(kinds_grade([origin("American")]), ({}, "none"))

    def test_a_recent_long_belgian_job_is_strong_and_an_old_one_is_medium(self):
        """2014 to 2019 is six years ending after 2015; 2001 to 2005 ends before 2016."""
        recent = job("c1", LEUVEN, "2019").model_copy(update={"valid_from": "2014", "valid_to": "2019"})
        old = job("c1", LEUVEN, "2005").model_copy(update={"valid_from": "2001", "valid_to": "2005"})
        self.assertEqual(kinds_grade([recent])[1], "strong")
        self.assertEqual(kinds_grade([old])[1], "medium")

    def test_a_belgian_place_is_medium_and_text_alone_is_weak(self):
        """A located Brussels residence is medium; 'Grew up in Ghent' is weak; nothing is none."""
        self.assertEqual(kinds_grade([lives("c1", "Brussels", 50.85, 4.35)])[1], "medium")
        self.assertEqual(kinds_grade([claim("c1", value="Grew up in Ghent")]), ({"belgian_text": ("c1",)}, "weak"))
        self.assertEqual(kinds_grade([]), ({}, "none"))

    def test_claim_ids_start_with_the_strongest_kind(self):
        """A birthplace claim c2 comes before the weak text claim c1."""
        claims = [claim("c1", value="Grew up in Ghent"), claim("c2", kind="location", relation="born_in", value="Ghent, Belgium")]
        self.assertEqual(of(claims).belgian.claim_ids, ("c2", "c1"))


class TopicRulesTest(unittest.TestCase):
    def test_an_organization_name_gives_words_and_no_match(self):
        """'health' in the name of an institute is a found word but no match; a topic claim matches."""
        org = claim("c1", relation="works_at", value="Institute for Health Policy", quote="Works at the Institute for Health Policy")
        health = Chip(text="health", origin="edited")
        found = topic_of([org], asked([health]))
        self.assertEqual((found.match, found.words), (False, ("health",)))
        found = topic_of([claim("c2", kind="topic", value="health economics")], asked([health]))
        self.assertEqual((found.match, found.related), (True, False))

    def test_a_related_entry_matches_only_without_an_own_word_match(self):
        """machine learning matches AI as related with no words; an own-word claim wins; version-1 chips have none."""
        found = topic_of([claim("c1", kind="topic", value="Leads machine learning at Example Corp")], asked([AI]))
        self.assertEqual((found.match, found.related, found.words, found.claim_ids), (True, True, (), ("c1",)))
        both = [claim("c1", kind="topic", value="AI lead"), claim("c2", kind="topic", value="machine learning")]
        self.assertEqual(topic_of(both, asked([AI])).related, False)
        self.assertFalse(topic_of(both[1:], asked([Chip(text="AI", origin="edited")])).match)

    def test_a_related_entry_inside_an_organization_name_is_no_match(self):
        """The org name is left out for related words as for own words."""
        org = claim("c1", relation="works_at", value="Machine Learning Labs", quote="Works at Machine Learning Labs")
        self.assertFalse(topic_of([org], asked([AI])).match)

    def test_a_page_title_in_place_of_a_role_adds_words_and_no_match(self):
        """A web person's role that is not in its quote is a page title; one inside its quote matches."""
        title = claim("c1", kind="role", value="AI Summit speakers", quote="Ann Example, CEO of Acme")
        found = topic_of([title], asked([Chip(text="AI", origin="edited")]), MENTION)
        self.assertEqual((found.match, found.words), (False, ("ai",)))
        said = claim("c1", kind="role", value="professor of wireless networks", quote="Ann is a professor of wireless networks")
        self.assertTrue(topic_of([said], asked([Chip(text="wireless networks", origin="edited")]), MENTION).match)

    def test_a_mention_affiliation_adds_words_and_no_match(self):
        """A web person's affiliation claim holding the chip words in its quote gives the words and no match."""
        aff = claim("c1", kind="affiliation", relation="works_at", value="Acme", quote="Ann Example leads machine learning research at Acme")
        found = topic_of([aff], asked([Chip(text="machine learning", origin="edited")]), MENTION)
        self.assertEqual((found.match, found.words), (False, ("machine", "learning")))

    def test_the_mention_rule_holds_only_for_the_mention_record(self):
        """On a card with a mention and a seed record, a title-like role of the seed record still matches."""
        title = claim("c1", "p2", kind="role", value="AI Summit speakers", quote="Ann Example, CEO of Acme")
        card = {"p1": frozenset({"mention"}), "p2": SEED}
        self.assertTrue(topic_of([title], asked([Chip(text="AI", origin="edited")]), card).match)


class RoleTest(unittest.TestCase):
    def test_a_role_claim_holding_a_chip_word_or_a_related_entry_is_met(self):
        """'Co-founder and CEO' meets founders through its related entries."""
        self.assertEqual(role_of([role_claim("Co-founder and CEO")], [FOUNDERS]), evidence.Role("met", ("c1",)))

    def test_an_academic_job_fails_a_non_research_role_and_a_seed_record_without_role_is_unknown(self):
        """Professor fails; OpenAlex-only without a role fails; a seed record without a role is unknown."""
        self.assertEqual(role_of([role_claim("Associate professor of marketing")], [FOUNDERS]).fit, "fails")
        self.assertEqual(role_of([], [FOUNDERS]).fit, "fails")
        self.assertEqual(role_of([], [FOUNDERS], {"p1": SEED}).fit, "unknown")

    def test_a_researcher_fails_only_beside_a_university_word(self):
        """A research scientist at a company is unknown; at a university it fails."""
        self.assertEqual(role_of([role_claim("Research scientist at Example Corp")], [FOUNDERS]).fit, "unknown")
        self.assertEqual(role_of([role_claim("Research scientist, Ghent University")], [FOUNDERS]).fit, "fails")

    def test_a_research_chip_or_a_business_title_with_a_degree_is_never_failed(self):
        """With a faculty chip professor is unknown; 'Chief Scientific Officer, PhD' is no academic job."""
        faculty = Chip(text="faculty", origin="edited", research=True)
        self.assertEqual(role_of([role_claim("Professor of chemistry")], [FOUNDERS, faculty]).fit, "unknown")
        leaders = Chip(text="business leaders", origin="edited", research=False)
        self.assertEqual(role_of([role_claim("Chief Scientific Officer, PhD at Example Bio")], [leaders]).fit, "unknown")

    def test_a_page_title_role_of_a_mention_is_unknown(self):
        """A mention's role that is the page title does not meet founders."""
        title = role_claim("Founders summit speakers", "Ann Example, CTO")
        self.assertEqual(role_of([title], [FOUNDERS], MENTION).fit, "unknown")

    def test_no_role_chip_is_unknown(self):
        """A question without role chips reads unknown for every person."""
        self.assertEqual(role_of([role_claim("Professor")], []).fit, "unknown")


class JobTest(unittest.TestCase):
    def job_of(self, claims, card=None):
        return evidence.job(claims, card or {"p1": frozenset({"openalex"})}, TODAY.date())

    def test_a_role_and_a_works_at_is_known_and_a_role_alone_or_an_old_affiliation_is_none(self):
        """known needs a role without a relation and an employer; an affiliation older than RECENT_YEARS is no employer."""
        role = role_claim("Chief of staff")
        self.assertEqual(self.job_of([role, job("c2", MIT, "2010")]), "known")
        self.assertEqual(self.job_of([role]), "none")
        self.assertEqual(self.job_of([role, job("c2", MIT, "2010", relation="affiliated_with")]), "none")
        self.assertEqual(self.job_of([role, job("c2", MIT, "2024", relation="affiliated_with")]), "known")

    def test_the_evidence_of_a_card_carries_its_job(self):
        """of passes the job through, so the ranker reads what the card shows of the person's work."""
        claims = [role_claim("Chief of staff"), job("c2", MIT, "2010")]
        found = evidence.of({"p1": frozenset({"openalex"})}, claims, FACTS, asked(roles=[]), TODAY, NAMES)
        self.assertEqual(found.job, "known")

    def test_a_fellowship_role_or_a_page_title_role_with_an_employer_is_an_employer_alone(self):
        """A role with a relation is a list entry, and a web person's page title is no role."""
        fellow = claim("c1", kind="role", relation="fellow_of", value="Fellow", quote="Fellow")
        self.assertEqual(self.job_of([fellow, job("c2", MIT, "2024", relation="affiliated_with")]), "employer")
        title = role_claim("Founders summit speakers", "Ann Example, CTO")
        self.assertEqual(self.job_of([title, job("c2", MIT, "2024")], MENTION), "employer")


if __name__ == "__main__":
    unittest.main()
