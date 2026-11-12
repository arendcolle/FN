# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "docling"]
# ///
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "missions"
YEAR = 2022
ORIGIN = "https://www.globalatlanta.com/wp-content/uploads/Belgian-Economic-Mission-USA_Program-updated-on-03.06.2022.pdf"
STAMP = "20220611174920"
URL = f"https://web.archive.org/web/{STAMP}id_/{ORIGIN}"
FILENAME = "Belgian-Economic-Mission-USA_Program-updated-on-03.06.2022.pdf"
SOURCE_TITLE = f"Belgian Economic Mission USA, Program, updated 3 June 2022 ({ORIGIN})"
SOURCE_DATE, DATE_METHOD = "2022-06-03", "document heading"
DOC_TITLE = "Program of the Belgian Economic Mission to the United States of America"
UPDATED = "Update 3/06/2022"
DAYS = 8
MIN_ROWS = 40
SKIPS = ("staff of the delegation's side", "royal family or minister", "no title or employer on any line",
         "line not split with confidence")

TIME = r"\d{1,2}[:.]\d{2}"
RANGE = rf"(?<![\d(:.]){TIME} ?[-–] ?{TIME}"
HEAD_RE = re.compile(rf"{RANGE}(?: \([^()]*\))? (?P<title>.+?)(?= [·●] | o (?=[A-Z0-9])| {RANGE}|$)")
BARE_RANGE = re.compile(rf"^{RANGE}$")
TITLE_END = re.compile(r" \(?(?:Lead|Venue|Participants?)\b.*$")
ITEM_SEP = re.compile(r" [·●] | ?; | o (?=[A-Z0-9]|moderated)")
MARK_RE = re.compile(r"\[(PDF page \d+|day|left|right|footer)\]")
DAY_RE = re.compile(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), \d{1,2} June 2022\b")
COLUMN_HEAD = re.compile(r"^(?:(?:HRH Princess \w+, Representative of His Majesty the King, and Ministers|Business delegation)\s*)+")
MARKERS = re.compile(r"(?i)\b(?:moderated by|by|from)\s+")
HONOURS = {"HE", "H.E.", "HRH"}
PREFIXES = {"Mr", "Mrs", "Ms", "Dr", "Prof", "Ir", "Professor", "Ambassador", "Dean", "Rector", "Assoc"}
PARTICLES = {"de", "van", "der", "den", "von", "da", "di", "du", "le", "la", "del"}
NAME_TOKEN = re.compile(r"^(?:[A-ZÀ-Þ][a-zß-ÿ'’]*[a-zß-ÿ](?:[A-Z][a-zß-ÿ]+)?(?:-[A-ZÀ-Þ][a-zß-ÿ'’]+)*|[A-Z]\.)$")
TITLE_WORDS = re.compile(
    r"(?i)\b(?:CEO|COO|CTO|CFO|CMO|CIO|CISO|President|VP|Director|Chair|Chairman|Chairwoman|Officer|Manager|Mgr|Head|"
    r"Professor|Founder|Co-founder|Partner|Counselor|Counsellor|Secretary|Leader|Lead|Editor|Fellow|Dean|Rector|Expert|"
    r"Executive|Chief|Coordinator|Specialist|Economist|Member|Adviser|Advisor|Attaché|Commissioner|Commissionner|"
    r"Researcher|Scientist|Engineer|Evangelist|Provost|Analyst|Consultant|Coach|Sergeant|Minister|Governor|Mayor)\b")
# Capitalized words that end a name: they start a title or an organization.
NOT_NAME = {"Managing", "Minister", "Princess", "King", "University", "Universiteit", "Tech", "Institute", "Bank",
            "Group", "Labs", "Lab", "Company", "Center", "Centre", "Office", "Hotel", "Inc", "Corporation",
            "Foundation", "Chamber", "Airport", "Port", "Hospital", "School", "College", "Department", "Agency",
            "Association", "Council", "Club", "Museum", "Capital", "Ventures", "Partners", "Therapeutics",
            "Biosciences", "Pharma", "Industries", "Systems", "Solutions", "Technologies", "Bio", "Wind", "Welcome",
            "Speech", "Introduction", "Presentation", "Keynote", "Panel", "Session", "Opening", "Closing"}
