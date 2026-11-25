"""How a person reads on every staff page: the view models of people and claims, and plain-words helpers."""
import json
import re
from calendar import month_name
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from html import unescape
from urllib.parse import urlsplit

from fn import deepen
from fn import evidence as ev
from fn import identity, importer, network, orgs, parse, rank
from fn.contracts import (
    AsideGroup,
    Candidate,
    CardFit,
    CardView,
    Chips,
    Claim,
    ClaimView,
    CompareRow,
    CompareValue,
    CompareView,
    ContactView,
    Event,
    FactGroup,
    FoldView,
    Identifier,
    ImportPreview,
    ImportRow,
    LaneOut,
    LastView,
    LookupView,
    NetworkFilter,
    NetworkView,
    Org,
    OrgView,
    Person,
    PersonView,
    Place,
    ProfileView,
    QuoteView,
    ReasonView,
    RecordView,
    ResultsHeading,
    ResultsView,
    Search,
    Source,
    SummaryRow,
    TitlesView,
    WhyView,
    name_key,
    profile_url,
)
from fn.evidence import places
from fn.geo import distance_km, regions_of
from fn.store import Store, fold

EMPLOYED = ("works_at", "worked_at", "affiliated_with")
RELATIONS = {
    "studied_at": "Studied at", "works_at": "Works at", "worked_at": "Worked at", "affiliated_with": "Named at",
    "hosted_by": "Hosted by", "member_of": "Member of", "fellow_of": "Fellow of", "consul_for": "Consul for",
}
# Seed list roles name a list, not a job.
LIST_ROLES = ("fellow_of", "member_of", "consul_for")
JOINING = ("works_at", "affiliated_with", "worked_at")
CURRENT = JOINING[:2]
PROSE = ("page", "seed_page", "vendor_page")
FIELDS = {"topic": "Topic", "email": "Email", "phone": "Phone", "linkedin": "LinkedIn"}
RECORD_LABELS = {"record": "OpenAlex record", "vendor_record": "LinkedIn record"}
# Dates of the day a record was read or changed, which never are a fact's own year.
RECORD_DATES = ("page_date", "sitemap", "wayback_first_seen", "document_heading", "read_date", "sheet_date")
FOLD_SHOWN = 20
TIES = "Ties to Flanders and Belgium"
GROUPS = ("Work", "Education", TIES, "Places")
DONE = {"add": "Added to your network", "skip": "Skipped", "merge": "Merged into this profile",
        "not_same": "Marked as a different person"}
