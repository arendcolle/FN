import dataclasses
import logging
import unittest
from collections import Counter
from datetime import UTC, date, datetime
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
from tests.helpers import StubHttp, load_seed_rows, make_db, make_settings, save_recorded_orgs

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

    def test_a_kvab_membership_puts_a_seed_record_on_the_list(self):
        """A seed hit on a KVAB member's record gets a belgian_years part from the KVAB member_of claim."""
        settings = make_settings(self)
        store = make_db(self, settings)
        save_recorded_orgs(store, settings)
        load_seed_rows(self, store, "kvab", "Ada Example", 2011)
        ctx = StepContext(search_id="s", store=store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        person_id = store.person_ids_by_identifier("seed", ["kvab|ada-example|2011|"]).popitem()[1]
        lane = LaneOut(lane="seeds", query="q", total_seen=1, hits=[
            LaneHit(person_id=person_id, name_key="ada example", lane="seeds", rank=7, score=1.0, matched_on="KVAB")])
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
          countries: tuple[str, ...] = (), institution: bool = False, only_openalex: bool = True,
          grade: str | None = None, role: str = "unknown", related: bool = False,
          job: str = "none") -> evidence.Evidence:
    """Evidence as rank reads it, with every field a test may vary."""
    near = evidence.Place(42.4, -71.1, "Cambridge", "US", "employer", "c-place", 2024) if km is not None else None
    return evidence.Evidence(
        topic=evidence.Topic(match=match and bool(words), words=words, claim_ids=("c-topic",) if words else (),
                            related=related),
        institution=evidence.Institution(match=institution, claim_ids=("c-inst",) if institution else ()),
        belgian=evidence.Tie(kinds={k: (f"c-{k}",) for k in kinds}, years=years, last=last,
                           grade=grade or ("strong" if kinds else "none")),
        role=evidence.Role(fit=role),
        place=evidence.Where(fit=fit, km=km, nearest=near, countries=frozenset(countries)),
        only_openalex=only_openalex, job=job)


def ranked(cases: dict[str, tuple[int, evidence.Evidence]], ask: Question = ASK,
           statuses: dict | None = None) -> list:
    """fuse over one OpenAlex-ranked entry per case, with the case's evidence."""
    entries = [hit_entry(key, openalex=lane) for key, (lane, _) in cases.items()]
    return rank.fuse("s", entries, statuses or {}, None, {key: ev for key, (_, ev) in cases.items()}, ask)


class OrderTest(unittest.TestCase):
    def test_the_tiers_come_in_order_whatever_the_lane_score(self):
        """Tier 1 inside, tier 2 outside, then abroad last in tier 2, then tier 5 (a tie and a word, no full topic match)."""
        out = ranked({
            "abroad": (1, found(countries=("BE",), kinds=("seed_list",), only_openalex=False)),
            "g1out": (2, found(match=False, fit="outside", km=900.0, countries=("US",))),
            "g1": (3, found(match=False)),
            "g0out": (4, found(fit="outside", km=900.0, countries=("US",))),
            "g0in": (5, found(fit="inside", km=5.0, countries=("US",))),
        })
        self.assertEqual([(c.person_id, c.group, c.rank) for c in out],
                         [("g0in", 0, 1), ("g0out", 0, 2), ("abroad", 0, 3), ("g1", 1, 4), ("g1out", 1, 5)])

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

    def test_topic_words_do_not_reorder_the_network_section(self):
        """A network person with one topic word and the better score stays above one with two words."""
        out = ranked({"one": (1, found(words=("wind",))), "two": (30, found(words=("wind", "power")))},
                     statuses={"one": "in_list", "two": "in_list"})
        self.assertEqual([c.person_id for c in out], ["one", "two"])


def v2(tie: str | None = None, *roles: Chip, **flags) -> Question:
    """A question over the same topic and area as ASK with version-2 chips, and a tie chip of the given need."""
    chips = Chips(topics=[Chip(text="wind power", origin="edited")], roles=list(roles), version=2,
                  tie=Chip(text="Flanders", origin="edited", need=tie) if tie else None)
    return Question(chips=chips, area=BOSTON, country="US", **flags)


