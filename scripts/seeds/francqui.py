# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import io
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "francqui"
PAGE_URL = "https://www.francquifoundation.be/english/francqui-fellowships-en/"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
PARTICLES = {"de", "von", "van", "der", "den", "du", "le", "la", "di", "da", "del", "ten", "ter", "het"}
HOMES = {
    "uclouvain": "Université catholique de Louvain", "ucl": "Université catholique de Louvain",
    "kuleuven": "KU Leuven", "ku leuven": "KU Leuven", "kul": "KU Leuven",
    "ugent": "Ghent University", "leuven": "KU Leuven", "ulg": "University of Liège", "uliège": "University of Liège",
    "ulb": "Université libre de Bruxelles", "umons": "University of Mons",
    "ua": "University of Antwerp", "university of antwerp": "University of Antwerp",
    "vub": "Vrije Universiteit Brussel", "fundp": "University of Namur (FUNDP)",
    "fucam": "FUCaM Mons", "fusagx": "FUSAGx (Gembloux)", "ug": "Ghent University", "faculté polytechnique de mons": "Faculté Polytechnique de Mons",
}
HOME_RE = re.compile(
    r"(?<![A-Za-z])(UCLouvain|UCL|KULeuven|KU Leuven|KUL|Leuven|UGent|Ugent|UG|ULiège|ULg|Ulg|ULB|UMons|UA|ua|VUB|FUNDP|FUCAM|FUSAGX"
    r"|University of Antwerp|Faculté Polytechnique de Mons)(?![A-Za-z])"
)
HOST_MARK_RE = re.compile(r"(?:^|\s)(?:went\s+to(?:\s+the)?|to|naar)\s*(?=[A-Z0-9])")
SEP_RE = re.compile(r"\s[-–—]|[-–—]\s|,|\n|\(|:|;|\s(?=for a\s|for the\s|in the\s)|\s(?=[Dd]ept\b|[Dd]epartment\b|[Dd]ivision\b|Prof\b)")
PLACES = ("Urbana-Champaign", "Salt Lake City", "Los Angeles", "San Diego", "San Francisco", "New York", "New Haven",
          "New Brunswich", "New Jersey", "Ann Arbor", "Chapel Hill", "Saint-Louis", "La Jolla", "Washington DC",
          "Washington D.C", "Massachusetts", "Connecticut", "Minnesota", "Cambridge", "California", "Pittsburgh",
          "Philadelphia", "Minneapolis", "Berkeley", "Boston", "Boulder", "Madison", "Austin", "Portland Oregon",
          "Rochester", "N.C", "PA", "MA", "USA")
PLACE_RE = re.compile(r"^\s*(?:" + "|".join(re.escape(p) for p in PLACES) + r")\b\.?[\s,;]*")
ORG_RE = re.compile(r"\b(Dept|Department|Division|School|Laboratory|Lab|Group|Center|Centre|Institute|Prof|Dr|College|"
                    r"Hospital|Faculty|Program|Programme|Campus|Professor|University)\b", re.IGNORECASE)
POSTDOC_RE = re.compile(r"\bPos?t?[-.]?[dD]oc(?:toral|\.)?\.?\s*(?:[Rr]es(?:earch|\.)?)?\s*(?:[:.]\s*)?(?:\b(?:on|in|to)\b\s*)?(?:[:.]\s*)?")
CAL_STATES = ("University of California", "University of Texas", "University of Colorado")
HOST_CANON = {"m.i.t": "Massachusetts Institute of Technology", "mit": "Massachusetts Institute of Technology"}
PLACE_CANON = {"Washington D.C": "Washington DC", "New Brunswich": "New Brunswick", "Portland Oregon": "Portland"}
STATES = {"California", "Massachusetts", "Connecticut", "Minnesota", "New Jersey"}
BARE_HOSTS = {"Columbia", "Harvard", "Yale", "Princeton", "Stanford", "Cornell"}
INSTITUTION_RE = re.compile(r"Universit|College|Institut|Insitute|Hospital|hospital|Center|Centre|School|Laborator|Academy|Clinic|Polytechn")
DISCIPLINE_RE = re.compile(r"\b(?:Biology|Pathology|Chemistry|Physics|Mathematics|Medicine|Neuroscience|Engineering|Economics|Psychology|Healing)\b")
UNIVERSITY_RE = re.compile(r"((?:[A-Z]\w+ )?University of [A-Z]\w+(?: at [A-Z]\w+)?|(?:[A-Z]\w+ )+University)")


