import unittest

from fn import rank
from fn.contracts import Entry, TieLabel


def entry(person_id: str, **lane_ranks: int) -> Entry:
    return Entry(name_key=person_id, person_ids=[person_id], lane_ranks=lane_ranks)


def label(tie: str) -> TieLabel:
    return TieLabel(tie=tie, checked=["s"], rules_version="1")


class RankTest(unittest.TestCase):
    def test_being_found_by_two_lanes_lifts_an_entry(self):
        """Reciprocal rank fusion puts an entry ranked 2 by two lanes above one ranked 1 by a single lane."""
        out = rank.fuse("s", [entry("a", seeds=1), entry("b", seeds=2, openalex=2)], {}, {})
        self.assertEqual([(c.person_id, c.rank) for c in out], [("b", 1), ("a", 2)])
        self.assertAlmostEqual(out[0].score, 2 / 62)

    def test_equal_scores_are_ordered_by_person_id(self):
        out = rank.fuse("s", [entry("p3", seeds=1), entry("p1", openalex=1), entry("p2", seeds=1)], {}, {})
        self.assertEqual([c.person_id for c in out], ["p1", "p2", "p3"])

    def test_sections_number_apart_and_ties_combine(self):
        """An entry with a record in the list is network; each section ranks from 1; the entry's tie is its strongest."""
        two = Entry(name_key="x", person_ids=["p2", "p4"], lane_ranks={"seeds": 2})
        out = rank.fuse("s", [entry("p1", seeds=1), two, entry("p3", seeds=3)],
                        {"p2": label("none_found"), "p4": label("belgian")}, {"p4": "in_list", "p1": "candidate"})
        self.assertEqual([(c.person_id, c.section, c.rank) for c in out],
                         [("p1", "new", 1), ("p2", "network", 1), ("p3", "new", 2)])
        self.assertEqual(out[1].tie.tie, "belgian")
        self.assertEqual(out[0].tie.tie, "none_found")


if __name__ == "__main__":
    unittest.main()
