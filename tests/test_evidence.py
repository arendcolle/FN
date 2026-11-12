import unittest
from datetime import UTC, datetime

from fn import evidence, geo
from fn.contracts import Chip, Chips, Claim, GeoArea, Org, Place, Question
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
        """Seed list, Belgian organization, Belgian text, Belgian place and institution each name their claims."""
        claims = [claim("seed", "p2", value="Fellow"), claim("org", relation="studied_at", org_id=LEUVEN.id, claim_date="2018"),
                  claim("text", value="Grew up in Ghent"), lives("place", "Home", 50.85, 4.35), job("mit", MIT, "2024")]
        card = {"p1": frozenset({"openalex"}), "p2": frozenset({"seed"})}
        found = of(claims, question(institutions=["MIT"]), card)
        self.assertEqual(found.belgian.kinds, {"seed_list": ("seed",), "belgian_org": ("org",), "belgian_text": ("text",),
                                               "belgian_place": ("place",), "institution": ("mit",)})
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


if __name__ == "__main__":
    unittest.main()