class TierTest(unittest.TestCase):
    CASES = {
        "t1": found(job="known", fit="inside", km=5.0, countries=("US",), only_openalex=False),
        "t2": found(job="known", fit="outside", km=900.0, countries=("US",), only_openalex=False),
        "t3": found(job="known", kinds=(), only_openalex=False),
        "t4": found(job="known", kinds=(), fit="outside", km=900.0, countries=("US",), only_openalex=False),
        "t5": found(match=False, only_openalex=False),
        "t6_tie": found(match=False, words=(), only_openalex=False),
        "t6_none": found(match=False, kinds=(), only_openalex=False),
        "t7": found(match=False, words=(), kinds=(), only_openalex=False),
    }

    def run_cases(self, ask: Question, cases: dict | None = None, statuses: dict | None = None) -> dict:
        cases = cases or self.CASES
        out = ranked({k: (n, ev) for n, (k, ev) in enumerate(reversed(list(cases.items())), 1)}, ask, statuses)
        return {c.person_id: c for c in out}

    def test_the_eight_cases_of_the_table_come_out_in_tiers_1_to_7_with_their_heading(self):
        """Topic before tie, tie before place; tier 6 stands under heading 3 with a tie and 4 without, after tier 5."""
        out = self.run_cases(v2())
        self.assertEqual([(k, c.tier, c.group, rank.heading(c.tier, c.fit.tie_grade), c.cut_reason) for k, c in out.items()],
                         [("t1", 1, 0, 1, None), ("t2", 2, 0, 1, None), ("t3", 3, 1, 2, None), ("t4", 4, 1, 2, None),
                          ("t5", 5, 1, 3, None), ("t6_tie", 6, 1, 3, None), ("t6_none", 6, 1, 4, None), ("t7", 7, 1, 4, None)])

    def test_a_tie_that_is_a_must_cuts_weak_and_no_tie_but_never_the_network(self):
        """Under a must tie a weak grade and no grade are cut no_tie; a network person with no tie is kept."""
        cases = dict(self.CASES, weak=found(kinds=("belgian_text",), grade="weak", only_openalex=False))
        out = self.run_cases(v2("must"), cases, {"t7": "in_list"})
        self.assertEqual({k: c.cut_reason for k, c in out.items()},
                         {"t1": None, "t2": None, "t3": "no_tie", "t4": "no_tie", "t5": None, "t6_tie": None,
                          "t6_none": "no_tie", "t7": None, "weak": "no_tie"})
        self.assertEqual(out["t7"].section, "network")

    def test_a_tie_that_is_nice_and_version_1_chips_cut_nobody_for_a_missing_tie(self):
        """Only a version-2 must tie cuts no_tie; a nice tie and version-1 chips keep everyone."""
        v1 = Question(chips=Chips(topics=[Chip(text="wind power", origin="edited")], tie=Chip(text="x", origin="edited")),
                      area=BOSTON, country="US")
        for ask in (v2("nice"), v1):
            self.assertEqual({c.cut_reason for c in self.run_cases(ask).values()}, {None})

    def test_in_tier_1_role_met_comes_before_unknown_then_own_words_then_strong_before_medium(self):
        """The met person with a related word and a worse score is first; then own words before a related word;
        then a strong tie before a medium one."""
        here = dict(fit="inside", km=5.0, countries=("US",), only_openalex=False, job="known")
        out = ranked({"unknown": (1, found(**here)), "met": (30, found(role="met", related=True, **here))}, v2())
        self.assertEqual([c.person_id for c in out], ["met", "unknown"])
        out = ranked({"related": (1, found(related=True, **here)), "own": (30, found(**here))}, v2())
        self.assertEqual([c.person_id for c in out], ["own", "related"])
        out = ranked({"medium": (1, found(grade="medium", **here)), "strong": (30, found(**here))}, v2())
        self.assertEqual([c.person_id for c in out], ["strong", "medium"])

    def test_in_tier_2_outside_comes_before_abroad_whatever_the_role_and_grade(self):
        """Abroad stands last in tier 2 even with role met and a strong tie against role unknown and a medium tie."""
        out = ranked({"abroad": (1, found(countries=("BE",), role="met", only_openalex=False, job="known")),
                      "outside": (30, found(job="known", fit="outside", km=900.0, countries=("US",), grade="medium", only_openalex=False))},
                     v2())
        self.assertEqual([(c.person_id, c.tier) for c in out], [("outside", 2), ("abroad", 2)])

    def test_a_failed_role_is_tier_7_under_heading_4_and_kept_under_a_must_tie(self):
        """Role fails with a topic and a strong tie: tier 7, heading 4, and not cut by a must tie."""
        out = ranked({"fails": (1, found(role="fails", fit="inside", km=5.0, countries=("US",), only_openalex=False))},
                     v2("must"))
        (c,) = out
        self.assertEqual((c.tier, rank.heading(c.tier, c.fit.tie_grade), c.cut_reason, c.fit.role), (7, 4, None, "fails"))

    def test_place_fit_for_each_value(self):
        """none without a place, abroad, inside, outside and unknown; an anywhere_us question has no area."""
        place = Chips(place=Place(text="Boston", origin="edited"))
        us = Question(chips=Chips(place=Place(text="the US", origin="edited", kind="anywhere_us")), country="US")
        self.assertEqual(
            [rank.place_fit(found(), None), rank.place_fit(found(), Question(chips=Chips())),
             rank.place_fit(found(countries=("BE",)), Question(chips=place, area=BOSTON, country="US")),
             rank.place_fit(found(fit="inside", countries=("US",)), Question(chips=place, area=BOSTON, country="US")),
             rank.place_fit(found(fit="outside", countries=("US",)), Question(chips=place, area=BOSTON, country="US")),
             rank.place_fit(found(), Question(chips=place, area=BOSTON, country="US")),
             rank.place_fit(found(countries=("US",)), us), rank.place_fit(found(countries=("US", "BE")), us),
             rank.place_fit(found(countries=("BE",)), us)],
            ["none", "none", "abroad", "inside", "outside", "unknown", "inside", "inside", "abroad"])

    def test_the_saved_fit_holds_grade_tie_claims_place_and_role(self):
        """A candidate stores the tie grade, the tie claims in evidence's order, the place fit and the role fit."""
        ev = found(kinds=("seed_list", "belgian_org"), role="met", fit="inside", km=5.0, countries=("US",))
        (c,) = ranked({"a": (1, ev)}, v2())
        self.assertEqual(c.fit.model_dump(), {"tie_grade": "strong", "tie_claim_ids": list(ev.belgian.claim_ids),
                                              "place": "inside", "role": "met"})
        self.assertIsNone(rank.fit_of(None, v2()))

    def test_no_evidence_is_tier_7_and_tier_6_splits_by_the_tie(self):
        """tier(None, None) is 7; heading(6, grade) is 3 for a strong or medium tie and 4 for weak or none."""
        self.assertEqual(rank.tier(None, None), 7)
        self.assertEqual([rank.heading(6, g) for g in ("strong", "medium", "weak", "none")], [3, 3, 4, 4])
        (c,) = rank.fuse("s", [hit_entry("a", seeds=1)], {})
        self.assertEqual((c.tier, c.fit), (7, None))


