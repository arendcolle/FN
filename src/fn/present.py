"""How a person reads on every staff page: the view models of people and claims, and plain-words helpers."""
import re
from calendar import month_name
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from urllib.parse import urlsplit

from fn import evidence as ev
from fn import identity, network, orgs, rank
from fn.contracts import (
    Candidate,
    CardFit,
    CardView,
    Claim,
    ClaimView,
    ContactView,
    Event,
    FactGroup,
    FoldView,
    LaneOut,
    LastView,
    NetworkFilter,
    NetworkView,
    Org,
    OrgView,
    Person,
    PersonView,
    ProfileView,
    QuoteView,
    ReasonView,
    RecordView,
    ResultsHeading,
    ResultsView,
    Search,
    Source,
    SummaryRow,
    WhyView,
    name_key,
)
from fn.evidence import places
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
FIELDS = {"topic": "Topic", "email": "Email", "phone": "Phone"}
RECORD_LABELS = {"record": "OpenAlex record", "vendor_record": "LinkedIn record", "staff": "Entered in FN"}
# Dates of the day a record was read or changed, which never are a fact's own year.
RECORD_DATES = ("page_date", "sitemap", "wayback_first_seen", "document_heading", "read_date", "sheet_date", "staff_edit")
FOLD_SHOWN = 20
TIES = "Ties to Flanders and Belgium"
GROUPS = ("Work", "Education", TIES, "Places")
DONE = {"add": "Added to your network", "skip": "Skipped", "edit_contact": "Saved", "merge": "Merged into this profile",
        "not_same": "Marked as a different person"}
RESULTS_STEP = 20
HEADINGS = {1: "Topic and a tie to Flanders or Belgium", 2: "Topic, no known tie", 3: "Tie, topic not confirmed", 4: "Other people found"}
WORK = "OpenAlex work "
UNKNOWN_DATE = "date unknown"
QUOTE_WORDS = 25
REASON_WORDS = 15
NO_TIE = "No known tie to Flanders"
FIELD_LABEL = re.compile(r"[*•-]\s*(?:[^\W_]| ){1,30}:")
ENTITY = re.compile(r"&#?\w+;")
IMAGE_TOKENS = ("orcid image", "author orcid", "![", "[image")
MIN_QUOTE_WORDS = 4


def job_date(claim: Claim) -> tuple[str, str]:
    return claim.valid_to or claim.claim_date or "", claim.claim_date or ""


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
    if stated := place_of([by_id[p.claim_id] for p in found if p.basis == "stated"]):
        return stated.value, stated.lat, stated.lon, "stated"
    jobs = [(by_id[p.claim_id], p) for p in found if p.basis == "employer"]
    if jobs:
        _, job = max(jobs, key=lambda t: (*job_date(t[0]), t[0].id))
        return job.text, job.lat, job.lon, "employer"
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
    source's record was read or changed.
    """
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
    """The fact in plain words, such as 'Studied at KU Leuven', 'Topic: 6G', 'Born in Leuven' or 'Origin: Belgian'.

    A role starts with a capital letter; a list role at an organization reads as its relation.
    """
    if claim.kind == "availability":
        return claim.value
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


def added_on(store: Store, person_id: str) -> str | None:
    """The day of the person's latest add event, such as '3 November 2026', or None when there is none."""
    at = next((e.at.astimezone() for e in store.events_of(person_id) if e.kind == "add"), None)
    return f"{at.day} {at:%B %Y}" if at else None


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

    A stated role joined to an employer claim is one line with it. A rejected claim is a line of its own.
    """
    joins = joined_roles(claims, sources)
    taken = {r.id for r in joins.values()}
    same: dict[tuple, list[Claim]] = {}
    for claim in claims:
        if claim.id in taken:
            continue
        if claim.rejected_at:
            key = (claim.id,)
        elif claim.id in joins:
            key = ("joined", fold(joins[claim.id].value), claim.org_id or fold(claim.value))
        else:
            key = line_key(claim)
        same.setdefault(key, []).append(claim)
    return [line_of(found, joins, facts, sources) for found in same.values()]


def line_of(found: list[Claim], joins: dict[str, Claim], facts: dict[str, Org], sources: dict[str, Source]) -> Line:
    shown = newest(found)
    org = facts.get(shown.org_id or "")
    role = joins.get(shown.id) or (shown if shown.kind == "role" and shown.relation is None else None)
    parts = [*found, *(joins[c.id] for c in found if c.id in joins)]
    own = frozenset().union(*(own_years(c, sources[c.source_id]) for c in parts))
    last = max((int(u) for c in parts for u in rank.units(c) if u != rank.UNDATED), default=0)
    what = what_of(shown, org)
    if role is not None and role is not shown:
        what = what_of(role, None)
        name = org.name if org else shown.value
        if not names(what, name):
            what = f"{what}, {name}"
    return Line(claims=found, shown=shown, role=role, org=org, what=what, own=own, last=last)


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
    """The heading the candidate's tier stands under in the new section; the candidate must have a tier."""
    return HEADINGS[rank.heading(candidate.tier, candidate.fit.tie_grade if candidate.fit else "none")]


