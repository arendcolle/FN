"""The people a stored page names: one extract call per chunk, each quote found in the page text, and their claims."""
import re
from bisect import bisect_right
from collections.abc import Callable
from datetime import date
from urllib.parse import urlsplit

from pydantic import ValidationError

from fn import geo, orgs
from fn.contracts import (
    ClaimDraft,
    Considered,
    DeathsOut,
    Identifier,
    Located,
    PageMention,
    PagePeople,
    PersonMention,
    PersonPeople,
    Relation,
    Source,
    SourceKind,
    Span,
    clean_name,
    name_key,
    normalize,
)
from fn.llm import FixtureMissing, LLMCallError, TagError
from fn.steps import StepContext, fan_out
from fn.store import Store

TASK = "extract"
LEADS_TASK = "extract_leads"
PERSON_TASK = "extract_person"
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d ().\-/]{6,18}\d(?!\w)")
# Two years joined by a dash, or a dated line, is a number that is no phone.
NOT_PHONE = re.compile(r"(?:1[89]|20)\d\d\s*[-–/]\s*(?:1[89]|20)\d\d|\d{4}-\d\d-\d\d|\d\d?/\d\d?/\d{4}|\d{5}-\d{4}")
# A run is a phone number only with a mark: a leading +, the North American shape, or a label right before it.
NORTH_AMERICAN = re.compile(r"(?:1[ .\-])?(?:\(\d{3}\) ?|\d{3}[ .\-])\d{3}[ .\-]\d{4}")
PHONE_LABEL = re.compile(r"(?<!\w)(?:t[eé]l(?:[eé]phone|efoon|efon)?|phone|ph|mobile|cell|gsm)\.?[^\S\n]*:?[^\S\n]*\Z",
                         re.IGNORECASE)
LABEL_REACH = 40
EDGE = "<>()[]{}\"',.;:"
# An email or phone counts as a person's when it starts this near a place the text writes their name.
CONTACT_REACH = 300
CHUNK_CHARS = 6_000
# A relation quote is looked for this far from the start of its mention quote, so each speaker keeps their own line.
NEAR_CHARS = 1_500
# A lead's place stands this near the lead's name on a page, and its quote is cut to this many characters.
PAGE_DATES = ("page_date", "read_date")
NAME_REACH = 1_000
# A name form is the last word of the person's name with up to this many words before it, on one line.
FORM_WORDS = 3
NAME_TOKEN = re.compile(r"[^\W\d_][\w.'-]*")
QUOTE_CHARS = 300
LEGAL_FORMS = frozenset({"llp", "llc", "inc", "ltd", "plc", "pllc", "pc", "corp", "co", "nv", "sa", "bv"})
PLACES: frozenset[Relation] = frozenset({"born_in", "lives_in", "origin"})
PARAGRAPH = re.compile(r"[^\n]+(?:\n[^\n]+)*")
LINE = re.compile(r"[^\n]+")
DIED_LINE = re.compile(r"^\|?[ \t]*Died[ \t]*[:|][^\n]*", re.MULTILINE)
YEAR = re.compile(r"(?<![0-9])(1[0-9]{3}|20[0-9]{2})(?![0-9])")
# A death line or lifespan counts this far before the person's first quote, and never past a neighbour's quote.
ENTRY_CHARS = 600
LIFE_YEARS = (25, 110)
LIFESPAN = r"\s*\(([^()\n]{4,60})\)"
DASH = re.compile(r"[-–—]")
DEATH_PAGES: tuple[SourceKind, ...] = ("page", "seed_page", "vendor_page")


def locate(text: str, quote: str, start: int = 0, end: int | None = None) -> tuple[int, int] | None:
    """The offsets in text of the normalized quote inside text[start:end], or None when it is not there.

    An exact match comes first, then a match in which any run of whitespace stands for any other.
    """
    end = len(text) if end is None else end
    wanted = normalize(quote)
    if not wanted:
        return None
    at = text.find(wanted, start, end)
    if at >= 0:
        return at, at + len(wanted)
    found = re.compile(r"\s+".join(re.escape(word) for word in wanted.split())).search(text, start, end)
    return found.span() if found else None


