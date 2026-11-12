"""CSV text to rows, the row checks, the preview and the confirm of an import, each a step of a job."""
import csv
import io
import re
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import NamedTuple

from fn import geo, network, orgs
from fn.contracts import (
    IMPORT_COLUMNS,
    ClaimDraft,
    GeoArea,
    Identifier,
    ImportOutcome,
    ImportPreview,
    ImportRecord,
    ImportRow,
    ImportStepIn,
    ImportStepOut,
    Source,
    clean_name,
    group_key,
    name_key,
    normalize,
    profile_url,
    record_source,
)
from fn.net import HttpError
from fn.steps import StepContext, run_step
from fn.store import Store, fold
from fn.worker import Worker

MAX_BYTES = 5 * 1024 * 1024
OUTCOMES: tuple[ImportOutcome, ...] = ("new", "update", "name_match", "skipped")
ORCID = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", re.IGNORECASE)
LINKEDIN = "https://www.linkedin.com/"
PLACE_COLUMNS = ("city", "state", "country")
LABELS = {"profile_url": "LinkedIn URL", "orcid": "ORCID", "email": "email address"}
NOT_CSV = "{file} is not a CSV file. In Excel, use Save as and pick CSV."
NO_NAME = "{file} has no name column. Rename the column that holds names to name and upload it again."
NO_ROWS = "{file} has no rows under the column names."
EMPTY = "{file} is empty. Upload a CSV file with the column names in its first row."
TOO_BIG = "{file} is larger than 5 MB. Split it into smaller files and upload them one by one."
DISCARDED = "{file} was discarded, so it cannot be imported. Upload it again to import it."


class ImportRefused(Exception):
    """A file or an action FN will not import; the message is one sentence for staff."""


class Table(NamedTuple):
    columns: dict[str, int]
    ignored: list[str]
    records: list[tuple[int, list[str]]]


def decode(filename: str, raw: bytes) -> str:
    """The file's text, read as UTF-8 with or without a byte-order mark, else as Windows-1252.

    Raises ImportRefused for a file over 5 MB, an empty one, and one that is not text, such as UTF-16 or .xlsx.
    """
    if len(raw) > MAX_BYTES:
        raise ImportRefused(TOO_BIG.format(file=filename))
    if raw.startswith((b"\xff\xfe", b"\xfe\xff", b"PK")) or b"\0" in raw:
        raise ImportRefused(NOT_CSV.format(file=filename))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            raise ImportRefused(NOT_CSV.format(file=filename)) from None
    if not text.strip():
        raise ImportRefused(EMPTY.format(file=filename))
    return text


def table(filename: str, text: str) -> Table:
    """The expected columns' positions, the other column names and every record with its row number, header row 1.

    The delimiter is the comma or the semicolon the header row has more of. Raises ImportRefused for tabs,
    a file without a name column and one without a filled row.
    """
    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    if header.count("\t") > header.count(delimiter):
        raise ImportRefused(NOT_CSV.format(file=filename))
    try:
        head, *rows = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    except (csv.Error, ValueError):
        raise ImportRefused(NOT_CSV.format(file=filename)) from None
    columns, ignored = {}, []
    for i, cell in enumerate(head):
        key = "_".join(cell.strip().lower().split())
        if key in IMPORT_COLUMNS and key not in columns:
            columns[key] = i
        elif cell.strip():
            ignored.append(cell.strip())
    if "name" not in columns:
        raise ImportRefused(NO_NAME.format(file=filename))
    records = [(n, row) for n, row in enumerate(rows, start=2) if any(c.strip() for c in row)]
    if not records:
        raise ImportRefused(NO_ROWS.format(file=filename))
    return Table(columns, ignored, records)


def cells_of(columns: dict[str, int], row: list[str]) -> dict[str, str]:
    """The filled expected cells of a row, normalized; the name on one line without titles."""
    # Drop the apostrophe an FN export puts before =, +, - and @ so a re-import reads the value it exported.
    found = {col: re.sub(r"^'(?=[=+\-@])", "", normalize(row[i])) for col, i in columns.items() if i < len(row)}
    if "name" in found:
        found["name"] = clean_name(found["name"])
    return {col: value for col, value in found.items() if value}