RESULTS_STEP = 20
HEADINGS = {1: "Topic and a tie to Flanders or Belgium", 2: "Topic, no known tie", 3: "Tie, topic not confirmed", 4: "Other people found"}
LOOKUP_WINDOW = timedelta(seconds=60)
OLD_LINE = "First record {year}, nothing recent"
ADDED = "Looked up on {date}: added {parts}."
NOTHING = "Looked up on {date}. Nothing new found."
NOT_SURE = "Looked up on {date}. Nothing added, because FN could not be sure the pages it found are about this person."
STOPPED = "This lookup stopped before it finished. Nothing was added."
GROUP_KEYS = ("other", "outside", "abroad", "unfit")
GROUP_TITLES = {"other": "Other people found", "abroad": "Outside the US", "unfit": "Other roles or topics"}
SET_ASIDE = "Set aside"
CLOSEST = "The closest people are below."
TIE_BELOW = "The people below have a known tie, but FN could not confirm their topic."
US_NAMES = ("us", "usa", "us based", "united states")
SOFTENERS = ("ideally", "preferably", "if possible")
READ_CHARS = 60
WORK = "OpenAlex work "
UNKNOWN_DATE = "date unknown"
QUOTE_WORDS = 25
REASON_WORDS = 15
NO_TIE = "No known tie to Flanders"
FIELD_LABEL = re.compile(r"[*•-]\s*(?:[^\W_]| ){1,30}:")
ENTITY = re.compile(r"&#?\w+;")
IMAGE_TOKENS = ("orcid image", "author orcid", "![", "[image")
MIN_QUOTE_WORDS = 4
COMPARE_FIELDS = ("Name", "Job", "Employer", "Place", "Studied", "Belgian tie", "Email", "Phone", "LinkedIn", "ORCID", "Found in")
FILE_FIELDS = ("Name", "Job", "Employer", "Place", "Email", "Phone", "LinkedIn", "ORCID")
DIFFERS = ("Employer", "Place", "Email", "Phone", "LinkedIn", "ORCID")
COMPARE_SHOWN = 3
SAME_SPOT_KM = 10.0  # an employer-based place sits on the org's coordinates, not the city centre
IMPORT_ROW = re.compile(r", row \d+$")
SOURCE_DAY = re.compile(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def in_city(org: Org | None, place: str | None) -> bool:
    """Whether the organization's city is the place, or the place's first part, as in 'Boston, MA'."""
    return bool(org and org.city and place and (place == org.city or place.startswith(f"{org.city},")))


def belgian_orgs(claims: list[Claim], facts: dict[str, Org]) -> list[tuple[str, list[int]]]:
    """Each Belgian organization the claims name with the years of those claims, earliest first."""
    years: dict[str, set[int]] = {}
    for claim, org in orgs.belgian_claims(claims, facts):
        years.setdefault(org.name, set()).update(int(u) for u in rank.units(claim) if u != rank.UNDATED)
    return sorted(((name, sorted(found)) for name, found in years.items()), key=lambda t: (t[1][:1] or [9999], t[0]))


def evidence(claims: list[Claim], facts: dict[str, Org], matched: list[str], topic: str | None = None) -> Claim | None:
    """The claim to show on a card: the topic claim when it is among the claims, else the newest at a Belgian
    organization, else the first the search matched."""
    if found := next((c for c in claims if c.id == topic), None):
        return found
    belgian = [c for c, _ in orgs.belgian_claims(claims, facts)]
    if belgian:
        return max(belgian, key=lambda c: (c.claim_date or "", c.id))
    return next((c for c in claims if c.id in matched), None)


def date_words(claim: Claim) -> str:
    """The claim's date as people write it: 2025, March 2024, 3 March 2024 or UNKNOWN_DATE.

    The day FN read an undated page reads "read 3 March 2024", so it is not taken for the page's own date.
    """
    parts = [int(p) for p in (claim.claim_date or "").split("-") if p.isdigit()]
    precision = claim.date_precision or ("year", "month", "day")[min(len(parts), 3) - 1] if parts else None
    if precision == "day" and len(parts) == 3:
        return ("read " if claim.date_method == "read_date" else "") + f"{parts[2]} {month_name[parts[1]]} {parts[0]}"
    if precision in ("month", "day") and len(parts) >= 2:
        return f"{month_name[parts[1]]} {parts[0]}"
    return str(parts[0]) if parts else UNKNOWN_DATE


def cut(text: str, limit: int) -> str:
    """The text, or its words up to limit characters and '…' when it is longer."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def plural(count: int, one: str, many: str) -> str:
    return f"{count:,} {one if count == 1 else many}"


def days_ago(at: datetime, today: date) -> str:
    """A past moment as people say it: today, yesterday, 3 days ago, last week, else 3 March 2026."""
    local = at.astimezone()
    days = (today - local.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago" if days < 7 else "last week" if days < 14 else f"{local.day} {local:%B %Y}"


def newest(claims: list[Claim]) -> Claim | None:
    """The claim with the latest date, undated ones first and equal dates by id, or None."""
    return max(claims, key=lambda c: (c.claim_date or "", c.id), default=None)


def place_of(claims: list[Claim]) -> Claim | None:
    """The newest dated location claim with coordinates, else an undated one with them, else the newest location.

    A born_in or origin claim never places anyone.
    """
    found = [c for c in claims if c.kind == "location" and c.relation not in ("born_in", "origin")]
    dotted = [c for c in found if c.lat is not None and c.lon is not None]
    return newest([c for c in dotted if c.claim_date] or dotted or found)


def located(claims: list[Claim], facts: dict[str, Org], today: date) -> tuple[str | None, float | None, float | None, str | None]:
    """The place, its coordinates and its basis: the newest stated place, else the city of the newest recent employer.

    Without either, the newest location claim gives its text only, as a stated place.
    """
    found, by_id = places(claims, facts, today), {c.id: c for c in claims}
    if place := ev.shown(found, by_id):
        return place.text, place.lat, place.lon, place.basis
    text = place_of(claims)
    return (text.value, None, None, "stated") if text else (None, None, None, None)


def linkedin(source: Source) -> bool:
    """Whether the source's page is on linkedin.com, whose profiles are records and not pages."""
    host = urlsplit(source.url).hostname or ""
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def prose(source: Source) -> bool:
    """Whether the source is a page with text a quote can come from; a LinkedIn profile is a record."""
    return source.kind in PROSE and not linkedin(source)


def own_years(claim: Claim, source: Source) -> frozenset[int]:
    """The years that belong to the fact: the ranker's units, without the year of a claim_date that is the day the
    source's record was read or changed. A death's year is in its words, so it has none.
    """
    if claim.kind == "death":
        return frozenset()
    stamped = claim.date_method in RECORD_DATES or claim.claim_date == source.source_date
    found = rank.units(claim.model_copy(update={"claim_date": None}) if stamped else claim)
    return frozenset(int(u) for u in found if u != rank.UNDATED)


def span_words(years: frozenset[int]) -> str:
    """The years as one span, '2009–2026', as one year, '2015', or empty."""
    if not years:
        return ""
    first, last = min(years), max(years)
    return str(first) if first == last else f"{first}–{last}"


def gap_words(years: frozenset[int]) -> str:
    """The years as runs, '2009, 2011–2012', when they have gaps, else empty."""
    if not years or max(years) - min(years) + 1 == len(years):
        return ""
    return rank.years_text(frozenset(map(str, years))).replace("-", "–")


def what_of(claim: Claim, org: Org | None) -> str:
    """The fact in plain words, such as 'Studied at KU Leuven', 'Topic: 6G', 'Born in Leuven' or 'Died 1966'.

    A role starts with a capital letter; a list role at an organization reads as its relation.
    """
    if claim.kind == "availability":
        return claim.value
    if claim.kind == "death":
        return f"Died {claim.value}"
    if claim.kind == "role":
        if claim.relation in LIST_ROLES and org:
            return f"{RELATIONS[claim.relation]} {org.name}"
        return claim.value[:1].upper() + claim.value[1:]
    if claim.kind == "location" and claim.relation == "origin":
        return f"Origin: {claim.value}"
    if claim.kind == "location":
        return f"{'Born in' if claim.relation == 'born_in' else 'Based in'} {claim.value}"
    if claim.kind in FIELDS:
        return f"{FIELDS[claim.kind]}: {claim.value}"
    name = org.name if org else claim.value
    return f"{RELATIONS[claim.relation]} {name}" if claim.relation in RELATIONS else name


def is_fact(claim: Claim, source: Source) -> bool:
    """Whether a claim is a fact the page shows: not a role the source does not state, such as its title, and not a
    place a record gives for an institution.
    """
    if claim.kind == "role" and claim.relation is None:
        return ev.stated_role(claim, source)
    return claim.kind != "location" or claim.relation is not None or prose(source)


def is_work(source: Source) -> bool:
    return source.kind == "record" and (source.title or "").startswith(WORK)


def label_of(source: Source) -> str:
    """The source as a citation names it: the record kind, the import file and row (its title), else the page title or host."""
    if is_work(source):
        return WORK.strip()
    if source.kind in RECORD_LABELS:
        return RECORD_LABELS[source.kind]
    if linkedin(source):
        return RECORD_LABELS["vendor_record"]
    if source.kind == "import":
        return f"Import {source.title}"
    return source.title or urlsplit(source.url).hostname or source.url


def source_name(source: Source) -> str:
    """The source's short name: the host of a page without a leading www., else its label."""
    host = (urlsplit(source.url).hostname or "").removeprefix("www.")
    return host if prose(source) and host else label_of(source)


def record_label(source: Source) -> str:
    """The name a row of Sources or a cite gives the source: a list by its title, else the source's short name."""
    return source.title if source.kind == "seed_page" and source.title else source_name(source)


def quoted(text: str) -> str:
    """The text in quote marks, inner double quotes made single."""
    inner = text.replace('"', "'").replace("“", "‘").replace("”", "’")
    return f"“{inner}”"


def quote_words(claim: Claim, cut_quote: bool) -> str:
    """The quote on one line in quote marks, inner double quotes made single, cut at 240 characters when cut_quote."""
    text = " ".join(claim.quote.split())
    return quoted(cut(text, 240) if cut_quote else text)


def debris(quote: str) -> bool:
    """Whether a quote is page furniture: it starts with a field label after a list mark, holds image or author-list
    tokens or a markup entity, or has fewer than 4 words.
    """
    text = " ".join(unescape(quote).split())
    return bool(FIELD_LABEL.match(text) or ENTITY.search(text) or any(t in fold(text) for t in IMAGE_TOKENS)
                or len(text.split()) < MIN_QUOTE_WORDS)


def proof_quote(claim: Claim, source: Source, name: str, words: list[str]) -> str | None:
    """The quote shown in an opened proof, or None for a record, page debris or an empty quote.

    It is at most 25 words centred on the first of words the quote holds (else from its start), with '…' at a cut end.
    """
    if not prose(source) or debris(claim.quote):
        return None
    text = " ".join(unescape(claim.quote).split())
    found, held = text.split(" "), fold(text)
    word = next((w for w in words if fold(w) in held), None)
    at = next((n for n, w in enumerate(found) if word and fold(word) in fold(w)), 0)
    start = max(min(at - QUOTE_WORDS // 2, len(found) - QUOTE_WORDS), 0)
    end = start + QUOTE_WORDS
    return quoted(f"{'…' if start else ''}{' '.join(found[start:end])}{'…' if end < len(found) else ''}")


def source_sentence(claim: Claim, source: Source, org: Org | None, name: str) -> str:
    """The one sentence a source page opens with: the stored fact, said as the page or the record says it, or only
    that the page names the person when the claim is no fact.
    """
    if not is_fact(claim, source):
        return f"The page names {name}."
    view = claim_view(claim, source, org)
    fact = f"{view.what}, {view.years}" if view.years else view.what
    return f"{'The page says' if prose(source) else 'The record lists'}: {fact}."


def source_cite(claim: Claim, source: Source, org: Org | None) -> str:
    """The proof's '{source name}, {date}' as the source page shows it, the date left out when unknown."""
    when = claim_view(claim, source, org).date
    return record_label(source) if when == UNKNOWN_DATE else f"{record_label(source)}, {when}"


def passage(source: Source, claim: Claim, words: int = 60) -> tuple[str, str, str]:
    """The text before the quote, the quote and the text after it, each side cut to words words with '…'.

    White space is collapsed. A side with no space in the 400 characters next to a cut is cut at 400 characters.
    """
    def side(text: str, before: bool) -> str:
        parts = " ".join(text.split()).split(" ")
        kept = " ".join(parts[-words:] if before else parts[:words])
        cut_here = len(parts) > words
        if len(kept) > 400 and " " not in (kept[-400:] if before else kept[:400]):
            kept, cut_here = (kept[-400:] if before else kept[:400]), True
        if not kept:
            return ""
        if before:
            return ("… " if cut_here else "") + kept + (" " if text[-1:].isspace() else "")
        return (" " if text[:1].isspace() else "") + kept + (" …" if cut_here else "")
    text = source.text
    return (side(text[:claim.quote_start], True), " ".join(text[claim.quote_start:claim.quote_end].split()),
            side(text[claim.quote_end:], False))


def claim_view(claim: Claim, source: Source, org: Org | None, seen_at: datetime | None = None,
               cut_quote: bool = True) -> ClaimView:
    """The claim as every page words it: the fact, its years, the quote when the source is prose, and the citation.

    org is the claim's stored orgs row, if any; is_new is true when the claim was first stored after seen_at. A topic
    claim from an OpenAlex work reads 'Paper: ' and the title, cut like a quote when cut_quote.
    """
    label, href, when = label_of(source), f"/sources/{claim.source_id}?claim={claim.id}#quote", date_words(claim)
    quote = QuoteView(text=quote_words(claim, cut_quote), label=label, href=href, date=when) if prose(source) else None
    own = own_years(claim, source)
    paper = claim.kind == "topic" and is_work(source)
    what = f"Paper: {cut(claim.value, 240) if cut_quote else claim.value}" if paper else what_of(claim, org)
    return ClaimView(claim_id=claim.id, kind=claim.kind, what=what, years=span_words(own), all_years=gap_words(own),
                     quote=quote, label=label, href=href, date=when,
                     is_new=bool(seen_at and claim.first_seen_at and claim.first_seen_at > seen_at),
                     source=source_name(source), url=None if source.url.startswith("fn:") else source.url)


def day_words(at: datetime) -> str:
    """The local day of the time, such as '3 November 2026'."""
    local = at.astimezone()
    return f"{local.day} {local:%B %Y}"


def added_on(store: Store, person_id: str) -> str | None:
    """The day of the person's latest add event, such as '3 November 2026', or None when there is none."""
    at = next((e.at for e in store.events_of(person_id) if e.kind == "add"), None)
    return day_words(at) if at else None


@dataclass(eq=False)
class Line:
    """One fact line: the claims that stand in it, the newest of them, the role it names, and where it sorts."""
    claims: list[Claim]
    shown: Claim
    role: Claim | None
    org: Org | None
    what: str
    own: frozenset[int]
    last: int
    tier: int = 3
    folded: bool = False
    roles: list[Claim] = field(default_factory=list)

    @property
    def span(self) -> int:
        return max(self.own) - min(self.own) + 1 if self.own else 0

    @property
    def joined(self) -> bool:
        return self.role is not None and self.role is not self.shown

    @property
    def belgian(self) -> bool:
        return bool(self.org and self.org.country_code == "BE")


def joined_roles(claims: list[Claim], sources: dict[str, Source]) -> dict[str, Claim]:
    """Each employer claim id with the stated role of its source that joins it.

    A role joins the works_at or affiliated_with claim of its source whose quote overlaps its own, works_at first,
    else the only such claim when the source holds one stated role; never a worked_at claim. A rejected claim joins
    only a rejected one.
    """
    roles = [c for c in claims if ev.stated_role(c, sources[c.source_id])]
    jobs = [c for c in claims if c.relation in CURRENT]
    joined: dict[str, Claim] = {}
    for role in roles:
        here = [j for j in jobs if j.source_id == role.source_id]
        free = [j for j in here if j.id not in joined and bool(j.rejected_at) == bool(role.rejected_at)]
        near = [j for j in free if j.quote_start < role.quote_end and role.quote_start < j.quote_end]
        alone = free if len(here) == 1 and sum(r.source_id == role.source_id for r in roles) == 1 else []
        if pick := min(near or alone, key=lambda j: CURRENT.index(j.relation), default=None):
            joined[pick.id] = role
    return joined


def names(text: str, name: str) -> bool:
    """Whether the text holds the name, compared by name_key on whole words."""
    return f" {name_key(name)} " in f" {name_key(text)} "


def lines_of(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source]) -> list[Line]:
    """One line per fact: claims with one kind, relation and organization or value are one line, cited by the newest.

    A stated role joined to an employer claim is one line with it. The claims one Not correct removed share the
    rejected state in their key, so they make one removed line.
    """
    joins = joined_roles(claims, sources)
    taken = {r.id for r in joins.values()}
    same: dict[tuple, list[Claim]] = {}
    for claim in claims:
        if claim.id in taken:
            continue
        if claim.id in joins:
            key = ("joined", fold(joins[claim.id].value), claim.org_id or fold(claim.value))
        else:
            key = line_key(claim)
        key = (bool(claim.rejected_at), *key)
        same.setdefault(key, []).append(claim)
    return [line_of(found, joins, facts, sources) for found in same.values()]


def line_of(found: list[Claim], joins: dict[str, Claim], facts: dict[str, Org], sources: dict[str, Source]) -> Line:
    shown = newest(found)
    org = facts.get(shown.org_id or "")
    role = joins.get(shown.id) or (shown if shown.kind == "role" and shown.relation is None else None)
    roles = [joins[c.id] for c in found if c.id in joins]
    parts = [*found, *roles]
    own = frozenset().union(*(own_years(c, sources[c.source_id]) for c in parts))
    last = max((int(u) for c in parts for u in rank.units(c) if u != rank.UNDATED), default=0)
    what = what_of(shown, org)
    if role is not None and role is not shown:
        what = what_of(role, None)
        name = org.name if org else shown.value
        if not names(what, name):
            what = f"{what}, {name}"
    return Line(claims=found, shown=shown, role=role, org=org, what=what, own=own, last=last, roles=roles)


def text_key(what: str) -> str:
    """The words with spaces collapsed and case folded, so two lines that read the same compare equal."""
    return " ".join(what.split()).casefold()


def newest_key(line: Line) -> tuple[str, str]:
    """The sort key of newest for the line's shown claim."""
    return line.shown.claim_date or "", line.shown.id


def merged(base: Line, others: list[Line]) -> Line:
    """The base line with the claims and roles of the others, the years of all, the latest year and the best tier."""
    return replace(base, claims=[*base.claims, *(c for o in others for c in o.claims)],
                   roles=[*base.roles, *(r for o in others for r in o.roles)],
                   own=base.own.union(*(o.own for o in others)), last=max(base.last, *(o.last for o in others)),
                   tier=min(base.tier, *(o.tier for o in others)))


def collapse(lines: list[Line], sets: list[tuple[Line, list[Line]]]) -> list[Line]:
    """The lines with each (base, others) set made one merged line, standing where the set's first line stood."""
    place = {id(line): n for n, line in enumerate(lines)}
    out: dict[int, Line | None] = {}
    for base, others in filter(lambda found: found[1], sets):
        first = min((base, *others), key=lambda line: place[id(line)])
        out |= {id(line): None for line in (base, *others)}
        out[id(first)] = merged(base, others)
    return [found for line in lines if (found := out.get(id(line), line))]


def groups_of(lines: list[Line], key: Callable[[Line], object]) -> list[list[Line]]:
    """The lines in groups of one key, in the order of each group's first line; a None key leaves the line alone."""
    found: dict = {}
    for n, line in enumerate(lines):
        found.setdefault(key(line) or n, []).append(line)
    return [group for group in found.values() if len(group) > 1]


def org_key(lines: list[Line]) -> Callable[[Line], object]:
    """The key of a Work line about an organization: its orgs row id, else the smallest id of a row in the lines
    with its name, else its name; None for a line without a relation.
    """
    ids: dict[str, str] = {}
    for line in lines:
        if line.org:
            ids[text_key(line.org.name)] = min(line.org.id, ids.get(text_key(line.org.name), line.org.id))

    def key(line: Line) -> tuple | None:
        if line.shown.relation not in RELATIONS:
            return None
        found = line.org.id if line.org else ids.get(text_key(line.shown.value))
        return bool(line.shown.rejected_at), "org" if found else "name", found or text_key(line.shown.value)
    return key


def fold_org(lines: list[Line]) -> list[Line]:
    """Work lines about one organization are one line: lines with one stated role fold into the newest of them, and
    lines without a role into the newest role line, else into the newer of their Works at and Worked at lines, else
    the newest.
    """
    sets = []
    for group in groups_of(lines, org_key(lines)):
        bare = [line for line in group if not line.joined]
        roles: dict[str, list[Line]] = {}
        for line in group:
            if line.joined:
                roles.setdefault(text_key(line.role.value), []).append(line)
        heads = [(base, [line for line in same if line is not base])
                 for same in roles.values() for base in [max(same, key=newest_key)]]
        if heads:
            top = max((base for base, _ in heads), key=newest_key)
            heads = [(base, others + bare if base is top else others) for base, others in heads]
        else:
            current = [line for line in bare if line.shown.relation in ("works_at", "worked_at")]
            base = max(current or bare, key=newest_key)
            heads = [(base, [line for line in bare if line is not base])]
        sets += heads
    return collapse(lines, sets)


def fold_places(lines: list[Line]) -> list[Line]:
    """Place lines at one spot, to two decimals of latitude and longitude, are one line with the longest words."""
    def spot(line: Line) -> tuple | None:
        claim = line.shown
        if claim.kind != "location" or claim.lat is None or claim.lon is None:
            return None
        return bool(claim.rejected_at), claim.relation, round(claim.lat, 2), round(claim.lon, 2)
    sets = []
    for group in groups_of(lines, spot):
        base = max(group, key=lambda line: (len(line.what), *newest_key(line)))
        sets.append((base, [line for line in group if line is not base]))
    return collapse(lines, sets)


def fold_words(lines: list[Line]) -> list[Line]:
    """Lines with the same words, case and spacing aside, are one line; one about an organization stands before a
    loose title.
    """
    sets = []
    for group in groups_of(lines, lambda line: (bool(line.shown.rejected_at), text_key(line.what)) if text_key(line.what) else None):
        base = max(group, key=lambda line: (line.org is not None or line.joined, *newest_key(line)))
        sets.append((base, [line for line in group if line is not base]))
    return collapse(lines, sets)


def fold_lines(lines: list[Line], work: bool) -> list[Line]:
    """The lines with the ones that state one fact folded into one, each where its group's first line stood.

    Work lines about one organization fold first, then places at one spot, then lines with the same words. Lines
    fold only within one rejected state.
    """
    return fold_words(fold_places(fold_org(lines) if work else lines))


def work_lines(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source], today: date,
               place: str | None = None) -> list[Line]:
    """The Work lines in order, the folded ones last.

    The head is the current line with the longest span; then lines with a stated role, lines at a Belgian
    organization and the rest, each longest span first. A line a record lists for one year at a non-Belgian
    organization folds, unless it is the head.
    """
    lines = lines_of(claims, facts, sources)
    current = [line for line in lines if any(
        c.relation == "works_at" or (c.relation == "affiliated_with" and line.last >= today.year - 1)
        for c in line.claims)]
    head = min(current, key=lambda s: (-s.span, not s.joined, not in_city(s.org, place), -s.last, s.what.casefold()),
               default=None)
    for line in lines:
        line.tier = 0 if line is head else 1 if line.role else 2 if line.belgian else 3
        line.folded = (line is not head and line.shown.relation == "affiliated_with" and not line.shown.rejected_at
                       and not prose(sources[line.shown.source_id]) and len(line.own) == 1 and not line.belgian)
    lines.sort(key=lambda s: (s.folded, s.tier, -s.span, -s.last, s.what.casefold()))
    return lines


def head_line(lines: list[Line]) -> Line | None:
    """The line that names the person's job: the current job, else the first line with a stated role, else None."""
    return lines[0] if lines and lines[0].tier < 2 else None


def job_claims(claims: list[Claim], sources: dict[str, Source]) -> list[Claim]:
    """The claims that can make a head line: stated roles and employer claims."""
    return [c for c in claims if ((c.kind == "role" and c.relation is None) or c.relation in JOINING)
            and is_fact(c, sources[c.source_id])]


def reason_rank(claim: Claim, sources: dict[str, Source]) -> int | None:
    """0 for a stated role or a topic a page gives, 1 for a topic fact from a record, else None."""
    if claim.rejected_at or claim.relation is not None or claim.kind not in ("role", "topic"):
        return None
    source = sources[claim.source_id]
    if claim.kind == "role":
        return 0 if ev.stated_role(claim, source) else None
    return 0 if prose(source) else 1


def reason_claim(claims: list[Claim], sources: dict[str, Source], ids: Sequence[str], role_line: str) -> Claim | None:
    """The claim a card gives as its reason: the first of the stored ids, else of the newest claims, that is a role or
    topic claim by reason_rank (rank 0 before 1) and whose words the role line does not already hold. A topic from a
    source that also lists the person as a fellow, host guest or student is that fellow's study, not a reason.
    """
    held = set(name_key(role_line).split())
    lists = {c.source_id for c in claims if c.relation in ("fellow_of", "hosted_by", "studied_at") and not c.rejected_at}
    claims = [c for c in claims if c.kind != "topic" or c.source_id not in lists]
    by_id = {c.id: c for c in claims}
    newest_first = sorted(claims, key=lambda c: (c.claim_date or "", c.id), reverse=True)
    for pool in ([by_id[i] for i in dict.fromkeys(ids) if i in by_id], newest_first):
        ranked = [(reason_rank(c, sources), c) for c in pool]
        for want in (0, 1):
            if found := next((c for r, c in ranked if r == want and not set(name_key(what_of(c, None)).split()) <= held), None):
                return found
    return None


def person_view(store: Store, person: Person, claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source],
                shown: Claim | None, today: date, records: int = 1, tie_ids: Sequence[str] = (),
                reason_ids: Sequence[str] | None = None) -> PersonView:
    """The view of one person from the claims of its records; shown is the claim the card gives as evidence.

    records is how many records not merged into one person the claims come from; tie_ids are the claim ids of the
    tie, strongest first. The role and employer are the head line's. With reason_ids, the evidence is the card's
    reason claim (see reason_claim) in place of shown.
    """
    member = person.list_status == "in_list"
    seen_at = person.seen_at if member else None
    (place, lat, lon, basis), found = located(claims, facts, today), belgian_orgs(claims, facts)
    lines = work_lines(job_claims(claims, sources), facts, sources, today, place)
    head = head_line(lines)
    role = head.role if head else None
    employer = (head.org.name if head.org else head.shown.value) if head and head.shown.relation in JOINING else None
    if employer and role and names(what_of(role, None), employer):
        employer = None
    if reason_ids is not None:
        shown = reason_claim(claims, sources, reason_ids, ", ".join(x for x in (what_of(role, None) if role else "", employer) if x))
    contact = {kind: newest([c for c in claims if c.kind == kind]) for kind in ("email", "phone")}
    tie = tie_claim(claims, facts, tie_ids)
    return PersonView(
        person_id=person.id, name=person.display_name, role=what_of(role, None) if role else None,
        employer=employer, place=place, lat=lat, lon=lon, place_basis=basis, records=records,
        orgs=[OrgView(org=name, years=f"{y[0]}–{y[-1]}" if len(y) > 1 else "".join(map(str, y))) for name, y in found[:3]],
        more_orgs=max(len(found) - 3, 0),
        evidence=claim_view(shown, sources[shown.source_id], facts.get(shown.org_id or ""), seen_at) if shown else None,
        status=person.list_status, added=added_on(store, person.id) if member else None,
        new_facts=sum(1 for c in claims if seen_at and c.first_seen_at and c.first_seen_at > seen_at),
        email=contact["email"].value if contact["email"] else None,
        phone=contact["phone"].value if contact["phone"] else None,
        tie=what_of(tie, facts.get(tie.org_id or "")) if tie else None, tie_claim_id=tie.id if tie else None,
    )


