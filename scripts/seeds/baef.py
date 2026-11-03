# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import datetime
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "baef"
URL = "https://baef.be/baef-be-fellows/"
YEARS = range(1920, 2020)
TOTAL_YEARS = range(2012, 2020)
NOBLE = {"viscount", "baron", "baroness", "count", "countess", "comte", "comtesse", "chevalier", "jonkheer", "vicomte"}
PARTICLES = {"'t", "de", "du", "van", "von", "der", "den", "des", "la", "le", "ten", "ter", "te", "het", "et", "di", "da", "del", "dos", "af"}
NOT_SURNAME = {"LLM", "MBA", "MA", "MS", "PHD", "MD", "US", "USA", "UK", "NYU", "MIT", "UC", "UCLA", "UCSF", "UCSD", "NIH", "SUNY",
               "CUNY", "GSB", "SIPA", "UCL", "ULB", "ULG", "VUB", "UGENT", "KULEUVEN", "UA", "CG", "RF", "PDF", "GF", "DNA", "RNA"}
CLERICAL = {"canon", "chanoine", "père", "pere", "abbé", "abbe"}
HOMES = {
    "UGent": "Ghent University", "KULeuven": "KU Leuven", "ULB": "Université libre de Bruxelles",
    "ULg": "Université de Liège", "UCL": "Université catholique de Louvain", "UCLouvain": "Université catholique de Louvain",
    "VUB": "Vrije Universiteit Brussel", "UA": "University of Antwerp", "UNamur": "University of Namur",
    "UMons": "University of Mons", "UHasselt/LUC": "Hasselt University", "FUNDP": "University of Namur",
    "UMH": "University of Mons", "FSAGX": "Gembloux Agro-Bio Tech", "FPMs": "Faculté Polytechnique de Mons",
}
NO_HOME = {"", "other", "none", "music"}
TITLE_WORDS = (r"(?:de\s+heer|mr|ms|mrs|mme|mlle|dr|drs|prof|professeur|professor|md|monsieur|madame|mevr|mevrouw|dhr|mw|ir"
               r"|baron|baroness|viscount|count|comte|comtesse|chevalier|jonkheer)")
TITLE_SEP = rf"[.;/\s]*(?:,(?=\s*{TITLE_WORDS}\b)[.;/\s]*)?"
HEAD = re.compile(rf'^"?\s*(?P<title>(?:{TITLE_WORDS}\b{TITLE_SEP})*)(?P<sur>[^,;]+?)\s*[,;]\s*(?P<given>[^,]+?)\s*(?:,|$)', re.IGNORECASE)
NEXT_SEG = re.compile(r"^\s*,\s*([^,]+?)\s*(?:,|$)")
HOST_WORD = re.compile(
    r"\b(U(?!\.S)|Univ\w*|College|Institut\w*|School|Hospital|Medical|Center|Centre|Clinic|Laborator\w*|Lab|Academy|Observatory|Foundation"
    r"|NIH|MIT|M\.I\.T\.|UC|UCLA|UCSF|NYU|SUNY|CalTech|Caltech|Harvard|Yale|Columbia|Stanford|Princeton|Cornell|Duke|Berkeley"
    r"|Wharton|Kellogg|Juilliard|Julliard|Georgetown|Dartmouth|Tufts|Vanderbilt|Rockefeller|Scripps|Salk|Northwestern|Carnegie"
    r"|Emory|Brown|Rice|Johns Hopkins|Conservator\w*)(?=\W|$)"
)
SUFFIX = {"jr.", "jr", "sr.", "sr", "md", "phd"}


class Structure(Exception):
    """The page no longer has the markup this scraper expects."""