CAPITAL_PARTICLES = {"Van", "De", "Le", "Du", "Da", "Di", "Von", "Der", "Den", "La", "Del"}
SUFFIXES = {"Inc", "Inc.", "LLC", "Ltd", "Ltd.", "Corp", "Corp.", "Co.", "NV", "N.V.", "SA", "S.A.", "BV", "B.V.",
            "GmbH", "PLC", "LLP"}
ACRONYM = r"(?:CEO|COO|CTO|CFO|CMO|CIO|CISO)"
# A title that the program runs straight into the employer's name, with no comma, "at" or "of" between them.
BARE_TITLE = re.compile(
    rf"(?P<title>{ACRONYM}(?: (?:and|&) (?:Co-?[Ff]ounder|Founder|President))?|(?:Senior|Executive) Vice President|"
    r"Managing Director|Executive Director|Managing Partner|Chief Economist|Chief [A-Z][A-Za-z&\- ]*? Officer) "
    r"(?P<employer>[A-Z0-9].*)$")
# "Head of", "Secretary of" and the like name a department or an office, not the employer.
OF_TITLE_ENDS = {"Head", "Chief", "Secretary", "Member", "Commissioner", "Governor", "Mayor", "Minister",
                 "Professor", "Ambassador", "Coach"}
# Heads of logistics, not sessions: a speaker after one gets no session from it.
LOGISTICS = re.compile(r"^(?:Bus )?(?:Transfer|Motorcade|Flight|Check-in|Take away|Breakfast for|Private time)")
CONNECTORS = {"of", "and", "for", "the", "de", "du", "des", "la", "le", "van", "&", "at", "in", "on", "et", "der",
              "den", "voor", "/"}
STAFF = re.compile(r"Flanders Investment & Trade|\bFIT\b|Delegation of Flanders|\bAWEX\b|(?i:hub\.brussels)|"
                   r"Belgian Foreign Trade Agency|(?<!Honorary )\bConsul\b|Consul General|Consulate|Embassy|"
                   r"\bAmbassador\b|Permanent Representative of Belgium|Foreign Affairs")
ORG_IN_PARENS = re.compile(r"\((?P<org>[^(),]+), (?P<name>[^(),]+), (?P<title>[^()]+)\)")
# "Nvidia - Director AI - Mr. Ada Example ( SF )" and "University Ghent - Rector Ada Example ( BE )"
ORG_FIRST = re.compile(r"^(?P<org>[^-]+?) - (?:(?P<title>[^-]+?) - )?(?P<person>[^-]+?)\s*(?:\(\s*[A-Z]{2,3}\s*\))?$")


class StructureError(Exception):
    pass


def fold(name: str) -> str:
    """The first and last token of a name, accents and case folded, so a middle initial joins two spellings."""
    tokens = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().split()
    return f"{tokens[0]}-{tokens[-1]}"


def take_name(text: str) -> tuple[str, str] | None:
    """Split text into a leading person name, without prefixes such as Mr or Dr, and the rest; None without a name."""
    tokens = list(re.finditer(r"\S+", text))
    i = 0
    while i < len(tokens) and tokens[i].group().rstrip(".") in PREFIXES:
        i += 1
    start, kept, end = i, [], None
    while i < len(tokens):
        word = tokens[i].group()
        core = word.rstrip(",;:")
        bare = core.rstrip(".") if core.endswith(".") and not re.fullmatch(r"[A-Z]\.", core) else core
        if bare in ("Jr", "III") and len(kept) >= 2:
            kept.append(i)
        elif bare in NOT_NAME or TITLE_WORDS.fullmatch(bare):
            break
        elif NAME_TOKEN.match(bare) or (bare in PARTICLES and i + 1 < len(tokens)):
            kept.append(i)
        else:
            break
        end = tokens[i].start() + len(bare)
        i += 1
        if core != word or bare != core:
            break
    words = [tokens[k].group().rstrip(",;:") for k in kept]
    full = [w for w in words if w.lower() not in PARTICLES and not re.fullmatch(r"[A-Z]\.", w)]
    if len(full) < 2 or words[-1] in CAPITAL_PARTICLES or words[-1].lower() in PARTICLES:
        return None
    return text[tokens[start].start():end], text[end:]