def person_views(store: Store, groups: list[list[str]], today: date, matched: list[list[str]] | None = None,
                 topics: list[str | None] | None = None, tie_ids: list[list[str] | None] | None = None,
                 reasons: list[list[str]] | None = None) -> list[PersonView]:
    """One view per group of stored person ids, named after its first; all claims come from one claims_of call.

    Ids are mapped to their canonical person first. matched holds, per group, the claim ids a search matched,
    which the evidence falls back to when the group has no claim at a Belgian organization. topics holds, per
    group, the claim the evidence shows first. tie_ids holds, per group, the claim ids of its tie, strongest first; a
    group with None takes the tie evidence's, and without tie_ids no view has a tie. reasons holds, per group, the stored
    reason claim ids; with it the evidence is the card's reason claim and matched and topics are not read.
    """
    canonical = store.canonical_ids([p for g in groups for p in g])
    groups = [list(dict.fromkeys(canonical[p] for p in g)) for g in groups]
    ids = list(dict.fromkeys(p for g in groups for p in g))
    by_person: dict[str, list[Claim]] = {}
    for claim in store.claims_of(ids):
        by_person.setdefault(claim.person_id, []).append(claim)
    persons = store.get_persons(ids)
    facts = store.get_orgs(list({c.org_id for found in by_person.values() for c in found if c.org_id}))
    owned = [[c for p in g for c in by_person.get(p, [])] for g in groups]
    shown = [None if reasons is not None else evidence(claims, facts, m, t) for claims, m, t in
             zip(owned, matched or [[] for _ in groups], topics or [None for _ in groups])]
    needed = {c.source_id for claims in owned for c in claims
              if c.kind == "role" or c.relation in JOINING or (reasons is not None and c.kind == "topic")}
    sources = store.get_sources(list(needed | {c.source_id for c in shown if c}))
    tied = [[] if tie_ids is None else t if t is not None else evidence_tie(store, g, claims, facts, today)
            for g, claims, t in zip(groups, owned, tie_ids or [None for _ in groups])]
    return [person_view(store, persons[g[0]], claims, facts, sources, s, today, len(g), t, r)
            for g, claims, s, t, r in zip(groups, owned, shown, tied, reasons or [None for _ in groups])]