def identifiers(cells: dict[str, str]) -> tuple[list[Identifier], list[str]]:
    """The row's LinkedIn URL, ORCID and email as identifiers, and a sentence for each such cell FN cannot use."""
    found, notes = [], []
    if url := cells.get("linkedin_url"):
        canonical = profile_url(url)
        if canonical.startswith(LINKEDIN) and len(canonical) > len(LINKEDIN):
            found.append(Identifier(scheme="profile_url", value=canonical))
        else:
            notes.append("Its linkedin_url is not a LinkedIn address, so FN does not use it to recognize the person.")
    if value := cells.get("orcid"):
        if match := ORCID.search(value):
            found.append(Identifier(scheme="orcid", value=f"https://orcid.org/{match.group().upper()}"))
        else:
            notes.append("Its orcid is not an ORCID iD, so FN does not use it to recognize the person.")
    if (email := cells.get("email", "").lower()) and "@" in email:
        found.append(Identifier(scheme="email", value=email))
    return found, notes


def place_of(cells: dict[str, str]) -> str:
    return ", ".join(cells[c] for c in PLACE_COLUMNS if c in cells)


def locate(cells: dict[str, str], names: geo.Names | None) -> GeoArea | None:
    if "city" not in cells or names is None:
        return None
    return geo.locate_city(cells["city"], cells.get("state"), cells.get("country"), names)


def _holders(store: Store, wanted: list[Identifier]) -> dict[tuple[str, str], str]:
    """The canonical person holding each identifier; one nobody holds is left out."""
    found: dict[tuple[str, str], str] = {}
    for scheme in {i.scheme for i in wanted}:
        values = [i.value for i in wanted if i.scheme == scheme]
        found |= {(scheme, v): p for v, p in store.person_ids_by_identifier(scheme, values).items()}
    canonical = store.canonical_ids(list(set(found.values())))
    return {key: canonical[p] for key, p in found.items()}


def rows_of(store: Store, record: ImportRecord, names: geo.Names | None) -> tuple[list[ImportRow], list[str]]:
    """What the import would do with every filled row as the store stands now, and the ignored column names."""
    parsed = table(record.filename, record.text)
    filled = [(n, cells_of(parsed.columns, row)) for n, row in parsed.records]
    idents = {n: identifiers(cells) for n, cells in filled}
    holders = _holders(store, [i for found, _ in idents.values() for i in found])
    people = store.get_persons(list(set(holders.values())))
    network_keys = store.network_by_group_key()
    seen: dict[tuple, int] = {}
    file_idents: dict[tuple[str, str], int] = {}
    file_names: dict[str, int] = {}
    rows = []
    for n, cells in filled:
        name = cells.get("name", "")
        if not name_key(name):
            rows.append(ImportRow(n=n, name=name, outcome="skipped", message=f"Row {n} has no name, so FN skips it.",
                                  cells=cells))
            continue
        key = tuple(sorted(cells.items()))
        if key in seen:
            rows.append(ImportRow(n=n, name=name, outcome="skipped", cells=cells,
                                  message=f"Row {n} is the same as row {seen[key]}, so FN skips it."))
            continue
        seen[key] = n
        found, notes = idents[n]
        owners: dict[str, str] = {}
        for i in found:
            if owner := holders.get((i.scheme, i.value)):
                owners.setdefault(owner, i.scheme)
        if len(owners) > 1:
            (a, a_scheme), (b, b_scheme) = list(owners.items())[:2]
            rows.append(ImportRow(n=n, name=name, outcome="skipped", cells=cells, message=(
                f"Row {n}'s {LABELS[a_scheme]} belongs to {people[a].display_name} and its {LABELS[b_scheme]} "
                f"to {people[b].display_name}, so FN skips it.")))
            continue
        outcome: ImportOutcome
        person_id = next(iter(owners), None)
        earlier = next((file_idents[(i.scheme, i.value)] for i in found if (i.scheme, i.value) in file_idents), None)
        gkey = group_key(name_key(name))
        if person_id:
            outcome = "update"
        elif earlier:
            outcome = "update"
            notes.insert(0, f"It has an identifier of row {earlier}, so FN adds it to the same person.")
        else:
            matches = network_keys.get(gkey, [])
            outcome, person_id = ("name_match", matches[0]) if matches else ("new", None)
            if gkey in file_names:
                notes.insert(0, f"Row {file_names[gkey]} has the same name, so FN imports this row as another person.")
            file_names.setdefault(gkey, n)
        for i in found:
            file_idents.setdefault((i.scheme, i.value), n)
        if "city" in cells and locate(cells, names) is None:
            notes.append(f"FN cannot find {place_of(cells)} on the map, so this person will not be on the map.")
        rows.append(ImportRow(n=n, name=name, outcome=outcome, person_id=person_id, message=" ".join(notes),
                              cells=cells))
    return rows, parsed.ignored


