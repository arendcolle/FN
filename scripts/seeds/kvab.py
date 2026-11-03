# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "docling"]
# ///
import re
import sys
import tempfile
from datetime import date
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "kvab"
URL = "https://kvab.be/sites/default/files/Jaarboek%202025.pdf"
FILENAME = "Jaarboek 2025.pdf"
FIRST_PAGE, LAST_PAGE = 129, 137
SECTION = "Samenstelling Academie - December 2025"
CATEGORIES = ("Gewone leden", "Ereleden", "Buitenlandse leden")
JONGE = "Jonge Academie"
CLASS_RE = re.compile(r"^Klasse van de [A-Z][a-z]+(?: [A-Z][a-z]+)*$")
ENTRY_RE = re.compile(r"^(\d{1,3})\.\s*(.*)$")
YEAR_RE = re.compile(r"\s*\((\d{4})\)\s*$")
TITLES = {"baron", "barones", "jonkheer", "burggraaf", "ridder", "Sir"}
PREFIX_TITLES = {"Dr.", "Prof.", "Sir"}
# two-word given names the page gives no sign of, found by reading the parsed list
GIVEN_PAIRS = {"Anne Teresa", "Willem Jan", "Eric Jan", "Robert Byron"}


def fail(msg: str) -> None:
    """Exit non-zero without writing JSONL."""
    sys.exit(f"{LIST}: structure check failed: {msg}")


def heading_of(text: str) -> tuple[str, str] | None:
    """Return ("class" | "category", value) when text is one of the expected headings."""
    text = common.norm(text).rstrip(":").strip()
    if CLASS_RE.match(text):
        return "class", text
    if text in CATEGORIES or text == JONGE:
        return "category", text
    return None