def heading_of(candidate: Candidate) -> str:
    """The heading the candidate stands under in the new section: its tier's; the candidate must have a tier."""
    return HEADINGS[rank.heading(candidate.tier, candidate.fit.tie_grade if candidate.fit else "none")]


def is_open(candidate: Candidate, chips: Chips | None) -> bool:
    """Whether the candidate stands in the open list the count and the map read: always on chips before version 2,
    else a network person, one without a tier, or one not set aside under headings 1 to 3."""
    if chips is None or chips.version < 2 or candidate.section == "network" or candidate.tier is None:
        return True
    return candidate.aside is None and rank.heading(candidate.tier, candidate.fit.tie_grade if candidate.fit else "none") <= 3


def area_words(place: Place) -> str:
    """The place as the reading line and the group title say it: 'in the US', 'in North Carolina', 'in the US West
    Coast', 'in Belgium' or, for a city or metro area, 'in the New York area'."""
    key, text = name_key(place.text), re.sub(r"^the\s+", "", place.text.strip(), flags=re.IGNORECASE)
    if place.kind == "anywhere_us":
        if key in US_NAMES:
            return "in the US"
        return f"in {place.text}" if regions_of(key, free_text=True) else f"in the {text}"
    if place.kind == "abroad":
        return f"in {place.text}"
    return f"in the {text}" if text.lower().endswith(" area") else f"in the {text} area"


def plain(text: str) -> str:
    """The chip's text without a leading softener or a trailing 'if possible', cut to READ_CHARS."""
    text = text.strip()
    for word in SOFTENERS:
        if re.match(rf"{word}\b", text, re.I):
            text = text[len(word):].lstrip(" ,")
            break
    if text.lower().endswith(" if possible"):
        text = text[:-len(" if possible")].rstrip(" ,")
    return cut(text, READ_CHARS)


def parts_of(chips: Chips) -> list[tuple[str, str]]:
    """The (need, words) of each part of the question, in reading order: roles, topics, institutions, tie, place."""
    found = [(c.need, c.text) for c in [*chips.roles, *chips.topics, *chips.institutions, *([chips.tie] if chips.tie else [])]]
    return [*found, *([(chips.place.need, area_words(chips.place))] if chips.place else [])]


def reading(chips: Chips | None) -> tuple[str | None, str | None] | None:
    """How FN read the question as (Required line, Wished line); None without chips, on version 1 or with no part."""
    if chips is None or chips.version < 2:
        return None
    seen, words = set(), {"must": [], "nice": []}
    for need, text in parts_of(chips):
        text = plain(text)
        if text and name_key(text) not in seen:
            seen.add(name_key(text))
            words[need].append(text)
    if not (words["must"] or words["nice"]):
        return None
    return tuple(f"{label}: {', '.join(found)}" if found else None
                 for label, found in (("Required", words["must"]), ("Wished", words["nice"])))


def group_key(candidate: Candidate, chips: Chips | None) -> str | None:
    """The set-aside group the candidate stands in, one of GROUP_KEYS; None for an open person. An outside person
    under a question without a place stands in 'other'."""
    if is_open(candidate, chips):
        return None
    key = candidate.aside or "other"
    return "other" if key == "outside" and (chips is None or chips.place is None) else key


def group_title(key: str, chips: Chips | None) -> str:
    """The group's title: 'Outside the Boston area' for outside, else its fixed words."""
    if key == "outside" and chips and chips.place:
        return "Outside " + area_words(chips.place).removeprefix("in ")
    return GROUP_TITLES[key]


def results_headings(candidates: list[Candidate], skipped: list[bool], shown: list[str],
                     chips: Chips | None) -> list[ResultsHeading]:
    """The new section's headings with the open people not skipped under each and the first shown card under it.

    shown holds the keys of the shown cards. Empty when a person of the section has no tier.
    """
    new = [(c, s) for c, s in zip(candidates, skipped) if c.section == "new" and is_open(c, chips)]
    if any(c.tier is None for c, _ in new):
        return []
    titles = {c.person_id: heading_of(c) for c, _ in new}
    counts = Counter(titles[c.person_id] for c, s in new if not s)
    firsts = {}
    for key in shown:
        if key in titles:
            firsts.setdefault(titles[key], key)
    return [ResultsHeading(title=title, count=counts[title], first_key=key) for title, key in firsts.items()]


def skipped_here(store: Store, person_id: str, search_id: str) -> bool:
    """Whether the person's latest skip was made on this search."""
    skip = next((e for e in store.events_of(person_id) if e.kind == "skip"), None)
    return bool(skip and skip.search_id == search_id)


def is_skipped(store: Store, candidate: Candidate) -> bool:
    """Whether every person on the candidate's card is skipped."""
    hits = identity.on_card(store, candidate)
    canonical = store.canonical_ids(hits)
    persons = store.get_persons(list(set(canonical.values())))
    return all(persons[canonical[p]].list_status == "skipped" for p in hits if p in canonical)


def added_card(store: Store, candidate: Candidate, base: dict, event: Event | None, today: date) -> CardView:
    """The card of a person added since: the note of the add or merge that brought them in, and its Undo."""
    view = base["person"]
    added = next((e for e in store.events_of(view.person_id)
                  if e.kind in ("add", "merge") and e.person_id == view.person_id), None)
    match, note, href = None, None, None
    if added and added.kind == "merge" and any(r["id"] in identity.on_card(store, candidate) for r in added.detail["merged"]):
        match, note = view, f"· same person as {view.name}"
    elif added and added.kind == "add" and added.detail.get("not_same"):
        match, note = person_views(store, [added.detail["not_same"][:1]], today)[0], "· as a new person"
    elif added and added.kind == "add" and (apart := len(added.detail.get("left_apart", []))):
        note, href = plural(apart, "possible match", "possible matches"), f"/people/{view.person_id}#matches"
    undo = (LastView(event_id=added.id, kind=added.kind, words=DONE["add"])
            if added and event and event.id == added.id else None)
    return CardView(**base, state="added", match=match, undo_event=undo, note=note, note_href=href)


def topic_claim(candidate: Candidate) -> str | None:
    """The first claim of the candidate's stored topic part, or None."""
    return next((p.claim_ids[0] for p in candidate.score_parts if p.feature == "topic" and p.claim_ids), None)


def reason_of(view: ClaimView | None, href: str) -> ReasonView | None:
    """The card's reason line: the fact cut at a word with '…' so that it, its years and its source name are at most
    15 words, then its years; None without a claim.
    """
    if view is None:
        return None
    room = max(REASON_WORDS - len(view.years.split()) - len(view.source.split()), 1)
    words = view.what.split()
    what = view.what if len(words) <= room else " ".join(words[:room]).rstrip(" ,;:.") + "…"
    return ReasonView(text=f"{what}, {view.years}" if view.years else what, source=view.source, href=href)


def place_words(view: PersonView) -> str | None:
    """'place unknown' when the person's role line shows no place, else None: the role line names a place itself."""
    return None if view.place else "place unknown"


def candidate_view(store: Store, candidate: Candidate, today: date) -> PersonView:
    """The view of the candidate's card, with the tie the ranker stored for it, else the tie evidence's."""
    return person_views(store, [identity.on_card(store, candidate)], today, tie_ids=[fit_tie(candidate.fit)],
                        reasons=[reason_ids(candidate)])[0]


def reason_ids(candidate: Candidate) -> list[str]:
    """The claim ids the ranker stored for the card's reason: its topic claim, then its reason claims."""
    return [*([c] if (c := topic_claim(candidate)) else []), *candidate.reason_claim_ids]


def fit_words(candidate: Candidate, view: PersonView) -> str | None:
    """The card's second line: the tie in words, left out under the heading 'Topic, no known tie', then the place words."""
    quiet = candidate.tier is not None and heading_of(candidate) == HEADINGS[2]
    # A tie that only says where the person is based repeats the place of the role line.
    repeat = bool(view.tie and view.place and name_key(view.tie) == name_key(f"Based in {view.place}"))
    parts = [None if quiet or repeat else view.tie or NO_TIE, place_words(view)]
    return " · ".join(p for p in parts if p) or None


def aside_line(store: Store, candidate: Candidate, today: date) -> ReasonView | None:
    """The place fact the ranker read, as the line that sets the card aside, with its source and no years: a stated
    place as its claim words it ('Based in Houston, TX'), an employer's as 'Works at Example Lab, Houston'. None when
    the card has no located place.
    """
    claims = store.claims_of(identity.on_card(store, candidate))
    facts = store.get_orgs(list({c.org_id for c in claims if c.org_id}))
    by_id = {c.id: c for c in claims}
    if (place := ev.shown(places(claims, facts, today), by_id)) is None:
        return None
    claim = by_id[place.claim_id]
    source = store.get_sources([claim.source_id])[claim.source_id]
    org = facts.get(claim.org_id or "")
    view = claim_view(claim, source, org)
    what = f"Works at {org.name}, {place.text}" if place.basis == "employer" and org else view.what
    return ReasonView(text=what, source=view.source, href=view.href)


