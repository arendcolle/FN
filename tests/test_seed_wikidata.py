import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "seeds"))
import wikidata

ITEM = "http://www.wikidata.org/entity/"


def fact(qid: str, kind: str, v: str, **values) -> dict:
    return {name: {"type": "literal", "value": value} for name, value in {"p": ITEM + qid, "kind": kind, "v": v,
                                                                           **values}.items()}


def answer(*facts: dict) -> dict:
    return {"head": {"vars": wikidata.VARS}, "results": {"bindings": list(facts)}}


US, BE = ITEM + "Q30", ITEM + "Q31"
ANSWER = answer(
    fact("Q101", "label", "Ada Example", lang="en"),
    fact("Q101", "label", "Ada Voorbeeld", lang="nl"),
    fact("Q101", "description", "Belgian chemist"),
    fact("Q101", "modified", "2026-10-03T08:00:00Z"),
    fact("Q101", "occupation", ITEM + "Q9", vLabel="chemist"),
    fact("Q101", "school", ITEM + "Q201", vLabel="Example University Leuven", start="2001-01-01T00:00:00Z"),
    fact("Q101", "employer", ITEM + "Q301", vLabel="Example Labs", country=US, start="2019-01-01T00:00:00Z",
         city=ITEM + "Q401", cityLabel="Portland", stateLabel="Oregon"),
    fact("Q101", "employer", ITEM + "Q302", vLabel="Old Example Corp", country=US, start="2010-01-01T00:00:00Z",
         end="2018-01-01T00:00:00Z"),
    fact("Q101", "residence", ITEM + "Q402", vLabel="Springfield", stateLabel="Missouri"),
    fact("Q102", "label", "Bo Example", lang="fr"),
    fact("Q102", "modified", "2025-01-02T00:00:00Z"),
    fact("Q102", "field", ITEM + "Q8", vLabel="robotics"),
    fact("Q102", "employer", ITEM + "Q303", vLabel="Example Robotics", country=US, start="2021-05-01T00:00:00Z",
         city=ITEM + "Q401", cityLabel="Portland", stateLabel="Oregon"),
    fact("Q102", "employer", ITEM + "Q304", vLabel="Example Institute Ghent", country=BE, start="2015-01-01T00:00:00Z"),
    fact("Q103", "label", "Q103", lang="en"),
    fact("Q103", "modified", "2025-01-02T00:00:00Z"),
    fact("Q104", "description", "a person without a label"),
    fact("Q104", "modified", "2025-01-02T00:00:00Z"),
    fact("Q105", "label", "Cy Example", lang="en"),
    fact("Q105", "modified", "2025-01-02T00:00:00Z"),
    fact("Q105", "school", ITEM + "Q201", vLabel="Example University Leuven"),
    fact("Q105", "employer", ITEM + "Q305", vLabel="Example Hospital", country=US),
    fact("Q106", "label", "Di Example", lang="en"),
    fact("Q106", "modified", "2025-01-02T00:00:00Z"),
    fact("Q106", "employer", ITEM + "Q306", vLabel="Example Bank", country=US, start="2020-01-01T00:00:00Z"),
    fact("Q106", "employer", ITEM + "Q307", vLabel="Example Bank Brussels", country=BE, start="2005-01-01T00:00:00Z",
         end="2019-01-01T00:00:00Z"),
    fact("Q107", "label", "Eve Example", lang="en"),
    fact("Q107", "modified", "2025-01-02T00:00:00Z"),
    fact("Q107", "employer", ITEM + "Q308", vLabel="Example Agency", country=US, start="2022-01-01T00:00:00Z"),
    fact("Q107", "employer", ITEM + "Q308", vLabel="Example Agency", country=BE, start="2022-01-01T00:00:00Z"),
    fact("Q107", "school", ITEM + "Q309", vLabel="Example College Antwerp"),
    fact("Q107", "employer", ITEM + "Q309", vLabel="Example College Antwerp", country=BE, start="2012-01-01T00:00:00Z"),
)