def chunks(text: str) -> list[tuple[int, int]]:
    """The offsets of consecutive parts of text, each at most CHUNK_CHARS long, packed with whole paragraphs.

    A paragraph longer than CHUNK_CHARS is packed a line at a time, and a line longer than that is cut every
    CHUNK_CHARS characters.
    """
    pieces = []
    for paragraph in PARAGRAPH.finditer(text):
        if paragraph.end() - paragraph.start() <= CHUNK_CHARS:
            pieces.append(paragraph.span())
            continue
        for line in LINE.finditer(text, paragraph.start(), paragraph.end()):
            pieces += [(at, min(at + CHUNK_CHARS, line.end())) for at in range(line.start(), line.end(), CHUNK_CHARS)]
    found: list[tuple[int, int]] = []
    for start, end in pieces:
        if found and end - found[-1][0] <= CHUNK_CHARS:
            found[-1] = (found[-1][0], end)
        else:
            found.append((start, end))
    return found


def identifier(url: str, name: str) -> Identifier:
    """The identity of a person named on a page, so a rerun over the URL finds the same person."""
    return Identifier(scheme="mention", value=f"{url}#{name_key(clean_name(name))}")


def words(text: str) -> str:
    return f" {name_key(text)} "


def names_org(org: str, quote: str) -> bool:
    """Whether the quote names the org, as the model spelled it or as data/org_aliases.csv spells its org id."""
    return any(name_key(s) and words(s) in words(quote) for s in [org, *orgs.names(orgs.org_id(org))])


def _drop(source: Source, mention: PageMention, stage: str, reason: str) -> Considered:
    name = clean_name(mention.name)
    return Considered(person_key=identifier(source.url, name).value, name=name, stage=stage, kept=False, reason=reason)


def _attached(source: Source, end: int, span: tuple[int, int], mention: PageMention) -> tuple[Located, list[Considered]]:
    """The mention located at span with its relations and topics found near it in the chunk ending at end, and a row
    per relation or topic dropped."""
    text, name = source.text, clean_name(mention.name)
    kept, dropped, claims = [], [], {}
    for rel in mention.relations:
        at = locate(text, rel.quote, span[0], min(span[0] + NEAR_CHARS, end))
        what = f"{rel.relation} {rel.org!r}"
        if at is None:
            dropped.append(_drop(source, mention, "relation", f"relation quote not near the mention: {what}, quote {rel.quote[:200]!r}"))
        elif not names_org(rel.org, text[at[0]:at[1]]):
            dropped.append(_drop(source, mention, "relation", f"org not in quote: {what}, quote {text[at[0]:at[1]][:200]!r}"))
        elif (claim := (rel.relation in PLACES, normalize(rel.org), at[0])) in claims:
            dropped.append(_drop(source, mention, "relation", f"same claim as {claims[claim].relation} {claims[claim].org!r}: {what}"))
        else:
            claims[claim] = rel
            kept.append((rel, Span(start=at[0], end=at[1])))
    topics, seen = [], set()
    for topic in mention.topics:
        at = locate(text, topic.quote, span[0], min(span[0] + NEAR_CHARS, end))
        if at is None:
            dropped.append(_drop(source, mention, "topic", f"topic quote not near the mention: {topic.topic!r}, quote {topic.quote[:200]!r}"))
        elif not name_key(topic.topic) or words(topic.topic) not in words(text[at[0]:at[1]]):
            dropped.append(_drop(source, mention, "topic", f"topic not in quote: {topic.topic!r}, quote {text[at[0]:at[1]][:200]!r}"))
        elif (again := (name_key(topic.topic), at[0])) in seen:
            dropped.append(_drop(source, mention, "topic", f"same topic as before: {topic.topic!r}"))
        else:
            seen.add(again)
            topics.append((normalize(topic.topic), Span(start=at[0], end=at[1])))
    located = Located(name=name, role=normalize(mention.role or "") or None, span=Span(start=span[0], end=span[1]),
                      relations=kept, topics=topics)
    return located, dropped


