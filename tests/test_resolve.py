import logging
import unittest
from datetime import UTC, datetime

from fn import network, resolve
from fn.contracts import Identifier, LaneHit, LaneOut, ResolveIn
from fn.steps import StepContext
from fn.worker import new_id, now
from tests.helpers import make_db, make_seeded_db, make_settings

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def hit(person_id: str, name_key: str, rank: int, lane: str = "seeds") -> LaneHit:
    return LaneHit(person_id=person_id, name_key=name_key, lane=lane, rank=rank, score=1.0, matched_on="x",
                   claim_ids=[f"c-{person_id}"])


class ResolveTest(unittest.TestCase):
    def test_one_entry_per_person_across_lanes(self):
        """A person hit by two lanes is one entry with each lane's best rank and both lanes' claims."""
        out = resolve.group([LaneOut(lane="seeds", query="q", total_seen=1, hits=[hit("p1", "anne", 3)]),
                             LaneOut(lane="openalex", query="q", total_seen=2,
                                     hits=[hit("p1", "anne", 1, "openalex"), hit("p2", "bob", 2, "openalex")])], {})
        self.assertEqual([(e.name_key, e.person_ids, e.lane_ranks, e.flag) for e in out.entries],
                         [("anne", ["p1"], {"seeds": 3, "openalex": 1}, None), ("bob", ["p2"], {"openalex": 2}, None)])
        self.assertEqual(out.entries[0].claim_ids, ["c-p1"])
        self.assertEqual(out.flags, [])

    def test_two_seed_rows_with_one_name_stay_two_persons_in_one_flagged_entry(self):
        """Both Jakob Cassiman rows stay separate persons; a hit on one gives one entry holding both, flagged."""
        settings = make_settings(self)
        store = make_seeded_db(self, settings)
        ids = [store.conn.execute("SELECT person_id FROM person_identifiers WHERE value = ?", (key,)).fetchone()[0]
               for key in ("baef|jakob-cassiman|2019|", "baef|jakob-cassiman|2018|")]
        self.assertNotEqual(*ids)
        ctx = StepContext(search_id="s", store=store, llm=None, http=None, now=now, new_id=new_id,
                          log=logging.getLogger("fn.step"), settings=settings)
        out = resolve.run(ctx, ResolveIn(outs=[LaneOut(lane="seeds", query="q", total_seen=1,
                                                       hits=[hit(ids[1], "jakob cassiman", 1)])]))
        (entry,) = out.entries
        self.assertEqual((entry.person_ids, entry.lane_ranks), ([ids[1], ids[0]], {"seeds": 1}))
        self.assertEqual(entry.card_person_ids, [ids[1], ids[0]])
        self.assertEqual(entry.flag, "same name in 2 records, not merged")
        self.assertEqual([(f.person_id, f.other_person_id, f.reason) for f in out.flags],
                         [(ids[1], ids[0], resolve.SAME_NAME)])


class StoredDecisionsTest(unittest.TestCase):
    def setUp(self):
        settings = make_settings(self)
        self.store = make_db(self, settings)
        self.ctx = StepContext(search_id="s", store=self.store, llm=None, http=None, now=now, new_id=new_id,
                               log=logging.getLogger("fn.step"), settings=settings)

    def person(self, *idents: tuple[str, str]) -> str:
        return self.store.resolve_person([Identifier(scheme=s, value=v) for s, v in idents], "Ann Example").id

    def entries(self, *hits: LaneHit) -> list:
        lanes = {}
        for h in hits:
            lanes.setdefault(h.lane, []).append(h)
        outs = [LaneOut(lane=lane, query="q", total_seen=len(found), hits=found) for lane, found in lanes.items()]
        return resolve.run(self.ctx, ResolveIn(outs=outs)).entries

    def test_two_hit_records_of_one_merged_person_are_one_person(self):
        """Hits on two records of one merged person give one entry with the canonical id as its one hit.

        The entry keeps both lanes' ranks and shows no "not merged" flag.
        """
        ann, twin = self.person(("seed", "ann")), self.person(("openalex", "A1"))
        network.merge(self.store, [twin], ann, now=T0)
        (entry,) = self.entries(hit(ann, "ann example", 2), hit(twin, "ann example", 1, "openalex"))
        self.assertEqual((entry.person_ids, entry.hit_person_ids, entry.flag), ([ann], [ann], None))
        self.assertEqual(entry.lane_ranks, {"seeds": 2, "openalex": 1})

    def test_a_not_same_pair_gives_two_entries(self):
        """Two persons staff declared different go on separate cards, each with its own hit."""
        ann, other = self.person(("seed", "ann")), self.person(("openalex", "A1"))
        network.not_same(self.store, ann, other, now=T0)
        found = self.entries(hit(ann, "ann example", 1), hit(other, "ann example", 1, "openalex"))
        self.assertEqual([(e.person_ids, e.hit_person_ids, e.name_key) for e in found],
                         [([ann], [ann], "ann example"), ([other], [other], "ann example")])

    def test_different_orcids_give_two_entries_and_a_shared_one_does_not(self):
        """Persons holding different ORCIDs are two people; an unhit same-name record joins the card it fits."""
        one = self.person(("openalex", "A1"), ("orcid", "0000-0001"))
        two = self.person(("openalex", "A2"), ("orcid", "0000-0002"))
        loose = self.person(("seed", "ann"))
        found = self.entries(hit(one, "ann example", 1, "openalex"), hit(two, "ann example", 2, "openalex"))
        self.assertEqual([e.person_ids for e in found], [[one, loose], [two]])
        self.assertEqual([e.hit_person_ids for e in found], [[one], [two]])


if __name__ == "__main__":
    unittest.main()
