import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "seeds"))
import advisors
from fn import seedload
from tests.helpers import FIXTURES, make_db, make_settings

PAGE = (FIXTURES / "seeds" / "advisors.html").read_text(encoding="utf-8")
LEAK = re.compile(r"@|\+?\d[\d ().-]{6,}\d")
DATE = re.compile(r"\d{4}-\d\d-\d\d(T[\d:]+Z)?")


def leaks(text: str) -> bool:
    """True when the text, once its ISO dates are removed, holds an email address or a phone number."""
    return bool(LEAK.search(DATE.sub("", text)))


def build(page: str = PAGE) -> tuple[advisors.AdvisorParser, list[dict]]:
    parser = advisors.parse(page)
    advisors.check_page(parser)
    return parser, advisors.build_rows(parser, "raw.txt", "2026-11-12")


class AdvisorsParserTest(unittest.TestCase):
    def test_rows_have_name_role_employer_state_and_the_page_date(self):
        """Flat, nested-span and split-role entries give name, role, employer, state and the date after the label."""
        _, rows = build()
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(list(by_name), ["Ann EXAMPLE", "Bo VOORBEELD", "Mr. Cy R. EXAMPLE", "Mr. Di EXAMPLE", "Ed VOORBEELD, PhD"])
        ann, bo = by_name["Ann EXAMPLE"], by_name["Bo VOORBEELD"]
        self.assertEqual((ann["role"], ann["institutions"], ann["place"], ann["jurisdiction"], ann["source_date"]), (
            "Producer & Senior Director", [{"name": "Example Fellowship (Example Studios)", "relation": "employer"}],
            "California", ["California"], "2025-05-12"))
        self.assertEqual((bo["role"], bo["institutions"]), (
            "Senior Director, Business Strategy", [{"name": "Example Labs", "relation": "employer"}]))
        self.assertEqual(by_name["Mr. Cy R. EXAMPLE"]["place"], "New York")
        ed = by_name["Ed VOORBEELD, PhD"]
        self.assertEqual((ed["role"], ed["institutions"], ed["place"], ed["quote"]), (
            "Chief Scientist", [{"name": "Example Biotech Inc", "relation": "employer"}], "Texas",
            "Ed VOORBEELD, PhD, Chief Scientist, Example Biotech Inc"))

    def test_no_row_field_and_no_text_layer_line_holds_an_email_or_a_phone_number(self):
        """Contact lines are dropped, labelled or not, so neither the rows nor the saved text carry them."""
        parser, rows = build()
        self.assertFalse(leaks(json.dumps(rows)))
        self.assertFalse(leaks(advisors.text_layer(parser, rows)))

    def test_a_section_after_the_last_state_and_an_empty_heading_add_no_entry(self):
        """The footer list under "Popular Services" and the update list are not advisors."""
        parser, rows = build()
        self.assertEqual(len(parser.entries), 5)
        self.assertNotIn("Services", json.dumps(rows))

    def test_a_repeated_name_gives_one_row_and_a_page_without_the_date_is_refused(self):
        page = PAGE.replace("<h3 class=\"menu__title\">", "<ul><li><strong>Ann EXAMPLE</strong></li><li>CEO</li></ul>"
                            "<h3 class=\"menu__title\">", 1)
        self.assertEqual(len(build(page)[1]), 5)
        with self.assertRaises(advisors.StructureError):
            advisors.check_page(advisors.parse(PAGE.replace("Last updated on", "Changed")))
        with self.assertRaises(advisors.StructureError):
            advisors.check_page(advisors.parse("<html><head><title>T</title></head><body></body></html>"))

    def test_loading_the_rows_stores_no_email_or_phone_number(self):
        """After seedload, no source text, claim value or claim quote holds "@" or a phone pattern."""
        parser, rows = build()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            raw = folder / "advisors.html.txt"
            raw.write_text(advisors.text_layer(parser, rows), encoding="utf-8")
            lines = [json.dumps(r | {"raw_path": str(raw)}) for r in rows]
            (folder / "advisors.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            store = make_db(self, make_settings(self))
            self.assertEqual(seedload.load(store, seeds=folder), 5)
        texts = [r[0] for r in store.conn.execute("SELECT text FROM sources")]
        claims = [v for r in store.conn.execute("SELECT value, quote FROM claims") for v in r if v]
        self.assertTrue(texts and claims)
        self.assertFalse([t for t in texts + claims if leaks(t)])


if __name__ == "__main__":
    unittest.main()