def check(source: Source, start: int, end: int, mention: PageMention) -> tuple[Located | None, list[Considered]]:
    """The mention with its quotes found in the chunk source.text[start:end], or None, and a row per part dropped.

    The mention needs a name of two words or more, found in its quote. A relation's or topic's quote must lie in
    the chunk within NEAR_CHARS of the mention quote's start and hold its org or topic. A relation or topic that
    would be the same claim as an earlier kept one is dropped, because store.upsert_claim keeps one.
    """
    name = clean_name(mention.name)
    text = source.text
    if len(name_key(name).split()) < 2:
        return None, [_drop(source, mention, "mention", f"name has fewer than two words: {mention.name!r}")]
    span = locate(text, mention.quote, start, end)
    if span is None:
        return None, [_drop(source, mention, "mention", f"quote not found: {mention.quote[:200]!r}")]
    if words(name) not in words(text[span[0]:span[1]]):
        return None, [_drop(source, mention, "mention", f"name not in quote: {text[span[0]:span[1]][:200]!r}")]
    return _attached(source, end, span, mention)


def name_forms(text: str, start: int, end: int, person: str, same: Callable[[str, str], bool]) -> list[int]:
    """Where in text[start:end] a name form of person starts: the last word of the name with up to FORM_WORDS words
    before it on one line, accepted by same(person, form)."""
    last = name_key(clean_name(person)).split()[-1:]
    tokens = list(NAME_TOKEN.finditer(text, start, end))
    found = []
    for i, token in enumerate(tokens):
        if name_key(token.group()).split()[-1:] != last:
            continue
        for k in range(1, FORM_WORDS + 1):
            if i < k or "\n" in (form := text[tokens[i - k].start():token.end()]):
                break
            if same(person, form):
                found.append(tokens[i - k].start())
                break
    return found


def anchored(source: Source, start: int, end: int, mention: PageMention, person: str,
             same: Callable[[str, str], bool]) -> tuple[Located, list[Considered]] | None:
    """The mention at its own quote when its name is the person by same and the chunk source.text[start:end] writes a
    name form of the person inside the quote or starting at most NAME_REACH characters before it; else None."""
    if len(name_key(clean_name(mention.name)).split()) < 2 or not same(person, mention.name):
        return None
    span = locate(source.text, mention.quote, start, end)
    if span is None or not any(at >= span[0] - NAME_REACH for at in name_forms(source.text, start, span[1], person, same)):
        return None
    return _attached(source, end, span, mention)


def leads_block(names: list[str]) -> str:
    """The names with white space collapsed, empty and repeated ones left out, one per line."""
    return "\n".join(dict.fromkeys(n for n in (" ".join(name.split()) for name in names) if n))


def read_all(ctx: StepContext, sources: list[Source],
             leads: list[list[str]] | None = None) -> list[tuple[list[Located], list[Considered]]]:
    """Every person each page names, in page order, from one extract call per chunk, ctx.settings.llm_workers at once.

    With leads (leads[i] for sources[i], ValueError if the lengths differ), a page with lead names is read for those
    people only, by the extract_leads task.

    The answers are checked on the calling thread, page by page and chunk by chunk. A chunk whose call fails gives a
    row with the error and a warning; any other exception is raised once every call is logged.
    """
    if leads is not None and len(leads) != len(sources):
        raise ValueError(f"{len(leads)} lead lists for {len(sources)} pages")
    blocks = [leads_block(names) for names in leads or [[] for _ in sources]]
    spans = [chunks(source.text) for source in sources]
    parts = [(source, start, end, block) for source, block, cuts in zip(sources, blocks, spans) for start, end in cuts]

    def ask(part: tuple[Source, int, int, str]) -> list[PageMention]:
        source, start, end, block = part
        page = source.text[start:end]
        task, data = (LEADS_TASK, {"page": page, "leads": block}) if block else (TASK, {"page": page})
        return ctx.llm.structured(task, data, PagePeople).value.people

    answers = iter(fan_out(ask, parts, ctx.settings.llm_workers))
    pages = []
    for source, cuts in zip(sources, spans):
        found: list[Located] = []
        considered: list[Considered] = []
        for i, (start, end) in enumerate(cuts, 1):
            people, where = next(answers), f"chunk {i} of {len(cuts)} [{start}:{end}]"
            if isinstance(people, (TagError, LLMCallError, ValidationError, FixtureMissing)):
                ctx.log.warning("extract on %s, %s: %s: %s", source.url, where, type(people).__name__, people)
                considered.append(Considered(person_key=source.url, name="", stage="chunk", kept=False,
                                             reason=f"{where}: {type(people).__name__}: {people}"))
                continue
            if isinstance(people, Exception):
                raise people
            for mention in people:
                located, dropped = check(source, start, end, mention)
                found += [located] if located else []
                considered += dropped
        pages.append((found, considered))
    return pages