def employer_ok(employer: str) -> bool:
    """An employer starts with a capital or a digit and holds no title word, dash, "at" or lowercase prose."""
    words = employer.split()
    if not words or not re.match(r"[A-Z0-9]", employer) and len(words) > 1:
        return False
    if TITLE_WORDS.search(employer) or any(sep in employer for sep in (" - ", " / ", " at ", " by ")):
        return False
    return len(words) == 1 or all(not w.isalpha() or not w.islower() or w in CONNECTORS for w in words)


def parts_of(tail: str) -> list[str]:
    """The tail split at commas outside brackets, with a company suffix such as Inc kept on its name."""
    parts, depth, current = [], 0, ""
    for ch in tail:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    merged: list[str] = []
    for part in (p.strip() for p in parts):
        if part in SUFFIXES and merged:
            merged[-1] += ", " + part
        elif part:
            merged.append(part)
    while len(merged) > 1 and merged[-1][0].islower():
        merged.pop()
    return merged


def split_title(tail: str) -> tuple[str, str] | None:
    """(title, employer) when the tail names both in a form the program uses; None when unsure."""
    parts = parts_of(tail)
    if len(parts) == 2:
        title, employer = parts
    elif len(parts) != 1:
        return None
    elif parts[0].count(" at ") == 1:
        title, employer = parts[0].split(" at ")
    elif m := BARE_TITLE.match(parts[0]):
        title, employer = m.group("title"), m.group("employer")
    elif " of " in parts[0]:
        title, employer = parts[0].split(" of ", 1)
        employer = employer.removeprefix("the ")
        if not title.strip() or " of " in employer or " for " in employer or title.split()[-1] in OF_TITLE_ENDS:
            return None
    else:
        return None
    title, employer = title.strip(), employer.strip().rstrip(".").strip()
    # "for Marketing, Communications and Engagement" is one title broken by its own comma.
    if len(parts) == 2 and " for " in title and " and " in employer:
        return None
    if not TITLE_WORDS.search(title) or not employer_ok(employer):
        return None
    return title, employer


def classify(text: str, at_start: bool) -> tuple[str, str, str | None, str | None] | None:
    """(kind, name, title, employer) for one person phrase; kind is row or a reason of SKIPS; None when no person.

    At the start of an item a name counts only when a separator follows it, since a session title looks like one.
    """
    text = re.sub(r"^(?:Moderator|Panelists?)\s*:\s*", "", text.strip())
    first = text.split(" ", 1)
    if first[0] in HONOURS and len(first) > 1:
        name = re.split(r",| - ", first[1])[0].strip()
        rest = first[1][len(name):]
        if not name:
            return None
        if first[0] == "HRH" or not rest.strip(" .") or re.search(r"Minister|State Secretary", rest):
            return SKIPS[1], name, None, None
        if STAFF.search(rest):
            return SKIPS[0], name, None, None
        text = first[1]
    found = take_name(text)
    if not found:
        return None
    name, rest = found
    rest = re.sub(r"\s*\([a-z][^()]*\)\s*$", "", rest)
    rest = re.sub(r"\s+(?:and|&)$", "", re.split(r"(?<=[A-Za-z]{3})\. (?=[A-Z])", rest)[0].rstrip(" .,"))
    if m := re.match(r"\s*(?:,|-|–)\s*(.+)$", rest):
        tail = m.group(1)
    elif re.match(rf"\s+{ACRONYM}\b", rest):
        tail = rest.strip()
    elif at_start:
        return None
    else:
        return (SKIPS[0] if STAFF.search(rest) else SKIPS[3] if TITLE_WORDS.search(rest) else SKIPS[2]), name, None, None
    split = split_title(tail)
    if split is None:
        reason = SKIPS[0] if STAFF.search(tail) else SKIPS[3] if TITLE_WORDS.search(tail) else SKIPS[2]
        return reason, name, None, None
    if STAFF.search(" ".join(split)):
        return SKIPS[0], name, None, None
    return "row", name, *split