def convert(pdf_bytes: bytes):
    """Run Docling on the section's pages and return its document."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / FILENAME
        path.write_bytes(pdf_bytes)
        return conv.convert(path, page_range=(FIRST_PAGE, LAST_PAGE)).document


def renumber(column: list[list]) -> None:
    """Fix one mistyped list number whose neighbours are consecutive (the source has 69 for 59)."""
    for i in range(1, len(column) - 1):
        prev, cur, nxt = column[i - 1][0], column[i][0], column[i + 1][0]
        if cur != prev + 1 and nxt == prev + 2:
            print(f"{LIST}: page {column[i][2]}: number {cur} read as {prev + 1}", file=sys.stderr)
            column[i][0] = prev + 1


def table_entries(grid, page: int, on_heading, on_entry) -> None:
    """Walk a Docling table grid: heading rows, numbered cells, and wrapped continuation cells."""
    cols: dict[int, list[list]] = {}
    for row in grid:
        cells = [common.norm(c.text) for c in row]
        if cells and cells[0] and (hd := heading_of(cells[0])) and cells[0] == cells[1]:
            for column in cols.values():
                renumber(column)
            cols.clear()
            on_heading(*hd)
            continue
        for col in (0, 2):
            num, text = cells[col], cells[col + 1]
            if num:
                m = ENTRY_RE.match(num)
                text = f"{m.group(2)} {text}".strip() if m else ""
                if not text:
                    fail(f"page {page}: bad numbered cell {num!r} {cells[col + 1]!r}")
                cols.setdefault(col, []).append([int(m.group(1)), text, page])
                on_entry(cols[col][-1])
            elif text:
                if col not in cols:
                    fail(f"page {page}: continuation cell without an entry: {text!r}")
                cols[col][-1][1] = f"{cols[col][-1][1]} {text}"
    for column in cols.values():
        renumber(column)


def walk(doc):
    """Return ordered (class, category, number, text, page) entries and the page text layers."""
    from docling_core.types.doc.document import TableItem

    state = {"cls": None, "cat": None}
    pending: list[list] = []
    out: list[tuple] = []
    layers: dict[int, list[str]] = {}
    seen_section = False

    def flush() -> None:
        for num, text, page in sorted(pending, key=lambda e: (e[2], e[0])):
            out.append((state["cls"], state["cat"], num, text, page))
            layers.setdefault(page, []).append(f"{num}. {text}")
        pending.clear()

    def heading(kind: str, value: str, *, page: int) -> None:
        flush()
        if kind == "class":
            state["cls"], state["cat"] = value, None
        else:
            state["cat"] = value
            if value == JONGE:
                state["cls"] = None
        layers.setdefault(page, []).append(value + (":" if kind == "category" else ""))

    for item, _ in doc.iterate_items():
        page = item.prov[0].page_no
        if isinstance(item, TableItem):
            table_entries(item.data.grid, page, partial(heading, page=page), pending.append)
            continue
        text = common.norm(getattr(item, "text", ""))
        if text == SECTION:
            seen_section = True
            layers.setdefault(page, []).append(text)
        elif hd := heading_of(text):
            heading(*hd, page=page)
        elif m := ENTRY_RE.match(text):
            pending.append([int(m.group(1)), m.group(2), page])
        else:
            fail(f"page {page}: unexpected {item.label} item {text!r}")
    flush()
    if not seen_section:
        fail(f"section heading {SECTION!r} not found")
    return out, layers


def check_structure(entries: list[tuple]) -> None:
    """Fail unless every class has its three categories, the Jonge Academie exists and numbering is gapless."""
    groups: dict[tuple, list[int]] = {}
    for cls, cat, num, text, page in entries:
        if cat is None or (cls is None and cat != JONGE) or not text:
            fail(f"entry outside a heading: {num}. {text!r} (page {page})")
        groups.setdefault((cls, cat), []).append(num)
    classes = {c for c, _ in groups if c}
    if len(classes) < 4:
        fail(f"expected 4 classes, found {sorted(classes)}")
    for cls in classes:
        for cat in CATEGORIES:
            if (cls, cat) not in groups:
                fail(f"{cls}: no {cat}")
    if (None, JONGE) not in groups:
        fail("no Jonge Academie")
    for key, nums in groups.items():
        if sorted(nums) != list(range(1, len(nums) + 1)):
            fail(f"{key}: numbering has gaps or duplicates")


def parse_name(text: str) -> tuple[str, str, int | None]:
    """Split an entry into (name, name_on_page, year); name is "Given Surname" without titles."""
    year = None
    if m := YEAR_RE.search(text):
        year, text = int(m.group(1)), text[: m.start()]
    on_page = text.strip()
    if re.search(r"[A-Za-z]{2,}\.$", on_page):
        on_page = on_page[:-1]
    tokens = on_page.split()
    while tokens and tokens[0] in PREFIX_TITLES:
        tokens.pop(0)
    body = " ".join(tokens)
    if "," in body:
        surname, rest = (p.strip() for p in body.split(",", 1))
        given = [t for t in rest.split() if t not in TITLES]
        given_s = " ".join(given)
    else:
        parts = body.split()
        k = 2 if len(parts) > 2 and (re.fullmatch(r"[A-Z]\.", parts[-1]) or " ".join(parts[-2:]) in GIVEN_PAIRS) else 1
        surname, given_s = " ".join(parts[:-k]), " ".join(parts[-k:])
    if not surname or not given_s:
        fail(f"cannot split name: {text!r}")
    return f"{given_s} {surname}", on_page, year


def build_rows(entries, layer_path: str, fetched_at: str) -> list[dict]:
    """Turn parsed entries into seed rows."""
    rows = []
    for cls, cat, num, text, page in entries:
        name, on_page, year = parse_name(text)
        extra = "-".join(filter(None, [cls and cls.removeprefix("Klasse van de ").lower().replace(" ", "-"), cat.lower().replace(" ", "-")]))
        rows.append({
            "list": LIST, "row_key": common.row_key(LIST, name, year, extra), "name": name,
            "name_on_page": on_page, "year": year, "role": ", ".join(filter(None, [cat, cls])),
            "institutions": [{"name": "KVAB", "relation": "member_of"}], "field": None, "place": None,
            "jurisdiction": None, "profile_url": None, "source_url": URL,
            "source_title": "Jaarboek 2025, Samenstelling Academie - December 2025",
            "source_date": "2025-12", "date_method": "document heading", "page": page,
            "quote": common.norm(text), "raw_path": layer_path, "fetched_at": fetched_at,
        })
    return rows


def main() -> None:
    """Fetch the yearbook, parse the membership section and write data/seeds/kvab.jsonl."""
    pdf = common.fetch(URL).content
    entries, layers = walk(convert(pdf))
    check_structure(entries)
    text = "\n".join(f"[PDF page {p}]\n" + "\n".join(lines) for p, lines in sorted(layers.items()))
    layer_path = common.save_raw(LIST, FILENAME, pdf, text)
    rows = build_rows(entries, layer_path, date.today().isoformat())
    out = common.write_rows(LIST, rows)
    print(f"{LIST}: {len(rows)} rows -> {out}")


if __name__ == "__main__":
    main()
