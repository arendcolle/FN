"""How a person reads on every staff page: the view models of people and claims, and plain-words helpers."""
from calendar import month_name
from datetime import date, datetime
from urllib.parse import urlsplit

from fn import orgs, rank
from fn.contracts import (
    Claim,
    ClaimView,
    LaneOut,
    Org,
    OrgView,
    Person,
    PersonView,
    QuoteView,
    ResultsView,
    Search,
    Source,
)
from fn.store import Store

EMPLOYED = ("works_at", "worked_at", "affiliated_with")
RELATIONS = {
    "studied_at": "Studied at", "works_at": "Works at", "worked_at": "Worked at", "affiliated_with": "Affiliated with",
    "hosted_by": "Hosted by", "member_of": "Member of", "fellow_of": "Fellow of", "consul_for": "Honorary consul for",
}
# Seed list roles name a list, not a job.
LIST_ROLES = ("fellow_of", "member_of", "consul_for")
PROSE = ("page", "seed_page", "vendor_page")
FIELDS = {"topic": "Field", "email": "Email", "phone": "Phone"}
RECORD_LABELS = {"record": "OpenAlex record", "vendor_record": "LinkedIn record", "staff": "Entered in FN"}


def employer_of(claims: list[Claim]) -> str | None:
    """The organization of the newest works_at, worked_at or affiliated_with claim, or None."""
    jobs = [c for c in claims if c.relation in EMPLOYED]
    return max(jobs, key=lambda c: (c.valid_to or c.claim_date or "", c.claim_date or "")).value if jobs else None


def belgian_orgs(claims: list[Claim], facts: dict[str, Org]) -> list[tuple[str, list[int]]]:
    """Each Belgian organization the claims name with the years of those claims, earliest first."""
    years: dict[str, set[int]] = {}
    for claim, org in orgs.belgian_claims(claims, facts):
        years.setdefault(org.name, set()).update(int(u) for u in rank.units(claim) if u != rank.UNDATED)
    return sorted(((name, sorted(found)) for name, found in years.items()), key=lambda t: (t[1][:1] or [9999], t[0]))


def evidence(claims: list[Claim], facts: dict[str, Org], matched: list[str]) -> Claim | None:
    """The claim to show on a card: the newest at a Belgian organization, else the first the search matched."""
    belgian = [c for c, _ in orgs.belgian_claims(claims, facts)]
    if belgian:
        return max(belgian, key=lambda c: (c.claim_date or "", c.id))
    return next((c for c in claims if c.id in matched), None)


def date_words(claim: Claim) -> str:
    """The claim's date as people write it: 2025, March 2024, 3 March 2024 or date unknown."""
    parts = [int(p) for p in (claim.claim_date or "").split("-") if p.isdigit()]
    precision = claim.date_precision or ("year", "month", "day")[min(len(parts), 3) - 1] if parts else None
    if precision == "day" and len(parts) == 3:
        return f"{parts[2]} {month_name[parts[1]]} {parts[0]}"
    if precision in ("month", "day") and len(parts) >= 2:
        return f"{month_name[parts[1]]} {parts[0]}"
    return str(parts[0]) if parts else "date unknown"


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

    A born_in claim never places anyone.
    """
    found = [c for c in claims if c.kind == "location" and c.relation != "born_in"]
    dotted = [c for c in found if c.lat is not None and c.lon is not None]
    return newest([c for c in dotted if c.claim_date] or dotted or found)


def is_job(claim: Claim, source: Source) -> bool:
    """Whether a role claim names a job: not a seed list role, nor a page title or host standing in for a role."""
    return claim.relation not in LIST_ROLES and claim.value not in (source.title, urlsplit(source.url).hostname, source.url)


def years_words(claim: Claim) -> str:
    """The years the claim covers as runs, such as '2008–2013' or '2001, 2008', or empty when it has none."""
    return rank.years_text(rank.units(claim) - {rank.UNDATED}).replace("-", "–")


def what_of(claim: Claim, org: Org | None) -> str:
    """The fact in plain words, such as 'Studied at KU Leuven', 'Field: 6G' or 'Born in Leuven'."""
    if claim.kind in ("role", "availability"):
        return claim.value
    if claim.kind == "location":
        return f"{'Born in' if claim.relation == 'born_in' else 'Based in'} {claim.value}"
    if claim.kind in FIELDS:
        return f"{FIELDS[claim.kind]}: {claim.value}"
    name = org.name if org else claim.value
    return f"{RELATIONS[claim.relation]} {name}" if claim.relation in RELATIONS else name


def label_of(source: Source) -> str:
    """The source as a citation names it: the record kind, the import file and row (its title), else the page title or host."""
    if source.kind in RECORD_LABELS:
        return RECORD_LABELS[source.kind]
    if source.kind == "import":
        return f"Import {source.title}"
    return source.title or urlsplit(source.url).hostname or source.url


def quote_words(claim: Claim, cut_quote: bool) -> str:
    """The quote on one line in quote marks, inner double quotes made single, cut at 240 characters when cut_quote."""
    text = " ".join(claim.quote.split()).replace('"', "'").replace("“", "‘").replace("”", "’")
    return f"“{cut(text, 240) if cut_quote else text}”"


def claim_view(claim: Claim, source: Source, org: Org | None, seen_at: datetime | None = None,
               cut_quote: bool = True) -> ClaimView:
    """The claim as every page words it: the fact, its years, the quote when the source is prose, and the citation.

    org is the claim's stored orgs row, if any; is_new is true when the claim was first stored after seen_at.
    """
    label, href, when = label_of(source), f"/sources/{claim.source_id}?claim={claim.id}#quote", date_words(claim)
    quote = QuoteView(text=quote_words(claim, cut_quote), label=label, href=href, date=when) if source.kind in PROSE else None
    return ClaimView(claim_id=claim.id, kind=claim.kind, what=what_of(claim, org), years=years_words(claim),
                     quote=quote, label=label, href=href, date=when,
                     is_new=bool(seen_at and claim.first_seen_at and claim.first_seen_at > seen_at))


def added_on(store: Store, person_id: str) -> str | None:
    """The day of the person's latest add event, such as '3 November 2026', or None when there is none."""
    at = next((e.at.astimezone() for e in store.events_of(person_id) if e.kind == "add"), None)
    return f"{at.day} {at:%B %Y}" if at else None