def card_view(store: Store, search: Search, candidate: Candidate, view: PersonView, skipped: bool,
              today: date) -> CardView:
    """The candidate's card: its state from the people's status now, the same-name network person and the Undo.

    An outside or abroad card also has the place fact that set it aside, and its role line then leaves the place out.
    An old first record gives the year for a line of its own after the second line.
    """
    reason = reason_of(view.evidence, view.evidence.href) if view.evidence else None
    line = aside_line(store, candidate, today) if candidate.aside in ("outside", "abroad") else None
    fit, old = fit_words(candidate, view), None
    if search.chips and search.chips.version >= 2 and candidate.section == "new" and not candidate.aside:
        age = ev.age(store.claims_of(identity.on_card(store, candidate)), today)
        old = age.first if rank.old(age) else None
    shown = view.model_copy(update={"place": None}) if line else view
    base = {"key": candidate.person_id, "section": candidate.section, "reason": reason, "fit": fit,
            "person": shown, "aside_line": line, "old_year": old}
    event = latest(store, view.person_id)
    if skipped:
        undo = LastView(event_id=event.id, kind="skip", words=DONE["skip"]) if event and event.kind == "skip" else None
        return CardView(**base, state="skipped", undo_event=undo)
    if candidate.section == "network":
        return CardView(**base, state="network")
    if view.status == "in_list":
        return added_card(store, candidate, base, event, today)
    if found := next(iter(network.name_matches(store, identity.on_card(store, candidate))), None):
        return CardView(**base, state="name_match", match=person_views(store, [[found]], today)[0])
    return CardView(**base, state="new")


def card(store: Store, search: Search, candidate: Candidate, today: date) -> CardView:
    """The card of one candidate, as the results page shows it."""
    return card_view(store, search, candidate, candidate_view(store, candidate, today), is_skipped(store, candidate), today)


def why_view(store: Store, search: Search, candidate: Candidate, today: date) -> WhyView:
    """The Person page's why block for the card it was opened from: the card's lines, the reason without its source."""
    view = candidate_view(store, candidate, today)
    reason = reason_of(view.evidence, view.evidence.href) if view.evidence else None
    tie, place = view.tie or NO_TIE, "Place unknown" if place_words(view) else None
    seen = {name_key(reason.text)} if reason else set()
    # The page leaves out an empty tie line.
    tie = "" if name_key(tie) in seen else tie
    place = None if place and (name_key(place) in seen or name_key(place) == name_key(tie)) else place
    return WhyView(reason=reason, tie=tie, place=place)


def shown_cards(store: Store, search: Search, rows: list[tuple[Candidate, PersonView, bool]], today: date, shown: int,
                show_skipped: bool) -> tuple[list[CardView], int, int, str | None]:
    """The cards of the rows' first shown people, how many people they are, how many people skipped elsewhere are
    hidden and the key of the first person not shown."""
    cards, counted, hidden, next_key = [], 0, 0, None
    for c, v, s in rows:
        if s:
            mine = skipped_here(store, v.person_id, search.id)
            hidden += not mine
            if next_key or not (mine or show_skipped):
                continue
        elif counted == shown:
            next_key = next_key or c.person_id
            continue
        else:
            counted += 1
        cards.append(card_view(store, search, c, v, s, today))
    return cards, counted, hidden, next_key


def no_match_line(chips: Chips) -> str:
    """The line over the list when nobody matches every wish: what FN found none of, and what follows. A question
    without a tie chip leaves the tie out of the line."""
    texts = [plain(c.text) for c in chips.roles] or [plain(c.text) for c in chips.topics]
    texts = [t for t in dict.fromkeys(texts) if t]
    what = ", ".join(texts[:-1]) + f" or {texts[-1]}" if len(texts) > 1 else texts[0] if texts else "people"
    place = f" {area_words(chips.place)}" if chips.place and parse.place_must(chips) else ""
    tie = " with a known tie to Flanders or Belgium" if chips.tie else ""
    return f"FN found no {what}{place}{tie}. " + (TIE_BELOW if parse.tie_must(chips) or not chips.tie else CLOSEST)


def results(store: Store, search: Search, today: date, shown: int = RESULTS_STEP,
            show_skipped: bool = False, group_shown: dict[str, int] | None = None) -> ResultsView:
    """The search's kept candidates: the open people who are not skipped by section, the cards of the first shown, and
    the set-aside groups with their own first shown cards (group_shown holds a group's shown count, else 20).

    A person skipped on this search keeps its card where it stood; one skipped elsewhere is counted as hidden and
    shows only with show_skipped. Skipped people never take a place among the shown. total and order keep everyone.
    """
    candidates = store.list_candidates(search.id, kept_only=True)
    views = person_views(store, [identity.on_card(store, c) for c in candidates], today,
                         tie_ids=[fit_tie(c.fit) for c in candidates], reasons=[reason_ids(c) for c in candidates])
    skipped = [is_skipped(store, c) for c in candidates]
    kept = [(c, v) for c, v, s in zip(candidates, views, skipped) if not s]
    chips = search.chips
    keys = [group_key(c, chips) for c in candidates]
    rows = list(zip(candidates, views, skipped))
    cards, counted, hidden, next_key = shown_cards(store, search, [r for r, k in zip(rows, keys) if k is None], today,
                                                   shown, show_skipped)
    groups = []
    for key in GROUP_KEYS:
        mine = [r for r, k in zip(rows, keys) if k == key]
        found, count, away, after = shown_cards(store, search, mine, today, (group_shown or {}).get(key, RESULTS_STEP),
                                                show_skipped)
        hidden += away
        if found or any(not s for _, _, s in mine):
            groups.append(AsideGroup(key=key, title=group_title(key, chips), count=sum(not s for _, _, s in mine),
                                     cards=found, shown=count, next_key=after))
    people = [(c, v) for c, v in kept if is_open(c, chips)]
    # Without a tie chip a person under "Topic, no known tie" matches every wish too.
    full = (1,) if chips is None or chips.tie else (1, 2)
    first = any(c.section == "new" and c.tier is not None and rank.heading(c.tier, c.fit.tie_grade if c.fit else "none") in full
                for c, _ in people)
    new = [v for c, v in people if c.section == "new"]
    done = search.status == "done" and chips is not None and chips.version >= 2
    return ResultsView(network=[v for c, v in people if c.section == "network"],
                       new=new, cards=cards, total=len(kept), shown=counted,
                       skipped_hidden=hidden, not_on_map=sum(1 for _, v in people if v.lat is None or v.lon is None),
                       matched=len(people),
                       next_key=next_key, order=[(v.person_id, c.person_id) for c, v in kept],
                       headings=results_headings(candidates, skipped, [c.key for c in cards], chips), groups=groups,
                       no_match=no_match_line(chips) if done and kept and not first else None)


def shown_for(position: int, shown: int) -> int:
    """The shown count that holds the card at the 1-based position: shown itself, else the next multiple of 20."""
    return shown if position <= shown else -(-position // RESULTS_STEP) * RESULTS_STEP


def walk(store: Store, search: Search, key: str) -> tuple[int, int, tuple[str, str] | None, tuple[str, str] | None] | None:
    """The card's 1-based place among the people of its list who are not skipped, the size of that list and the
    (person id, card key) before and after it; None when the key is not in a list.

    The list is the open list, or the set-aside group the card stands in, in the order results() gives.
    """
    kept = [c for c in store.list_candidates(search.id, kept_only=True) if not is_skipped(store, c)]
    lists = {c.person_id: group_key(c, search.chips) for c in kept}
    if key not in lists:
        return None
    kept = [c for c in kept if lists[c.person_id] == lists[key]]
    firsts = [identity.on_card(store, c)[0] for c in kept]
    canonical = store.canonical_ids(firsts)
    order = [(canonical[first], c.person_id) for first, c in zip(firsts, kept)]
    at = next(n for n, (_, found) in enumerate(order) if found == key)
    return at + 1, len(order), order[at - 1] if at else None, order[at + 1] if at + 1 < len(order) else None


def network_view(store: Store, flt: NetworkFilter, limit: int | None, today: date) -> NetworkView:
    """The filtered network: views of the first limit people, the total and how many of all of them have no place.

    new_facts counts how many of all of them have a new fact.
    """
    ids, total = store.list_network(flt, None)
    views = person_views(store, [[p] for p in ids], today)
    shown = views if limit is None else views[:limit]
    return NetworkView(people=shown, total=total, not_on_map=sum(1 for v in views if v.lat is None or v.lon is None),
                       shown=len(shown), new_facts=sum(1 for v in views if v.new_facts))


def geo(people: list[PersonView], listed: dict[str, dict] | None = None) -> dict:
    """GeoJSON for map.js: one point per person with a place, carrying what the map's popup shows.

    listed holds, by person id, whether the results list shows the person and the link that does; the answer carries
    it as the member 'list' for the people on the map.
    """
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [v.lon, v.lat]},
        "properties": {"id": v.person_id, "name": v.name, "role": v.role, "employer": v.employer, "place": v.place,
                       "new_facts": v.new_facts, "href": f"/people/{v.person_id}"},
    } for v in people if v.lat is not None and v.lon is not None]
    found = {"type": "FeatureCollection", "features": features}
    if listed is not None:
        found["list"] = {f["properties"]["id"]: listed[f["properties"]["id"]] for f in features if f["properties"]["id"] in listed}
    return found


def sources_read(store: Store, search: Search) -> int:
    """How many records the search's lanes looked at."""
    total = 0
    for step in store.list_steps(search.id):
        output = store.get_payload(step.id)[1] if step.output_model == "LaneOut" else None
        total += LaneOut.model_validate_json(output).total_seen if output else 0
    return total


def group_of(claim: Claim, facts: dict[str, Org], source: Source) -> str | None:
    """The profile section a claim shows under, one only; None for a contact or a claim that is no fact.

    Study is Education and a job Work. A birthplace or origin that shows a tie is a tie, any other place Places. A
    fellowship, membership or consul's post is a tie when its source is a seed list or it shows one, else Work, as
    are topics, papers and roles.
    """
    if claim.kind in ("email", "phone") or not is_fact(claim, source):
        return None
    if claim.relation == "studied_at":
        return "Education"
    if claim.relation in ("works_at", "worked_at", "affiliated_with", "hosted_by"):
        return "Work"
    if claim.relation in ("born_in", "origin"):
        return TIES if ev.shows_tie(claim, facts) else "Places"
    if claim.kind == "location":
        return "Places"
    if claim.relation in LIST_ROLES:
        return TIES if source.kind == "seed_page" or ev.shows_tie(claim, facts) else "Work"
    return "Work"


def line_key(claim: Claim) -> tuple:
    """What makes two claims one line: the kind, relation and organization or folded value."""
    return claim.kind, claim.relation, claim.org_id or fold(claim.value)