class WikidataParserTest(unittest.TestCase):
    def rows(self, found: dict = ANSWER) -> tuple[dict[str, dict], dict]:
        saved = {}

        def save(qid: str, facts: list[dict], text: str) -> str:
            saved[qid] = text
            return f"raw/{qid}.json.txt"

        rows, skips = wikidata.build_rows(wikidata.group([found]), save, "2026-11-12")
        self.saved = saved
        return {r["name"]: r for r in rows}, dict(skips)

    def test_an_open_us_job_is_an_employer_an_ended_one_is_left_out_and_a_belgian_school_is_student(self):
        """A US employer with a start and no end is employer; an ended one is gone; a Belgian school is student.

        The quote is the person's own text layer, and the row's date is the item's change date.
        """
        rows, skips = self.rows()
        ada = rows["Ada Example"]
        self.assertEqual(ada["institutions"], [{"name": "Example Labs", "relation": "employer"},
                                               {"name": "Example University Leuven", "relation": "student"}])
        self.assertEqual((ada["role"], ada["field"], ada["source_date"], ada["date_method"]),
                         ("chemist", "Belgian chemist", "2026-10-03", "item modified"))
        self.assertEqual((ada["row_key"], ada["profile_url"], ada["raw_path"]),
                         ("wikidata|ada-example||Q101", ITEM + "Q101", "raw/Q101.json.txt"))
        self.assertEqual(ada["quote"], wikidata.common.norm(self.saved["Q101"]))
        self.assertNotIn("Old Example Corp", ada["quote"])
        self.assertEqual(skips["employer statement ended"], 2)
        bo = rows["Bo Example"]
        self.assertEqual(bo["institutions"], [{"name": "Example Robotics", "relation": "employer"},
                                              {"name": "Example Institute Ghent", "relation": "home"}])
        self.assertEqual(bo["field"], "robotics")

    def test_the_place_is_the_us_residence_else_the_employer_city(self):
        rows, _ = self.rows()
        self.assertEqual(rows["Ada Example"]["place"], "Springfield, Missouri")
        self.assertEqual(rows["Bo Example"]["place"], "Portland, Oregon")

    def test_people_without_a_label_or_a_current_us_tie_are_left_out_and_counted(self):
        """No label, a label that is the item id, and only an undated US job each leave the person out, counted."""
        rows, skips = self.rows()
        self.assertEqual(sorted(rows), ["Ada Example", "Bo Example", "Eve Example"])
        self.assertEqual((skips["no label in en, nl or fr"], skips["label is only the item id"],
                          skips["employer statement without a start date"],
                          skips["no current US employer or US residence"]), (1, 1, 1, 1))

    def test_a_person_whose_only_belgian_tie_is_a_past_job_is_left_out_and_counted(self):
        rows, skips = self.rows()
        self.assertNotIn("Di Example", rows)
        self.assertEqual(skips["no Belgian school or current Belgian employer"], 1)

    def test_an_institution_is_listed_once_under_its_first_relation(self):
        """An employer in both countries is a US employer only; a school that also employs is a student school."""
        rows, _ = self.rows()
        self.assertEqual(rows["Eve Example"]["institutions"], [{"name": "Example Agency", "relation": "employer"},
                                                               {"name": "Example College Antwerp", "relation": "student"}])

    def test_a_changed_answer_shape_raises(self):
        """Renamed columns, no bindings and an unknown fact kind each raise StructureError."""
        for found in ({"head": {"vars": ["p", "v"]}, "results": {"bindings": []}}, answer(),
                      answer(fact("Q101", "nickname", "Ada"))):
            with self.assertRaises(wikidata.StructureError):
                wikidata.group([found])
        with self.assertRaises(wikidata.StructureError):
            wikidata.people_of({"head": {"vars": ["p"]}, "results": {"bindings": [{"p": {"value": "Ada"}}]}})


if __name__ == "__main__":
    unittest.main()