def paragraphs(docx: bytes) -> list[str]:
    """Return the text of every w:p in document order, runs joined directly, w:br and w:tab respected."""
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))
    out = []
    for p in root.iter(W + "p"):
        parts = []
        for el in p.iter():
            if el.tag == W + "t":
                parts.append(el.text or "")
            elif el.tag in (W + "br", W + "cr"):
                parts.append("\n")
            elif el.tag == W + "tab":
                parts.append("\t")
            elif el.tag == W + "noBreakHyphen":
                parts.append("-")
        out.append("".join(parts))
    return out


def is_given(tok: str) -> bool:
    """A given-name token: a capitalized word or a single initial like J."""
    if re.fullmatch(r"[A-ZÀ-ÖØ-Þ]\.", tok):
        return True
    return bool(re.fullmatch(r"[A-ZÀ-ÖØ-Þ][^\W\d_]*(?:[-'’][^\W\d_]+)*", tok)) and not tok.isupper()


def is_caps(tok: str) -> bool:
    """A surname token in capitals, at least two letters."""
    return tok.isupper() and len(re.sub(r"[\W\d_]", "", tok)) >= 2


def split_name(text: str):
    """Return (given_tokens, surname_tokens, end_offset) for the name at the start of text, or None."""
    toks = list(re.finditer(r"\S+", text))
    i, given = 0, []
    while i < len(toks) and is_given(toks[i].group()):
        given.append(toks[i].group())
        i += 1
    sur, end = [], 0
    while i < len(toks):
        t = toks[i].group()
        if t.endswith("-") and is_caps(t.rstrip("-")):
            sur.append(t.rstrip("-"))
            end = toks[i].start() + len(t.rstrip("-"))
            break
        if is_caps(t) or t in PARTICLES:
            sur.append(t)
            end = toks[i].end()
            i += 1
        else:
            break
    while sur and sur[-1] in PARTICLES:
        end = text.rfind(sur.pop(), 0, end)
        end = len(text[:end].rstrip())
    if not any(is_caps(t) for t in sur):
        return None
    return given, sur, end


def title_surname(tok: str) -> str:
    """Title-case an all-caps surname token, leave particles alone."""
    return tok if tok in PARTICLES else tok.title()


def clean_host(text: str) -> str | None:
    """Cut the host text to the institution name; None when nothing usable is left."""
    text = common.norm(text)
    dm = re.match(r"[A-Za-z ]+?\s(?:Department|Dept)\s+of\s+the\s+((?:[A-Z]\w+\s)+University)", text)
    if dm:
        return dm.group(1)
    m = SEP_RE.search(text)
    head = text[:m.start()] if m else text
    rest = text[m.start():] if m else ""
    if head.strip() in CAL_STATES and re.match(r"\s*[,\-–]", rest):
        campus = re.match(r"\s*[,\-–]\s*([A-Z][\w.]*(?: [A-Z][\w.]*)?)(?=\s*(?:[-–,]|$|\s[Dd]ept))", rest)
        if campus:
            head = f"{head}, {campus.group(1)}"
    cut = re.match(r"(.*?\b(?:University|Universty))\s+(?!of\b|at\b|School\b|Medical\b|Law\b|Hospital\b|Dept|Department)\S",
                   head)
    if cut:
        head = cut.group(1)
    head = head.strip(" .,;-–—")
    head = re.sub(r"\s+(?:and|et)$", "", head)
    if re.search(r"(?:Center|Centre|Laborator\w*)$", head) and not re.search(r"Universit|College", head):
        um = UNIVERSITY_RE.search(rest)
        if um:
            return um.group(1)
    unit = re.match(r"(?:Department|Dept|Division|Graduate School)\b", head)
    if unit and "Universit" in head:
        um = re.search(r"((?:[A-Z]\w+ )?University of [A-Z]\w+|[A-Z]\w+ University)", head)
        head = um.group(1) if um else head
    if unit and not re.search(r"Universit|College|Institute|Hospital", head) and rest.startswith(","):
        return clean_host(rest[1:])
    head = HOST_CANON.get(head.lower(), head)
    return head if len(head) >= 3 else None


