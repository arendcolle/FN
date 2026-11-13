import logging
import unittest
from datetime import UTC, date, datetime
from unittest import mock

from fn import identity, network, present, resolve
from fn.contracts import (
    Candidate,
    ClaimDraft,
    Identifier,
    LaneHit,
    LaneOut,
    ResolveIn,
    Search,
    Source,
)
from fn.steps import StepContext
from fn.worker import new_id, now
from tests.helpers import make_db, make_settings

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def hit(person_id: str, name_key: str, rank: int = 1, lane: str = "openalex") -> LaneHit:
    return LaneHit(person_id=person_id, name_key=name_key, lane=lane, rank=rank, score=1.0, matched_on="x",
                   claim_ids=[])


class KeyTest(unittest.TestCase):
    def test_key_keeps_the_first_name_and_the_surname_from_its_first_particle(self):
        """A trailing letter goes from three tokens up, particles join the surname, other given names go."""
        for name, key in (("Nick M. Vandewiele", "nick vandewiele"), ("Pierre F.J. Lermusiaux", "pierre lermusiaux"),
                          ("A. Kumar", "a kumar"), ("J. C. de Wit", "j dewit"), ("Kumar A", "kumar a"), ("", ""),
                          ("Lena Marie Peeters Q", "lena peeters"), ("Jan Van de Wiele", "jan vandewiele"),
                          ("Jan Vandewiele", "jan vandewiele"), ("Karel de Groot-Smit", "karel degrootsmit"),
                          ("Maria Anna Peeters", "maria peeters"), ("Ana", "ana")):
            with self.subTest(name=name):
                self.assertEqual(identity.key(name), key)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.n = 0

    def person(self, name: str, *idents: tuple[str, str]) -> str:
        self.n += 1
        idents = idents or (("openalex", f"A{self.n}"),)
        return self.store.resolve_person([Identifier(scheme=s, value=v) for s, v in idents], name).id

    def claim(self, person_id: str, org_id: str | None = None, kind: str = "affiliation", value: str = "Example Lab",
              **fields) -> None:
        self.n += 1
        text = f"{value} {self.n}"
        source = Source(id=f"src-{self.n}", kind="page", url=f"https://example.org/{self.n}", text=text,
                        content_hash=f"h-{self.n}")
        self.store.upsert_claim(ClaimDraft(person_id=person_id, kind=kind, org_id=org_id, value=value, quote=text,
                                           quote_start=0, quote_end=len(text), source=source, **fields), at=T0)

    def common(self, name: str = "Ann Example", count: int = 4) -> None:
        """Enough other records with the name to make it common."""
        for _ in range(count):
            self.person(name)

    def level(self, a: str, b: str) -> tuple[str, str]:
        return identity.same_person(self.store, a, b)


