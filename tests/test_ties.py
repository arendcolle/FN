import json
import unittest
from collections import Counter

from fn import seedload, ties
from fn.contracts import Claim

ROWS = [json.loads(line) for path in sorted(seedload.SEEDS.glob("*.jsonl")) for line in path.read_text().splitlines()]


def claim(value: str, source_id: str = "s1", kind: str = "affiliation") -> Claim:
    return Claim(id=f"c-{value}", person_id="p1", kind=kind, value=value, quote=value, quote_start=0,
                 quote_end=len(value), source_id=source_id)


class TieTest(unittest.TestCase):
    def test_institutions_map_to_their_tie(self):
        """Flemish, Belgian and Dutch institutions give their tie; MIT and an unknown name give none_found."""
        expected = {"KU Leuven": "flemish", "KULeuven": "flemish", "VUB": "flemish", "ULB": "belgian",
                    "IMEC": "flemish", "iMinds": "flemish", "Ghent University": "flemish", "TU Delft": "dutch",
                    "MIT": "none_found", "Institute of Nowhere": "none_found"}
        for name, tie in expected.items():
            with self.subTest(name=name):
                label = ties.label([claim(name)])
                self.assertEqual(label.tie, tie)
                self.assertEqual(label.claim_ids, [] if tie == "none_found" else [f"c-{name}"])
                self.assertEqual(label.checked, ["s1"])

    def test_strongest_tie_wins_and_every_source_is_checked(self):
        """A Flemish claim outranks a Belgian one; a role claim naming an institution gives no tie."""
        label = ties.label([claim("ULB", "s1"), claim("KU Leuven", "s2"), claim("MIT", "s3")])
        self.assertEqual((label.tie, label.claim_ids, label.checked), ("flemish", ["c-KU Leuven"], ["s1", "s2", "s3"]))
        self.assertEqual(ties.label([claim("KU Leuven", kind="role")]).tie, "none_found")
        self.assertEqual(ties.label([]).tie, "none_found")
        combined = ties.combine([ties.label([claim("ULB", "s1")]), ties.label([claim("MIT", "s2")])])
        self.assertEqual((combined.tie, combined.claim_ids, combined.checked), ("belgian", ["c-ULB"], ["s1", "s2"]))

    def test_every_frequent_seed_institution_is_mapped_or_listed_unmapped(self):
        """Each institution string on 5 or more seed rows is in ties.csv or on the unmapped list, never both."""
        counts = Counter(inst["name"] for row in ROWS for inst in row["institutions"])
        frequent = [name for name, n in counts.items() if n >= 5]
        self.assertGreater(len(frequent), 80)
        for name in frequent:
            with self.subTest(name=name):
                self.assertNotEqual(ties.org_id(name) is not None, ties.fold(name) in ties.unmapped())

    def test_aliases_and_ref_come_from_ties_csv(self):
        self.assertEqual(ties.aliases("mit"), ["MIT", "M.I.T.", "Massachusetts Institute of Technology"])
        self.assertEqual(ties.ref("MIT"), "ror:https://ror.org/042nb2s44")
        self.assertEqual((ties.aliases("Nowhere"), ties.ref("Nowhere"), ties.ref("ILVO")), ([], None, None))


if __name__ == "__main__":
    unittest.main()