class Page(HTMLParser):
    """Collects headings, table cells and loose text between the 'Belgian Alumni' and 'About us' headings."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events, self.on, self.cell_depth, self.head, self.head_buf, self.cell_buf = [], False, 0, None, [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self.head, self.head_buf = tag, []
        elif tag == "td":
            self.cell_depth, self.cell_buf = self.cell_depth + 1, []
        elif tag in ("p", "br", "li") and self.on:
            self.newline()

    def handle_endtag(self, tag):
        if tag == self.head:
            text = common.norm("".join(self.head_buf))
            self.head = None
            if tag == "h3" and text == "Belgian Alumni":
                self.on = True
            elif tag == "h3" and text == "About us":
                self.on = False
            if self.on:
                self.events.append(("h", tag, text))
        elif tag == "td":
            self.cell_depth -= 1
            if self.on:
                self.events.append(("td", "".join(self.cell_buf)))
        elif tag in ("p", "li") and self.on:
            self.newline()

    def handle_data(self, data):
        if self.head:
            self.head_buf.append(data)
        elif self.cell_depth:
            self.cell_buf.append(data)
        elif self.on:
            self.events_text().append(data)

    def newline(self) -> None:
        (self.cell_buf if self.cell_depth else self.events_text()).append("\n")

    def events_text(self) -> list:
        """Return the open loose-text buffer, starting one when the last event is not text."""
        if not self.events or self.events[-1][0] != "text":
            self.events.append(("text", []))
        return self.events[-1][1]


def split_sections(events: list) -> tuple[dict, list]:
    """Group the page into {year: {'intro': [...], 'cells': [...]}} and return it with the text-layer lines."""
    years, lines, year = {}, [], None
    for ev in events:
        if ev[0] == "h":
            lines.append(ev[2])
            if ev[1] in ("h1", "h2") and re.fullmatch(r"\d{4}", ev[2]):
                year = int(ev[2])
                if year in years:
                    raise Structure(f"year heading {year} appears twice")
                years[year] = {"intro": [], "cells": []}
            elif ev[1] in ("h1", "h2", "h3"):
                year = None
        elif ev[0] == "td":
            text = common.norm(ev[1])
            if text:
                lines.append(text)
                if year:
                    years[year]["cells"].append(text)
        else:
            for part in "".join(ev[1]).split("\n"):
                part = common.norm(part)
                if part:
                    lines.append(part)
                    if year:
                        years[year]["intro"].append(part)
    return years, lines


def shouted(token: str) -> bool:
    """True for a token printed mostly in capitals, such as BAHREBAR or NlHARD."""
    letters = [c for c in token if c.isalpha()]
    return len(letters) >= 2 and sum(c.isupper() for c in letters) * 2 > len(letters)


def shouted_any(token: str) -> bool:
    """True when any hyphen part of the token is shouted, as in Strugnell-PIERLOT."""
    return any(shouted(part) for part in re.split(r"[-–]", token) if part)


def plain(token: str) -> str:
    return re.sub(r"[^A-Za-z]", "", token).upper()


def surname_ok(sur: str, titled: bool) -> bool:
    """Check that the text before the first comma reads as a surname block."""
    tokens = sur.split()
    if not 1 <= len(tokens) <= 7 or re.search(r"[\d@:;]", sur) or not any(c.isupper() for c in sur):
        return False
    if titled:
        return True
    if not any(shouted_any(t) and plain(t) not in NOT_SURNAME for t in tokens):
        return False
    return all(t.lower() in PARTICLES or t in ("-", "–") or shouted_any(t) or t[0].isupper() for t in tokens)


def given_ok(given: str) -> bool:
    """Check that the text after the surname reads as a given name."""
    tokens = given.split()
    if not 1 <= len(tokens) <= 5 or not (given[0].isupper() or tokens[0].lower().rstrip(".") in CLERICAL):
        return False
    ok = all(re.fullmatch(r"\(?[^\W\d_][\w.'\-()~]*", t) and plain(t) not in NOT_SURNAME for t in tokens)
    return ok and not any(shouted(t) and "." not in t for t in tokens)


def split_no_comma(cell: str) -> dict | None:
    """Split a name-only cell such as 'RENARD Séverine' into surname and given name."""
    tokens = cell.split()
    cut = next((i for i, t in enumerate(tokens) if not (t.lower() in PARTICLES or shouted_any(t))), None)
    if not cut:
        return None
    sur, given = " ".join(tokens[:cut]), " ".join(tokens[cut:])
    if not surname_ok(sur, False) or not given_ok(given):
        return None
    return {"start": 0, "end": len(cell), "sur": sur, "given": given}


def parse_head(cell: str, name_only: bool) -> dict | None:
    """Return surname, given name and offsets when the cell starts an entry, else None."""
    m = HEAD.match(cell)
    if not m:
        return split_no_comma(cell) if name_only and "," not in cell else None
    sur, given, end = m["sur"].strip(), m["given"].strip(), m.end("given")
    if given.lower() in NOBLE:
        nxt = NEXT_SEG.match(cell[end:])
        if not nxt:
            return None
        given, end = f"{given} {nxt[1]}", end + nxt.end(1)
    if not surname_ok(sur, bool(m["title"].strip())) or not given_ok(given):
        return None
    return {"start": m.start("title"), "end": end, "sur": sur, "given": given}


def natural_surname(sur: str) -> str:
    out = []
    for token in sur.split():
        if token.lower() in PARTICLES and token.isupper():
            out.append(token.lower())
        else:
            out.append(re.sub(r"[^\W\d_]+", lambda w: w[0].capitalize() if shouted(w[0]) else w[0], token))
    return " ".join(out)


def natural_given(given: str) -> str:
    kept = [t for t in given.split() if t.lower().rstrip(".") not in NOBLE | CLERICAL and t.lower() not in SUFFIX]
    return " ".join(re.sub(r"[^\W\d_]+", lambda w: w[0].capitalize() if shouted(w[0]) else w[0], t) for t in kept)


def split_rest(rest: str) -> tuple[str | None, str | None, list]:
    """Split the text after the given name into role, field and institutions; unknown parts stay None."""
    segs = [s.strip() for s in rest.split(",")][1:]
    if segs and segs[0] not in HOMES and segs[0].lower() not in NO_HOME:
        segs.insert(0, "")
    home = segs[0] if segs else ""
    role = (segs[1] if len(segs) > 1 else "") or None
    tail = [s for s in segs[2:] if s]
    insts = []
    if home.lower() not in NO_HOME:
        insts.append({"name": HOMES.get(home, home), "relation": "home"})
    k = next((i for i, s in enumerate(tail) if HOST_WORD.search(s)), None)
    field = ", ".join(tail[:k] if k is not None else tail).strip(" ;:-–") or None
    if k is not None:
        host = re.split(r"\s+[–-]\s*|\s*[–-]\s+|;", tail[k])[0].strip(" ;") or None
        if host:
            insts.append({"name": host, "relation": "host"})
    return role, field, insts


def split_glued(cell: str) -> list[str]:
    """Split a name-only cell that holds two names run together, such as 'BOUTE, Raymond CASSIMAN, Jean-Jacques'."""
    tokens, parts, start, comma_seen = cell.split(), [], 0, False
    for i, t in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        if comma_seen and shouted(t) and len(t) > 2 and "." not in t and not shouted(prev) and prev.lower() not in PARTICLES and not prev.endswith(","):
            parts.append(" ".join(tokens[start:i]))
            start, comma_seen = i, False
        comma_seen = comma_seen or "," in t
    return parts + [" ".join(tokens[start:])]


def build_entries(year: int, cells: list) -> list:
    """Group a year's cells into entries; a cell that is not an entry start continues the previous one."""
    entries = []
    for cell in [part for c in cells for part in (split_glued(c) if year < 2000 else [c])]:
        head = parse_head(cell, year < 2000)
        if head:
            entries.append({"head": head, "cells": [cell]})
        elif entries:
            entries[-1]["cells"].append(cell)
        else:
            raise Structure(f"{year}: first cell is not an entry: {cell[:80]!r}")
    return entries