def results_headings(candidates: list[Candidate], skipped: list[bool], shown: list[str]) -> list[ResultsHeading]:
    """The new section's headings with the people not skipped under each and the first shown card under it.

    shown holds the keys of the shown cards. Empty when a person of the section has no tier.
    """
    new = [(c, s) for c, s in zip(candidates, skipped) if c.section == "new"]
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


def card_view(store: Store, search: Search, candidate: Candidate, view: PersonView, skipped: bool,
              today: date) -> CardView:
    """The candidate's card: its state from the people's status now, the same-name network person and the Undo."""
    base = {"key": candidate.person_id, "section": candidate.section, "person": view,
            "reason": reason_of(view.evidence, view.evidence.href) if view.evidence else None,
            "fit": fit_words(candidate, view)}
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


def results(store: Store, search: Search, today: date, shown: int = RESULTS_STEP,
            show_skipped: bool = False) -> ResultsView:
    """The search's kept candidates: the people who are not skipped by section, and the cards of the first shown.

    A person skipped on this search keeps its card where it stood; one skipped elsewhere is counted as hidden and
    shows only with show_skipped. Skipped people never take a place among the shown.
    """
    candidates = store.list_candidates(search.id, kept_only=True)
    views = person_views(store, [identity.on_card(store, c) for c in candidates], today,
                         tie_ids=[fit_tie(c.fit) for c in candidates], reasons=[reason_ids(c) for c in candidates])
    skipped = [is_skipped(store, c) for c in candidates]
    kept = [(c, v) for c, v, s in zip(candidates, views, skipped) if not s]
    cards, counted, hidden, next_key = [], 0, 0, None
    for c, v, s in zip(candidates, views, skipped):
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
    people = [v for _, v in kept]
    return ResultsView(network=[v for c, v in kept if c.section == "network"],
                       new=[v for c, v in kept if c.section == "new"], cards=cards, total=len(kept), shown=counted,
                       skipped_hidden=hidden, not_on_map=sum(1 for v in people if v.lat is None or v.lon is None),
                       next_key=next_key, order=[(v.person_id, c.person_id) for c, v in kept],
                       headings=results_headings(candidates, skipped, [c.key for c in cards]))


def shown_for(position: int, shown: int) -> int:
    """The shown count that holds the card at the 1-based position: shown itself, else the next multiple of 20."""
    return shown if position <= shown else -(-position // RESULTS_STEP) * RESULTS_STEP


def walk(store: Store, search: Search, key: str) -> tuple[int, int, tuple[str, str] | None, tuple[str, str] | None] | None:
    """The card's 1-based place among the kept people who are not skipped, the size of that list and the
    (person id, card key) before and after it; None when the key is not in the list.

    The list is the one results().order gives, built without the person views.
    """
    kept = [c for c in store.list_candidates(search.id, kept_only=True) if not is_skipped(store, c)]
    firsts = [identity.on_card(store, c)[0] for c in kept]
    canonical = store.canonical_ids(firsts)
    order = [(canonical[first], c.person_id) for first, c in zip(firsts, kept)]
    at = next((n for n, (_, found) in enumerate(order) if found == key), None)
    if at is None:
        return None
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
    """The line as the page shows it: its newest claim's view with the line's own years, its proof quote and, for a
    joined role, the role's id and both in the words.
    """
    shown = line.shown
    source = sources[shown.source_id]
    view = claim_view(shown, source, line.org, seen_at, cut_quote=False)
    text = proof_quote(shown, source, name, words)
    update = {"years": span_words(line.own), "all_years": gap_words(line.own),
              "is_new": any(seen_at and c.first_seen_at and c.first_seen_at > seen_at for c in (*line.claims, line.role) if c),
              "quote": QuoteView(text=text, label=view.label, href=view.href, date=view.date) if text else None}
    if line.joined:
        update |= {"what": line.what, "joined_claim_id": line.role.id}
    return view.model_copy(update=update)


def fact_lines(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source], seen_at: datetime | None,
               name: str = "", words: Sequence[str] = ()) -> list[ClaimView]:
    """One line per fact, as lines_of builds them, with the years of all its claims.

    A line is new when any of its claims is; new lines come first, then newest first, equal dates by claim id.
    """
    lines = sorted(lines_of(claims, facts, sources), key=lambda s: (s.shown.claim_date or "", s.shown.id), reverse=True)
    views = [line_view(line, sources, seen_at, name, words) for line in lines]
    return sorted(views, key=lambda v: not v.is_new)


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


