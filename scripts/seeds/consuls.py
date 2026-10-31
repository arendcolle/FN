# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import re
import sys
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "consuls"
URL = "https://unitedstates.diplomatie.belgium.be/en/belgian-network-us/honorary-consulates/honorary-consulates-united-states"
FILENAME = "honorary-consulates-united-states.html"
ROLE = "Honorary Consul of Belgium"
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
STATE_TOKENS = "|".join(sorted([*STATES, *STATES.values()], key=len, reverse=True))
CITY_RE = re.compile(rf"^(?:.*,\s*)?(?P<city>[^,]+?),?\s+(?:{STATE_TOKENS})\.?$")
ZIP_RE = re.compile(r"[\s,]*\d{5}(?:-\d{4})?$")
CONTACT_RE = re.compile(r"(?i)(?:^|(?<=[\d\w]))(?:Tel|Phone|Fax|Cell|Mobile|E-?mail)\s*:|^www\.|^For |^Please refer")
CONTACT_VALUE_RE = re.compile(r"@|\+\s*\d|\b\d{3}[ .-]\d{3}[ .-]\d{4}\b")
ORG_RE = re.compile(
    r"\b(University|College|School|Institute|Therapeutics|Pharma\w*|LLC|LLP|PLLC|Inc\.?|Corp\.?|Corporation|"
    r"Company|Ltd\.?|Bank|Firm|Group|Foundation|Association|Partners|Hospital|Laboratories)\b"
)
TITLE_RE = re.compile(r"^(?:Mr|Mrs|Ms|Miss|Dr|Prof|Hon)\.?\s+")
SUFFIX_RE = re.compile(r",?\s*(?:Esq|Jr|Sr|PhD|MD)\.?$")
HEAD_TAGS = {"h1", "h2", "h3", "h4"}
BLOCK_TAGS = {"p", "div", "li", "tr", "ul", "ol", "table", "section"}


class StructureError(Exception):
    pass


class LineParser(HTMLParser):
    """Turn HTML into (kind, text) lines where kind is h1 to h4 or text and each heading is one line."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[str, str]] = []
        self.buf: list[str] = []
        self.kind = "text"
        self.skip = 0
        self.title = ""
        self.in_title = False

    def flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf).replace("\xa0", " ")).strip()
        if text:
            self.lines.append((self.kind, text))
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag in HEAD_TAGS:
            self.flush()
            self.kind = tag
        elif tag in BLOCK_TAGS:
            self.flush()
        elif tag == "br":
            if self.kind == "text":
                self.flush()
            else:
                self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        elif tag == "title":
            self.in_title = False
        elif tag in HEAD_TAGS:
            self.flush()
            self.kind = "text"
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.buf.append(data)


def parse_lines(html: str) -> tuple[list[tuple[str, str]], str]:
    parser = LineParser()
    parser.feed(html)
    parser.flush()
    return parser.lines, common.norm(parser.title)


def source_date(lines: list[tuple[str, str]]) -> str:
    for i, (_, text) in enumerate(lines):
        if text == "Last updated on" and i + 1 < len(lines):
            try:
                return datetime.strptime(lines[i + 1][1], "%B %d, %Y").date().isoformat()
            except ValueError:
                break
    raise StructureError('no parseable "Last updated on <date>" line')


def is_person_heading(text: str) -> bool:
    if text.startswith("For ") or "Counties" in text:
        return False
    return bool(re.match(r"^[A-Z][^\s]*(?:\s+\S+)+", text))


def split_entries(lines: list[tuple[str, str]]) -> list[dict]:
    """Walk the region between the 'Honorary consulates in the United States' h2 and 'Previous' and collect consul entries."""
    start = next((i for i, (k, t) in enumerate(lines) if k == "h2" and t == "Honorary consulates in the United States"), None)
    if start is None:
        raise StructureError("h2 'Honorary consulates in the United States' missing")
    end = next((i for i in range(start, len(lines)) if lines[i][0] == "text" and lines[i][1].startswith("Previous")), None)
    if end is None:
        raise StructureError("'Previous' end marker missing")
    entries, state, current = [], None, None
    for kind, text in lines[start:end]:
        if kind == "h3":
            state, current = text, None
        elif kind == "h4":
            current = None
            if is_person_heading(text):
                if state is None:
                    raise StructureError(f"consul heading before any state heading: {text!r}")
                current = {"state": state, "heading": text, "body": []}
                entries.append(current)
        elif kind == "text" and current is not None:
            current["body"].append(text)
    return entries


def address_lines(body: list[str]) -> list[str]:
    """Lines after the heading up to the first contact, visa or area line, cut at a glued contact marker."""
    out = []
    for text in body:
        match = CONTACT_RE.search(text)
        if match:
            if match.start() > 0:
                out.append(text[: match.start()].strip())
            break
        out.append(text)
    return out


def city_of(addr: list[str]) -> str | None:
    for text in reversed(addr):
        match = CITY_RE.match(ZIP_RE.sub("", text).strip())
        if match:
            return match["city"].strip()
    return None


def employer_of(addr: list[str]) -> str | None:
    for text in addr:
        if ORG_RE.search(text) and not re.match(r"^\d", text) and text != "Honorary Consulate of Belgium":
            return text
    return None


def clean_name(name_on_page: str) -> str:
    name = SUFFIX_RE.sub("", TITLE_RE.sub("", name_on_page)).strip()
    if not name:
        raise StructureError(f"empty name from {name_on_page!r}")
    return name


def build_rows(entries: list[dict], date_str: str, title: str, raw_path: str, fetched: str) -> list[dict]:
    people: dict[str, dict] = {}
    for entry in entries:
        heading = re.sub(r",?\s*Honorary Consul of Belgium\s*$", "", entry["heading"]).strip()
        name = clean_name(heading)
        person = people.setdefault(name, {"heading": heading, "full": entry["heading"], "addr": address_lines(entry["body"]), "states": []})
        if entry["state"] not in person["states"]:
            person["states"].append(entry["state"])
    rows = []
    for name, p in people.items():
        quote = common.norm(" ".join([p["full"], *p["addr"]]))
        employer = employer_of(p["addr"])
        row = {
            "list": LIST, "row_key": common.row_key(LIST, name, None), "name": name, "name_on_page": p["heading"],
            "year": None, "role": ROLE, "institutions": [{"name": employer, "relation": "employer"}] if employer else [],
            "field": None, "place": city_of(p["addr"]), "jurisdiction": p["states"], "profile_url": None,
            "source_url": URL, "source_title": title, "source_date": date_str, "date_method": "page text",
            "page": None, "quote": quote, "raw_path": raw_path, "fetched_at": fetched,
        }
        for key in ("quote", "place", "name"):
            if row[key] and CONTACT_VALUE_RE.search(row[key]):
                raise StructureError(f"contact detail leaked into {key} for {name}")
        rows.append(row)
    return rows


def main() -> None:
    resp = common.fetch(URL)
    lines, title = parse_lines(resp.text)
    if not title or not any(k == "h1" for k, _ in lines):
        raise StructureError("page title or h1 missing")
    raw_path = common.save_raw(LIST, FILENAME, resp.content, "\n".join(text for _, text in lines))
    entries = split_entries(lines)
    if not entries:
        raise StructureError("no consul entries found")
    rows = build_rows(entries, source_date(lines), title, raw_path, date.today().isoformat())
    out = common.write_rows(LIST, rows)
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    try:
        main()
    except (StructureError, ValueError) as err:
        print(f"consuls: {err}", file=sys.stderr)
        sys.exit(1)