def read_person(ctx: StepContext, pages: list[tuple[Source, str]], same: Callable[[str, str], bool] | None = None,
                ) -> list[tuple[list[tuple[Located, PersonMention]], list[Considered]]]:
    """The named person on each page, in page order, from one extract_person call per chunk, ctx.settings.llm_workers at once.

    Each mention is checked as read_all checks one. A chunk whose call fails gives a row with the error, and a warning
    unless the recording is missing; any other exception is raised once every call is logged. With same, a mention
    dropped because its quote lacks its name is kept when `anchored` accepts it.
    """
    spans = [chunks(source.text) for source, _ in pages]
    parts = [(source, start, end, name) for (source, name), cuts in zip(pages, spans) for start, end in cuts]

    def ask(part: tuple[Source, int, int, str]) -> list[PersonMention]:
        source, start, end, name = part
        return ctx.llm.structured(PERSON_TASK, {"page": source.text[start:end], "person": name}, PersonPeople).value.people

    answers = iter(fan_out(ask, parts, ctx.settings.llm_workers))
    found_pages = []
    for (source, person), cuts in zip(pages, spans):
        found: list[tuple[Located, PersonMention]] = []
        considered: list[Considered] = []
        for i, (start, end) in enumerate(cuts, 1):
            people, where = next(answers), f"chunk {i} of {len(cuts)} [{start}:{end}]"
            if isinstance(people, (TagError, LLMCallError, ValidationError, FixtureMissing)):
                if not isinstance(people, FixtureMissing):
                    ctx.log.warning("extract_person on %s, %s: %s: %s", source.url, where, type(people).__name__, people)
                considered.append(Considered(person_key=source.url, name="", stage="chunk", kept=False,
                                             reason=f"{where}: {type(people).__name__}: {people}"))
                continue
            if isinstance(people, Exception):
                raise people
            for mention in people:
                located, dropped = check(source, start, end, mention)
                if located is None and same is not None and (kept := anchored(source, start, end, mention, person, same)):
                    located, dropped = kept
                found += [(located, mention)] if located else []
                considered += dropped
        found_pages.append((found, considered))
    return found_pages


def mentions(ctx: StepContext, source: Source) -> tuple[list[Located], list[Considered]]:
    """Every person the page names, from one extract call per chunk of at most CHUNK_CHARS characters.

    A chunk whose call fails gives a row with the error and a warning, and the next chunk goes on. A mention or
    relation whose quote fails a check is dropped with a row naming the reason.
    """
    return read_all(ctx, [source])[0]


def stated(year: int | None, quote: str) -> str | None:
    """The year as text when its four digits stand in the quote, else None."""
    if year is None or not 1000 <= year <= 9999 or not re.search(rf"(?<![0-9]){year}(?![0-9])", quote):
        return None
    return str(year)


def page_dated(source: Source) -> dict:
    """The date fields of a claim from a page FN read itself: the page's own date, else the day it was read.

    Empty for any other source, whose claims stay undated unless their quote states a year.
    """
    if source.date_method not in PAGE_DATES or not source.source_date:
        return {}
    precision = ("year", "month", "day")[min(source.source_date.count("-"), 2)]
    return {"claim_date": source.source_date, "date_precision": precision, "date_method": source.date_method}