def counts(rows: list[ImportRow]) -> dict[str, int]:
    found = Counter(r.outcome for r in rows)
    return {outcome: found[outcome] for outcome in OUTCOMES}


def row_source(record: ImportRecord, row: ImportRow) -> tuple[Source, dict[str, tuple[int, int]]]:
    """The row as an import source, one `column: value` line per filled cell, dated the import's day."""
    return record_source(
        f"fn:import/{record.id}#row-{row.n}", f"{record.filename}, row {row.n}",
        [(c, row.cells[c]) for c in IMPORT_COLUMNS if c in row.cells], row.cells, record.uploaded_at,
        record.uploaded_at.date().isoformat(), kind="import",
    )


def drafts(person_id: str, source: Source, spans: dict[str, tuple[int, int]], cells: dict[str, str],
           area: GeoArea | None) -> list[ClaimDraft]:
    """The row's claims, each quoting its own lines of the source; the location quotes its city line to its last part."""

    def draft(kind, value: str, start: int, end: int, **extra) -> ClaimDraft:
        return ClaimDraft(person_id=person_id, kind=kind, value=value, quote=source.text[start:end], quote_start=start,
                          quote_end=end, source=source, claim_date=source.source_date, date_precision="day",
                          date_method="sheet_date", **extra)

    found = []
    if value := cells.get("organization"):
        found.append(draft("affiliation", value, *spans["organization"], relation="works_at",
                           org_id=orgs.org_id(value)))
    for kind in ("role", "email", "phone"):
        if value := cells.get(kind):
            found.append(draft(kind, value, *spans[kind]))
    if "city" in cells:
        end = max(spans[c][1] for c in PLACE_COLUMNS if c in cells)
        found.append(draft("location", place_of(cells), spans["city"][0], end, relation="lives_in",
                           lat=area.lat if area else None, lon=area.lon if area else None))
    return found


def _names(ctx: StepContext) -> geo.Names | None:
    """The city names through the step's HTTP client; None, with a log line, when they cannot be fetched."""
    if ctx.http is None:
        return None
    try:
        return geo.cities(ctx.http)
    except HttpError as exc:
        ctx.log.warning("no city names for the import: %s", exc)
        return None


def _preview(ctx: StepContext, inp: ImportStepIn) -> ImportStepOut:
    record = ctx.store.get_import(inp.import_id)
    rows, ignored = rows_of(ctx.store, record, _names(ctx))
    preview = ImportPreview(import_id=record.id, filename=record.filename, status=record.status, rows=rows,
                            ignored_columns=ignored, counts=counts(rows))
    ctx.store.set_import(record.id, record.status, preview.model_dump(mode="json"))
    return ImportStepOut(counts=preview.counts)


def _write(store: Store, record: ImportRecord, rows: list[ImportRow], merge_rows: set[int],
           names: geo.Names | None, now: datetime) -> list[ImportRow]:
    """Write every row that is not skipped and return the rows as written, each with the person it became part of."""
    previewed = {r.n: r for r in ImportPreview.model_validate(record.summary).rows} if record.summary else {}
    written = []
    for row in rows:
        if row.outcome == "skipped":
            written.append(row)
            continue
        shown = previewed.get(row.n)
        into = None
        if row.outcome in ("new", "name_match") and row.n in merge_rows and shown and shown.outcome == "name_match":
            target = store.canonical_ids([shown.person_id])[shown.person_id]
            into = store.get_persons([target])[target]
        merging = into is not None and into.list_status == "in_list"
        found, _ = identifiers(row.cells)
        person = store.resolve_person([*found, Identifier(scheme="import", value=f"import:{record.id}:{row.n}")],
                                      row.name)
        held = {(c.kind, fold(c.value))
                for c in store.claims_of([person.id, *([into.id] if merging else [])], include_hidden=True)}
        source, spans = row_source(record, row)
        for draft in drafts(person.id, source, spans, row.cells, locate(row.cells, names)):
            if (draft.kind, fold(draft.value)) not in held:
                store.upsert_claim(draft, at=now)
        if merging:
            network.merge(store, [person.id], into.id, now=now)
        else:
            network.add(store, [person.id], via="import", now=now, import_id=record.id)
        if into is not None and not merging:
            left = f"{into.display_name} left your network since this preview, so FN imported this row as a new person."
            row = row.model_copy(update={"outcome": "new", "message": " ".join(filter(None, [left, row.message]))})
        (canonical,) = store.canonical_ids([person.id]).values()
        written.append(row.model_copy(update={"person_id": canonical}))
    return written