class WorkAndAgeOrderTest(unittest.TestCase):
    HERE = dict(fit="inside", km=5.0, countries=("US",), only_openalex=False)

    def key(self, ask: Question, stale: bool = False, **fields) -> tuple:
        ev = dataclasses.replace(found(**self.HERE, **fields), age=evidence.Age(stale=stale))
        return rank.order_key(ev, ask, 1)

    def test_in_a_tier_a_known_job_comes_before_an_employer_before_none_and_a_fresh_fact_before_a_stale_one(self):
        """With the same role fit and verdict a version-2 key sorts known, employer, none, then not stale before stale."""
        ask = v2()
        keys = [self.key(ask, job=j) for j in ("none", "known", "employer")]
        self.assertEqual(sorted(range(3), key=keys.__getitem__), [1, 2, 0])
        self.assertLess(self.key(ask, job="known"), self.key(ask, stale=True, job="known"))
        self.assertLess(self.key(ask, stale=True, job="known"), self.key(ask, job="employer"))

    def test_a_met_role_without_a_job_still_comes_before_an_unknown_role_with_a_known_job(self):
        """The role fit stands before the job in the key."""
        ask = v2()
        self.assertLess(self.key(ask, role="met", job="none", stale=True), self.key(ask, job="known"))

    def test_version_1_chips_ignore_job_and_age_and_a_person_without_evidence_gets_the_last_values(self):
        """A version-1 key is the same for a known job and none; the blank version-2 key is as long as the others."""
        self.assertEqual(self.key(ASK, job="known"), self.key(ASK, stale=True, job="none"))
        self.assertEqual(len(rank.order_key(None, v2(), 7)), len(self.key(v2())))
        self.assertGreater(rank.order_key(None, v2(), 7), self.key(v2(), stale=True, job="none"))


class ConfirmedTest(unittest.TestCase):
    BIZ = Chip(text="founders", origin="edited", research=False)
    HERE = dict(fit="inside", km=5.0, countries=("US",), only_openalex=False)

    def tiers(self, ask: Question, **people) -> dict:
        out = ranked({k: (n, ev) for n, (k, ev) in enumerate(people.items(), 1)}, ask)
        return {c.person_id: c.tier for c in out}

    def test_a_topic_match_without_a_known_job_stands_in_tier_5_and_a_job_without_a_tie_before_it(self):
        """Topic words and a tie without role and employer are tier 5; with both tier 1; a job without a tie is tier 3."""
        ask = v2("nice", self.BIZ)
        out = ranked({"none": (1, found(**self.HERE)), "job": (2, found(job="known", **self.HERE)),
                      "bare": (3, found(job="known", kinds=(), **self.HERE))}, ask)
        self.assertEqual([(c.person_id, c.tier) for c in out], [("job", 1), ("bare", 3), ("none", 5)])

    def test_version_1_chips_keep_a_person_without_a_job_in_tier_1(self):
        """Stored searches carry version-1 chips, whose tiers do not read the job."""
        v1 = Question(chips=ASK.chips, area=BOSTON, country="US")
        self.assertEqual(self.tiers(v1, none=found(**self.HERE)), {"none": 1})

    def test_an_employer_alone_confirms_only_an_openalex_only_card_on_a_question_that_wants_research(self):
        """OpenAlex-only with an employer is tier 1 without a role chip and tier 5 beside a business role chip;
        a seed person with an employer alone is tier 5 on both."""
        people = dict(oa=found(job="employer", **self.HERE | {"only_openalex": True}), seed=found(job="employer", **self.HERE))
        self.assertEqual(self.tiers(v2(), **people), {"oa": 1, "seed": 5})
        self.assertEqual(self.tiers(v2(None, self.BIZ), **people), {"oa": 5, "seed": 5})

    def test_a_met_role_confirms_without_an_employer_and_no_role_chip_does_not(self):
        """A consul who meets the role chip is tier 1 without an employer; without a role chip the same person is tier 5."""
        consul = found(role="met", **self.HERE)
        self.assertEqual(self.tiers(v2(None, self.BIZ), consul=consul), {"consul": 1})
        self.assertEqual(self.tiers(v2(), consul=found(**self.HERE)), {"consul": 5})

    def test_a_met_role_confirms_without_a_topic_word_and_stands_after_role_and_topic(self):
        """A brewer who meets the role chip but holds no topic word is tier 1, behind a person with role and topic."""
        ask = v2(None, self.BIZ)
        people = {"role": (1, found(role="met", words=(), **self.HERE)), "both": (2, found(role="met", **self.HERE)),
                  "topic": (3, found(job="known", **self.HERE))}
        self.assertEqual([(c.person_id, c.tier) for c in ranked(people, ask)], [("both", 1), ("role", 1), ("topic", 1)])

    def test_a_person_the_web_researcher_named_counts_as_confirmed_on_version_2_only(self):
        """Found by the scout lane, a person without a topic word or a known job is tier 3, or 1 with a tie; not on version 1."""
        bare = dict(words=(), match=False, **self.HERE)
        entries = [hit_entry("tied", scout=1), hit_entry("free", scout=2), hit_entry("stored", seeds=1)]
        evidence_of = {"tied": found(**bare), "free": found(kinds=(), **bare), "stored": found(kinds=(), **bare)}
        v1 = Question(chips=ASK.chips, area=BOSTON, country="US")
        for ask, want in ((v2("nice", self.BIZ), {"tied": 1, "free": 3, "stored": 7}), (v1, {"tied": 6, "free": 7, "stored": 7})):
            got = {c.person_id: c.tier for c in rank.fuse("s", entries, {}, None, evidence_of, ask)}
            self.assertEqual(got, want)

    def test_inside_the_area_stands_before_an_unknown_place_on_version_2_only(self):
        """Within tier 1 a version-2 question puts the inside person first despite the worse score; version 1 keeps score order."""
        people = {"unknown": (1, found(job="known", kinds=("belgian_org", "seed_list"), only_openalex=False)),
                  "inside": (2, found(job="known", **self.HERE))}
        self.assertEqual([c.person_id for c in ranked(people, v2())], ["inside", "unknown"])
        v1 = Question(chips=Chips(topics=ASK.chips.topics, place=Place(text="Boston", origin="edited")),
                      area=BOSTON, country="US")
        self.assertEqual([c.person_id for c in ranked(people, v1)], ["unknown", "inside"])