def same_fact(claim: Claim, claims: list[Claim]) -> list[str]:
    """The ids of the claims that stand in the claim's line."""
    return [c.id for c in claims if line_key(c) == line_key(claim)]


def years_of(ids: list[str], claims: list[Claim], sources: dict[str, Source]) -> str:
    return span_words(frozenset().union(*(own_years(c, sources[c.source_id]) for c in claims if c.id in ids)))


def summary_of(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source], ids: Sequence[str]) -> list[SummaryRow]:
    """The rows under the head: the newest study, the tie and the contact values or 'Not found'.

    The tie is the first of ids that shows one; it reads 'Tie to Flanders' when it lies in Flanders. The study is
    left out when it is the tie.
    """
    rows = []
    tie = tie_claim(claims, facts, ids)
    if (study := newest([c for c in claims if c.relation == "studied_at"])) and not (tie and tie.id in same_fact(study, claims)):
        line = same_fact(study, claims)
        org = facts.get(study.org_id or "")
        rows.append(SummaryRow(key="Studied", value=org.name if org else study.value, years=years_of(line, claims, sources),
                               claim_ids=line))
    if tie:
        org, line = facts.get(tie.org_id or ""), same_fact(tie, claims)
        rows.append(SummaryRow(key="Tie to Flanders" if ev.in_flanders(tie, org) else "Tie to Belgium", value=what_of(tie, org),
                               years=years_of(line, claims, sources), claim_ids=line))
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
    return ContactView(kind=kind, value=claim.value, claim=view)


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
    matches = network.possible_matches(store, canonical)
    possible = [p for p in matches if p != name_match and p not in persons]
    views = person_views(store, [persons, *([[name_match]] if name_match else []), *[[p] for p in possible]], today)
    lines = {title: fact_lines(found, facts, sources, seen_at, person.display_name, words) for title, found in groups.items()
             if title != "Work"}
    work = work_lines(groups.get("Work", []), facts, sources, today, views[0].place)
    lines["Work"] = [line_view(s, sources, seen_at, person.display_name, words) for s in work if not s.folded]
    removed = None
    if gone:
        removed = next((v for found in lines.values() for v in found if v.claim_id == gone[0].id),
                       claim_view(gone[0], sources[gone[0].source_id], facts.get(gone[0].org_id or "")))
    shown_tie = evidence_tie(store, persons, claims, facts, today) if tie_ids is None else tie_ids
    fold_line = fold_of(work, sources)
    rows = found_as(store, persons, claims, sources, matches, facts, today, not (any(lines.values()) or fold_line))
    return ProfileView(
        person=views[0], contact=[contact_of(kind, claims, sources) for kind in ("email", "phone")],
        facts=[FactGroup(title=title, facts=lines.get(title, []), fold=fold_line if title == "Work" else None)
               for title in GROUPS if lines.get(title) or (title == "Work" and fold_line)],
        found_as=rows, possible=views[2:] if name_match else views[1:],
        name_match=views[1] if name_match else None, last=last_of(store, person, event, removed),
        summary=summary_of(claims, facts, sources, shown_tie), records=len(rows) if len(persons) > 1 else 1,
    )
