import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "seeds"))
import fayat

HEAD = "<tr><th>Naam</th><th>Land</th><th>Universiteit</th><th>Studierichting</th></tr>"
PAGE = f"""<html><head><title>Fayat page | Test</title></head><body><h1>Laureaten</h1>
<h2>Exacte Wetenschappen</h2><h3>Laureaten najaar 2022</h3><table>{HEAD}
<tr><td><a href="https://example.org/in/jan-peeters">Jan Peeters</a></td><td>Nederland</td><td>Delft University</td><td>MSc Physics</td></tr>
<tr><td>Els Maes</td><td>Zwitserland</td><td>ETH Test</td><td>MSc Maths</td></tr></table>
<h3>Laureaten 2024</h3><table>{HEAD}
<tr><td><a href="https://example.org/in/an-dewit">An De Wit</a></td><td>Japan</td><td>Test University</td><td>PhD Chemistry</td></tr></table>
<h2>Contact</h2><h3>Vragen</h3></body></html>"""


class FayatParserTest(unittest.TestCase):
    def rows(self, html: str = PAGE) -> list[dict]:
        items, title = fayat.parse(html)
        return fayat.build_rows(fayat.collect(items), title, "raw.txt", "2026-01-01")

    def test_rows_take_their_year_from_the_period_heading_and_the_link_from_the_name(self):
        """Each body row gets the year of its Laureaten heading, its cells, and the name link when there is one."""
        rows = self.rows()
        self.assertEqual([(r["name"], r["year"]) for r in rows], [("Jan Peeters", 2022), ("Els Maes", 2022), ("An De Wit", 2024)])
        self.assertEqual(rows[0]["institutions"], [{"name": "Delft University", "relation": "student"}])
        self.assertEqual((rows[0]["place"], rows[0]["field"], rows[0]["profile_url"]),
                         ("Nederland", "MSc Physics", "https://example.org/in/jan-peeters"))
        self.assertIsNone(rows[1]["profile_url"])
        self.assertEqual(rows[1]["quote"], "Els Maes Zwitserland ETH Test MSc Maths")

    def test_a_changed_page_shape_raises(self):
        """Renamed columns, a row outside any period and a page with no rows each raise StructureError."""
        for html in (PAGE.replace("Studierichting", "Richting"), PAGE.replace("Laureaten 2024", "Andere"),
                     "<html><title>x</title><h1>x</h1></html>"):
            with self.assertRaises(fayat.StructureError):
                self.rows(html)


if __name__ == "__main__":
    unittest.main()