class ExemptionTest(unittest.TestCase):
    def people(self, n: int = 25, **flags) -> dict:
        base = dict(kinds=(), years=0, last=None, countries=("US",))
        return {f"p{k:02d}": (k + 1, found(**base | flags)) for k in range(n)}

    def test_twenty_topic_experts_without_belgian_evidence_come_back_and_the_rest_keep_the_cut(self):
        """With version-2 chips and a nice tie 20 of 25 are kept in order; a must tie cuts all; version 1 cuts all."""
        out = ranked(self.people(), v2("nice"))
        self.assertEqual([c.cut_reason for c in out], [None] * 20 + ["no_belgian_evidence"] * 5)
        self.assertEqual([c.person_id for c in out[:3]], ["p00", "p01", "p02"])
        self.assertEqual({c.cut_reason for c in ranked(self.people(), v2("must"))}, {"no_belgian_evidence"})
        v1 = Question(chips=ASK.chips, area=BOSTON, country="US")
        self.assertEqual({c.cut_reason for c in ranked(self.people(), v1)}, {"no_belgian_evidence"})
        self.assertEqual({c.cut_reason for c in ranked(self.people(), None)}, {"no_belgian_evidence"})

    def test_abroad_and_people_without_a_topic_match_do_not_come_back(self):
        """Only a person who matches the topic and is not abroad is let back in."""
        out = ranked({"abroad": (1, found(kinds=(), years=0, last=None, countries=("BE",))),
                      "off": (2, found(kinds=(), years=0, last=None, match=False))}, v2("nice"))
        self.assertEqual({c.person_id: c.cut_reason for c in out}, {"abroad": "no_belgian_evidence", "off": "no_belgian_evidence"})


class CapTest(unittest.TestCase):
    def crowd(self, total: int, openalex: set[int], lanes: dict | None = None) -> list:
        """Heading 1 people p00.. in tier 1, ordered by score, with the given positions OpenAlex-only."""
        cases = {f"p{k:02d}": (k + 1, found(fit="inside", km=5.0, countries=("US",), only_openalex=k in openalex))
                 for k in range(total)}
        entries = [hit_entry(key, **(lanes or {"seeds": lane})) for key, (lane, _) in cases.items()]
        return rank.fuse("s", entries, {}, None, {key: ev for key, (_, ev) in cases.items()}, v2("nice"))

    def test_the_sixth_openalex_only_person_in_the_first_20_moves_to_the_end_of_its_heading(self):
        """Of 8 OpenAlex-only people in the first 20 of a heading of 30, 5 stay and 3 go to the end, in order."""
        out = self.crowd(30, set(range(2, 10)), {"seeds": 1, "openalex": 2})
        names = [c.person_id for c in out]
        self.assertEqual(names[:7], ["p00", "p01", "p02", "p03", "p04", "p05", "p06"])
        self.assertEqual(names[-3:], ["p07", "p08", "p09"])
        self.assertEqual([c.rank for c in out], list(range(1, 31)))

    def test_people_who_move_up_into_the_first_20_are_capped_too(self):
        """OpenAlex-only people at positions 20 to 22 move up when others leave; at most 5 stay in the first 20."""
        out = self.crowd(30, set(range(2, 10)) | {20, 21, 22}, {"seeds": 1, "openalex": 2})
        self.assertLessEqual(sum(1 for c in out[:20] if int(c.person_id[1:]) in set(range(2, 10)) | {20, 21, 22}), 5)

    def test_two_capped_people_at_the_edge_of_the_first_20_do_not_loop(self):
        """A heading of 21 with OpenAlex-only people at 0 to 4, 19 and 20 returns; the one that cannot leave stays."""
        out = self.crowd(21, set(range(5)) | {19, 20}, {"seeds": 1, "openalex": 2})
        self.assertEqual(sorted(c.person_id for c in out), [f"p{k:02d}" for k in range(21)])

    def test_a_heading_that_ends_inside_the_first_20_keeps_its_order(self):
        """Heading 1 of 10 people with 8 OpenAlex-only: moving inside the heading would not leave the first 20, so the order stays."""
        out = self.crowd(10, set(range(2, 10)), {"seeds": 1, "openalex": 2})
        self.assertEqual([c.person_id for c in out], [f"p{k:02d}" for k in range(10)])

    def test_the_cap_does_not_apply_to_version_1_chips_or_a_question_for_researchers(self):
        """Version-1 chips and a research role chip leave the order alone."""
        cases = {f"p{k:02d}": (k + 1, found(fit="inside", km=5.0, countries=("US",))) for k in range(30)}
        entries = [hit_entry(key, seeds=lane) for key, (lane, _) in cases.items()]
        researcher = v2("nice", Chip(text="professor", origin="edited", research=True))
        for ask in (ASK, researcher):
            out = rank.fuse("s", entries, {}, None, {key: ev for key, (_, ev) in cases.items()}, ask)
            self.assertEqual([c.person_id for c in out], [f"p{k:02d}" for k in range(30)])


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


