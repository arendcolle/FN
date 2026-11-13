# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import advisors
import chambers
import common

LIST = "belcham"
URL = "https://www.belcham.org/about-us"
CHAMBER = "The Belgian American Chamber of Commerce in the United States"
OWN_NAMES = {CHAMBER.casefold(), "belcham"}
PLACES = {*advisors.STATES, "Belgium"}
StructureError = chambers.StructureError


class ListParser(HTMLParser):
    """Collect the title, the copyright year and the list items: a name and the lines of its description."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.year = "", None
        self.entries: list[dict] = []
        self.current: dict | None = None
        self.in_title = self.in_name = False
        self.name = ""
        self.skip = self.depth = 0
        self.line = ""

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "title":
            self.in_title = True
        elif tag in ("script", "style"):
            self.skip += 1
        elif tag == "h2" and "list-item-content__title" in classes:
            self.in_name, self.name = True, ""
        elif tag == "div" and self.depth:
            self.depth += 1
        elif tag == "div" and "list-item-content__description" in classes:
            self.depth = 1
        elif tag in ("br", "p") and self.depth:
            self.flush()

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag in ("script", "style"):
            self.skip -= 1
        elif tag == "h2" and self.in_name:
            self.in_name = False
            name = common.norm(self.name)
            self.current = {"name": name, "lines": []} if name else None
            if self.current:
                self.entries.append(self.current)
        elif tag == "p" and self.depth:
            self.flush()
        elif tag == "div" and self.depth:
            self.depth -= 1
            self.flush()

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.skip:
            return
        if self.in_name:
            self.name += data
        elif self.depth:
            self.line += data
        elif match := chambers.COPYRIGHT_RE.search(common.norm(data)):
            self.year = match[1]

    def flush(self):
        if self.current is not None and (text := common.norm(self.line)):
            self.current["lines"].append(text)
        self.line = ""


def parse(html: str) -> ListParser:
    parser = ListParser()
    parser.feed(html)
    return parser


def check_page(parser: ListParser) -> None:
    """Raises StructureError when the title, the list items or the copyright year are missing."""
    if not common.norm(parser.title):
        raise StructureError("page title missing")
    if not parser.entries:
        raise StructureError("no list item with a name")
    if parser.year is None:
        raise StructureError("no copyright year to date the page")


def join_dashes(lines: list[str]) -> list[str]:
    """Lines with a trailing " -" joined to the line after them, where the page broke the line after the dash."""
    out, carry = [], ""
    for line in lines:
        line = f"{carry} {line}".strip()
        carry = line if line.endswith(" -") else ""
        if not carry:
            out.append(line)
    return out + ([carry] if carry else [])


def role_of(lines: list[str]) -> tuple[str | None, str]:
    """The role and the company of an entry's lines.

    The first line with " - " is "job - company"; the line before it, if any, is a board office. An entry
    without such a line is chamber staff: its first line is the role and it has no company. A company that
    is a state or country is a place and gives none.
    """
    for i, line in enumerate(lines):
        if " - " in line:
            job, company, *_ = [*line.split(" - "), ""]
            office = lines[i - 1] if i else ""
            return (f"{office}, {job}" if office else job), ("" if company in PLACES else company.strip())
    return (lines[0] if lines else None), ""


def build_rows(parser: ListParser, raw_path: str, fetched: str) -> list[dict]:
    """One row per named person, the first one when a name repeats; the delegation's own side is left out."""
    rows, seen = [], set()
    for entry in parser.entries:
        lines = join_dashes(entry["lines"])
        name, quote = entry["name"], common.norm(" ".join([entry["name"], *lines]))
        key = common.row_key(LIST, name, None)
        if key in seen or any(word in quote.casefold() for word in chambers.STAFF):
            continue
        seen.add(key)
        role, company = role_of(lines)
        institutions = [{"name": CHAMBER, "relation": "member_of"}]
        if company and company.casefold() not in OWN_NAMES:
            institutions.insert(0, {"name": company, "relation": "employer"})
        rows.append({
            "list": LIST, "row_key": key, "name": name, "name_on_page": name, "year": None, "role": role,
            "institutions": institutions, "field": None, "place": None, "jurisdiction": None,
            "profile_url": None, "source_url": URL, "source_title": common.norm(parser.title),
            "source_date": parser.year, "date_method": "page text", "page": None, "quote": quote,
            "raw_path": raw_path, "fetched_at": fetched,
        })
    return rows


def text_layer(parser: ListParser) -> str:
    """The title, each entry's name and role lines, and the copyright year line."""
    lines = [common.norm(parser.title)]
    lines += [" ".join([e["name"], *join_dashes(e["lines"])]) for e in parser.entries]
    return "\n".join([*lines, f"© {parser.year}"])


def main() -> None:
    chambers.check_robots(URL)
    resp = common.fetch(URL)
    parser = parse(resp.text)
    check_page(parser)
    raw_path = common.save_raw(LIST, "belcham-about.html", resp.content, text_layer(parser))
    rows = build_rows(parser, raw_path, date.today().isoformat())
    out = common.write_rows(LIST, rows)
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    try:
        main()
    except (StructureError, chambers.Forbidden, ValueError, httpx.HTTPError) as err:
        print(f"belcham: {err}", file=sys.stderr)
        sys.exit(1)
