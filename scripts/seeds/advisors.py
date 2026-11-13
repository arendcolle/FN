# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chambers
import common

LIST = "advisors"
URL = "https://unitedstates.diplomatie.belgium.be/en/belgian-network-us/advisors-economic-diplomacy"
STATES = (
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
    "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska",
    "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas",
    "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
)
CONTACT_LABELS = {"tel", "phone", "mobile", "cell", "fax", "email", "e-mail", "linkedin", "website", "web"}
PHONE_RE = re.compile(r"\+?\d[\d ().-]{6,}\d")
UPDATED = "Last updated on"
StructureError = chambers.StructureError


class AdvisorParser(HTMLParser):
    """Collect the title, the update timestamp and the entries under each US state heading.

    An entry is a plain `ul` (one without a class); when its items hold line breaks, each item is its own entry.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.updated = "", None
        self.entries: list[dict] = []
        self.section: str | None = None
        self.in_title = self.in_h3 = False
        self.heading = ""
        self.skip = 0
        self.after_label = False
        self.items: list[dict] | None = None
        self.line = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        elif tag in ("script", "style"):
            self.skip += 1
        elif tag == "h3":
            self.in_h3, self.heading = True, ""
        elif tag == "ul" and self.section and not dict(attrs).get("class"):
            self.items = []
        elif tag == "li" and self.items is not None:
            self.items.append({"lines": [], "br": False})
            self.line = ""
        elif tag == "br" and self.items:
            self.flush()
            self.items[-1]["br"] = True
        elif tag == "time" and self.after_label:
            self.updated, self.after_label = dict(attrs).get("datetime"), False

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag in ("script", "style"):
            self.skip -= 1
        elif tag == "h3":
            self.in_h3 = False
            text = common.norm(self.heading)
            if text:
                self.section = text if text in STATES else None
        elif tag == "li" and self.items:
            self.flush()
        elif tag == "ul" and self.items is not None:
            self.close_list()

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.skip:
            return
        if self.in_h3:
            self.heading += data
        elif self.items:
            self.line += data
        elif common.norm(data) == UPDATED:
            self.after_label = True

    def flush(self):
        if self.items and (text := common.norm(self.line)):
            self.items[-1]["lines"].append(text)
        self.line = ""

    def close_list(self):
        groups = [[line for item in self.items for line in item["lines"]]]
        if any(item["br"] for item in self.items):
            groups = [item["lines"] for item in self.items]
        self.entries += [{"state": self.section, "lines": lines} for lines in groups if lines]
        self.items = None


def parse(html: str) -> AdvisorParser:
    parser = AdvisorParser()
    parser.feed(html)
    return parser


def check_page(parser: AdvisorParser) -> None:
    """Raises StructureError when the title, the state entries or the update timestamp are missing."""
    if not common.norm(parser.title):
        raise StructureError("page title missing")
    if not parser.entries:
        raise StructureError("no entry under a US state heading")
    if not parser.updated:
        raise StructureError("no 'Last updated on' timestamp to date the page")


def is_contact(line: str) -> bool:
    """True for a line that holds a phone number, an email address or a contact link, whatever its label."""
    label = line.partition(":")[0].strip(" .").casefold()
    return label in CONTACT_LABELS or "@" in line or bool(PHONE_RE.search(line))


def split_entry(lines: list[str]) -> tuple[str, str | None, str | None]:
    """The name, the role and the employer of an entry's lines once the contact lines are dropped.

    A role with ", " and no employer line is split at its last ", ".
    """
    name, *rest = [line for line in lines if not is_contact(line)] or [""]
    role, employer = (rest + [None, None])[:2]
    if role and not employer and ", " in role:
        role, employer = role.rsplit(", ", 1)
    return name, role, employer


def quote_of(name: str, role: str | None, employer: str | None) -> str:
    return ", ".join(part for part in (name, role, employer) if part)


def build_rows(parser: AdvisorParser, raw_path: str, fetched: str) -> list[dict]:
    """One row per named advisor, the first one when a name repeats; no contact line reaches a field."""
    rows, seen = [], set()
    for entry in parser.entries:
        name, role, employer = split_entry(entry["lines"])
        key = common.row_key(LIST, name, None)
        if not name or key in seen:
            continue
        seen.add(key)
        rows.append({
            "list": LIST, "row_key": key, "name": name, "name_on_page": name, "year": None, "role": role,
            "institutions": [{"name": employer, "relation": "employer"}] if employer else [], "field": None,
            "place": entry["state"], "jurisdiction": [entry["state"]], "profile_url": None,
            "source_url": URL, "source_title": common.norm(parser.title), "source_date": parser.updated[:10],
            "date_method": "page text", "page": None, "quote": quote_of(name, role, employer),
            "raw_path": raw_path, "fetched_at": fetched,
        })
    return rows


def text_layer(parser: AdvisorParser, rows: list[dict]) -> str:
    """The title, the state headings, the row quotes and the date line, and nothing else from the page."""
    lines, state = [common.norm(parser.title)], None
    for row in rows:
        if row["place"] != state:
            state = row["place"]
            lines.append(state)
        lines.append(row["quote"])
    return "\n".join([*lines, f"{UPDATED} {parser.updated}"])


def main() -> None:
    chambers.check_robots(URL)
    parser = parse(common.fetch(URL).text)
    check_page(parser)
    today = date.today().isoformat()
    rows = build_rows(parser, "", today)
    text = text_layer(parser, rows)
    raw_path = common.save_raw(LIST, "advisors.html", text.encode(), text)
    for row in rows:
        row["raw_path"] = raw_path
    out = common.write_rows(LIST, rows)
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    try:
        main()
    except (StructureError, chambers.Forbidden, ValueError, httpx.HTTPError) as err:
        print(f"advisors: {err}", file=sys.stderr)
        sys.exit(1)
