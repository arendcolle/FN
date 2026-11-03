import logging
import unittest

from fn import resolve
from fn.contracts import LaneHit, LaneOut, ResolveIn
from fn.steps import StepContext
from fn.worker import new_id, now
from tests.helpers import make_seeded_db, make_settings


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
        self.assertEqual(entry.flag, "same name in 2 records, not merged")
        self.assertEqual([(f.person_id, f.other_person_id, f.reason) for f in out.flags],
                         [(ids[1], ids[0], resolve.SAME_NAME)])


if __name__ == "__main__":
    unittest.main()
