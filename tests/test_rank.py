import logging
import unittest
from datetime import UTC, datetime
from unittest import mock

from fn import evidence, geo, rank, resolve
from fn.contracts import (
    Chip,
    Chips,
    Claim,
    ClaimDraft,
    Entry,
    GeoArea,
    Identifier,
    LaneHit,
    LaneOut,
    Org,
    Place,
    Question,
    RankIn,
    ResolveIn,
    ScorePart,
    Search,
    Source,
)
from fn.steps import StepContext
from fn.worker import new_id, now
from tests.helpers import StubHttp, make_db, make_seeded_db, make_settings

FETCHED = datetime(2026, 11, 3, tzinfo=UTC)
ULB = Org(id="ror:01r9htc13", name="ULB", country_code="BE", source_id="s", fetched_at=FETCHED)
MIT = Org(id="ror:042nb2s44", name="MIT", country_code="US", source_id="s", fetched_at=FETCHED)
FACTS = {o.id: o for o in (ULB, MIT)}


def entry(person_id: str, **lane_ranks: int) -> Entry:
    return Entry(name_key=person_id, person_ids=[person_id], lane_ranks=lane_ranks)


def hit_entry(person_id: str, **lane_ranks: int) -> Entry:
    return Entry(name_key=person_id, person_ids=[person_id], hit_person_ids=[person_id], lane_ranks=lane_ranks)


def claim(claim_id: str, person_id: str = "p1", org_id: str = ULB.id, **dates: str | list[int]) -> Claim:
    return Claim(id=claim_id, person_id=person_id, kind="affiliation", relation="worked_at", org_id=org_id,
                 value=claim_id, quote="q", quote_start=0, quote_end=1, source_id="src", **dates)


def units(*claims: Claim) -> frozenset[str]:
    return rank.counted(list(claims), FACTS)[1]