class LevelTest(StoreTest):
    def test_one_record_and_a_staff_merge_are_sure(self):
        """A record is sure with itself, and two records a staff merge joined are sure, whatever they hold."""
        ann, twin = self.person("Ann Example", ("orcid", "0000-0001")), self.person("Ann Example", ("orcid", "0000-0002"))
        self.assertEqual(self.level(ann, ann), ("sure", "merged"))
        network.merge(self.store, [twin], ann, now=T0)
        self.assertEqual(self.level(ann, twin), ("sure", "merged"))

    def test_each_veto_says_no_before_any_backer(self):
        """A not-same decision, two ORCIDs, two profile links and contradicting middle names each say no,
        even when the two share a small organization and the name is rare."""
        cases = {
            "not_same": (("Ann Example",), ("Ann Example",)),
            "orcid": (("Ann Example", ("orcid", "0000-0001")), ("Ann Example", ("orcid", "0000-0002"))),
            "profile_url": (("Ann Example", ("profile_url", "https://example.org/a")),
                            ("Ann Example", ("profile_url", "https://example.org/b"))),
            "middle": (("Ann B. Example",), ("Ann C. Example",)),
        }
        for word, (first, second) in cases.items():
            with self.subTest(word=word):
                self.store = make_db(self)
                a, b = self.person(*first), self.person(*second)
                self.claim(a, "org:lab"), self.claim(b, "org:lab")
                if word == "not_same":
                    network.not_same(self.store, a, b, now=T0)
                self.assertEqual(self.level(a, b), ("no", word))

    def test_a_middle_name_that_fits_the_other_is_no_veto(self):
        """One name's middle initials inside the other's, or one name without a middle, is no veto."""
        a, b, c = self.person("Ann B. Example"), self.person("Ann Beth C. Example"), self.person("Ann Example")
        for p in (a, b, c):
            self.claim(p, "org:lab")
        self.assertEqual(self.level(a, b), ("likely", "shared_org"))
        self.assertEqual(self.level(a, c), ("likely", "shared_org"))

    def test_different_keys_say_no_and_an_initial_stays_possible(self):
        """Two names with different keys are not compared; two with one key and a one-letter first name are
        possible, even when they share a small organization and nobody else holds the name."""
        self.assertEqual(self.level(self.person("Ann Example"), self.person("Bea Example")), ("no", "name"))
        a, b = self.person("A. Example"), self.person("A Example")
        self.claim(a, "org:lab"), self.claim(b, "org:lab")
        self.assertEqual(self.level(a, b), ("possible", "initial"))

    def test_each_likely_backer(self):
        """A shared small organization, two rows of one seed list a year apart, or a rare name at a shared large
        organization when one of the two is a list row each make likely."""
        self.common()
        a, b = self.person("Ann Example"), self.person("Ann Example")
        self.claim(a, "org:lab"), self.claim(b, "org:lab")
        self.assertEqual(self.level(a, b), ("likely", "shared_org"))
        c = self.person("Ann Example", ("seed", "baef|ann-example|2018|"))
        d = self.person("Ann Example", ("seed", "baef|ann-example|2019|"))
        self.assertEqual(self.level(c, d), ("likely", "same_seed_row"))
        e, f = self.person("Bea Example", ("seed", "kvab|bea-example||")), self.person("Bea Example")
        self.claim(e, "org:university"), self.claim(f, "org:university")
        with mock.patch.object(identity, "BIG_ORG", 2):
            self.assertEqual(self.level(e, f), ("likely", "rare_name_org"))

    def test_two_full_profiles_with_a_rare_name_at_a_large_organization_are_possible(self):
        """Two author profiles are each a person's own record: a rare name at one large organization does not join them."""
        a, b = self.person("Bea Example"), self.person("Bea Example")
        self.claim(a, "org:university"), self.claim(b, "org:university")
        with mock.patch.object(identity, "BIG_ORG", 2):
            self.assertEqual(self.level(a, b), ("possible", "name_only"))

    def test_a_rare_name_without_a_shared_organization_is_possible(self):
        """A name no other record holds backs nothing alone: without a shared organization the pair stays possible."""
        a, b = self.person("Bea Example"), self.person("Bea Example")
        self.claim(a, "org:lab"), self.claim(b, "org:other")
        self.assertEqual(self.level(a, b), ("possible", "name_only"))

    def test_a_rare_name_with_a_web_mention_is_likely_and_a_common_one_is_possible(self):
        """A record that is only a web mention has no organization to share, so a rare name backs it alone; once
        the name is common the pair stays possible."""
        a = self.person("Bea Example")
        b = self.person("Bea Example", ("mention", "https://example.org/page#bea"))
        self.assertEqual(self.level(a, b), ("likely", "rare_name_mention"))
        self.common("Bea Example", count=3)
        self.assertEqual(self.level(a, b), ("possible", "name_only"))

    def test_two_seed_rows_more_than_ten_years_apart_are_possible(self):
        """Two rows of one seed list 11 years apart are not one row; ten years apart still are."""
        self.common()
        a = self.person("Ann Example", ("seed", "baef|ann-example|2000|"))
        b = self.person("Ann Example", ("seed", "baef|ann-example|2011|"))
        c = self.person("Ann Example", ("seed", "baef|ann-example|2010|"))
        self.assertEqual(self.level(a, b), ("possible", "name_only"))
        self.assertEqual(self.level(a, c), ("likely", "same_seed_row"))

    def test_two_seed_rows_decades_apart_stay_possible_with_the_lists_organization(self):
        """Rows of one seed list more than ten years apart are possible even with a rare name, although both
        hold the list's own organization."""
        a = self.person("Bea Example", ("seed", "baef|bea-example|1951|"))
        b = self.person("Bea Example", ("seed", "baef|bea-example|2001|"))
        self.claim(a, "org:fund", kind="role"), self.claim(b, "org:fund", kind="role")
        self.assertEqual(self.level(a, b), ("possible", "name_only"))

    def test_seed_rows_that_differ_in_more_than_the_year_are_not_one_row(self):
        """Two rows of one list with another last part, or of two lists, back nothing; a common name stays possible."""
        self.common()
        a = self.person("Ann Example", ("seed", "kvab|ann-example|2010|arts"))
        b = self.person("Ann Example", ("seed", "kvab|ann-example|2012|sciences"))
        c = self.person("Ann Example", ("seed", "fayat|ann-example|2010|arts"))
        self.assertEqual(self.level(a, b), ("possible", "name_only"))
        self.assertEqual(self.level(a, c), ("possible", "name_only"))

    def test_a_common_name_sharing_only_a_large_organization_is_possible(self):
        """An organization held by BIG_ORG records or more backs nothing, so a common name there stays possible."""
        self.common()
        a, b, c = self.person("Ann Example"), self.person("Ann Example"), self.person("Cas Other")
        for p in (a, b, c):
            self.claim(p, "org:university")
        with mock.patch.object(identity, "BIG_ORG", 3):
            self.assertEqual(self.level(a, b), ("possible", "name_only"))
        self.assertEqual(self.level(a, b), ("likely", "shared_org"))

    def test_web_mentions_do_not_count_toward_rarity(self):
        """Records whose only identifier is a web mention leave a name rare; four real records make it common."""
        a, b = self.person("Ann Example", ("seed", "kvab|ann-example||")), self.person("Ann Example")
        self.claim(a, "org:university"), self.claim(b, "org:university")
        for n in range(3):
            self.person("Ann Example", ("mention", f"https://example.org/{n}#ann"))
        with mock.patch.object(identity, "BIG_ORG", 2):
            self.assertEqual(self.level(a, b), ("likely", "rare_name_org"))
            self.common(count=3)
            self.assertEqual(self.level(a, b), ("possible", "name_only"))

    def test_seed_rows_do_not_count_toward_rarity(self):
        """A person on four seed lists is still one rare name: seed rows prove no namesake."""
        a, b = self.person("Ann Example", ("seed", "one|ann-example|2001|")), self.person("Ann Example", ("seed", "two|ann-example||"))
        self.claim(a, "org:university"), self.claim(b, "org:university")
        for n in range(3):
            self.person("Ann Example", ("seed", f"list{n}|ann-example||"))
        with mock.patch.object(identity, "BIG_ORG", 2):
            self.assertEqual(self.level(a, b), ("likely", "rare_name_org"))
            self.common(count=4)
            self.assertEqual(self.level(a, b), ("possible", "name_only"))