def people_in(item: str) -> list[tuple[str, str, str | None, str | None]]:
    """Every person phrase of one program item, classified; two people joined by "and" or "&" are two phrases."""
    body = re.sub(rf"^(?:[·●o] )?(?:{TIME}:? )?(?:o )?", "", item.strip())
    found = []
    for k, segment in enumerate(MARKERS.split(body)):
        pieces, rest = [], segment
        for m in list(re.finditer(r",? (?:and|&) ", segment))[::-1]:
            after = take_name(re.sub(r"^(?:HE|H\.E\.|HRH) ", "", rest[m.end():]))
            known = classify(rest[m.end():], at_start=False)
            if after and (not after[1].strip(" .") or after[1].lstrip().startswith(",") and known and known[0] != SKIPS[2]):
                pieces.insert(0, rest[m.end():])
                rest = rest[:m.start()]
        for j, piece in enumerate([rest] + pieces):
            if person := classify(piece, at_start=k == 0 and j == 0):
                found.append(person)
    if (m := ORG_FIRST.match(body)) and not take_name(m.group("org")) and "," not in m.group("org"):
        title, person = m.group("title"), m.group("person")
        if title is None and person.split(" ", 1)[0] in ("Rector", "Dean"):
            title = person.split(" ", 1)[0]
        name = take_name(person)
        if title and name and not name[1].strip() and TITLE_WORDS.search(title) and employer_ok(m.group("org")):
            found.append(("row", name[0], title.strip(), m.group("org").strip()))
    for m in ORG_IN_PARENS.finditer(body):
        name = take_name(m.group("name"))
        title, org = m.group("title").strip(), m.group("org").strip()
        if name and not name[1].strip() and TITLE_WORDS.search(title) and employer_ok(org) and not STAFF.search(org):
            found.append(("row", name[0], title, org))
    return found


def blocks(layer: str) -> list[tuple[int, str, str]]:
    """(page, column or marker kind, text) for every marked block of a text layer."""
    out, page = [], 0
    pieces = MARK_RE.split(layer)
    for mark, text in zip(pieces[1::2], pieces[2::2]):
        if mark.startswith("PDF page"):
            page = int(mark.split()[-1])
        else:
            out.append((page, mark, common.norm(text)))
    return out


def parse(layer: str) -> tuple[dict[str, dict], Counter]:
    """The speakers of a program text layer by folded name, each with its sessions; and the people left out by reason.

    Raises StructureError when the layer lacks the program title, the "updated on" line or its days.
    """
    if DOC_TITLE not in layer or UPDATED not in layer:
        raise StructureError("the program title or its 'Update 3/06/2022' line is missing")
    found = blocks(layer)
    days = {text for _, kind, text in found if kind == "day" and DAY_RE.match(text)}
    if len(days) < DAYS:
        raise StructureError(f"expected {DAYS} program days, found {len(days)}")
    people: dict[str, dict] = {}
    reasons: dict[str, set[str]] = {}
    session: dict[str, str | None] = {"left": None, "right": None}
    title_next: dict[str, bool] = {"left": False, "right": False}
    for page, column, text in found:
        if column not in session:
            continue
        if BARE_RANGE.match(text):
            title_next[column] = True
            continue
        if title_next[column]:
            session[column], title_next[column] = TITLE_END.sub("", text).strip(), False
            continue
        heads = [(m.start(), None if LOGISTICS.match(m.group("title")) else TITLE_END.sub("", m.group("title")).strip())
                 for m in HEAD_RE.finditer(text)]
        starts = [0] + [m.end() for m in ITEM_SEP.finditer(text)]
        ends = [m.start() for m in ITEM_SEP.finditer(text)] + [len(text)]
        for start, end in zip(starts, ends):
            item = text[start:end].strip()
            current = next((title for at, title in reversed(heads) if at <= start), session[column])
            for kind, name, title, employer in people_in(item):
                key = fold(name)
                person = people.get(key)
                if kind == "row" and (person is None or "title" not in person):
                    people[key] = {"name": name, "title": title, "employer": employer, "quote": item, "page": page,
                                   "sessions": person["sessions"] if person else []}
                elif kind != "row":
                    reasons.setdefault(key, set()).add(kind)
                people.setdefault(key, {"sessions": []})
                if current and current not in people[key]["sessions"]:
                    people[key]["sessions"].append(current)
        if heads:
            session[column] = heads[-1][1]
    speakers = {key: p for key, p in people.items() if "title" in p}
    skips = Counter(min(reasons[key], key=SKIPS.index) for key in reasons if key not in speakers)
    return speakers, skips