def drafts(person_id: str, source: Source, located: Located, ctx: StepContext | None = None) -> list[ClaimDraft]:
    """A role claim quoting the mention, then one claim per kept relation quoting its own passage, then one per topic.

    The role is the mention's, else the page title, else the URL's host. born_in and origin give a location claim
    without coordinates, lives_in one with the coordinates geo finds when ctx is given, any other relation an
    affiliation claim at the alias file's org id. The years a relation's quote states date its claim; without
    them a claim from a page FN read itself takes the page's date (page_dated).
    """
    def quoted(span: Span) -> dict:
        return {"person_id": person_id, "quote": source.text[span.start:span.end], "quote_start": span.start,
                "quote_end": span.end, "source": source} | page_dated(source)

    role = located.role or source.title or urlsplit(source.url).hostname or source.url
    found = [ClaimDraft(kind="role", value=role, **quoted(located.span))]
    for rel, span in located.relations:
        base = quoted(span)
        start, end = stated(rel.year_from, base["quote"]), stated(rel.year_to, base["quote"])
        if start or end:
            base |= {"valid_from": start, "valid_to": end, "claim_date": max(y for y in (start, end) if y),
                     "date_precision": "year", "date_method": "stated_in_quote"}
        if rel.relation in PLACES:
            where = geo.coordinates(ctx.http, normalize(rel.org), ctx.log) if ctx and rel.relation == "lives_in" else None
            lat, lon = where or (None, None)
            found.append(ClaimDraft(kind="location", relation=rel.relation, value=normalize(rel.org), lat=lat, lon=lon,
                                    **base))
        else:
            found.append(ClaimDraft(kind="affiliation", relation=rel.relation, org_id=orgs.org_id(rel.org),
                                    value=normalize(rel.org), **base))
    found += [ClaimDraft(kind="topic", value=topic, **quoted(span)) for topic, span in located.topics]
    return found


def _near(text: str, phrase: str, name: str) -> list[tuple[int, int, int]]:
    """Where phrase stands in text, casefolded and on word boundaries, as (distance to the name's last word, start, end).

    Any white space may stand between the phrase's words. A text that does not hold the name gives no place.
    """
    words, surnames = phrase.split(), re.findall(r"[^\W_]+", clean_name(name))
    if not words or not surnames:
        return []
    around = [m.start() for m in re.finditer(rf"(?<!\w){re.escape(surnames[-1])}(?!\w)", text, re.IGNORECASE)]
    if not around:
        return []
    return sorted((min(abs(m.start() - at) for at in around), m.start(), m.end())
                  for m in re.finditer(rf"(?<!\w){r'\s+'.join(map(re.escape, words))}(?!\w)", text, re.IGNORECASE))


def _is_phone(text: str, start: int, run: str) -> bool:
    """True when the PHONE run at start is a phone number: 7 to 15 digits, no date or fax, and a mark."""
    digits = len(re.sub(r"\D", "", run))
    if not 7 <= digits <= 15 or NOT_PHONE.fullmatch(run.strip("()")) \
            or "fax" in text[max(0, start - 8):start].casefold():
        return False
    return (run.startswith("+") and digits >= 8) or bool(NORTH_AMERICAN.fullmatch(run)) \
        or bool(PHONE_LABEL.search(text, max(0, start - LABEL_REACH), start))


def contacts(person_id: str, source: Source, name: str) -> list[ClaimDraft]:
    """At most one email and one phone claim for the person, read from the page text by rule.

    An email is the person's when the surname (3 letters or more) stands in its local part, or when it starts within
    CONTACT_REACH characters of a place the text writes the name; the first that qualifies, surname matches first.
    A phone is a PHONE run with a mark (`_is_phone`) that starts within CONTACT_REACH of such a place or of the
    email; the nearest wins.
    """
    text, parts, words = source.text, name_key(name).split(), clean_name(name).split()
    surname = parts[-1] if parts else ""
    if not surname or not words:
        return []
    spans = [m.span() for m in EMAIL.finditer(text)]
    places = [at for _, at, _ in _near(text, words[-1], name) if not any(a <= at < b for a, b in spans)]

    def reach(at: int, anchors: list[int]) -> int | None:
        gap = min((abs(at - a) for a in anchors), default=None)
        return gap if gap is not None and gap <= CONTACT_REACH else None

    emails = []
    for m in EMAIL.finditer(text):
        value = m.group().lstrip(EDGE).rstrip(EDGE)
        start = m.start() + m.group().index(value)
        by_surname = len(surname) >= 3 and surname in name_key(value.split("@")[0]).replace(" ", "")
        if by_surname or (reach(start, places) is not None and not _other_name(text, start, name)):
            emails.append((not by_surname, start, start + len(value)))
    email = min(emails, default=None)
    phones = []
    for m in PHONE.finditer(text):
        gap = reach(m.start(), places + ([email[1]] if email else []))
        if gap is not None and _is_phone(text, m.start(), m.group()):
            phones.append((gap, m.start(), m.end()))
    found = []
    for kind, at in (("email", email and email[1:]), ("phone", phones and min(phones)[1:])):
        if at:
            start, end = _line(text, *at)
            found.append(ClaimDraft(person_id=person_id, kind=kind, value=text[at[0]:at[1]], quote=text[start:end],
                                    quote_start=start, quote_end=end, source=source, **page_dated(source)))
    return found