def find_place(host_text: str, host: str | None) -> str | None:
    """Return the US city (else state) named in the first clause of the host text, if any."""
    clause = re.split(r"\s[-–—]\s|;|\n", host_text)[0] + " " + (host or "")
    found = []
    for p in PLACES[:-4]:
        m = re.search(r"(?<![A-Za-z])" + re.escape(p) + r"\b", clause)
        if m and not (host and host.startswith(p)):
            found.append((p in STATES, m.start(), p))
    return PLACE_CANON.get(min(found)[2], min(found)[2]) if found else None


def parse_entry(text: str, name_end: int):
    """Return (role, institutions, field, place) from the part of an entry after the name."""
    rest = text[name_end:]
    role = None
    m = re.match(r"\s*\(([^)]*)\)", rest)
    if m:
        if "Francqui" in m.group(1) and "Prize" not in m.group(1):
            role = common.norm(m.group(1))
        rest = rest[m.end():]
    rest = re.sub(r"\s*\*\s*", " ", re.sub(r"andKUL", "and KUL", rest))
    first = HOME_RE.search(rest)
    mark = HOST_MARK_RE.search(rest, first.end() if first else 0)
    homes, last_home_end = [], 0
    for h in HOME_RE.finditer(rest[:mark.start()] if mark else rest):
        last_home_end = h.end()
        canon = HOMES[h.group(1).lower()]
        if canon not in homes:
            homes.append(canon)
    institutions = [{"name": h, "relation": "home"} for h in homes]
    host_text = rest[mark.end():] if mark else ""
    host = clean_host(host_text) if host_text else None
    place = find_place(host_text, host) if host_text else None
    host_as_field = None
    if host and DISCIPLINE_RE.search(host) and not INSTITUTION_RE.search(host):
        host, host_as_field = None, host
    field = None
    trail = common.norm(rest[last_home_end:]).strip(" .,;:-–—") if homes and not mark and last_home_end else ""
    if trail and not POSTDOC_RE.search(rest):
        am = re.match(r"(.*?)\s+at\s+((?:[A-Z]\w+\s?)+University)$", trail)
        if trail in BARE_HOSTS:
            host, trail = trail, ""
        elif am:
            host, trail = am.group(2), am.group(1)
        field = trail or None
    if host:
        institutions.append({"name": host, "relation": "host"})
    pm = POSTDOC_RE.search(rest)
    if pm:
        stop = [len(rest)]
        sm = re.compile(r"\s[-–—]|[-–—]\s*\n|\n|[-–—]\s*$").search(rest, pm.end())
        if sm:
            stop.append(sm.start())
        if first and first.start() >= pm.end():
            stop.append(first.start())
        if mark and mark.start() >= pm.end() and not first:
            stop.append(mark.start())
        field = re.sub(r"^the ", "", common.norm(rest[pm.end():min(stop)]).strip(" .,;:-–—")) or None
    elif host_text:
        head_len = len(common.norm(host_text)) and SEP_RE.search(common.norm(host_text))
        tail = common.norm(host_text)[head_len.start():] if head_len else ""
        segs = []
        tail = re.sub(r"\([^)]*\)", "", tail)
        for seg in re.split(r"\s[-–—]\s|[-–—]\s|\s[-–—]|\n|;", tail.lstrip(" ,")):
            seg = re.sub(r"^\s*\([^)]*\)[\s,]*", "", seg.lstrip(" ,:."))
            while (pm2 := PLACE_RE.match(seg)):
                seg = seg[pm2.end():]
            seg = re.sub(r"^(?:for a|for the|for|in the)\s+", "", seg.strip(" .,;:-–—"))
            if seg and not ORG_RE.search(seg):
                segs.append(seg)
        field = "; ".join(segs) or None
    return role, institutions, field or host_as_field, place