class ResolveTest(StoreTest):
    def entries(self, *hits: LaneHit) -> list:
        ctx = StepContext(search_id="s", store=self.store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=self.settings)
        return resolve.run(ctx, ResolveIn(outs=[LaneOut(lane="openalex", query="q", total_seen=len(hits),
                                                        hits=list(hits))])).entries

    def test_two_initial_only_hits_give_two_entries(self):
        """Two hits whose first name is one letter are only possible, so each gets its own entry."""
        a, b = self.person("J. Example"), self.person("J. Example")
        found = self.entries(hit(a, "j example", 1), hit(b, "j example", 2))
        self.assertEqual([e.card_person_ids for e in found], [[a], [b]])

    def test_a_stored_likely_record_joins_the_card_and_a_possible_one_does_not(self):
        """With a common name, the stored record sharing a small organization goes on the card; the others stay
        in person_ids only."""
        hit_id, likely = self.person("Ann Example"), self.person("Ann Example")
        self.claim(hit_id, "org:lab"), self.claim(likely, "org:lab")
        others = [self.person("Ann Example") for _ in range(3)]
        (entry,) = self.entries(hit(hit_id, "ann example"))
        self.assertEqual(entry.card_person_ids, [hit_id, likely])
        self.assertCountEqual(entry.person_ids, [hit_id, likely, *others])

    def test_a_veto_between_two_records_linked_through_a_third_gives_two_cards(self):
        """A fits B and B fits C, but A and C hold different ORCIDs, so C starts a second card."""
        a = self.person("Ann Example", ("orcid", "0000-0001"))
        b = self.person("Ann Example")
        c = self.person("Ann Example", ("orcid", "0000-0002"))
        for p in (a, b, c):
            self.claim(p, "org:lab")
        found = self.entries(hit(a, "ann example", 1), hit(b, "ann example", 2), hit(c, "ann example", 3))
        self.assertEqual([e.card_person_ids for e in found], [[a, b], [c]])

    def test_a_network_person_likely_with_a_hit_stays_off_its_card(self):
        """A stored record of a network person is linked only by sure: a hit sharing its organization keeps its own
        card."""
        member, other = self.person("Ann Example"), self.person("Ann Example")
        self.claim(member, "org:lab"), self.claim(other, "org:lab")
        network.add(self.store, [member], via="import", now=T0)
        (entry,) = self.entries(hit(other, "ann example"))
        self.assertEqual((entry.card_person_ids, entry.person_ids), ([other], [other, member]))


