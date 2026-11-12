import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "seeds"))
import missions

DAYS = " ".join(f"[day] {day}, {n} June 2022, Example City" for n, day in enumerate(
    ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"], start=4))
PROGRAM = f"""[PDF page 1] [left] Program of the Belgian Economic Mission to the United States of America {DAYS}
[PDF page 2] [right] 9:00 - 10:00 Panel on example widgets · 9:00 Welcome by Ada Example, CEO, Example Widgets Inc
· 9:10 Speech by HE Bo Minister, Minister of Examples · 9:20 Introduction by Cy Staffer, Economic Adviser,
Flanders Investment & Trade · 9:30 Presentation by Dot Nameless (Example Labs) o Moderator: Ed Example - Managing
Director Example Bank
[right] o Fay
Example, Chief Example Officer at Example Labs & Gus Example, CTO, Example Robotics, Inc. o Example Systems - Director of
Examples - Mr. Ivy Example ( SF )
[PDF page 3] [left] 11:00 - 12:00 Lunch on example trade · 11:00 Keynote by Ada Example, CEO, Example Widgets Inc
[left] 14:00 - 15:00 Roundtable on examples · 14:00 Words by Ada Example
[left] 15:00 - 15:30 Transfer from the hotel to the venue with the bus D1
[left] 16:00 - 16:30 Closing panel · 16:00 Remarks by Hal Example, Senior Vice President, Example Partners, Example
Holdings, Example Group
[footer] Update 3/06/2022 - Page 3
"""


class MissionsParserTest(unittest.TestCase):
    def test_a_speaker_has_title_employer_and_every_session_joined(self):
        """A speaker named with title and employer is one row; a later line naming them without either adds its session.

        The quote is the first line with title and employer, on its page.
        """
        speakers, _ = missions.parse(PROGRAM)
        ada = speakers["ada-example"]
        self.assertEqual((ada["title"], ada["employer"], ada["page"]), ("CEO", "Example Widgets Inc", 2))
        self.assertEqual(ada["quote"], "9:00 Welcome by Ada Example, CEO, Example Widgets Inc")
        row = missions.build_rows(speakers, "raw/program.txt", "2026-11-12")[0]
        self.assertEqual((row["row_key"], row["field"], row["institutions"], row["place"], row["year"]),
                         ("missions|ada-example|2022|", "Panel on example widgets; Lunch on example trade; Roundtable on examples",
                          [{"name": "Example Widgets Inc", "relation": "employer"}], None, 2022))
        self.assertEqual((row["source_url"], row["source_date"]), (missions.URL, "2022-06-03"))

    def test_the_delegation_staff_a_minister_and_unclear_lines_are_left_out_and_counted(self):
        """Staff of the trade agency, a minister, a name without title or employer and a line with too many commas."""
        speakers, skips = missions.parse(PROGRAM)
        self.assertEqual(sorted(speakers), ["ada-example", "ed-example", "fay-example", "gus-example", "ivy-example"])
        self.assertEqual([skips[reason] for reason in missions.SKIPS], [1, 1, 1, 1])

    def test_two_speakers_on_one_line_are_two_rows_and_a_name_over_two_lines_is_one(self):
        speakers, _ = missions.parse(PROGRAM)
        self.assertEqual((speakers["fay-example"]["name"], speakers["fay-example"]["title"], speakers["fay-example"]["employer"]),
                         ("Fay Example", "Chief Example Officer", "Example Labs"))
        self.assertEqual((speakers["gus-example"]["title"], speakers["gus-example"]["employer"]), ("CTO", "Example Robotics, Inc"))
        self.assertEqual((speakers["ed-example"]["title"], speakers["ed-example"]["employer"]),
                         ("Managing Director", "Example Bank"))

    def test_a_line_that_starts_with_the_employer_gives_its_title_and_name(self):
        speakers, _ = missions.parse(PROGRAM)
        self.assertEqual((speakers["ivy-example"]["name"], speakers["ivy-example"]["title"], speakers["ivy-example"]["employer"]),
                         ("Ivy Example", "Director of Examples", "Example Systems"))

    def test_a_changed_document_shape_raises(self):
        """No program title, no "updated on" line, or fewer days than the mission had each raise StructureError."""
        for changed in (PROGRAM.replace("Program of the", "Agenda of the"), PROGRAM.replace("Update 3/06/2022", "Update"),
                        PROGRAM.replace("[day] Friday", "[left] Friday")):
            with self.assertRaises(missions.StructureError):
                missions.parse(changed)


if __name__ == "__main__":
    unittest.main()