def make_row(year: int, entry: dict, raw_path: str, today: str) -> dict:
    quote = re.sub(r"[\s,]*\bTRUE\s*$", "", " ".join(entry["cells"])).strip()
    head = entry["head"]
    first = entry["cells"][0]
    on_page = first[head["start"]:head["end"]].strip()
    if on_page.startswith('"'):
        on_page = on_page[1:].strip()
    name = f'{natural_given(head["given"])} {natural_surname(head["sur"])}'.strip()
    role, field, insts = split_rest(quote[quote.find(on_page) + len(on_page):])
    return {
        "list": LIST, "row_key": common.row_key(LIST, name, year), "name": name, "name_on_page": on_page, "year": year,
        "role": role, "institutions": insts, "field": field, "place": None, "jurisdiction": None, "profile_url": None,
        "source_url": URL, "source_title": "BAEF Belgian Fellows", "source_date": None, "date_method": "none",
        "page": None, "quote": quote, "raw_path": raw_path, "fetched_at": today,
    }


def check_totals(years: dict, counts: dict) -> None:
    """Compare each parsed year with the 'N Belgian Fellows' line the page prints for 2012 to 2019."""
    for year in TOTAL_YEARS:
        found = re.findall(r"(\d+)\s*Belgian Fellows", " ".join(years[year]["intro"]))
        if len(found) != 1:
            raise Structure(f"{year}: expected one 'N Belgian Fellows' line, found {found}")
        stated, parsed = int(found[0]), counts[year]
        if abs(parsed - stated) > max(5, round(stated * 0.1)):
            raise Structure(f"{year}: parsed {parsed} entries, page states {stated} Belgian Fellows")


def main() -> int:
    resp = common.fetch(URL)
    page = Page()
    page.feed(resp.text)
    if not any(ev[:2] == ("h", "h3") and ev[2] == "Belgian Alumni" for ev in page.events):
        raise Structure("'Belgian Alumni' heading missing")
    years, lines = split_sections(page.events)
    if set(years) != set(YEARS):
        raise Structure(f"year headings off: missing {sorted(set(YEARS) - set(years))}, extra {sorted(set(years) - set(YEARS))}")
    raw_path = common.save_raw(LIST, "baef-be-fellows.html", resp.content, "\n".join(lines))
    today = datetime.date.today().isoformat()
    rows, counts, seen = [], {}, set()
    for year in sorted(years, reverse=True):
        entries = build_entries(year, years[year]["cells"])
        if not entries:
            raise Structure(f"{year}: no entries")
        counts[year] = len(entries)
        for i, entry in enumerate(entries):
            row = make_row(year, entry, raw_path, today)
            if not row["name"] or not row["name_on_page"]:
                raise Structure(f"{year}: empty name in {entry['cells'][0][:80]!r}")
            if row["row_key"] in seen:
                row["row_key"] = common.row_key(LIST, row["name"], year, str(i + 1))
            seen.add(row["row_key"])
            rows.append(row)
    check_totals(years, counts)
    out = common.write_rows(LIST, rows)
    print(f"wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Structure as exc:
        print(f"structure check failed: {exc}", file=sys.stderr)
        sys.exit(1)