class VerdictTest(unittest.TestCase):
    HERE = dict(fit="inside", km=5.0, countries=("US",), only_openalex=False, job="known")

    def fused(self, ask: Question, verdicts: dict, **people) -> dict:
        entries = [hit_entry(k, openalex=n) for n, k in enumerate(people, 1)]
        return {c.person_id: c for c in rank.fuse("s", entries, {}, None, people, ask, verdicts)}

    def test_a_no_verdict_drops_a_confirmed_person_to_the_tie_branch_on_version_2_only(self):
        """A confirmed person with verdict no is tier 5 with a tie and a topic word, 6 without a tie; version 1 ignores it."""
        tied, bare = found(**self.HERE), found(kinds=(), **self.HERE)
        out = self.fused(v2(), {"tied": "no", "bare": "no"}, tied=tied, bare=bare)
        self.assertEqual({k: c.tier for k, c in out.items()}, {"tied": 5, "bare": 6})
        words = self.fused(v2(), {"none": "no"}, none=found(kinds=(), words=(), **self.HERE))
        self.assertEqual(words["none"].tier, 7)
        v1 = Question(chips=ASK.chips, area=BOSTON, country="US")
        out = self.fused(v1, {"tied": "no", "bare": "no"}, tied=tied, bare=bare)
        self.assertEqual({k: c.tier for k, c in out.items()}, {"tied": 1, "bare": 3})

    def test_only_a_yes_confirms_a_word_match_and_partly_leads_the_unconfirmed(self):
        """Once the check ran, a partly person and one it did not look at are tier 5 with a tie, partly first and
        a no last; a person who meets the asked role keeps tier 1 with a partly verdict, after the yes person."""
        people = dict(partly=found(**self.HERE), yes=found(**self.HERE), plain=found(**self.HERE), nope=found(**self.HERE),
                      met=found(role="met", **self.HERE))
        ask = v2(None, Chip(text="founders", origin="edited", research=False))
        out = self.fused(ask, {"partly": "partly", "yes": "yes", "nope": "no", "met": "partly"}, **people)
        self.assertEqual({k: c.tier for k, c in out.items()}, {"partly": 5, "yes": 1, "plain": 5, "nope": 5, "met": 1})
        self.assertEqual(sorted(out, key=lambda k: out[k].rank), ["met", "yes", "partly", "plain", "nope"])
        late = self.fused(ask, {"partly": "partly"}, partly=found(role="met", **self.HERE), met=found(role="met", **self.HERE))
        self.assertEqual({k: c.tier for k, c in late.items()}, {"partly": 1, "met": 5})
        unchecked = self.fused(v2(), {}, plain=found(**self.HERE))
        self.assertEqual(unchecked["plain"].tier, 1)
        v1 = Question(chips=ASK.chips, area=BOSTON, country="US")
        out = self.fused(v1, {"partly": "partly", "yes": "yes"}, **people)
        self.assertEqual({c.tier for c in out.values()}, {1})

    def test_a_yes_confirms_a_person_with_a_job_and_no_topic_word_and_leads_heading_3(self):
        """On version 2 a yes with a known job is tier 1 inside the area and tier 2 with an unknown place under a
        required place; without a job it stays tier 6. Under heading 3 the order is yes, partly, none, no."""
        bare = dict(match=False, words=(), **{**self.HERE, "job": "known"})
        out = self.fused(v2(), {"yes": "yes"}, yes=found(**bare), jobless=found(**{**bare, "job": "none"}))
        self.assertEqual({k: c.tier for k, c in out.items()}, {"yes": 1, "jobless": 6})
        ask = v2()
        must = ask.model_copy(update={"chips": ask.chips.model_copy(update={
            "place": Place(text="Boston", origin="edited", need="must")})})
        lost = found(**{**bare, "fit": "unknown", "km": None, "countries": ()})
        self.assertEqual(self.fused(must, {"yes": "yes"}, yes=lost)["yes"].tier, 2)
        jobless = {k: found(**{**bare, "job": "none"}) for k in ("no", "none", "partly", "yes")}
        out = self.fused(v2(), {"no": "no", "partly": "partly", "yes": "yes"}, **jobless)
        self.assertEqual(sorted(out, key=lambda k: out[k].rank), ["yes", "partly", "none", "no"])
        v1 = Question(chips=ASK.chips, area=BOSTON, country="US")
        self.assertEqual(self.fused(v1, {"yes": "yes"}, yes=found(**bare))["yes"].tier,
                         self.fused(v1, {}, yes=found(**bare))["yes"].tier)

    def test_a_person_the_check_sent_without_a_verdict_keeps_the_tier(self):
        """A person in unsure (failed batch, skipped line) is not demoted as an unchecked word match."""
        entries = [hit_entry(k, openalex=n) for n, k in enumerate(("plain", "lost"), 1)]
        people = dict(plain=found(**self.HERE), lost=found(**self.HERE))
        out = {c.person_id: c.tier for c in rank.fuse("s", entries, {}, None, people, v2(), {"x": "yes"}, unsure=["lost"])}
        self.assertEqual(out, {"plain": 5, "lost": 1})

    def test_a_verdict_is_found_by_any_record_of_the_card_and_a_network_person_is_not_demoted(self):
        """A card whose first record changed keeps its yes; a person in the network is not sent, so no verdict costs them nothing."""
        merged = Entry(name_key="m", person_ids=["new-first", "old-first"], hit_person_ids=["new-first"], lane_ranks={"openalex": 1})
        member = hit_entry("member", openalex=2)
        people = {"new-first": found(**self.HERE), "member": found(**self.HERE)}
        out = {c.person_id: c for c in rank.fuse("s", [merged, member], {"member": "in_list"}, None, people, v2(),
                                                 {"old-first": "yes"})}
        self.assertEqual((out["new-first"].tier, out["member"].tier), (1, 1))

    def test_rank_run_passes_the_verdicts_of_its_input_to_fuse(self):
        """RankIn.verdicts reaches the ranking."""
        store = make_db(self)
        person = store.resolve_person([Identifier(scheme="openalex", value="A1")], "Ann Example")
        ctx = StepContext(search_id="s", store=store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=make_settings(self))
        with mock.patch.object(rank, "fuse", return_value=[]) as fuse:
            rank.run(ctx, RankIn(entries=[Entry(name_key="a", person_ids=[person.id], lane_ranks={"openalex": 1})], chips=Chips(),
                                 verdicts={person.id: "no"}))
        self.assertEqual(fuse.call_args.args[-1], {person.id: "no"})