class AddTest(StoreTest):
    def merged_into(self, *person_ids: str) -> list[str | None]:
        found = self.store.get_persons(list(person_ids))
        return [found[p].merged_into for p in person_ids]

    def test_add_merges_two_rows_of_one_seed_list(self):
        """Two rows of one seed list a year apart merge on Add, also when the name is common."""
        self.common()
        a = self.person("Ann Example", ("seed", "baef|ann-example|2018|"))
        b = self.person("Ann Example", ("seed", "baef|ann-example|2019|"))
        event = network.add(self.store, [a, b], via="search", now=T0)
        self.assertEqual((event.detail["merged"], event.detail["left_apart"]), ([b], []))

    def test_add_merges_two_openalex_ids_and_leaves_another_orcid_apart_and_undo_restores_them(self):
        """Two OpenAlex ids with a rare name at a shared organization merge; a record with another ORCID stays apart;
        undo restores every row."""
        a = self.person("Ann Example", ("openalex", "A1"), ("orcid", "0000-0001"))
        b = self.person("Ann Example", ("openalex", "A2"))
        c = self.person("Ann Example", ("openalex", "A3"), ("orcid", "0000-0002"))
        for p in (a, b, c):
            self.claim(p, "org:lab")
        event = network.add(self.store, [a, b, c], via="search", now=T0)
        self.assertEqual((event.detail["merged"], event.detail["left_apart"]), ([b], [c]))
        self.assertEqual(self.merged_into(a, b, c), [None, a, None])
        network.undo(self.store, event.id, now=T0)
        self.assertEqual(self.merged_into(a, b, c), [None, None, None])


class OnCardTest(StoreTest):
    def candidate(self, hits: list[str], card: list[str], person_ids: list[str] | None = None) -> Candidate:
        person_ids = person_ids or hits or card
        return Candidate(search_id="s", person_id=person_ids[0], person_ids=person_ids, section="new", rank=1,
                         score=1.0, lane_ranks={"openalex": 1}, hit_person_ids=hits, card_person_ids=card)

    def test_on_card_drops_a_record_after_a_not_same_decision(self):
        """A not-same decision made after the search was stored takes that record off the card."""
        a, b, c = self.person("Ann Example"), self.person("Ann Example"), self.person("Ann Example")
        found = self.candidate([a], [a, b, c])
        self.assertEqual(identity.on_card(self.store, found), [a, b, c])
        network.not_same(self.store, a, c, now=T0)
        self.assertEqual(identity.on_card(self.store, found), [a, b])

    def test_an_old_row_reads_its_hit_records_else_its_first_record(self):
        """A candidate stored without card records reads the hit records, and without those its first record."""
        a, b, c = self.person("Ann Example"), self.person("Ann Example"), self.person("Ann Example")
        self.assertEqual(identity.on_card(self.store, self.candidate([a, b], [], [a, b, c])), [a, b])
        self.assertEqual(identity.on_card(self.store, self.candidate([], [], [c, a])), [c])

    def test_a_card_shows_a_place_only_its_likely_record_holds(self):
        """The card reads every record on it, so a place held by the likely record shows on the hit's card."""
        a, b = self.person("Ann Example"), self.person("Ann Example")
        self.claim(b, kind="location", value="Gent", relation="lives_in", lat=51.05, lon=3.72)
        search = Search(id="s", question="q", status="done", created_at=now(), code_sha=None, dirty=False,
                        llm_mode="replay", settings_json="{}", boot_id="b")
        view = present.card(self.store, search, self.candidate([a], [a, b]), date(2026, 11, 12))
        self.assertEqual(view.person.place, "Gent")


if __name__ == "__main__":
    unittest.main()