def line_view(line: Line, sources: dict[str, Source], seen_at: datetime | None, name: str,
              words: Sequence[str]) -> ClaimView:
    """The line as the page shows it: its shown claim's view with the line's own years, its proof quote, the ids of
    its other claims, which Not correct hides with it, and, for a joined role, both in the words.
    """
    shown = line.shown
    source = sources[shown.source_id]
    view = claim_view(shown, source, line.org, seen_at, cut_quote=False)
    text = proof_quote(shown, source, name, words)
    every = (*line.claims, *line.roles)
    update = {"years": span_words(line.own), "all_years": gap_words(line.own),
              "fold_ids": list(dict.fromkeys(c.id for c in every if c is not shown)),
              "is_new": any(seen_at and c.first_seen_at and c.first_seen_at > seen_at for c in every),
              "quote": QuoteView(text=text, label=view.label, href=view.href, date=view.date) if text else None}
    if line.joined:
        update["what"] = line.what
    return view.model_copy(update=update)


def fact_lines(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source], seen_at: datetime | None,
               name: str = "", words: Sequence[str] = ()) -> list[ClaimView]:
    """One line per fact, as lines_of builds them, with the years of all its claims.

    A line is new when any of its claims is; new lines come first, then newest first, equal dates by claim id.
    """
    lines = sorted(fold_lines(lines_of(claims, facts, sources), work=False), key=newest_key, reverse=True)
    views = [line_view(line, sources, seen_at, name, words) for line in lines]
    return sorted(views, key=lambda v: not v.is_new)


def titles_of(views: list[ClaimView]) -> TitlesView:
    """The gathered line of loose titles: 'Also described as' and the wordings in order, leaving out one whose words
    all stand in another or that repeats an earlier one, and the source name when the titles share one.
    """
    words = [set(name_key(v.what).split()) for v in views]
    kept = [v.what for n, v in enumerate(views) if not any(
        words[n] < other or (words[n] == other and m < n) for m, other in enumerate(words) if m != n)]
    names = list(dict.fromkeys(v.source for v in views))
    return TitlesView(what=f"Also described as {' · '.join(kept)}", source=names[0] if len(names) == 1 else f"{len(names)} sources",
                      facts=views)


def fold_of(lines: list[Line], sources: dict[str, Source]) -> FoldView | None:
    """The folded line of the Work lines: how many, the source named most often, and each '{organization}, {year}'."""
    folded = [line for line in lines if line.folded]
    if not folded:
        return None
    names = Counter(source_name(sources[line.shown.source_id]) for line in folded)
    return FoldView(count=len(folded), source=names.most_common(1)[0][0],
                    orgs=[f"{line.org.name if line.org else line.shown.value}, {min(line.own)}" for line in folded])


def tie_claim(claims: list[Claim], facts: dict[str, Org], ids: Sequence[str]) -> Claim | None:
    """The first of ids, strongest first, among the claims that show a tie, else None."""
    return next((c for i in ids for c in claims if c.id == i and ev.shows_tie(c, facts)), None)


def fit_tie(fit: CardFit | None) -> list[str] | None:
    """The claim ids of the tie the ranker stored for the card: None without a fit, none for a weak or no tie."""
    if fit is None:
        return None
    return list(fit.tie_claim_ids) if fit.tie_grade in rank.TIED else []


def evidence_tie(store: Store, persons: list[str], claims: list[Claim], facts: dict[str, Org], today: date) -> list[str]:
    """The claim ids of the persons' tie by the tie evidence, strongest first, when it is strong or medium."""
    card = ev.card_of(store.identifiers_of(persons), persons)
    found = ev.tie(card, claims, facts, places(claims, facts, today))
    return list(found.claim_ids) if found.grade in rank.TIED else []


def same_fact(claim: Claim, claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source]) -> list[str]:
    """The ids of the claims that stand in the claim's line of its section, the claim's own when it has none."""
    group = group_of(claim, facts, sources[claim.source_id])
    if group is None:
        return [claim.id]
    section = [c for c in claims if group_of(c, facts, sources[c.source_id]) == group]
    found = fold_lines(lines_of(section, facts, sources), work=group == "Work")
    line = next((s for s in found if any(c is claim for c in (*s.claims, *s.roles))), None)
    return [c.id for c in (*line.claims, *line.roles)] if line else [claim.id]


def years_of(ids: list[str], claims: list[Claim], sources: dict[str, Source]) -> str:
    return span_words(frozenset().union(*(own_years(c, sources[c.source_id]) for c in claims if c.id in ids)))


def summary_of(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source], ids: Sequence[str],
               member: bool) -> list[SummaryRow]:
    """The rows under the head: the newest study, the tie and, for a network person, the contact values or 'Not found'.

    The tie is the first of ids that shows one; it reads 'Tie to Flanders' when it lies in Flanders. The study is
    left out when it is the tie.
    """
    rows = []
    tie = tie_claim(claims, facts, ids)
    if (study := newest([c for c in claims if c.relation == "studied_at"])) and not (tie and tie.id in same_fact(study, claims, facts, sources)):
        line = same_fact(study, claims, facts, sources)
        org = facts.get(study.org_id or "")
        rows.append(SummaryRow(key="Studied", value=org.name if org else study.value, years=years_of(line, claims, sources),
                               claim_ids=line))
    if tie:
        org, line = facts.get(tie.org_id or ""), same_fact(tie, claims, facts, sources)
        rows.append(SummaryRow(key="Tie to Flanders" if ev.in_flanders(tie, org) else "Tie to Belgium", value=what_of(tie, org),
                               years=years_of(line, claims, sources), claim_ids=line))
    if not member:
        return rows
    found = [c for c in (contact_of(kind, claims, sources) for kind in ("email", "phone")) if c.claim]
    return rows + [SummaryRow(key="Contact", value=" · ".join(c.value for c in found) or "Not found",
                              claim_ids=[c.claim.claim_id for c in found])]


def contact_of(kind: str, claims: list[Claim], sources: dict[str, Source]) -> ContactView:
    """The newest value of the contact kind with its citation, which names an import as 'From import <file>, row n'."""
    found = [c for c in claims if c.kind == kind]
    if not found:
        return ContactView(kind=kind)
    claim = max(found, key=lambda c: (c.claim_date or "", c.first_seen_at.isoformat() if c.first_seen_at else "", c.id))
    source = sources[claim.source_id]
    view = claim_view(claim, source, None)
    if source.kind == "import":
        view = view.model_copy(update={"label": f"From import {source.title}"})
    return ContactView(kind=kind, value=claim.value, claim=view, found=prose(source))


def linkedin_of(store: Store, persons: list[str]) -> ContactView | None:
    """The LinkedIn address of the record merged last, with the LinkedIn record or import it came from, or None.

    A source is the record's vendor_record with that address, else its newest import; without one the row has
    no citation. An unmerged record counts as merged first.
    """
    records = {r.id: r for p in persons for r in store.records_of(p)}
    held = store.identifiers_of(list(records))
    holders = [records[i] for i, found in held.items() if any(f.scheme == "profile_url" for f in found)]
    if not holders:
        return None
    record = max(holders, key=lambda r: (r.merged_at.isoformat() if r.merged_at else "", r.id))
    url = profile_url(next(i.value for i in held[record.id] if i.scheme == "profile_url"))
    view = ContactView(kind="linkedin", value=url.removeprefix("https://www."), url=url)
    claims = store.claims_of(persons, include_hidden=True)
    owner = store.claim_records([c.id for c in claims])
    sources = store.get_sources(list({c.source_id for c in claims if owner[c.id] == record.id})).values()
    vendor = next((s for s in sources if s.kind == "vendor_record" and profile_url(s.url) == url), None)
    imports = [s for s in sources if s.kind == "import" and s.fetched_at]
    source = vendor or max(imports, key=lambda s: s.fetched_at, default=None)
    if source is None:
        return view
    if source is vendor:
        return view.model_copy(update={"label": "From a LinkedIn record", "href": f"/sources/{source.id}"})
    return view.model_copy(update={"label": f"From import {source.title}", "href": f"/sources/{source.id}",
                                   "date": day_words(source.fetched_at)})


def work_org(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source], today: date) -> str | None:
    """The organization of the first Work line that has one among the claims, else None."""
    work = [c for c in claims if group_of(c, facts, sources[c.source_id]) == "Work"]
    line = next((s for s in work_lines(work, facts, sources, today) if s.shown.relation in (*JOINING, "hosted_by")), None)
    return (line.org.name if line.org else line.shown.value) if line else None


def found_as(store: Store, persons: list[str], claims: list[Claim], sources: dict[str, Source], possible: list[str],
             facts: dict[str, Org], today: date, no_facts: bool) -> list[RecordView]:
    """One row per record the persons' facts came from, the page's own record first.

    A row's source is the one that gave the record most claims. Rows that share a label add the organization of the
    record's first Work line. A record can be separated when it is merged into the first person or is one of its
    possible matches. Rows show for two records or more, or when the page has no fact line.
    """
    records = {r.id: p for p in persons for r in store.records_of(p)}
    owner = store.claim_records([c.id for c in claims])
    mine: dict[str, list[Claim]] = {}
    for claim in claims:
        mine.setdefault(owner[claim.id], []).append(claim)
    order = {record: n for n, record in enumerate(records)}
    ids = sorted(mine, key=lambda r: order.get(r, len(order)))
    if len(ids) < 2 and not no_facts:
        return []
    top = {r: Counter(c.source_id for c in mine[r]).most_common(1)[0][0] for r in ids}
    labels = Counter(record_label(sources[top[r]]) for r in ids)
    rows = []
    for record in ids:
        label = record_label(sources[top[record]])
        if labels[label] > 1 and (org := work_org(mine[record], facts, sources, today)):
            label = f"{label}, {org}"
        rows.append(RecordView(record_id=record, label=label, href=f"/sources/{top[record]}",
                               facts=sum(is_fact(c, sources[c.source_id]) for c in mine[record]),
                               separate=record != persons[0] and (records.get(record) == persons[0] or records.get(record) in possible)))
    return rows


def separated_label(store: Store, record_id: str) -> str:
    """The source label of a separated record's source with most claims, else its name."""
    claims = store.claims_of([record_id])
    if not claims:
        return store.get_persons([record_id])[record_id].display_name
    top = Counter(c.source_id for c in claims).most_common(1)[0][0]
    return record_label(store.get_sources([top])[top])


def looking(store: Store, search: Search) -> bool:
    """Whether the search is looking up now: a lookup step runs in a running search, or any step runs in a done one.
    Only version 2 chips and later have the lookups."""
    if search.status not in ("running", "done") or search.chips is None or search.chips.version < 2:
        return False
    return any(s.status == "running" and (s.step == deepen.STEP or search.status == "done")
               for s in store.list_steps(search.id))