class RankTest(unittest.TestCase):
    def test_being_found_by_two_lanes_lifts_an_entry(self):
        """Reciprocal rank fusion puts an entry ranked 2 by two lanes above one ranked 1 by a single lane."""
        out = rank.fuse("s", [entry("a", seeds=1), entry("b", seeds=2, openalex=2)], {})
        self.assertEqual([(c.person_id, c.rank) for c in out], [("b", 1), ("a", 2)])
        self.assertAlmostEqual(out[0].score, 2 / 62)

    def test_equal_scores_are_ordered_by_person_id(self):
        out = rank.fuse("s", [entry("p3", seeds=1), entry("p1", openalex=1), entry("p2", seeds=1)], {})
        self.assertEqual([c.person_id for c in out], ["p1", "p2", "p3"])

    def test_sections_number_apart(self):
        """An entry with a record in the list is network; each section ranks from 1."""
        two = Entry(name_key="x", person_ids=["p2", "p4"], hit_person_ids=["p2", "p4"], lane_ranks={"seeds": 2})
        out = rank.fuse("s", [entry("p1", seeds=1), two, entry("p3", seeds=3)], {"p4": "in_list", "p1": "candidate"})
        self.assertEqual([(c.person_id, c.section, c.rank) for c in out],
                         [("p1", "new", 1), ("p2", "network", 1), ("p3", "new", 2)])

    def test_a_same_name_record_in_the_list_that_no_lane_hit_leaves_the_card_new(self):
        """Only hit persons decide the section: an in_list record joined by name alone keeps the card in new.

        The candidate keeps its hit ids, so a page shows and scores only those.
        """
        two = Entry(name_key="x", person_ids=["p2", "p4"], hit_person_ids=["p2"], lane_ranks={"seeds": 2})
        (out,) = rank.fuse("s", [two], {"p4": "in_list"})
        self.assertEqual((out.section, out.hit_person_ids), ("new", ["p2"]))

    def test_a_hit_person_in_the_list_makes_the_card_a_network_card(self):
        """A hit whose person is in_list puts its card in section network, also when another hit is a candidate."""
        two = Entry(name_key="x", person_ids=["p2", "p4"], hit_person_ids=["p2", "p4"], lane_ranks={"seeds": 2})
        (out,) = rank.fuse("s", [two], {"p2": "candidate", "p4": "in_list"})
        self.assertEqual((out.section, out.hit_person_ids), ("network", ["p2", "p4"]))

    def test_an_entry_stored_without_hit_ids_counts_its_first_person_as_the_hit(self):
        """An entry from before hit ids were stored scores and sections on its first person only."""
        old = Entry(name_key="x", person_ids=["p2", "p4"], lane_ranks={"seeds": 2})
        self.assertEqual(rank.fuse("s", [old], {"p2": "in_list"})[0].section, "network")
        (out,) = rank.fuse("s", [old], {"p4": "in_list"})
        self.assertEqual((out.section, out.hit_person_ids), ("new", ["p2"]))

    def test_two_entries_with_one_name_key_keep_their_own_belgian_part(self):
        """Entries that share a name key, split by resolve, each get the belgian_years part of their own hits."""
        entries = [Entry(name_key="ann", person_ids=[p], hit_person_ids=[p], lane_ranks={"seeds": 1})
                   for p in ("p1", "p2")]
        claims = [claim("c1", "p1", valid_from="2001", valid_to="2003"), claim("c2", "p2", claim_date="2010")]
        out = rank.fuse("s", entries, {}, rank.belgian_list(entries, claims, FACTS))
        found = {c.person_id: [p.claim_ids for p in c.score_parts if p.feature == "belgian_years"] for c in out}
        self.assertEqual(found, {"p1": [["c1"]], "p2": [["c2"]]})

    def test_each_lane_rank_is_one_score_part_and_the_parts_sum_to_the_score(self):
        """A candidate stores one part per lane that ranked it, worth 1 / (60 + rank), and its score is their sum."""
        (out,) = rank.fuse("s", [entry("a", seeds=3, openalex=40)], {})
        self.assertEqual([(p.feature, p.rank, p.detail) for p in out.score_parts],
                         [("seeds", 3, "1 / (60 + 3)"), ("openalex", 40, "1 / (60 + 40)")])
        self.assertEqual([p.points for p in out.score_parts], [1 / 63, 1 / 100])
        self.assertEqual(out.score, sum(p.points for p in out.score_parts))

    def test_the_belgian_years_part_is_one_more_part_of_the_sum(self):
        """An entry on the belgian_years list gets a part worth 1 / (60 + its list rank), and the score is still the sum."""
        entries = [hit_entry("p1", seeds=3)]
        found = rank.belgian_list(entries, [claim("c1", valid_from="1999", valid_to="2002")], FACTS)
        (out,) = rank.fuse("s", entries, {}, found)
        self.assertEqual([(p.feature, p.rank, p.claim_ids, p.detail) for p in out.score_parts],
                         [("seeds", 3, [], "1 / (60 + 3)"),
                          ("belgian_years", 1, ["c1"], "4 years at Belgian organizations; 1 / (60 + 1)")])
        self.assertEqual(out.score, sum(p.points for p in out.score_parts))
        self.assertAlmostEqual(out.score, 1 / 63 + 1 / 61)

    def test_an_openalex_only_entry_without_belgian_years_is_cut_and_the_others_are_kept(self):
        """Only a new-section entry that OpenAlex alone found and with no belgian_years part is cut."""
        part = ScorePart(feature="belgian_years", rank=1, points=1 / 61, detail="d")
        out = {c.person_id: c for c in rank.fuse(
            "s", [entry("web", web=1), entry("oa", openalex=1), entry("net", openalex=2), entry("be", openalex=3)],
            {"net": "in_list"}, {"be": part})}
        self.assertEqual({p: c.cut_reason for p, c in out.items()},
                         {"web": None, "oa": "no_belgian_evidence", "net": None, "be": None})

    def test_kept_ranks_run_from_1_without_a_gap_and_cut_entries_number_apart(self):
        """Cut entries do not take a kept rank, and each group keeps the order fuse gave it."""
        entries = [entry("p1", openalex=1), entry("p2", seeds=2), entry("p3", openalex=3), entry("p4", seeds=4)]
        out = rank.fuse("s", entries, {})
        self.assertEqual([(c.person_id, c.rank, c.cut_reason is not None) for c in out],
                         [("p1", 1, True), ("p2", 1, False), ("p3", 2, True), ("p4", 2, False)])