def _other_name(text: str, at: int, name: str) -> bool:
    """True when the line of `at` writes a capitalised two-word name and not this person's."""
    first, last = text.rfind("\n", 0, at) + 1, text.find("\n", at)
    line = text[first:len(text) if last < 0 else last]
    return bool(re.search(r"[A-Z][a-z]+ [A-Z][a-z]+", line)) and not _near(line, clean_name(name).split()[-1], name)


def _line(text: str, start: int, end: int) -> tuple[int, int]:
    """The line of text that holds [start, end), cut to QUOTE_CHARS characters around it."""
    first, last = text.rfind("\n", 0, start) + 1, text.find("\n", end)
    last = len(text) if last < 0 else last
    if last - first > QUOTE_CHARS:
        first = max(first, min(start - (QUOTE_CHARS - (end - start)) // 2, last - QUOTE_CHARS))
        last = min(last, first + QUOTE_CHARS)
    return first, last


def stated_place(person_id: str, source: Source, name: str, place: str, ctx: StepContext | None) -> ClaimDraft | None:
    """A lives_in claim for place when its city stands within NAME_REACH characters of the name's last word, else None.

    The city is the part of place before its first comma, compared casefolded on word boundaries. The quote is
    the line of the text that holds it, cut to QUOTE_CHARS characters around it.
    """
    found = next(((a, b) for far, a, b in _near(source.text, place.split(",")[0].strip(), name) if far <= NAME_REACH), None)
    if found is None:
        return None
    start, end = _line(source.text, *found)
    where = geo.coordinates(ctx.http, normalize(place), ctx.log) if ctx else None
    lat, lon = where or (None, None)
    return ClaimDraft(person_id=person_id, kind="location", relation="lives_in", value=normalize(place), lat=lat, lon=lon,
                      quote=source.text[start:end], quote_start=start, quote_end=end, source=source, **page_dated(source))


def stated_employer(person_id: str, source: Source, name: str, employer: str) -> ClaimDraft | None:
    """A works_at claim for employer when the source's text prints its name near the person or in its title line.

    The name is tried as given, then without trailing legal forms such as LLP or Inc when two or more words
    remain. A place counts within NAME_REACH characters of the person's name, or on the first line when that is
    the page's title. The value is the name as the page writes it, the quote its line.
    """
    words = employer.split()
    while len(words) > 2 and name_key(words[-1]).replace(" ", "") in LEGAL_FORMS:
        words = words[:-1]
    title_end = len(source.text.split("\n", 1)[0]) if source.title and source.text.startswith(source.title) else 0
    for phrase in dict.fromkeys((employer, " ".join(words))):
        for far, a, b in _near(source.text, phrase, name):
            if far > NAME_REACH and b > title_end:
                continue
            start, end = _line(source.text, a, b)
            value = normalize(source.text[a:b])
            return ClaimDraft(person_id=person_id, kind="affiliation", relation="works_at", org_id=orgs.org_id(value),
                              value=value, quote=source.text[start:end], quote_start=start, quote_end=end, source=source,
                              **page_dated(source))
    return None


def locate_stored(store: Store, names: geo.Names) -> int:
    """Give stored place claims without coordinates the ones geo finds for their place; returns how many it filled.

    These are the claims evidence reads as a stated place: every location claim that is not a birthplace or an
    origin. A place that names no city stays as it is.
    """
    filled = 0
    with store.tx():
        for claim_id, place in store.unlocated_places():
            if found := geo.locate(place, names):
                filled += store.fill_claim_place(claim_id, found.lat, found.lon)
    return filled


def died_line(text: str, lo: int, q: int, named: re.Pattern, others: list[tuple[int, int]],
              today: date) -> tuple[str, tuple[int, int]] | None:
    """The year and span of the last Died line starting in [lo, q) after the surname, overlapped by no other
    person's quote, whose first year is at most today's; None when there is none."""
    found = None
    for start in (m.start() for m in DIED_LINE.finditer(text, lo, q)):
        line = DIED_LINE.match(text, start)
        year = YEAR.search(line.group())
        if (year and int(year.group()) <= today.year and named.search(text[lo:start])
                and not any(a < q and b > start for a, b in others)):
            found = year.group(), line.span()
    return found


def lifespan(text: str, regions: list[tuple[int, int]], named: re.Pattern,
             today: date) -> tuple[str, tuple[int, int]] | None:
    """The death year and span of the first surname followed by '(1894–1966)' that starts in one of regions.

    The parenthesis holds two years with a dash between them, LIFE_YEARS apart, the second at most today's.
    """
    life = re.compile(named.pattern + LIFESPAN, re.IGNORECASE)
    for a, b in regions:
        # A surname that starts before b may end past it; the pattern is longer than any word it matches.
        for m in named.finditer(text, a, b + len(named.pattern)):
            if m.start() >= b or not (found := life.match(text, m.start())):
                continue
            inner = found.group(1)
            years = list(YEAR.finditer(inner))
            if len(years) != 2 or not DASH.search(inner, years[0].end(), years[1].start()):
                continue
            born, died = (int(y.group()) for y in years)
            if LIFE_YEARS[0] <= died - born <= LIFE_YEARS[1] and died <= today.year:
                return str(died), found.span()
    return None


def deaths(source: Source, people: dict[str, tuple[str, list[Span]]], today: date) -> list[ClaimDraft]:
    """One death claim per person whose own entry on the page states a death, by a Died line, else a lifespan.

    people maps a person id, or a mention identifier, to the name and quote spans. The entry starts at the latest of
    ENTRY_CHARS before the person's first quote and the end of every other quote before it; the surname must stand in it.
    """
    text = source.text
    spans = sorted((s.end, s.start, key) for key, (_, own) in people.items() for s in own)
    ends = [end for end, _, _ in spans]
    found = []
    for key, (name, own) in people.items():
        surnames = re.findall(r"[^\W_]+", clean_name(name))
        if not own or not surnames:
            continue
        q = min(s.start for s in own)
        before = bisect_right(ends, q)
        lo = max(0, q - ENTRY_CHARS, ends[before - 1] if before else 0)
        named = re.compile(rf"(?<!\w){re.escape(surnames[-1])}(?!\w)", re.IGNORECASE)
        others = [(start, end) for end, start, k in spans[before:] if k != key and start < q]
        hit = died_line(text, lo, q, named, others, today) or lifespan(
            text, [(lo, q), *((s.start, s.end) for s in own)], named, today)
        if hit:
            year, (start, end) = hit
            first, last = _line(text, start, end)
            found.append(ClaimDraft(person_id=key, kind="death", value=year, quote=text[first:last], quote_start=first,
                                    quote_end=last, source=source, claim_date=year, date_precision="year",
                                    date_method="stated_in_quote"))
    return found


def deaths_stored(store: Store, today: date) -> DeathsOut:
    """Store the death claims of every page, seed page and vendor page with claims, one transaction per page."""
    pages, found = store.page_people(DEATH_PAGES), 0
    for source_id, people in pages.items():
        drafts = deaths(store.get_sources([source_id])[source_id], people, today)
        with store.tx():
            for draft in drafts:
                store.upsert_claim(draft)
        found += len(drafts)
    return DeathsOut(pages=len(pages), deaths=found)