def lookup_parts(store: Store, records: list[str], at: datetime, today: date) -> str:
    """What a lookup row added, in words: the records' claims from pages a lookup read that were first stored up to
    LOOKUP_WINDOW before the row, each counted once, as a job, a place, recent facts, an email and a phone number."""
    near = [c for c in store.claims_of(records) if c.first_seen_at and at - LOOKUP_WINDOW <= c.first_seen_at <= at]
    sources = store.get_sources(list({c.source_id for c in near}))
    mine = [c for c in near if "lookup" in json.loads(sources[c.source_id].raw_json or "{}")]
    job = [c for c in mine if (c.kind == "role" and c.relation is None) or c.relation == "works_at"]
    recent = sum(ev.recent_fact([c], today) for c in mine if c not in job and c.kind not in ("location", "email", "phone"))
    kinds = {c.kind for c in mine}
    parts = [p for p in ("a current job" if job else None, "a place" if "location" in kinds else None,
                         "a recent fact" if recent == 1 else f"{recent} recent facts" if recent else None,
                         "an email address" if "email" in kinds else None,
                         "a phone number" if "phone" in kinds else None) if p]
    return " and ".join([", ".join(parts[:-1]), parts[-1]] if len(parts) > 1 else parts)


def lookup_view(store: Store, records: list[str], person_id: str, today: date) -> LookupView:
    """The person's lookup line: running while the latest lookup job of the person is queued or running; stopped when
    that job ended without a row at or after its start, or the newest row failed; else the newest row's words."""
    job, last = store.latest_job(deepen.job_question(person_id)), store.last_lookup(records, deepen.KIND)
    if job and job.status in ("queued", "running"):
        return LookupView(state="running")
    if (job and not (last and last[1] >= job.created_at)) or (last and last[0].verdict == "failed"):
        return LookupView(state="stopped", words=STOPPED)
    if last is None:
        return LookupView(state="before")
    row, at = last
    day = day_words(at)
    parts = lookup_parts(store, records, at, today) if row.verdict == "added" else ""
    words = (ADDED.format(date=day, parts=parts) if parts else NOT_SURE.format(date=day) if row.verdict == "not_sure"
             else NOTHING.format(date=day))
    return LookupView(state="after", words=words)


def latest(store: Store, person_id: str) -> Event | None:
    """The person's latest event when it is about them and can still be undone, else None."""
    event = next(iter(store.events_of(person_id)), None)
    return event if event and event.person_id == person_id and not network.refusal(store, event) else None


def last_of(store: Store, person: Person, event: Event | None, removed: ClaimView | None) -> LastView | None:
    """The latest event with the words the page shows for it; removed is the fact a reject removed.

    An add made elsewhere, by a search or an import, leaves the head at 'In your network since' with Remove.
    """
    if event is None or (event.kind == "add" and event.detail.get("via") != "profile"):
        return None
    separated = event.kind == "not_same" and bool(event.detail.get("separated"))
    if event.kind == "remove":
        words = f"{person.display_name} removed from your network."
    elif event.kind == "reject_claim":
        words = f"{removed.what} · Removed" if removed else "Removed"
    elif separated:
        words = f"{separated_label(store, event.detail['separated']['id'])} · Separated"
    else:
        words = DONE[event.kind]
    return LastView(event_id=event.id, kind=event.kind, words=words, claim_id=event.claim_id, separated=separated)


def card_candidate(store: Store, search_id: str, person_id: str, key: str) -> Candidate | None:
    """The search's kept candidate whose card holds a record of the person: the one with that key and a card that
    starts with the person, else the first.
    """
    candidates = store.list_candidates(search_id, kept_only=True)

    def holds(candidate: Candidate, first_only: bool) -> bool:
        records = identity.on_card(store, candidate)
        return person_id in store.canonical_ids(records[:1] if first_only else records).values()

    found = next((c for c in candidates if c.person_id == key and holds(c, True)), None)
    return found or next((c for c in candidates if holds(c, False)), None)


def card_records(store: Store, search_id: str, person_id: str, key: str) -> list[str] | None:
    """The records on the card the person's page was opened from, or None when the search has no such card."""
    found = card_candidate(store, search_id, person_id, key)
    return identity.on_card(store, found) if found else None


def profile(store: Store, person_id: str, today: date, card: list[str] | None = None,
            words: Sequence[str] = (), tie_ids: Sequence[str] | None = None) -> ProfileView | None:
    """Everything the Person page shows of the id's person, or None for an unknown id.

    The facts a just-undoable reject removed stay in their section, so the page can show the line with Undo. With
    card, the page combines the records on the card as the card does: their claims, their records under Sources and
    their newest undoable decision; words are the topic words the quotes are centred on. tie_ids are the claims of
    the tie the summary shows, strongest first; None means the tie evidence picks them.
    """
    canonical = store.canonical_ids([person_id]).get(person_id)
    if canonical is None:
        return None
    persons = list(dict.fromkeys([canonical, *store.canonical_ids(card or []).values()]))
    person = store.get_persons([canonical])[canonical]
    member = person.list_status == "in_list"
    claims = store.claims_of(card or [canonical])
    event = max(filter(None, (latest(store, p) for p in persons)), key=lambda e: (e.at, e.id), default=None)
    gone = []
    if event and event.kind == "reject_claim":
        gone = [c for c in map(store.get_claim, (event.claim_id, *event.detail.get("also", []))) if c]
    shown = claims + [c for c in gone if c.id not in {k.id for k in claims}]
    facts = store.get_orgs(list({c.org_id for c in shown if c.org_id}))
    sources = store.get_sources(list({c.source_id for c in shown}))
    seen_at = person.seen_at if member else None
    groups: dict[str, list[Claim]] = {}
    for claim in shown:
        if group := group_of(claim, facts, sources[claim.source_id]):
            groups.setdefault(group, []).append(claim)
    name_match = None
    if not member:
        name_match = next(iter(network.name_matches(store, card or [canonical])), None)
    matches = network.possible_matches(store, canonical) if member else []
    possible = [p for p in matches if p != name_match and p not in persons]
    groups_of = [persons, *([[name_match]] if name_match else []), *[[p] for p in possible]]
    views = person_views(store, groups_of, today)
    sides = person_sides(store, groups_of, today) if len(groups_of) > 1 else []
    name_compare = None
    if name_match:
        name_compare = compare_view(sides[0], sides[1], COMPARE_FIELDS, ("This person", "In your network"),
                                    f"This person and {views[1].name} in your network", "Not known")
    first = 2 if name_match else 1
    compares = [compare_view(sides[0], theirs, COMPARE_FIELDS, ("This person", "Possible match"),
                             f"This person and possible match {n} of {len(possible)}" if len(possible) > 1
                             else "This person and the possible match", "Not known")
                for n, theirs in enumerate(sides[first:], 1)]
    lines = {title: fact_lines(found, facts, sources, seen_at, person.display_name, words) for title, found in groups.items()
             if title != "Work"}
    work = work_lines(groups.get("Work", []), facts, sources, today, views[0].place)
    shown_work = fold_lines([s for s in work if not s.folded], work=True)
    loose = [s for s in shown_work if s.role is s.shown and not s.shown.rejected_at]
    titles = None
    if len(loose) > 1:
        titles = titles_of([line_view(s, sources, seen_at, person.display_name, words) for s in loose])
        shown_work = [s for s in shown_work if s not in loose]
    lines["Work"] = [line_view(s, sources, seen_at, person.display_name, words) for s in shown_work]
    removed = None
    if gone:
        removed = next((v for found in lines.values() for v in found if v.claim_id == gone[0].id),
                       claim_view(gone[0], sources[gone[0].source_id], facts.get(gone[0].org_id or "")))
    contact = [contact_of(kind, claims, sources) for kind in ("email", "phone")]
    contact = [c.model_copy(update={"removed": gone[0].value}) if gone and c.kind == gone[0].kind else c for c in contact]
    contact = [c for c in [*contact, linkedin_of(store, persons)] if c and (c.value or c.removed)]
    shown_tie = evidence_tie(store, persons, claims, facts, today) if tie_ids is None else tie_ids
    fold_line = fold_of(work, sources)
    separable = matches if member else persons[1:]
    rows = found_as(store, persons, claims, sources, separable, facts, today,
                    not (any(lines.values()) or fold_line or titles))
    return ProfileView(
        person=views[0], contact=contact,
        facts=[FactGroup(title=title, facts=lines.get(title, []), fold=fold_line if title == "Work" else None,
                         titles=titles if title == "Work" else None)
               for title in GROUPS if lines.get(title) or (title == "Work" and (fold_line or titles))],
        found_as=rows, possible=views[2:] if name_match else views[1:],
        name_match=views[1] if name_match else None, compares=compares, name_compare=name_compare,
        last=last_of(store, person, event, removed),
        summary=summary_of(claims, facts, sources, shown_tie, member), records=len(rows) if len(persons) > 1 else 1,
        lookup=lookup_view(store, list(dict.fromkeys(r.id for p in persons for r in store.records_of(p))), canonical, today),
    )


@dataclass(frozen=True)
class Value:
    text: str
    key: str
    href: str | None = None
    org: str | None = None
    spot: tuple[float, float] | None = None
    bare: str | None = None


Side = dict[str, list[Value]]


def keyed(field: str, text: str, href: str | None = None, org: str | None = None,
          spot: tuple[float, float] | None = None) -> Value:
    """The value with the key two values of the field are compared by: a phone's digits, a LinkedIn address, an
    employer's words, else the folded text with single spaces, a place without a trailing US country word. An
    employer that ends in brackets, as "Imec (Belgium)" does, also gets its words without them as bare."""
    key = " ".join(text.split()).casefold()
    if field == "Phone":
        key = re.sub(r"\D", "", text) or key
    elif field == "LinkedIn":
        key = fold(href or text)
    elif field == "Place":
        key = re.sub(r",? (usa|us|united states)$", "", key)
    elif field == "Employer":
        key = " ".join(orgs.words(text)) or key
        cut = re.sub(r"\s*\([^()]*\)\s*$", "", text)
        return Value(text=text, key=key, href=href, org=org, bare=" ".join(orgs.words(cut)) if cut != text else None)
    return Value(text=text, key=key, href=href, org=org, spot=spot)