class YearsTest(unittest.TestCase):
    def test_a_span_counts_every_year_in_it(self):
        """A claim valid from 1999 to 2002 covers four calendar years."""
        self.assertEqual(units(claim("c1", valid_from="1999-09", valid_to="2002")), {"1999", "2000", "2001", "2002"})

    def test_a_claim_with_only_a_claim_date_counts_its_year(self):
        """Without validity dates, the claim date's year is the one unit."""
        self.assertEqual(units(claim("c1", claim_date="2011-05-02")), {"2011"})

    def test_undated_claims_add_one_unit_together(self):
        """A claim with no date is one undated unit, and a second undated claim adds nothing."""
        self.assertEqual(units(claim("c1")), {"undated"})
        self.assertEqual(units(claim("c1"), claim("c2")), {"undated"})

    def test_the_same_year_from_two_claims_counts_once(self):
        """Units are a set: a 2018 claim date inside a 2013 to 2018 span adds no year."""
        self.assertEqual(len(units(claim("c1", valid_from="2013", valid_to="2018"), claim("c2", claim_date="2018"))), 6)

    def test_listed_years_count_and_the_years_between_them_do_not(self):
        """A claim whose source lists 2012 and 2023 counts 2, though it is valid from 2012 to 2023."""
        listed = claim("c1", valid_from="2012", valid_to="2023", years=[2012, 2023])
        self.assertEqual(units(listed), {"2012", "2023"})

    def test_a_span_that_ends_before_it_starts_counts_its_endpoint_years_only(self):
        """valid_to before valid_from is no span: only the years that are set count."""
        self.assertEqual(units(claim("c1", valid_from="2002", valid_to="1999")), {"1999", "2002"})