def placed(need: str = "must", kind: str | None = None, version: int = 2, area: GeoArea | None = BOSTON,
           country: str | None = "US") -> Question:
    """A question over ASK's topic with a place chip of the given need and kind."""
    place = Place(text="Boston", origin="edited", need=need, kind=kind)
    return Question(chips=Chips(topics=ASK.chips.topics, place=place, version=version), area=area, country=country)


class AsideTest(unittest.TestCase):
    HERE = dict(fit="inside", km=5.0, countries=("US",), only_openalex=False, job="known")
    AWAY = dict(fit="outside", km=900.0, countries=("US",), only_openalex=False, job="known")
    FAR = dict(countries=("BE",), only_openalex=False, job="known")
    NOWHERE = dict(only_openalex=False, job="known")

    def fused(self, ask: Question, verdicts: dict | None = None, statuses: dict | None = None, **people) -> list:
        entries = [hit_entry(k, openalex=n) for n, k in enumerate(people, 1)]
        return rank.fuse("s", entries, statuses or {}, None, people, ask, verdicts)

    def test_a_must_place_sets_an_outside_person_aside_after_every_open_person_and_a_nice_place_keeps_them(self):
        """Outside a must area the best-scored person is kept in tier 2, set aside and last; a nice place keeps them open."""
        people = dict(away=found(**self.AWAY), tie5=found(match=False, only_openalex=False), here=found(**self.HERE))
        out = self.fused(placed("must"), **people)
        self.assertEqual([(c.person_id, c.tier, c.aside, c.cut_reason) for c in out],
                         [("here", 1, None, None), ("tie5", 5, None, None), ("away", 2, "outside", None)])
        out = self.fused(placed("nice"), **people)
        self.assertEqual([(c.person_id, c.tier, c.aside) for c in out],
                         [("here", 1, None), ("away", 2, None), ("tie5", 5, None)])

    def test_a_place_without_a_need_is_a_wish(self):
        """A place chip stored without need reads as nice: an outside person stays open in tier 2."""
        ask = Question(chips=Chips(topics=ASK.chips.topics, place=Place(text="Boston", origin="edited"), version=2),
                       area=BOSTON, country="US")
        (c,) = self.fused(ask, away=found(**self.AWAY))
        self.assertEqual((c.tier, c.aside), (2, None))

    def test_abroad_under_a_nice_us_place_is_set_aside(self):
        """A person placed only in Belgium under a wished US place stands aside as abroad."""
        (c,) = self.fused(placed("nice"), far=found(**self.FAR))
        self.assertEqual((c.aside, c.cut_reason), ("abroad", None))

    def test_a_place_of_kind_abroad_sets_nobody_aside(self):
        """A place abroad gives the question no country, so nobody is abroad or outside it."""
        out = self.fused(placed("must", "abroad", area=None, country=None), far=found(**self.FAR),
                         home=found(countries=("US",), only_openalex=False, job="known"))
        self.assertEqual({c.aside for c in out}, {None})

    def test_a_must_anywhere_us_place_sets_abroad_aside_and_keeps_an_unknown_place_open_in_tier_2(self):
        """Under a required US a person in Belgium is abroad, one in the US is tier 1 and one without a place tier 2."""
        out = self.fused(placed("must", "anywhere_us", area=None), far=found(**self.FAR),
                         home=found(countries=("US",), only_openalex=False, job="known"), unknown=found(**self.NOWHERE))
        self.assertEqual({c.person_id: (c.tier, c.aside) for c in out},
                         {"far": (2, "abroad"), "home": (1, None), "unknown": (2, None)})

    def test_a_must_place_that_was_not_located_sets_nobody_aside(self):
        """Without an area or a country nobody is known to be outside, so nobody stands aside."""
        out = self.fused(placed("must", area=None, country=None), far=found(**self.FAR), here=found(**self.NOWHERE))
        self.assertEqual({c.aside for c in out}, {None})

    def test_no_entries_give_no_candidates(self):
        """An empty lane result ranks to an empty list under a must place."""
        self.assertEqual(rank.fuse("s", [], {}, None, {}, placed("must")), [])

    def test_outside_wins_over_a_no_verdict(self):
        """A person outside a must area whom the fit check said no to stands aside as outside."""
        (c,) = self.fused(placed("must"), {"away": "no"}, away=found(**self.AWAY))
        self.assertEqual(c.aside, "outside")

    def test_an_exempted_openalex_person_outside_a_must_area_is_kept_and_set_aside(self):
        """A topic expert without Belgian evidence comes back by the exemption and then stands aside as outside."""
        (c,) = self.fused(placed("must"), oa=found(kinds=(), years=0, last=None, fit="outside", km=900.0, countries=("US",)))
        self.assertEqual((c.cut_reason, c.aside), (None, "outside"))

    def test_a_network_person_outside_a_must_area_is_never_set_aside(self):
        """The network section stays open whatever the place."""
        (c,) = self.fused(placed("must"), statuses={"away": "in_list"}, away=found(**self.AWAY))
        self.assertEqual((c.section, c.aside, c.cut_reason), ("network", None, None))

    def test_version_1_chips_with_a_must_place_set_nobody_aside_and_keep_the_unknown_place_in_tier_1(self):
        """Stored version-1 chips never read the place's need."""
        out = self.fused(placed("must", version=1), {"away": "no"}, away=found(**self.AWAY), unknown=found(**self.NOWHERE))
        self.assertEqual({c.person_id: (c.tier, c.aside) for c in out}, {"away": (2, None), "unknown": (1, None)})

    def test_a_must_place_puts_an_unknown_place_in_tier_2_behind_a_worse_scored_inside_person(self):
        """An unknown place does not fit a required area."""
        out = self.fused(placed("must"), unknown=found(**self.NOWHERE), inside=found(**self.HERE))
        self.assertEqual([(c.person_id, c.tier) for c in out], [("inside", 1), ("unknown", 2)])

    def test_in_tier_5_a_must_place_puts_inside_before_unknown_despite_a_weaker_role(self):
        """Under a must place the spot follows the heading; under a nice place the role still leads."""
        people = dict(unknown=found(only_openalex=False), inside=found(match=False, fit="inside", km=5.0, countries=("US",),
                                                                        only_openalex=False))
        out = self.fused(placed("must"), **people)
        self.assertEqual([(c.person_id, c.tier) for c in out], [("inside", 5), ("unknown", 5)])
        self.assertEqual([c.person_id for c in self.fused(placed("nice"), **people)], ["unknown", "inside"])

    def test_a_nice_place_puts_an_inside_medium_tie_before_an_unknown_strong_tie_and_version_1_the_reverse(self):
        """On version 2 the place spot precedes the tie grade; version 1 keeps the tie grade first."""
        people = dict(strong=found(**self.NOWHERE), medium=found(grade="medium", **self.HERE))
        self.assertEqual([c.person_id for c in self.fused(placed("nice"), **people)], ["medium", "strong"])
        self.assertEqual([c.person_id for c in self.fused(placed("nice", version=1), **people)], ["strong", "medium"])

    def test_a_no_verdict_sets_a_person_aside_as_unfit_on_version_2_only(self):
        """The fit check's no sets aside on version-2 chips; version 1 ignores it."""
        (c,) = self.fused(v2(), {"nope": "no"}, nope=found(**self.HERE))
        self.assertEqual(c.aside, "unfit")
        (c,) = self.fused(ASK, {"nope": "no"}, nope=found(**self.HERE))
        self.assertIsNone(c.aside)

    def test_60_people_in_tiers_1_5_and_7_lose_0_10_and_10_over_the_cap(self):
        """Headings 3 and 4 keep HEADING_CAP people each; heading 1 and version-1 chips keep everyone."""
        people = {f"t{t}-{k:02d}": ev for t, ev in ((1, found(**self.HERE)), (5, found(match=False, only_openalex=False)),
                                                    (7, found(role="fails", **self.HERE))) for k in range(60)}
        out = self.fused(v2(), **people)
        cut = Counter(c.person_id[:2] for c in out if c.cut_reason == "over_cap")
        self.assertEqual((cut["t1"], cut["t5"], cut["t7"]), (0, 10, 10))
        self.assertEqual({c.cut_reason for c in self.fused(ASK, **people)}, {None})

    def test_120_people_under_heading_4_keep_50(self):
        """Past the first 50 of heading 4 everyone is cut over_cap, in rank order."""
        out = self.fused(v2(), **{f"p{k:03d}": found(role="fails", **self.HERE) for k in range(120)})
        self.assertEqual([c.person_id for c in out if c.cut_reason is None], [f"p{k:03d}" for k in range(50)])
        self.assertEqual(sum(1 for c in out if c.cut_reason == "over_cap"), 70)

    def test_openalex_only_people_never_pass_an_aside_row(self):
        """Moving the sixth OpenAlex-only person to the end of its heading stops before the people set aside."""
        people = {f"a{k}": found(**self.AWAY) for k in range(3)}
        people |= {f"p{k:02d}": found(fit="inside", km=5.0, countries=("US",), job="known", only_openalex=k in range(2, 10))
                   for k in range(30)}
        entries = [hit_entry(key, seeds=1, openalex=2) for key in people]
        out = rank.fuse("s", entries, {}, None, people, placed("must"))
        self.assertEqual([c.person_id for c in out[-3:]], ["a0", "a1", "a2"])
        self.assertEqual({c.aside for c in out[-3:]}, {"outside"})
        self.assertEqual({c.aside for c in out[:-3]}, {None})