def same(field: str, a: Value, b: Value) -> bool:
    """Whether two values of the field are one: an employer by its organization when both have an id of one registry,
    else by its name, by one name without its brackets being the other, or by a name of two words or more standing
    inside the other; a place by distance when both have coordinates; else by key."""
    if field == "Employer":
        if a.org and b.org and a.org.split(":")[0] == b.org.split(":")[0]:
            return a.org == b.org
        if a.key == b.key or a.bare == b.key or b.bare == a.key:
            return True
        short, long = sorted((a.key, b.key), key=len)
        return " " in short and f" {short} " in f" {long} "
    if field == "Place" and a.spot and b.spot:
        return distance_km(*a.spot, *b.spot) <= SAME_SPOT_KM
    return a.key == b.key


def compare_values(field: str, found: list[Value], other: list[Value], link: bool) -> tuple[list[CompareValue], int]:
    """The first COMPARE_SHOWN values and how many more there are: one value per group the field calls the same,
    and those the other side also holds first, so a shared value is never among the hidden ones."""
    kept: list[Value] = []
    for value in sorted(found, key=lambda v: not any(same(field, v, o) for o in other)):
        if not any(same(field, value, k) for k in kept):
            kept.append(value)
    shown = [CompareValue(text=v.text, href=v.href if link else None) for v in kept[:COMPARE_SHOWN]]
    return shown, max(len(kept) - COMPARE_SHOWN, 0)


def compare_view(left: Side, right: Side, fields: tuple[str, ...], titles: tuple[str, str], caption: str,
                 left_none: str) -> CompareView:
    """The fields in order as rows, a field empty on both sides left out.

    A row differs when its field can, both sides hold a value and no value on one side is the same as one on the other.
    The left Name never links: only the other person's name does.
    """
    rows = []
    for field in fields:
        a, b = left.get(field, []), right.get(field, [])
        if not (a or b):
            continue
        shown_a, more_a = compare_values(field, a, b, field != "Name")
        shown_b, more_b = compare_values(field, b, a, True)
        differs = field in DIFFERS and bool(a and b) and not any(same(field, x, y) for x in a for y in b)
        rows.append(CompareRow(field=field, left=shown_a, right=shown_b, left_more=more_a, right_more=more_b,
                               differs=differs))
    return CompareView(caption=caption, titles=titles, left_none=left_none, rows=rows)


def newest_first(claims: list[Claim]) -> list[Claim]:
    return sorted(claims, key=lambda c: (c.claim_date or "", c.id), reverse=True)


def job_values(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source], today: date,
               place: str | None) -> tuple[list[Value], list[Value]]:
    """The Job and Employer values of the Work lines, the head line first."""
    lines = work_lines(job_claims(claims, sources), facts, sources, today, place)
    jobs = [keyed("Job", what_of(line.role, None)) for line in lines if line.role]
    employers = [keyed("Employer", line.org.name if line.org else line.shown.value, org=line.org.id if line.org else None)
                 for line in lines if line.shown.relation in JOINING]
    return jobs, employers


def place_values(claims: list[Claim], facts: dict[str, Org], today: date) -> list[Value]:
    """The place the page shows, then the newest stated places, each with its coordinates when it has them."""
    text, lat, lon, _ = located(claims, facts, today)
    found = [keyed("Place", text, spot=(lat, lon) if lat is not None and lon is not None else None)] if text else []
    stated = [c for c in newest_first(claims) if c.kind == "location" and c.relation not in ("born_in", "origin")]
    return found + [keyed("Place", c.value, spot=(c.lat, c.lon) if c.lat is not None and c.lon is not None else None)
                    for c in stated]


def studied_values(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source]) -> list[Value]:
    """Each study as '{organization}, {years}', the newest first."""
    lines: dict[tuple, list[Claim]] = {}
    for claim in newest_first([c for c in claims if c.relation == "studied_at"]):
        lines.setdefault(line_key(claim), []).append(claim)
    found = []
    for same_line in lines.values():
        org = facts.get(same_line[0].org_id or "")
        years = span_words(frozenset().union(*(own_years(c, sources[c.source_id]) for c in same_line)))
        found.append(keyed("Studied", ", ".join(x for x in (org.name if org else same_line[0].value, years) if x)))
    return found


def tel_href(phone: str) -> str | None:
    """The tel: address of a phone value, None when it holds no digit."""
    return f"tel:{re.sub(r'[^0-9+]', '', phone)}" if re.search(r"\d", phone) else None


def contact_values(claims: list[Claim], held: list[Identifier]) -> tuple[list[Value], list[Value]]:
    """The email values, claims newest first and then the email identifiers, and the phone values."""
    emails = [c.value for c in newest_first([c for c in claims if c.kind == "email"])] + [
        i.value for i in held if i.scheme == "email"]
    phones = [c.value for c in newest_first([c for c in claims if c.kind == "phone"])]
    return ([keyed("Email", e, href=f"mailto:{e}") for e in emails],
            [keyed("Phone", p, href=tel_href(p)) for p in phones])


def identifier_values(held: list[Identifier]) -> tuple[list[Value], list[Value]]:
    """The LinkedIn addresses, shown without 'https://www.', and the bare ORCID iDs."""
    urls = [keyed("LinkedIn", i.value.removeprefix("https://www."), href=i.value) for i in held if i.scheme == "profile_url"]
    return urls, [keyed("ORCID", i.value.removeprefix("https://orcid.org/")) for i in held if i.scheme == "orcid"]


def source_day(source: Source) -> str | None:
    """The source's own date as '3 November 2026', 'May 2024' or '2024', else the day FN fetched it, else None."""
    found = SOURCE_DAY.match(source.source_date or "")
    if found and (month := int(found[2] or 0)) <= 12:
        year, day = found[1], found[3]
        if month and day:
            return f"{int(day)} {month_name[month]} {year}"
        return f"{month_name[month]} {year}" if month else year
    return day_words(source.fetched_at) if source.fetched_at else None


def found_values(records: list[str], mine: dict[str, list[Claim]], sources: dict[str, Source]) -> list[Value]:
    """Per record with claims, its source with most claims as '{label}, {date}', an import without its row."""
    found = []
    for record in records:
        if not mine.get(record):
            continue
        source = sources[Counter(c.source_id for c in mine[record]).most_common(1)[0][0]]
        label = IMPORT_ROW.sub("", record_label(source)) if source.kind == "import" else record_label(source)
        found.append(keyed("Found in", ", ".join(x for x in (label, source_day(source)) if x)))
    return found


def person_sides(store: Store, groups: list[list[str]], today: date) -> list[Side]:
    """One Side per group of stored person ids, named after its first, from one claims_of call."""
    canonical = store.canonical_ids([p for g in groups for p in g])
    groups = [list(dict.fromkeys(canonical[p] for p in g)) for g in groups]
    ids = list(dict.fromkeys(p for g in groups for p in g))
    by_person: dict[str, list[Claim]] = {}
    for claim in store.claims_of(ids):
        by_person.setdefault(claim.person_id, []).append(claim)
    persons, records = store.get_persons(ids), {p: [r.id for r in store.records_of(p)] for p in ids}
    held = store.identifiers_of([r for found in records.values() for r in found])
    owned = [[c for p in g for c in by_person.get(p, [])] for g in groups]
    facts = store.get_orgs(list({c.org_id for claims in owned for c in claims if c.org_id}))
    sources = store.get_sources(list({c.source_id for claims in owned for c in claims}))
    owner = store.claim_records([c.id for claims in owned for c in claims])
    sides = []
    for group, claims in zip(groups, owned):
        mine: dict[str, list[Claim]] = {}
        for claim in claims:
            mine.setdefault(owner[claim.id], []).append(claim)
        ordered = [r for p in group for r in records[p]]
        idents = [i for r in ordered for i in held.get(r, [])]
        place = place_values(claims, facts, today)
        jobs, employers = job_values(claims, facts, sources, today, place[0].text if place else None)
        tie = tie_claim(claims, facts, evidence_tie(store, group, claims, facts, today))
        emails, phones = contact_values(claims, idents)
        urls, orcids = identifier_values(idents)
        side = {"Name": [keyed("Name", persons[group[0]].display_name, href=f"/people/{group[0]}")], "Job": jobs,
                "Employer": employers, "Place": place, "Studied": studied_values(claims, facts, sources),
                "Belgian tie": [keyed("Belgian tie", what_of(tie, facts.get(tie.org_id or "")))] if tie else [],
                "Email": emails, "Phone": phones, "LinkedIn": urls, "ORCID": orcids,
                "Found in": found_values(ordered, mine, sources)}
        sides.append({field: found for field, found in side.items() if found})
    return sides


def row_side(row: ImportRow) -> Side:
    """The file row's cells as a Side; a LinkedIn or ORCID cell FN does not use as an identifier stays plain text."""
    cells = row.cells
    held = {i.scheme: i.value for i in importer.identifiers(cells)[0]}
    side = {"Name": [keyed("Name", row.name)]}
    if "role" in cells:
        side["Job"] = [keyed("Job", cells["role"])]
    if "phone" in cells:
        side["Phone"] = [keyed("Phone", cells["phone"], href=tel_href(cells["phone"]))]
    if "organization" in cells:
        side["Employer"] = [keyed("Employer", cells["organization"], org=orgs.org_id(cells["organization"]))]
    if place := importer.place_of(cells):
        spot = (row.lat, row.lon) if row.lat is not None and row.lon is not None else None
        side["Place"] = [keyed("Place", place, spot=spot)]
    if "@" in cells.get("email", ""):
        side["Email"] = [keyed("Email", cells["email"], href=f"mailto:{cells['email']}")]
    elif "email" in cells:
        side["Email"] = [keyed("Email", cells["email"])]
    if "profile_url" in held:
        side["LinkedIn"] = [keyed("LinkedIn", held["profile_url"].removeprefix("https://www."), href=held["profile_url"])]
    elif "linkedin_url" in cells:
        side["LinkedIn"] = [keyed("LinkedIn", cells["linkedin_url"])]
    if "orcid" in held:
        side["ORCID"] = [keyed("ORCID", held["orcid"].removeprefix("https://orcid.org/"))]
    elif "orcid" in cells:
        side["ORCID"] = [keyed("ORCID", cells["orcid"])]
    return side


def import_compares(store: Store, preview: ImportPreview, today: date) -> dict[int, CompareView]:
    """The Compare table of each name match row, by row number: the file's row beside the network person."""
    matched = [r for r in preview.rows if r.outcome == "name_match" and r.person_id]
    sides = person_sides(store, [[r.person_id] for r in matched], today)
    return {row.n: compare_view(
        row_side(row), theirs, FILE_FIELDS, ("In the file", "In your network"),
        f"Row {row.n} of {preview.filename} and {theirs['Name'][0].text} in your network", "Not in the file")
        for row, theirs in zip(matched, sides)}