class BelgianListTest(unittest.TestCase):
    def test_a_record_joined_only_by_name_never_scores(self):
        """A same-name record with Belgian claims is shown on the entry but adds no belgian_years part."""
        hit = LaneHit(person_id="p1", name_key="anne example", lane="seeds", rank=1, score=1.0, matched_on="x")
        out = resolve.group([LaneOut(lane="seeds", query="q", total_seen=1, hits=[hit])],
                            {"anne example": [("p1", "anne example"), ("p2", "anne example")]})
        (found,) = out.entries
        self.assertEqual((found.person_ids, found.hit_person_ids), (["p1", "p2"], ["p1"]))
        claims = [claim("c1", "p1", MIT.id, claim_date="2020"), claim("c2", "p2", claim_date="2011")]
        self.assertEqual(rank.belgian_list(out.entries, claims, FACTS), {})
        (candidate,) = rank.fuse("s", out.entries, {}, rank.belgian_list(out.entries, claims, FACTS))
        self.assertEqual([p.feature for p in candidate.score_parts], ["seeds"])

    def test_equal_counts_share_a_rank_and_a_count_of_zero_is_off_the_list(self):
        """Ranks follow standard competition ranking (1, 2, 2, 4), so no order between equal counts enters the score."""
        entries = [hit_entry(p, seeds=1) for p in ("p1", "p2", "p3", "p4", "p5")]
        claims = [claim("a", "p1", valid_from="2001", valid_to="2003"), claim("b", "p2", valid_from="2001", valid_to="2002"),
                  claim("c", "p3", claim_date="2010"), claim("d", "p3", claim_date="2012"), claim("e", "p4"),
                  claim("f", "p5", MIT.id, claim_date="2015")]
        found = rank.belgian_list(entries, claims, FACTS)
        self.assertEqual({key: part.rank for key, part in found.items()}, {"p1": 1, "p2": 2, "p3": 2, "p4": 4})

    def test_sweldens_kvab_membership_puts_his_seed_record_on_the_list(self):
        """A seed hit on Wim Sweldens' KVAB record gets a belgian_years part from his KVAB member_of claim."""
        settings = make_settings(self)
        store = make_seeded_db(self, settings)
        ctx = StepContext(search_id="s", store=store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        person_id = store.person_ids_by_identifier(
            "seed", ["kvab|wim-sweldens|2011|technische-wetenschappen-buitenlandse-leden"]).popitem()[1]
        lane = LaneOut(lane="seeds", query="q", total_seen=1, hits=[
            LaneHit(person_id=person_id, name_key="wim sweldens", lane="seeds", rank=7, score=1.0, matched_on="KVAB")])
        entries = resolve.run(ctx, ResolveIn(outs=[lane])).entries
        (candidate,) = rank.run(ctx, RankIn(entries=entries, chips=Chips())).candidates
        part = next(p for p in candidate.score_parts if p.feature == "belgian_years")
        kvab = [c for c in store.claims_of([person_id]) if c.org_id == "wikidata:Q1301699"]
        self.assertEqual({c.relation for c in kvab}, {"member_of"})
        self.assertEqual(set(part.claim_ids), {c.id for c in kvab})
        self.assertEqual((part.rank, part.detail), (1, "1 year at Belgian organizations; 1 / (60 + 1)"))


BOSTON = GeoArea(place="Boston", city="Boston, US", lat=42.36, lon=-71.06, radius_km=100.0)
ASK = Question(chips=Chips(topics=[Chip(text="wind power", origin="edited")]), area=BOSTON, country="US")


def found(*, words: tuple[str, ...] = ("wind",), match: bool = True, kinds: tuple[str, ...] = ("belgian_org",),
          years: int = 5, last: int | None = 2024, fit: str = "unknown", km: float | None = None,
          countries: tuple[str, ...] = (), institution: bool = False, only_openalex: bool = True) -> evidence.Evidence:
    """Evidence as rank reads it, with every field a test may vary."""
    near = evidence.Place(42.4, -71.1, "Cambridge", "US", "employer", "c-place", 2024) if km is not None else None
    return evidence.Evidence(
        topic=evidence.Topic(match=match and bool(words), words=words, claim_ids=("c-topic",) if words else ()),
        institution=evidence.Institution(match=institution, claim_ids=("c-inst",) if institution else ()),
        belgian=evidence.Tie(kinds={k: (f"c-{k}",) for k in kinds}, years=years, last=last),
        place=evidence.Where(fit=fit, km=km, nearest=near, countries=frozenset(countries)),
        only_openalex=only_openalex)


def ranked(cases: dict[str, tuple[int, evidence.Evidence]], ask: Question = ASK,
           statuses: dict | None = None) -> list:
    """fuse over one OpenAlex-ranked entry per case, with the case's evidence."""
    entries = [hit_entry(key, openalex=lane) for key, (lane, _) in cases.items()]
    return rank.fuse("s", entries, statuses or {}, None, {key: ev for key, (_, ev) in cases.items()}, ask)


class OrderTest(unittest.TestCase):
    def test_the_five_bands_come_in_order_whatever_the_lane_score(self):
        """Group 0 not outside, group 0 outside, group 1 not outside, group 1 outside, then placed only abroad."""
        out = ranked({
            "abroad": (1, found(countries=("BE",), kinds=("seed_list",), only_openalex=False)),
            "g1out": (2, found(match=False, fit="outside", km=900.0, countries=("US",))),
            "g1": (3, found(match=False)),
            "g0out": (4, found(fit="outside", km=900.0, countries=("US",))),
            "g0in": (5, found(fit="inside", km=5.0, countries=("US",))),
        })
        self.assertEqual([(c.person_id, c.group, c.rank) for c in out],
                         [("g0in", 0, 1), ("g0out", 0, 2), ("g1", 1, 3), ("g1out", 1, 4), ("abroad", 0, 5)])

    def test_an_unknown_place_moves_nobody_down(self):
        """A group-0 person with no place and a better score stays above a group-0 person inside the area."""
        out = ranked({"unknown": (1, found(kinds=("seed_list",))), "inside": (30, found(fit="inside", km=5.0, countries=("US",)))})
        self.assertEqual([c.person_id for c in out], ["unknown", "inside"])

    def test_inside_a_band_more_topic_words_come_before_a_better_score(self):
        """Two words of the question found beat one word with a better lane rank; equal words fall back to the score."""
        out = ranked({"one": (1, found(words=("wind",))), "two": (30, found(words=("wind", "power"))),
                      "also_two": (20, found(words=("power", "wind")))})
        self.assertEqual([c.person_id for c in out], ["also_two", "two", "one"])

    def test_groups_never_go_up_down_the_list_outside_the_last_band(self):
        """Over every mix of topic match, tie and place, no group-1 card comes before a group-0 card."""
        cases = {}
        for n, (match, kinds, fit) in enumerate((m, k, f) for m in (True, False) for k in ((), ("seed_list",))
                                                for f in ("inside", "outside", "unknown")):
            cases[f"p{n:02d}"] = (n + 1, found(match=match, kinds=kinds, fit=fit, km=5.0 if fit == "inside" else 900.0,
                                               countries=("US",) if fit != "unknown" else (), only_openalex=False))
        groups = [c.group for c in ranked(cases)]
        self.assertEqual(groups, sorted(groups))
        self.assertEqual(groups.count(0), 3)

    def test_without_a_topic_chip_a_tie_alone_is_group_0(self):
        """A question of only an institution, or of generic words, puts everyone with a tie in group 0."""
        for chips in (Chips(institutions=[Chip(text="MIT", origin="edited")]), Chips(topics=[Chip(text="research", origin="edited")])):
            with self.subTest(chips=chips):
                out = ranked({"tie": (2, found(words=())), "none": (1, found(words=(), kinds=(), only_openalex=False))},
                             Question(chips=chips))
                self.assertEqual([(c.person_id, c.group) for c in out], [("tie", 0), ("none", 1)])

    def test_topic_place_and_seed_list_parts_carry_their_claims_and_details(self):
        """topic ranks by words found and names them, place ranks the inside by distance, seed_list is 1 / 61."""
        out = {c.person_id: c for c in ranked({
            "two": (1, found(words=("wind", "power"), kinds=("seed_list",), fit="inside", km=30.0, countries=("US",))),
            "one": (2, found(words=("wind",), fit="inside", km=5.0, countries=("US",)))})}
        parts = {k: [(p.feature, p.rank, p.claim_ids, p.detail) for p in c.score_parts[1:]] for k, c in out.items()}
        self.assertEqual(parts["two"], [("topic", 1, ["c-topic"], "wind, power"),
                                        ("place", 2, ["c-place"], "employer: Cambridge"),
                                        ("seed_list", 1, ["c-seed_list"], "seed-list record; 1 / (60 + 1)")])
        self.assertEqual(parts["one"], [("topic", 2, ["c-topic"], "wind"), ("place", 1, ["c-place"], "employer: Cambridge")])
        self.assertAlmostEqual(out["two"].score, 1 / 61 + 1 / 61 + 1 / 62 + 1 / 61)

    def test_the_network_section_is_ordered_by_score_alone_and_never_cut(self):
        """A network person placed only abroad with no Belgian years keeps its place by score and is kept."""
        out = ranked({"abroad": (1, found(countries=("BE",), years=0)), "home": (2, found())},
                     statuses={"abroad": "in_list", "home": "in_list"})
        self.assertEqual([(c.person_id, c.section, c.rank, c.cut_reason) for c in out],
                         [("abroad", "network", 1, None), ("home", "network", 2, None)])


class CutTest(unittest.TestCase):
    def cut(self, ev: evidence.Evidence, ask: Question = ASK, section: str = "new") -> str | None:
        return rank.cut_reason(section, ev, ask)

    def test_no_belgian_evidence_cuts_an_openalex_only_person_without_belgian_years(self):
        """No Belgian years cuts; one year with a topic word keeps."""
        self.assertEqual(self.cut(found(years=0, last=None)), "no_belgian_evidence")
        self.assertIsNone(self.cut(found(years=1, last=2024, countries=("US",))))

    def test_weak_openalex_cuts_no_topic_word_and_few_or_old_years_unless_inside_or_at_the_institution(self):
        """Two years, or five years ending 2015, without a topic word cut; the same person inside the area, or with
        a claim at the institution asked for, is kept."""
        self.assertEqual(self.cut(found(words=(), years=2)), "weak_openalex")
        self.assertEqual(self.cut(found(words=(), years=5, last=2015)), "weak_openalex")
        self.assertIsNone(self.cut(found(words=(), years=5, last=2015, institution=True)))
        self.assertIsNone(self.cut(found(words=(), years=2, fit="inside", km=5.0, countries=("US",))))

    def test_no_claim_cuts_no_topic_word_no_institution_and_not_inside(self):
        """Many recent years but no topic word cut; an institution match keeps the person."""
        self.assertEqual(self.cut(found(words=(), years=5, last=2024)), "no_claim")
        self.assertEqual([self.cut(found(words=(), years=3, last=last)) for last in (2024, 2016)], ["no_claim"] * 2)
        self.assertIsNone(self.cut(found(words=(), years=5, last=2024, institution=True)))

    def test_outside_country_cuts_a_person_placed_only_outside_the_question_s_country(self):
        """Placed only in Belgium for a US question cuts; a Belgian and a US place, no place, or an institution keep."""
        self.assertEqual(self.cut(found(countries=("BE",))), "outside_country")
        self.assertIsNone(self.cut(found(countries=("BE", "US"))))
        self.assertIsNone(self.cut(found()))
        self.assertIsNone(self.cut(found(countries=("BE",), institution=True)))

    def test_an_anywhere_us_question_asks_about_the_us_and_a_question_without_a_country_cuts_nobody_by_country(self):
        """anywhere_us gives US, so a person placed only in Belgium is cut; abroad gives no country, so nobody is."""
        us = Question(chips=ASK.chips, country=geo.question_country(None, Place(text="the US", origin="edited", kind="anywhere_us"), None))
        abroad = Question(chips=ASK.chips, country=geo.question_country(None, Place(text="Europe", origin="edited", kind="abroad"), None))
        self.assertEqual(self.cut(found(countries=("BE",)), us), "outside_country")
        self.assertIsNone(self.cut(found(countries=("BE",)), abroad))

    def test_the_network_section_a_seed_list_person_and_a_web_person_are_never_cut(self):
        """Evidence that would cut an OpenAlex-only person keeps one in the network or with another record."""
        bare = dict(words=(), years=0, last=None, countries=("BE",))
        self.assertIsNone(self.cut(found(**bare), section="network"))
        self.assertIsNone(self.cut(found(**bare, kinds=("seed_list",), only_openalex=False)))
        self.assertIsNone(self.cut(found(**bare, kinds=(), only_openalex=False)))


class CardRecordsTest(unittest.TestCase):
    def test_the_records_on_the_card_score_and_a_possible_match_does_not(self):
        """Belgian years count the claims of every card record; a record only in person_ids adds nothing."""
        settings = make_settings(self)
        store = make_db(self, settings)
        source = Source(id="s", kind="record", url="https://ror.org/01r9htc13", text="ULB", content_hash="o",
                        fetched_at=FETCHED)
        store.upsert_source(source)
        store.upsert_org(ULB, True)
        ids = []
        for n, year in enumerate(("2001", "2011", "2021")):
            person = store.resolve_person([Identifier(scheme="openalex", value=f"A{n}")], "Ann Example")
            text = f"Ann Example, ULB {year}"
            store.upsert_claim(ClaimDraft(person_id=person.id, kind="affiliation", relation="worked_at", org_id=ULB.id,
                                          value="ULB", quote=text, quote_start=0, quote_end=len(text), claim_date=year,
                                          source=Source(id=f"s{n}", kind="record", url=f"https://example.org/{n}",
                                                        text=text, content_hash=f"h{n}")))
            ids.append(person.id)
        entry = Entry(name_key="ann example", person_ids=ids, hit_person_ids=ids[:1], card_person_ids=ids[:2],
                      lane_ranks={"openalex": 1})
        ctx = StepContext(search_id="s", store=store, llm=None, http=StubHttp(), now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        (candidate,) = rank.run(ctx, RankIn(entries=[entry], chips=Chips())).candidates
        (part,) = [p for p in candidate.score_parts if p.feature == "belgian_years"]
        self.assertEqual((part.detail.split(";")[0], candidate.cut_reason, candidate.group),
                         ("2 years at Belgian organizations", "weak_openalex", 0))

    def test_a_rerun_ranks_as_of_the_search_it_repeats(self):
        """An employer recent at the original search's creation stays a place in a rerun created years later."""
        settings = make_settings(self)
        store = make_db(self, settings)
        lab = Org(id="ror:00abcd123", name="Example Lab", country_code="US", city="Boston", lat=42.36, lon=-71.06,
                  source_id="s", fetched_at=FETCHED)
        store.upsert_source(Source(id="s", kind="record", url="https://ror.org/00abcd123", text="Example Lab",
                                   content_hash="o", fetched_at=FETCHED))
        store.upsert_org(lab, False)
        person = store.resolve_person([Identifier(scheme="openalex", value="A1")], "Ann Example")
        text = "Ann Example, Example Lab 2022"
        store.upsert_claim(ClaimDraft(person_id=person.id, kind="affiliation", relation="works_at", org_id=lab.id,
                                      value="Example Lab", quote=text, quote_start=0, quote_end=len(text),
                                      claim_date="2022", source=Source(id="s1", kind="record", url="https://example.org/1",
                                                                       text=text, content_hash="h1")))
        stamp = {"question": "q", "status": "done", "code_sha": "abc", "dirty": False, "llm_mode": "replay",
                 "settings_json": "{}", "boot_id": "boot"}
        store.create_search(Search(id="first", created_at=datetime(2026, 11, 5, tzinfo=UTC), **stamp))
        store.create_search(Search(id="again", created_at=datetime(2031, 1, 1, tzinfo=UTC), rerun_of="first", **stamp))
        ctx = StepContext(search_id="again", store=store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        entry = Entry(name_key="ann example", person_ids=[person.id], lane_ranks={"openalex": 1})
        with mock.patch.object(evidence, "of", wraps=evidence.of) as of:
            rank.run(ctx, RankIn(entries=[entry], chips=Chips()))
        (call,) = of.call_args_list
        self.assertEqual([(p.text, p.basis) for p in evidence.places(call.args[1], call.args[2], call.args[4])],
                         [("Boston", "employer")])


if __name__ == "__main__":
    unittest.main()
