import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "seeds"))
import belcham
from tests.helpers import FIXTURES

PAGE = (FIXTURES / "seeds" / "belcham-about.html").read_text(encoding="utf-8")
CHAMBER = belcham.CHAMBER


def rows(page: str = PAGE) -> list[dict]:
    parser = belcham.parse(page)
    belcham.check_page(parser)
    return belcham.build_rows(parser, "raw.txt", "2026-11-12")


def item(name: str, *lines: str) -> str:
    body = "<br>".join(lines)
    return (f'<h2 class="list-item-content__title">{name}</h2>'
            f'<div class="list-item-content__description"><p>{body}</p></div>')


def page(*items: str) -> str:
    return f"<html><head><title>T</title></head><body>{''.join(items)}<p>&copy; 2022 X</p></body></html>"


class BelchamParserTest(unittest.TestCase):
    def test_board_rows_have_office_role_employer_chamber_membership_and_the_year(self):
        """A board entry gives "office, job", its company as employer, the chamber as member_of, the page year, no place."""
        by_name = {r["name"]: r for r in rows()}
        di = by_name["Di Example"]
        self.assertEqual((di["role"], di["institutions"], di["place"], di["source_date"], di["date_method"]), (
            "President Example Chamber, Founder and Managing Partner",
            [{"name": "Example Labs", "relation": "employer"}, {"name": CHAMBER, "relation": "member_of"}],
            None, "2022", "page text"))
        self.assertEqual(di["quote"], "Di Example President Example Chamber Founder and Managing Partner - Example Labs")
        gus = by_name["Gus Example"]
        self.assertEqual((gus["role"], gus["institutions"][0]), ("Founder & CEO", {"name": "Example Foods, LLC", "relation": "employer"}))
        self.assertEqual(by_name["Fay Voorbeeld"]["role"], "Co-Founder")

    def test_a_company_that_is_the_chamber_gives_only_the_membership(self):
        """The chamber named as company is the membership, not a works_at claim that would collide with it."""
        found = rows(page(item("Ann Example", "Advisor - " + CHAMBER + " - Texas"), item("Bo Example", "Chair - BelCham")))
        self.assertEqual([r["institutions"] for r in found], [[{"name": CHAMBER, "relation": "member_of"}]] * 2)

    def test_staff_rows_have_the_first_line_as_role_and_no_employer(self):
        """An entry without " - " is chamber staff: role is its first line, only the chamber is linked."""
        ann = next(r for r in rows() if r["name"] == "Ann Example")
        self.assertEqual((ann["role"], ann["institutions"]), ("Managing Director", [{"name": CHAMBER, "relation": "member_of"}]))

    def test_a_state_after_the_job_is_no_company_and_a_repeated_name_gives_one_row(self):
        """"Job - Texas" has no employer; the second row of a name is dropped; the attribute JSON is not read."""
        found = rows(page(item("Ann Example", "Chair - Texas"), item("Ann Example", "CEO - Example Labs")))
        self.assertEqual([(r["name"], r["role"], r["institutions"]) for r in found],
                         [("Ann Example", "Chair", [{"name": CHAMBER, "relation": "member_of"}])])
        self.assertNotIn("Hidden Attribute", [r["name"] for r in rows()])

    def test_the_delegations_own_side_is_left_out(self):
        found = rows(page(item("Ann Example", "Consul General - Belgium Embassy"), item("Bo Example", "CEO - Example Labs")))
        self.assertEqual([r["name"] for r in found], ["Bo Example"])

    def test_check_page_refuses_a_page_without_list_items_title_or_year(self):
        for bad in ("<html><head><title>T</title></head><body><p>&copy; 2022 X</p></body></html>",
                    "<html><body>" + item("Ann Example", "CEO - X") + "<p>&copy; 2022 X</p></body></html>",
                    "<html><head><title>T</title></head><body>" + item("Ann Example", "CEO - X") + "</body></html>"):
            with self.assertRaises(belcham.StructureError):
                belcham.check_page(belcham.parse(bad))

    def test_every_quote_is_in_the_text_layer(self):
        parser = belcham.parse(PAGE)
        text = " ".join(belcham.text_layer(parser).split())
        for row in belcham.build_rows(parser, "raw.txt", "2026-11-12"):
            self.assertIn(row["quote"], text)


if __name__ == "__main__":
    unittest.main()