def build_rows(speakers: dict[str, dict], layer_path: str, fetched_at: str) -> list[dict]:
    """One seed row per speaker."""
    rows = []
    for person in speakers.values():
        rows.append({
            "list": LIST, "row_key": common.row_key(LIST, person["name"], YEAR), "name": person["name"],
            "name_on_page": person["name"], "year": YEAR, "role": person["title"],
            "institutions": [{"name": person["employer"], "relation": "employer"}],
            "field": "; ".join(person["sessions"]) or None, "place": None, "jurisdiction": None, "profile_url": None,
            "source_url": URL, "source_title": SOURCE_TITLE, "source_date": SOURCE_DATE, "date_method": DATE_METHOD,
            "page": person["page"], "quote": person["quote"], "raw_path": layer_path, "fetched_at": fetched_at,
        })
    return rows


def convert(pdf_bytes: bytes):
    """Run Docling on the program and return its document."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / FILENAME
        path.write_bytes(pdf_bytes)
        return conv.convert(path).document


def layer_of(doc) -> str:
    """The marked text layer: per page its day, its left and right column blocks and its footer."""
    from docling_core.types.doc import ContentLayer
    from docling_core.types.doc.document import TableItem

    lines: list[str] = []
    page = 0

    def add(on: int, kind: str, text: str) -> None:
        nonlocal page
        text = common.norm(text)
        if on != page:
            page = on
            lines.append(f"[PDF page {page}]")
        if kind in ("left", "right"):
            text = COLUMN_HEAD.sub("", text).strip()
        if text:
            lines.append(f"[{'day' if DAY_RE.match(text) else kind}] {text}")

    for item, _ in doc.iterate_items(included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE}):
        if not item.prov:
            continue
        prov = item.prov[0]
        if item.content_layer == ContentLayer.FURNITURE:
            if UPDATED in getattr(item, "text", ""):
                add(prov.page_no, "footer", item.text)
        elif isinstance(item, TableItem):
            for cell in item.data.table_cells:
                add(prov.page_no, "left" if cell.start_col_offset_idx == 0 else "right", cell.text)
        elif getattr(item, "text", ""):
            middle = doc.pages[prov.page_no].size.width / 2
            add(prov.page_no, "left" if prov.bbox.l < middle else "right", item.text)
    return "\n".join(lines)


def main() -> None:
    """Fetch the archived program, parse its speakers and write data/seeds/missions.jsonl."""
    try:
        pdf = common.fetch(URL).content
    except httpx.HTTPError as err:
        sys.exit(f"{LIST}: the Wayback copy {URL} is unavailable ({type(err).__name__}: {err}); nothing written")
    if not pdf.startswith(b"%PDF"):
        raise StructureError(f"{URL} did not answer a PDF")
    layer = layer_of(convert(pdf))
    speakers, skips = parse(layer)
    if len(speakers) < MIN_ROWS:
        raise StructureError(f"only {len(speakers)} speakers found, expected at least {MIN_ROWS}")
    layer_path = common.save_raw(LIST, FILENAME, pdf, layer)
    rows = build_rows(speakers, layer_path, date.today().isoformat())
    out = common.write_rows(LIST, rows)
    print(f"{LIST}: {len(rows)} rows -> {out}")
    for reason in SKIPS:
        print(f"left out, {reason}: {skips[reason]}")


if __name__ == "__main__":
    try:
        main()
    except (StructureError, ValueError) as err:
        print(f"{LIST}: {err}", file=sys.stderr)
        sys.exit(1)