def aged(ev: evidence.Evidence, *claims: Claim, **age) -> evidence.Evidence:
    """The evidence with the age its claims give as of 17 November 2026, else the age fields given."""
    return dataclasses.replace(ev, age=evidence.age(list(claims), date(2026, 11, 17)) if claims else evidence.Age(**age))


def fact(claim_id: str, kind: str, relation: str | None = None, stamp: str | None = None, method: str = "record_field",
         years: tuple[int, ...] = ()) -> Claim:
    return Claim(id=claim_id, person_id="p1", kind=kind, relation=relation, value="Professor", quote="q", quote_start=0,
                 quote_end=1, source_id="src", claim_date=stamp, date_method=method if stamp else None, years=list(years))


OLD = dict(first=1958, back=68)


class AgeOrderTest(unittest.TestCase):
    HERE, NOWHERE, AWAY = AsideTest.HERE, AsideTest.NOWHERE, AsideTest.AWAY
    fused = AsideTest.fused

    def order(self, ask: Question, **people) -> list[str]:
        return [c.person_id for c in self.fused(ask, **people)]

    def test_a_dead_tier_1_person_is_cut_as_died_and_on_version_1_keeps_tier_1(self):
        """A death cuts the person as died with no aside and their tier; version-1 chips leave them open."""
        people = dict(dead=aged(found(**self.HERE), died="d1"), nope=found(**self.HERE), open=found(**self.HERE))
        out = self.fused(v2(), {"nope": "no", "dead": "yes", "open": "yes"}, **people)
        kept = [(c.person_id, c.aside) for c in out if not c.cut_reason]
        self.assertEqual(kept, [("open", None), ("nope", "unfit")])
        dead = next(c for c in out if c.person_id == "dead")
        self.assertEqual((dead.cut_reason, dead.aside, dead.tier), ("died", None, 1))
        alive = {k: v for k, v in people.items() if k != "dead"}
        again = self.fused(v2(), {"nope": "no", "open": "yes"}, **alive)
        self.assertEqual([(c.person_id, c.rank, c.aside) for c in out if not c.cut_reason],
                         [(c.person_id, c.rank, c.aside) for c in again])
        dead = self.fused(ASK, **people)[0]
        self.assertEqual((dead.person_id, dead.tier, dead.aside, dead.cut_reason), ("dead", 1, None, None))

    def test_a_dead_person_outside_a_must_area_is_cut_as_died_and_a_dead_network_person_stays_open(self):
        """A dead person outside a required area is cut as died; the network section is never cut or set aside."""
        (c,) = self.fused(placed("must"), away=aged(found(**self.AWAY), died="d1"))
        self.assertEqual((c.cut_reason, c.aside), ("died", None))
        (c,) = self.fused(placed("must"), statuses={"dead": "in_list"}, dead=aged(found(**self.HERE), died="d1"))
        self.assertEqual((c.section, c.aside, c.cut_reason), ("network", None, None))

    def test_a_dead_person_with_a_weak_tie_under_a_required_tie_stays_cut_as_no_tie(self):
        """Another cut reason wins over died."""
        weak = aged(found(kinds=("belgian_text",), grade="weak", only_openalex=False), died="d1")
        (c,) = self.fused(v2("must"), weak=weak)
        self.assertEqual(c.cut_reason, "no_tie")

    def test_a_dead_exempted_openalex_person_is_cut_as_died(self):
        """The exemption brings back a topic expert without Belgian evidence, and the death then cuts them."""
        dead = aged(found(kinds=(), years=0, last=None, fit="inside", km=5.0, countries=("US",)), died="d1")
        (c,) = self.fused(placed("must"), oa=dead)
        self.assertEqual((c.cut_reason, c.aside), ("died", None))

    def test_a_dead_person_among_fifty_tied_tier_6_people_is_the_only_one_cut(self):
        """Fifty tied tier-6 people fill the cap; the dead one is cut as died and no living one is cut."""
        tied6 = found(match=False, words=(), only_openalex=False)
        out = self.fused(v2(), dead=aged(tied6, died="d1"), **{f"t{k:02d}": tied6 for k in range(50)})
        self.assertEqual([(c.person_id, c.cut_reason) for c in out if c.cut_reason], [("dead", "died")])

    def test_under_a_required_place_an_old_tier_1_person_follows_tier_2_and_precedes_heading_2(self):
        """An old first record with nothing recent goes last under its heading, not below it."""
        people = dict(old=aged(found(**self.HERE), **OLD), unknown=found(**self.NOWHERE),
                      heading2=found(kinds=(), fit="inside", km=5.0, countries=("US",), only_openalex=False, job="known"))
        out = self.fused(placed("must"), **people)
        self.assertEqual([(c.person_id, c.tier) for c in out], [("unknown", 2), ("old", 1), ("heading2", 3)])

    def test_an_old_tier_5_person_follows_tier_6_with_a_tie_precedes_heading_4_and_counts_in_heading_3_s_cap(self):
        """Tier 6 with a tie closes heading 3, so an old tier-5 person stands after it and is the 51st there."""
        old5 = aged(found(match=False, only_openalex=False), **OLD)
        tied6, none6 = found(match=False, words=(), only_openalex=False), found(match=False, kinds=(), only_openalex=False)
        self.assertEqual(self.order(v2(), old5=old5, tied6=tied6, none6=none6), ["tied6", "old5", "none6"])
        out = self.fused(v2(), old5=old5, **{f"t{k:02d}": tied6 for k in range(50)})
        self.assertEqual([(c.person_id, c.cut_reason) for c in out if c.cut_reason], [("old5", "over_cap")])

    def test_a_professor_with_a_1958_degree_and_a_2025_role_stays_and_without_the_role_moves(self):
        """A role the source dates in 2025 makes an old first record recent and current."""
        degree = fact("c1", "affiliation", "studied_at", "1958")
        role = fact("c2", "role", stamp="2025-10-01")
        other = found(**self.HERE)
        self.assertEqual(self.order(v2(), prof=aged(found(**self.HERE), degree, role), other=other), ["prof", "other"])
        self.assertEqual(self.order(v2(), prof=aged(found(**self.HERE), degree), other=other), ["other", "prof"])

    def test_an_emeritus_person_follows_a_lower_scored_active_one(self):
        """Inside a tier a retired-looking person stands after the active people."""
        self.assertEqual(self.order(v2(), emeritus=aged(found(**self.HERE), emeritus=True), active=found(**self.HERE)),
                         ["active", "emeritus"])

    def test_46_years_back_with_two_openalex_years_since_2021_stays_and_with_a_read_date_role_alone_moves(self):
        """Two recent OpenAlex years make a 1980 first record current; a role dated when FN read the page does not."""
        busy = aged(found(**self.HERE), fact("c1", "affiliation", "affiliated_with", years=(1980, 2022, 2024)))
        read = aged(found(**self.HERE), fact("c1", "affiliation", "affiliated_with", years=(1980,)),
                    fact("c2", "role", stamp="2026-11-16", method="read_date"))
        other = found(**self.HERE)
        self.assertEqual(self.order(v2(), busy=busy, other=other), ["busy", "other"])
        self.assertEqual(self.order(v2(), read=read, other=other), ["other", "read"])

    def test_version_1_chips_keep_their_order(self):
        """Old, retired-looking and dead people keep their score order on version-1 chips."""
        people = dict(old=aged(found(**self.HERE), **OLD), emeritus=aged(found(**self.HERE), emeritus=True),
                      dead=aged(found(**self.HERE), died="d1"), plain=found(**self.HERE))
        self.assertEqual(self.order(placed("must", version=1), **people), ["old", "emeritus", "dead", "plain"])


if __name__ == "__main__":
    unittest.main()