def person_view(store: Store, person: Person, claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source],
                shown: Claim | None) -> PersonView:
    """The view of one person from the claims of its records; shown is the claim the card gives as evidence."""
    member = person.list_status == "in_list"
    seen_at = person.seen_at if member else None
    job = newest([c for c in claims if c.kind == "role" and is_job(c, sources[c.source_id])])
    place, found = place_of(claims), belgian_orgs(claims, facts)
    contact = {kind: newest([c for c in claims if c.kind == kind]) for kind in ("email", "phone")}
    return PersonView(
        person_id=person.id, name=person.display_name, role=job.value if job else None,
        employer=employer_of(claims), place=place.value if place else None,
        lat=place.lat if place else None, lon=place.lon if place else None,
        orgs=[OrgView(org=name, years=f"{y[0]}–{y[-1]}" if len(y) > 1 else "".join(map(str, y))) for name, y in found[:3]],
        more_orgs=max(len(found) - 3, 0),
        evidence=claim_view(shown, sources[shown.source_id], facts.get(shown.org_id or ""), seen_at) if shown else None,
        status=person.list_status, added=added_on(store, person.id) if member else None,
        new_facts=sum(1 for c in claims if seen_at and c.first_seen_at and c.first_seen_at > seen_at),
        email=contact["email"].value if contact["email"] else None,
        phone=contact["phone"].value if contact["phone"] else None,
    )


def person_views(store: Store, groups: list[list[str]], today: date,
                 matched: list[list[str]] | None = None) -> list[PersonView]:
    """One view per group of stored person ids, named after its first; all claims come from one claims_of call.

    Ids are mapped to their canonical person first. matched holds, per group, the claim ids a search matched,
    which the evidence falls back to when the group has no claim at a Belgian organization.
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
    shown = [evidence(claims, facts, m) for claims, m in zip(owned, matched or [[] for _ in groups])]
    needed = {c.source_id for claims in owned for c in claims if c.kind == "role"} | {c.source_id for c in shown if c}
    sources = store.get_sources(list(needed))
    return [person_view(store, persons[g[0]], claims, facts, sources, s) for g, claims, s in zip(groups, owned, shown)]


def results(store: Store, search: Search, today: date) -> ResultsView:
    """The search's kept candidates as views by section, each from the records a lane hit, else from its first record."""
    candidates = store.list_candidates(search.id, kept_only=True)
    views = person_views(store, [c.hit_person_ids or c.person_ids[:1] for c in candidates], today,
                         [c.reason_claim_ids for c in candidates])
    return ResultsView(network=[v for c, v in zip(candidates, views) if c.section == "network"],
                       new=[v for c, v in zip(candidates, views) if c.section == "new"])


def sources_read(store: Store, search: Search) -> int:
    """How many records the search's lanes looked at."""
    total = 0
    for step in store.list_steps(search.id):
        output = store.get_payload(step.id)[1] if step.output_model == "LaneOut" else None
        total += LaneOut.model_validate_json(output).total_seen if output else 0
    return total
