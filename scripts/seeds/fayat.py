# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "fayat"
URL = "https://www.vlaanderen.be/onderwijs-en-vorming/naar-school-gaan-studeren-of-een-stage-volgen-in-het-buitenland/fayatbeurzen/fayatbeurs-contactgegevens-laureaten"
FILENAME = "fayat-laureaten.html"
ROLE = "Fayat scholarship laureate"
COLUMNS = ["Naam", "Land", "Universiteit", "Studierichting"]
YEAR_RE = re.compile(r"\b(20\d\d)\b")


class StructureError(Exception):
    pass


class TableParser(HTMLParser):
    """Collect h1, h2, h3 headings and table rows as ("h1" | "h2" | "h3" | "row", cells, link) in page order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, list[str], str | None]] = []
        self.title = ""
        self.in_title = False
        self.heading: str | None = None
        self.cell: list[str] | None = None
        self.row: list[str] | None = None
        self.link: str | None = None
        self.buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        elif tag in ("h1", "h2", "h3"):
            self.heading, self.buf = tag, []
        elif tag == "tr":
            self.row, self.link = [], None
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "a" and self.cell is not None and self.link is None:
            self.link = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == self.heading:
            self.items.append((tag, [common.norm("".join(self.buf))], None))
            self.heading = None
        elif tag in ("td", "th") and self.cell is not None:
            self.row.append(common.norm("".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.items.append(("row", self.row, self.link))
            self.row = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.heading:
            self.buf.append(data)
        if self.cell is not None:
            self.cell.append(data)


def parse(html: str) -> tuple[list[tuple[str, list[str], str | None]], str]:
    parser = TableParser()
    parser.feed(html)
    return parser.items, common.norm(parser.title)


def collect(items: list[tuple[str, list[str], str | None]]) -> list[dict]:
    """Pair every body row with its h3 period; raises StructureError when the columns, periods or rows are off."""
    people, year = [], None
    for kind, cells, link in items:
        if kind == "h2":
            year = None
        elif kind == "h3":
            match = YEAR_RE.search(cells[0])
            year = int(match[1]) if match and cells[0].startswith("Laureaten") else None
        elif kind == "row" and cells[:1] == COLUMNS[:1]:
            if cells != COLUMNS:
                raise StructureError(f"table columns changed: {cells}")
        elif kind == "row":
            if year is None:
                raise StructureError(f"table row outside a 'Laureaten <year>' section: {cells}")
            if len(cells) != len(COLUMNS) or not all(cells[:3]):
                raise StructureError(f"unexpected row shape: {cells}")
            people.append({"cells": cells, "link": link, "year": year})
    if not people:
        raise StructureError("no laureate rows found")
    return people


def build_rows(people: list[dict], title: str, raw_path: str, fetched: str) -> list[dict]:
    rows = []
    for person in people:
        name, country, university, study = person["cells"]
        rows.append({
            "list": LIST, "row_key": common.row_key(LIST, name, person["year"]), "name": name, "name_on_page": name,
            "year": person["year"], "role": ROLE, "institutions": [{"name": university, "relation": "student"}],
            "field": study or None, "place": country or None, "jurisdiction": None, "profile_url": person["link"],
            "source_url": URL, "source_title": title, "source_date": None, "date_method": "none", "page": None,
            "quote": common.norm(" ".join(person["cells"])), "raw_path": raw_path, "fetched_at": fetched,
        })
    return rows


def text_layer(items: list[tuple[str, list[str], str | None]]) -> str:
    return "\n".join(cells[0] if kind != "row" else " ".join(cells) for kind, cells, _ in items)


def main() -> None:
    resp = common.fetch(URL)
    items, title = parse(resp.text)
    if not title or not any(k == "h1" for k, _, _ in items):
        raise StructureError("page title or h1 missing")
    raw_path = common.save_raw(LIST, FILENAME, resp.content, text_layer(items))
    rows = build_rows(collect(items), title, raw_path, date.today().isoformat())
    out = common.write_rows(LIST, rows)
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    try:
        main()
    except (StructureError, ValueError) as err:
        print(f"fayat: {err}", file=sys.stderr)
        sys.exit(1)