def main() -> None:
    """Fetch the docx linked from the fellowships page and write data/seeds/francqui.jsonl."""
    page = common.fetch(PAGE_URL)
    links = re.findall(r'href="([^"]*Complete-list-of-Francqui-Fellows[^"]*\.docx)"', page.text)
    if not links:
        sys.exit("francqui: no Complete-list-of-Francqui-Fellows link on the fellowships page")
    doc_url = urljoin(PAGE_URL, links[0])
    doc = common.fetch(doc_url)
    paras = paragraphs(doc.content)
    page_text = re.sub(r"<[^>]+>", " ", page.text)
    common.save_raw(LIST, "francqui-fellowships-en.html", page.content, page_text)
    raw_path = common.save_raw(LIST, doc_url.rsplit("/", 1)[1], doc.content, "\n".join(paras))

    heads = [i for i, t in enumerate(paras) if common.norm(t)]
    title, note = (common.norm(paras[i]) for i in heads[:2])
    nm = re.search(r"last modified (\w+) (\d{4})", note)
    if "Francqui Fellows" not in title or not nm or nm.group(1).lower() not in MONTHS:
        sys.exit(f"francqui: unexpected title lines: {title!r}, {note!r}")
    source_date = f"{nm.group(2)}-{MONTHS.index(nm.group(1).lower()) + 1:02d}"
    date_method = f"document note ({note.strip('()')})"

    entries, year, seen_header = [], None, False
    for i, t in enumerate(paras):
        text = common.norm(t)
        if i in heads[:2] or not text:
            continue
        hm = re.fullmatch(r"(\d{4})\s*[-–]\s*(\d{4})", text)
        if hm:
            if int(hm.group(2)) != int(hm.group(1)) + 1:
                sys.exit(f"francqui: odd cohort header {text!r}")
            year, seen_header = int(hm.group(1)), True
            continue
        if not seen_header:
            sys.exit(f"francqui: text before the first cohort header: {text!r}")
        parsed = split_name(t.strip())
        if parsed is None or not parsed[0]:
            if parsed is not None and entries and entries[-1]["last_index"] == i - 1:
                entries[-1]["text"] += "\n" + t.strip()
                entries[-1]["last_index"] = i
                continue
            sys.exit(f"francqui: paragraph {i} does not start with a name: {text[:80]!r}")
        given, sur, end = parsed
        t = t.strip()
        on_page = common.norm(t[:end])
        entries.append({"year": year, "text": t, "given": given, "sur": sur, "end": end,
                        "on_page": on_page, "last_index": i})
    if not entries:
        sys.exit("francqui: no fellow entries found")

    today = date.today().isoformat()
    rows, counts = [], {}
    for e in entries:
        name = common.norm(" ".join(e["given"] + [title_surname(s) for s in e["sur"]]))
        if not name:
            sys.exit(f"francqui: empty name in {e['text'][:60]!r}")
        role, institutions, field, place = parse_entry(e["text"], e["end"])
        base = common.row_key(LIST, name, e["year"])
        counts[base] = counts.get(base, 0) + 1
        key = base if counts[base] == 1 else common.row_key(LIST, name, e["year"], str(counts[base]))
        rows.append({
            "list": LIST, "row_key": key, "name": name,
            "name_on_page": e["on_page"], "year": e["year"], "role": role,
            "institutions": institutions, "field": field, "place": place, "jurisdiction": None,
            "profile_url": None, "source_url": doc_url, "source_title": title, "source_date": source_date,
            "date_method": date_method, "page": None, "quote": common.norm(e["text"]),
            "raw_path": raw_path, "fetched_at": today,
        })
    out = common.write_rows(LIST, rows)
    print(f"wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