def _confirm(ctx: StepContext, inp: ImportStepIn, now: datetime) -> ImportStepOut:
    names = _names(ctx)
    store = ctx.store
    with store.tx():
        record = store.get_import(inp.import_id)
        if record.status == "discarded":
            raise ImportRefused(DISCARDED.format(file=record.filename))
        if record.status == "preview":
            fresh, ignored = rows_of(store, record, names)
            rows = _write(store, record, fresh, set(inp.merge_rows), names, now)
            preview = ImportPreview(import_id=record.id, filename=record.filename, status="confirmed", rows=rows,
                                    ignored_columns=ignored, counts=counts(rows))
            network.record_import(store, record.id, now=now, detail={"counts": preview.counts})
            store.set_import(record.id, "confirmed", preview.model_dump(mode="json"), now)
            record = store.get_import(inp.import_id)
    return ImportStepOut(counts=record.summary["counts"])


def _run(worker: Worker, import_id: str, step: str, fn: Callable[[StepContext, ImportStepIn], ImportStepOut],
         inp: ImportStepIn) -> None:
    """Run fn as the one step of a job in the calling thread; raises RuntimeError when the job does not end done."""
    job = worker.create_search(f"fn-import {import_id}", kind="job")
    ended = worker.execute(job.id, lambda ctx, _: run_step(ctx, step, fn, inp))
    if ended.status != "done":
        raise RuntimeError(f"import {import_id}: the {step} job {job.id} ended {ended.status}")


def upload(worker: Worker, filename: str, raw: bytes, now: datetime) -> str:
    """Check the file, store it as an import in preview and store its preview; returns the import id.

    Raises ImportRefused with one sentence for staff when FN cannot read the file.
    """
    text = decode(filename, raw)
    table(filename, text)
    import_id = str(uuid.uuid4())
    worker.store.add_import(ImportRecord(id=import_id, filename=filename, uploaded_at=now, status="preview", text=text))
    _run(worker, import_id, "import_preview", _preview, ImportStepIn(import_id=import_id))
    return import_id


def get(store: Store, import_id: str) -> ImportPreview | None:
    """The stored preview with the import's status and file name; None for an unknown id or one without a preview."""
    record = store.get_import(import_id)
    if record is None or not record.summary:
        return None
    return ImportPreview.model_validate(record.summary | {"status": record.status, "filename": record.filename})


def confirm(worker: Worker, import_id: str, merge_rows: set[int], now: datetime) -> ImportPreview:
    """Write every row in one transaction, merging the ticked name matches, and return the final preview.

    A confirmed import comes back unchanged. Raises ImportRefused for a discarded import, LookupError for an unknown one.
    """
    record = worker.store.get_import(import_id)
    if record is None:
        raise LookupError(f"no import {import_id}")
    if record.status == "discarded":
        raise ImportRefused(DISCARDED.format(file=record.filename))
    if record.status == "preview":
        inp = ImportStepIn(import_id=import_id, merge_rows=sorted(merge_rows))
        _run(worker, import_id, "import_confirm", lambda ctx, step_in: _confirm(ctx, step_in, now), inp)
    return get(worker.store, import_id)


def discard(store: Store, import_id: str) -> None:
    """Set a previewed import discarded; raises ImportRefused for a confirmed one, LookupError for an unknown one."""
    record = store.get_import(import_id)
    if record is None:
        raise LookupError(f"no import {import_id}")
    if record.status == "confirmed":
        raise ImportRefused(f"{record.filename} is already imported, so it cannot be discarded.")
    store.set_import(import_id, "discarded")
