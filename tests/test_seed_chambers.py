import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "seeds"))
import chambers

SOUTH = {"key": "south", "name": "Example Chamber of the South", "url": "https://south.example.org/about"}
WEST = {"key": "west", "name": "Example Chamber of the West", "url": "https://west.example.org/board"}
SOUTH_PAGE = """<html><head><title>About &#183; Example South</title><script>var x = "Board of directors";</script></head>
<body><article class="intro"><b>Welcome</b><small>before the board</small></article>
<div><span>Board of directors</span></div>
<article class="bcard"><img alt="Portrait of Ada Example"><div><b>Ada Example</b><small>Chair of the Board</small></div></article>
<article class="bcard"><div><b>Bo Voorbeeld</b></div></article>
<article class="bcard"><div><b></b><small>Board Member</small></div></article>
<article class="bcard"><div><b>Dr. Cy Example, PhD</b><small>Treasurer</small></div></article>
<footer>&copy; 2013&ndash;2026 Example South</footer></body></html>"""
WEST_PAGE = """<html><head><title>Our Boards | Example West</title></head><body>
<h2>Board of directors</h2>
<p><strong>Ada Example</strong> <br>President &amp; CEO at Example Labs</p>
<p><strong>Di Example</strong> <br>Industry Lead at Example Group, Vice President at Example West</p>
<p><strong>Gus Example</strong> <br>Treasurer at Example Chamber of the West</p>
<p><strong>Eve Example</strong> <br>Independent Film Producer</p>
<p><strong>Ada Example</strong> <br>Advisor at Other Company</p>
<h2>Honorary members</h2>
<p><a href="/people/fay"><strong>Fay Example</strong></a><br>Founder at Example Studio</p>
<p><strong>Hal Example</strong> <br>Partner at Example Law in Salem</p>
<p><strong>Ivy Example</strong> <br>Director at Example Trade in Nowhere</p>
<p><strong>Jo Example</strong> <br>Consul General of Belgium in Salem</p>
<p><strong>Kai Example</strong> <br>Trade Commissioner at Flanders Investment &amp; Trade</p>
<p>Plain footer text</p>
<p>&copy; 2025 Example West - Privacy</p></body></html>"""


def rows(page: str, chamber: dict) -> list[dict]:
    parser = chambers.parse(page)
    chambers.check_page(parser)
    return chambers.build_rows(parser, chamber, "raw.txt", "2026-11-12")


class ChambersParserTest(unittest.TestCase):
    def test_a_card_page_and_a_paragraph_page_give_rows_with_role_company_and_the_chamber(self):
        """Each page shape gives role, company, chamber membership, copyright year and the person's quote, and no guessed place."""
        south = rows(SOUTH_PAGE, SOUTH)
        self.assertEqual([(r["name"], r["role"]) for r in south],
                         [("Ada Example", "Chair of the Board"), ("Bo Voorbeeld", "Board of directors"),
                          ("Dr. Cy Example, PhD", "Treasurer")])
        self.assertEqual((south[0]["place"], south[0]["source_date"], south[0]["source_title"]),
                         (None, "2026", "About · Example South"))
        west = {r["name"]: r for r in rows(WEST_PAGE, WEST)}
        ada = west["Ada Example"]
        self.assertEqual((ada["role"], ada["institutions"], ada["quote"]), (
            "President & CEO", [{"name": "Example Labs", "relation": "employer"},
                                {"name": "Example Chamber of the West", "relation": "member_of"}],
            "Ada Example President & CEO at Example Labs"))
        self.assertEqual(west["Di Example"]["institutions"][0], {"name": "Example Group", "relation": "employer"})
        self.assertEqual(west["Fay Example"]["profile_url"], "https://west.example.org/people/fay")
        self.assertEqual(west["Fay Example"]["source_date"], "2025")

    def test_no_row_has_a_place(self):
        """The pages state no city for a board member, so no row guesses one from the chamber's home."""
        self.assertEqual({r["place"] for r in rows(WEST_PAGE, WEST) + rows(SOUTH_PAGE, SOUTH)}, {None})

    def test_the_delegations_own_side_is_left_out(self):
        """A consul and a trade commissioner on a board page are FN's users and give no row."""
        names = [r["name"] for r in rows(WEST_PAGE, WEST)]
        self.assertNotIn("Jo Example", names)
        self.assertNotIn("Kai Example", names)
        self.assertIn("Hal Example", names)

    def test_an_entry_without_a_company_gives_a_row_and_an_entry_without_a_name_is_left_out(self):
        """A job with no company or at the chamber itself has only the membership; a card without a name gives no row; a repeated name gives one."""
        west = rows(WEST_PAGE, WEST)
        eve = next(r for r in west if r["name"] == "Eve Example")
        self.assertEqual((eve["role"], eve["institutions"]), (
            "Independent Film Producer", [{"name": "Example Chamber of the West", "relation": "member_of"}]))
        self.assertEqual([r["name"] for r in rows(SOUTH_PAGE, SOUTH)].count(""), 0)
        self.assertEqual(len(rows(SOUTH_PAGE, SOUTH)), 3)
        self.assertEqual([r["name"] for r in west].count("Ada Example"), 1)
        gus = next(r for r in west if r["name"] == "Gus Example")
        self.assertEqual((gus["role"], gus["institutions"]), (
            "Treasurer", [{"name": "Example Chamber of the West", "relation": "member_of"}]))

    def test_a_changed_page_shape_raises(self):
        """No board heading, no entries under it, no title or no copyright year each raise StructureError."""
        for html in (SOUTH_PAGE.replace("Board of directors", "Team"), "<html><title>x</title><h2>Board of directors</h2></html>",
                     WEST_PAGE.replace("<title>Our Boards | Example West</title>", ""),
                     WEST_PAGE.replace("&copy; 2025", "")):
            with self.assertRaises(chambers.StructureError):
                rows(html, WEST)


class RobotsTest(unittest.TestCase):
    def check(self, robots: str | int, url: str = "https://west.example.org/board") -> None:
        def fetch(_: str):
            if isinstance(robots, int):
                resp = httpx.Response(robots, request=httpx.Request("GET", url))
                resp.raise_for_status()
            return httpx.Response(200, text=robots)

        chambers.check_robots(url, fetch)

    def test_robots_that_bar_the_page_or_cannot_be_read_stop_the_run_and_a_404_means_no_rules(self):
        """A Disallow on the page and a 403 on robots.txt raise Forbidden; a 404 and an allowing file pass."""
        self.check(404)
        self.check("User-agent: *\nDisallow: /search")
        for robots in ("User-agent: *\nDisallow: /board", 403):
            with self.assertRaises(chambers.Forbidden):
                self.check(robots)


if __name__ == "__main__":
    unittest.main()
