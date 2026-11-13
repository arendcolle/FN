"""The people a stored page names: one extract call per chunk, each quote found in the page text, and their claims."""
import re
from urllib.parse import urlsplit

from pydantic import ValidationError

from fn import geo, orgs
from fn.contracts import (
    ClaimDraft,
    Considered,
    Identifier,
    Located,
    PageMention,
    PagePeople,
    Relation,
    Source,
    Span,
    clean_name,
    name_key,
    normalize,
)
from fn.llm import FixtureMissing, LLMCallError, TagError
from fn.steps import StepContext, fan_out
from fn.store import Store

TASK = "extract"
CHUNK_CHARS = 6_000
# A relation quote is looked for this far from the start of its mention quote, so each speaker keeps their own line.
NEAR_CHARS = 1_500
PLACES: frozenset[Relation] = frozenset({"born_in", "lives_in", "origin"})
PARAGRAPH = re.compile(r"[^\n]+(?:\n[^\n]+)*")
LINE = re.compile(r"[^\n]+")


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


def check(source: Source, start: int, end: int, mention: PageMention) -> tuple[Located | None, list[Considered]]:
    """The mention with its quotes found in the chunk source.text[start:end], or None, and a row per part dropped.

    The mention needs a name of two words or more, found in its quote. A relation's or topic's quote must lie in
    the chunk within NEAR_CHARS of the mention quote's start and hold its org or topic. A relation or topic that
    would be the same claim as an earlier kept one is dropped, because store.upsert_claim keeps one.
    """
    text, name = source.text, clean_name(mention.name)
    key = identifier(source.url, name).value

    def drop(stage: str, reason: str) -> Considered:
        return Considered(person_key=key, name=name, stage=stage, kept=False, reason=reason)

    if len(name_key(name).split()) < 2:
        return None, [drop("mention", f"name has fewer than two words: {mention.name!r}")]
    span = locate(text, mention.quote, start, end)
    if span is None:
        return None, [drop("mention", f"quote not found: {mention.quote[:200]!r}")]
    if words(name) not in words(text[span[0]:span[1]]):
        return None, [drop("mention", f"name not in quote: {text[span[0]:span[1]][:200]!r}")]
    kept, dropped, claims = [], [], {}
    for rel in mention.relations:
        at = locate(text, rel.quote, span[0], min(span[0] + NEAR_CHARS, end))
        what = f"{rel.relation} {rel.org!r}"
        if at is None:
            dropped.append(drop("relation", f"relation quote not near the mention: {what}, quote {rel.quote[:200]!r}"))
        elif not names_org(rel.org, text[at[0]:at[1]]):
            dropped.append(drop("relation", f"org not in quote: {what}, quote {text[at[0]:at[1]][:200]!r}"))
        elif (claim := (rel.relation in PLACES, normalize(rel.org), at[0])) in claims:
            dropped.append(drop("relation", f"same claim as {claims[claim].relation} {claims[claim].org!r}: {what}"))
        else:
            claims[claim] = rel
            kept.append((rel, Span(start=at[0], end=at[1])))
    topics, seen = [], set()
    for topic in mention.topics:
        at = locate(text, topic.quote, span[0], min(span[0] + NEAR_CHARS, end))
        if at is None:
            dropped.append(drop("topic", f"topic quote not near the mention: {topic.topic!r}, quote {topic.quote[:200]!r}"))
        elif not name_key(topic.topic) or words(topic.topic) not in words(text[at[0]:at[1]]):
            dropped.append(drop("topic", f"topic not in quote: {topic.topic!r}, quote {text[at[0]:at[1]][:200]!r}"))
        elif (again := (name_key(topic.topic), at[0])) in seen:
            dropped.append(drop("topic", f"same topic as before: {topic.topic!r}"))
        else:
            seen.add(again)
            topics.append((normalize(topic.topic), Span(start=at[0], end=at[1])))
    located = Located(name=name, role=normalize(mention.role or "") or None, span=Span(start=span[0], end=span[1]),
                      relations=kept, topics=topics)
    return located, dropped


def read_all(ctx: StepContext, sources: list[Source]) -> list[tuple[list[Located], list[Considered]]]:
    """Every person each page names, in page order, from one extract call per chunk, ctx.settings.llm_workers at once.

    The answers are checked on the calling thread, page by page and chunk by chunk. A chunk whose call fails gives a
    row with the error and a warning; any other exception is raised once every call is logged.
    """
    spans = [chunks(source.text) for source in sources]
    parts = [(source, start, end) for source, cuts in zip(sources, spans) for start, end in cuts]
    answers = iter(fan_out(lambda part: ctx.llm.structured(TASK, {"page": part[0].text[part[1]:part[2]]},
                                                           PagePeople).value.people,
                           parts, ctx.settings.llm_workers))
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


def drafts(person_id: str, source: Source, located: Located, ctx: StepContext | None = None) -> list[ClaimDraft]:
    """A role claim quoting the mention, then one claim per kept relation quoting its own passage, then one per topic.

    The role is the mention's, else the page title, else the URL's host. born_in and origin give a location claim
    without coordinates, lives_in one with the coordinates geo finds when ctx is given, any other relation an
    affiliation claim at the alias file's org id. Only the years a relation's quote states date its claim.
    """
    def quoted(span: Span) -> dict:
        return {"person_id": person_id, "quote": source.text[span.start:span.end], "quote_start": span.start,
                "quote_end": span.end, "source": source}

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
