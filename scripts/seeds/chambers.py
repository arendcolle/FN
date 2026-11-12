# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "chambers"
CHAMBERS = [
    {"key": "bacos", "name": "Belgian American Chamber of the South",
     "url": "https://www.bacos.us/about.html", "filename": "bacos-about.html"},
    {"key": "belwest", "name": "Belwest", "url": "https://www.belwest.org/board", "filename": "belwest-board.html"},
]
# People on the delegation's own side are FN's users, not people to find.
STAFF = ("consul", "ambassador", "embassy", "trade commissioner", "flanders investment", "awex", "hub.brussels",
         "delegation of flanders")
SECTIONS = {"board of directors", "advisory board", "honorary members"}
BOARD = "board of directors"
COPYRIGHT_RE = re.compile(r"©\s*(?:(?:19|20)\d\d\s*[-–]\s*)?((?:19|20)\d\d)\b")


class StructureError(Exception):
    pass


class Forbidden(Exception):
    pass


class BoardParser(HTMLParser):
    """Collect the title, the copyright year and the people of the page as entries, in page order.

    An entry is the innermost article or p whose first b or strong text is the name; its other text is the role line.
    It belongs to the last section heading seen (SECTIONS); entries before the first heading are left out.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.year = "", None
        self.entries: list[dict] = []
        self.lines: list[str] = []
        self.section: str | None = None
        self.in_title = False
        self.skip = 0
        self.box: dict | None = None
        self.outer: list[dict] = []
        self.bold = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        elif tag in ("script", "style"):
            self.skip += 1
        elif tag in ("article", "p"):
            self.outer.append(self.box)
            self.box = {"tag": tag, "name": [], "rest": [], "link": None}
        elif self.box is not None and tag in ("b", "strong"):
            self.bold = True
        elif self.box is not None and tag == "a" and self.box["link"] is None:
            self.box["link"] = dict(attrs).get("href") or None

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag in ("script", "style"):
            self.skip -= 1
        elif tag in ("b", "strong"):
            self.bold = False
        elif self.box is not None and tag == self.box["tag"]:
            self.finish()

    def handle_data(self, data):
        text = common.norm(data)
        if self.in_title:
            self.title += data
        if self.skip or not text:
            return
        if text.lower() in SECTIONS:
            self.section = text
            self.lines.append(text)
        elif match := COPYRIGHT_RE.search(text):
            self.year = match[1]
            self.lines.append(text)
        if self.box is not None:
            self.box["name" if self.bold and not self.box["rest"] else "rest"].append(data)

    def finish(self):
        box, self.box = self.box, self.outer.pop()
        name, rest = common.norm("".join(box["name"])), common.norm("".join(box["rest"]))
        if self.section and name:
            self.entries.append({"name": name, "rest": rest, "section": self.section, "link": box["link"]})
            self.lines.append(f"{name} {rest}".strip())


def parse(html: str) -> BoardParser:
    parser = BoardParser()
    parser.feed(html)
    return parser


def check_page(parser: BoardParser) -> None:
    """Raises StructureError when the title, the board entries or the copyright year are missing."""
    if not common.norm(parser.title):
        raise StructureError("page title missing")
    if not any(e["section"].lower() == BOARD for e in parser.entries):
        raise StructureError("no entry under the 'Board of directors' heading")
    if parser.year is None:
        raise StructureError("no copyright year to date the page")


def split_job(rest: str) -> tuple[str, str]:
    """The job title and the company of a role line "Title at Company"; the company is empty without " at "."""
    job, _, company = rest.partition(" at ")
    if " at " in company:
        company = company.split(", ")[0]
    return job.strip(), company.strip()


def build_rows(parser: BoardParser, chamber: dict, raw_path: str, fetched: str) -> list[dict]:
    """One row per named person, the first one when a name repeats on the page; the delegation's own side is left out.

    A company that is the chamber itself is left out as employer: its works_at claim would collide with member_of.
    """
    rows, seen = [], set()
    for entry in parser.entries:
        job, company = split_job(entry["rest"])
        name, key = entry["name"], common.row_key(LIST, entry["name"], None, chamber["key"])
        if key in seen or any(word in entry["rest"].casefold() for word in STAFF):
            continue
        seen.add(key)
        own = company.casefold() in (chamber["name"].casefold(), chamber["key"])
        institutions = [{"name": company, "relation": "employer"}] if company and not own else []
        rows.append({
            "list": LIST, "row_key": key, "name": name, "name_on_page": name, "year": None,
            "role": job or entry["section"], "institutions": institutions + [{"name": chamber["name"], "relation": "member_of"}],
            "field": None, "place": None, "jurisdiction": None,
            "profile_url": urljoin(chamber["url"], entry["link"]) if entry["link"] else None,
            "source_url": chamber["url"], "source_title": common.norm(parser.title), "source_date": parser.year,
            "date_method": "page text", "page": None, "quote": common.norm(f"{name} {entry['rest']}"),
            "raw_path": raw_path, "fetched_at": fetched,
        })
    return rows


def check_robots(url: str, fetch=common.fetch) -> None:
    """Read the host's robots.txt and raise Forbidden when it bars the page for this client or cannot be read.

    A 404 on robots.txt means no rules.
    """
    parts = urlsplit(url)
    robots = RobotFileParser()
    try:
        robots.parse(fetch(f"{parts.scheme}://{parts.netloc}/robots.txt").text.splitlines())
        robots.modified()
    except httpx.HTTPStatusError as err:
        if err.response.status_code != 404:
            raise Forbidden(f"robots.txt of {parts.netloc} answered {err.response.status_code}") from err
        robots.allow_all = True
    if not robots.can_fetch(common.USER_AGENT, url):
        raise Forbidden(f"robots.txt of {parts.netloc} forbids {url}")


def main() -> None:
    rows, today = [], date.today().isoformat()
    for chamber in CHAMBERS:
        check_robots(chamber["url"])
        resp = common.fetch(chamber["url"])
        parser = parse(resp.text)
        check_page(parser)
        raw_path = common.save_raw(LIST, chamber["filename"], resp.content, "\n".join([common.norm(parser.title), *parser.lines]))
        found = build_rows(parser, chamber, raw_path, today)
        print(f"{chamber['key']}: {len(found)} rows")
        rows += found
    out = common.write_rows(LIST, rows)
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    try:
        main()
    except (StructureError, Forbidden, ValueError, httpx.HTTPError) as err:
        print(f"chambers: {err}", file=sys.stderr)
        sys.exit(1)
