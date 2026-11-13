"""How a person reads on every staff page: the view models of people and claims, and plain-words helpers."""
from calendar import month_name
from datetime import date, datetime
from urllib.parse import urlsplit

from fn import identity, network, orgs, rank
from fn.contracts import (
    Candidate,
    CardView,
    Claim,
    ClaimView,
    ContactView,
    Event,
    FactGroup,
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
    RecordView,
    ResultsView,
    Search,
    Source,
)
from fn.evidence import places
from fn.store import Store, fold

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
GROUPS = ("Ties to Belgium", "Work", "Places")
DONE = {"add": "Added to your network", "skip": "Skipped", "edit_contact": "Saved", "merge": "Merged into this profile",
        "not_same": "Marked as a different person"}
RESULTS_STEP = 20
WORK = "OpenAlex work "


def employer_of(claims: list[Claim], facts: dict[str, Org] | None = None, place: str | None = None) -> str | None:
    """The organization of the newest works_at, worked_at or affiliated_with claim, or None.

    Of the jobs that share the newest date, one at an organization in the city of place comes first.
    """
    jobs = [c for c in claims if c.relation in EMPLOYED]
    if not jobs:
        return None
    top = max(jobs, key=job_date)
    local = [c for c in jobs if job_date(c)[0] == job_date(top)[0]
             and in_city(facts.get(c.org_id or "") if facts else None, place)]
    return max(local or [top], key=job_date).value


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


def is_job(claim: Claim, source: Source) -> bool:
    """Whether a role claim names a job: not a seed list role, nor a page title or host standing in for a role."""
    return claim.relation not in LIST_ROLES and claim.value not in (source.title, urlsplit(source.url).hostname, source.url)


def years_words(claim: Claim) -> str:
    """The years the claim covers as runs, such as '2008–2013' or '2001, 2008', or empty when it has none."""
    return rank.years_text(rank.units(claim) - {rank.UNDATED}).replace("-", "–")


def what_of(claim: Claim, org: Org | None) -> str:
    """The fact in plain words, such as 'Studied at KU Leuven', 'Field: 6G', 'Born in Leuven' or 'Origin: Belgian'."""
    if claim.kind in ("role", "availability"):
        return claim.value
    if claim.kind == "location" and claim.relation == "origin":
        return f"Origin: {claim.value}"
    if claim.kind == "location":
        return f"{'Born in' if claim.relation == 'born_in' else 'Based in'} {claim.value}"
    if claim.kind in FIELDS:
        return f"{FIELDS[claim.kind]}: {claim.value}"
    name = org.name if org else claim.value
    return f"{RELATIONS[claim.relation]} {name}" if claim.relation in RELATIONS else name


def is_work(source: Source) -> bool:
    return source.kind == "record" and (source.title or "").startswith(WORK)


def label_of(source: Source) -> str:
    """The source as a citation names it: the record kind, the import file and row (its title), else the page title or host."""
    if is_work(source):
        return WORK.strip()
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

    org is the claim's stored orgs row, if any; is_new is true when the claim was first stored after seen_at. A topic
    claim from an OpenAlex work reads 'Paper: ' and the title, cut like a quote when cut_quote.
    """
    label, href, when = label_of(source), f"/sources/{claim.source_id}?claim={claim.id}#quote", date_words(claim)
    quote = QuoteView(text=quote_words(claim, cut_quote), label=label, href=href, date=when) if source.kind in PROSE else None
    paper = claim.kind == "topic" and is_work(source)
    what = f"Paper: {cut(claim.value, 240) if cut_quote else claim.value}" if paper else what_of(claim, org)
    return ClaimView(claim_id=claim.id, kind=claim.kind, what=what, years=years_words(claim),
                     quote=quote, label=label, href=href, date=when,
                     is_new=bool(seen_at and claim.first_seen_at and claim.first_seen_at > seen_at))


def added_on(store: Store, person_id: str) -> str | None:
    """The day of the person's latest add event, such as '3 November 2026', or None when there is none."""
    at = next((e.at.astimezone() for e in store.events_of(person_id) if e.kind == "add"), None)
    return f"{at.day} {at:%B %Y}" if at else None


def person_view(store: Store, person: Person, claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source],
                shown: Claim | None, today: date, records: int = 1) -> PersonView:
    """The view of one person from the claims of its records; shown is the claim the card gives as evidence.

    records is how many records not merged into one person the claims come from.
    """
    member = person.list_status == "in_list"
    seen_at = person.seen_at if member else None
    job = newest([c for c in claims if c.kind == "role" and is_job(c, sources[c.source_id])])
    (place, lat, lon, basis), found = located(claims, facts, today), belgian_orgs(claims, facts)
    contact = {kind: newest([c for c in claims if c.kind == kind]) for kind in ("email", "phone")}
    return PersonView(
        person_id=person.id, name=person.display_name, role=job.value if job else None,
        employer=employer_of(claims, facts, place), place=place, lat=lat, lon=lon, place_basis=basis, records=records,
        orgs=[OrgView(org=name, years=f"{y[0]}–{y[-1]}" if len(y) > 1 else "".join(map(str, y))) for name, y in found[:3]],
        more_orgs=max(len(found) - 3, 0),
        evidence=claim_view(shown, sources[shown.source_id], facts.get(shown.org_id or ""), seen_at) if shown else None,
        status=person.list_status, added=added_on(store, person.id) if member else None,
        new_facts=sum(1 for c in claims if seen_at and c.first_seen_at and c.first_seen_at > seen_at),
        email=contact["email"].value if contact["email"] else None,
        phone=contact["phone"].value if contact["phone"] else None,
    )


def person_views(store: Store, groups: list[list[str]], today: date, matched: list[list[str]] | None = None,
                 topics: list[str | None] | None = None) -> list[PersonView]:
    """One view per group of stored person ids, named after its first; all claims come from one claims_of call.

    Ids are mapped to their canonical person first. matched holds, per group, the claim ids a search matched,
    which the evidence falls back to when the group has no claim at a Belgian organization. topics holds, per
    group, the claim the evidence shows first.
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
    shown = [evidence(claims, facts, m, t) for claims, m, t in
             zip(owned, matched or [[] for _ in groups], topics or [None for _ in groups])]
    needed = {c.source_id for claims in owned for c in claims if c.kind == "role"} | {c.source_id for c in shown if c}
    sources = store.get_sources(list(needed))
    return [person_view(store, persons[g[0]], claims, facts, sources, s, today, len(g))
            for g, claims, s in zip(groups, owned, shown)]


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


def why_of(candidate: Candidate, view: PersonView) -> str | None:
    """The why line from the candidate's stored parts: the topic words found, else the place it was listed for."""
    parts = {p.feature: p for p in candidate.score_parts}
    if topic := parts.get("topic"):
        return f"Matches: {topic.detail}" + (" · Place from the employer" if view.place_basis == "employer" else "")
    if place := parts.get("place"):
        return f"Based in {place.detail.split(': ', 1)[-1]}"
    return None


def card_view(store: Store, candidate: Candidate, view: PersonView, skipped: bool, today: date) -> CardView:
    """The candidate's card: its state from the people's status now, the same-name network person and the Undo."""
    base = {"key": candidate.person_id, "section": candidate.section, "person": view, "why": why_of(candidate, view)}
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


def card(store: Store, candidate: Candidate, today: date) -> CardView:
    """The card of one candidate, as the results page shows it."""
    view = person_views(store, [identity.on_card(store, candidate)], today, [candidate.reason_claim_ids],
                        [topic_claim(candidate)])[0]
    return card_view(store, candidate, view, is_skipped(store, candidate), today)


def results(store: Store, search: Search, today: date, shown: int = RESULTS_STEP,
            show_skipped: bool = False) -> ResultsView:
    """The search's kept candidates: the people who are not skipped by section, and the cards of the first shown.

    A person skipped on this search keeps its card where it stood; one skipped elsewhere is counted as hidden and
    shows only with show_skipped. Skipped people never take a place among the shown.
    """
    candidates = store.list_candidates(search.id, kept_only=True)
    views = person_views(store, [identity.on_card(store, c) for c in candidates], today, [c.reason_claim_ids for c in candidates],
                         [topic_claim(c) for c in candidates])
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
        cards.append(card_view(store, c, v, s, today))
    people = [v for _, v in kept]
    return ResultsView(network=[v for c, v in kept if c.section == "network"],
                       new=[v for c, v in kept if c.section == "new"], cards=cards, total=len(kept), shown=counted,
                       skipped_hidden=hidden, not_on_map=sum(1 for v in people if v.lat is None or v.lon is None),
                       next_key=next_key, order=[(v.person_id, c.person_id) for c, v in kept])


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


def group_of(claim: Claim, facts: dict[str, Org]) -> str | None:
    """The profile group a claim shows under: at a Belgian organization, a place, or work; None for a contact."""
    if claim.org_id in facts and facts[claim.org_id].country_code == "BE":
        return "Ties to Belgium"
    if claim.kind == "location":
        return "Places"
    return None if claim.kind in ("email", "phone") else "Work"


def fact_lines(claims: list[Claim], facts: dict[str, Org], sources: dict[str, Source],
               seen_at: datetime | None) -> list[ClaimView]:
    """One line per fact: claims with one kind, relation and organization or value, cited by the newest of them.

    A line has the years of all its claims and is new when any of them is; new lines come first, then newest first.
    A rejected claim is a line of its own.
    """
    same: dict[tuple, list[Claim]] = {}
    for claim in claims:
        key = (claim.id,) if claim.rejected_at else (claim.kind, claim.relation, claim.org_id or fold(claim.value))
        same.setdefault(key, []).append(claim)
    lines = []
    for found in same.values():
        shown = newest(found)
        years = frozenset().union(*(rank.units(c) for c in found)) - {rank.UNDATED}
        fresh = any(seen_at and c.first_seen_at and c.first_seen_at > seen_at for c in found)
        view = claim_view(shown, sources[shown.source_id], facts.get(shown.org_id or ""), seen_at, cut_quote=False)
        lines.append((shown.claim_date or "", view.model_copy(
            update={"years": rank.years_text(years).replace("-", "–"), "is_new": fresh})))
    lines.sort(key=lambda t: t[0], reverse=True)
    return [view for _, view in sorted(lines, key=lambda t: not t[1].is_new)]


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


def found_as(store: Store, person_id: str, claims: list[Claim], sources: dict[str, Source]) -> list[RecordView]:
    """One entry per record and source the person's facts came from, with its fact count; none for a single record."""
    records = store.records_of(person_id)
    if len(records) < 2:
        return []
    owner = store.claim_records([c.id for c in claims])
    counts: dict[tuple[str, str], int] = {}
    for claim in claims:
        key = (owner[claim.id], claim.source_id)
        counts[key] = counts.get(key, 0) + 1
    order = {r.id: n for n, r in enumerate(records)}
    return [RecordView(record_id=record, label=label_of(sources[source]), href=f"/sources/{source}", facts=n)
            for (record, source), n in sorted(counts.items(), key=lambda t: order.get(t[0][0], len(order)))]


def separated_label(store: Store, record_id: str) -> str:
    """The source label of a separated record's first fact, else its name."""
    claims = store.claims_of([record_id])
    if not claims:
        return store.get_persons([record_id])[record_id].display_name
    return label_of(store.get_sources([claims[0].source_id])[claims[0].source_id])


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


def profile(store: Store, person_id: str, today: date) -> ProfileView | None:
    """Everything the Person page shows of the id's person, or None for an unknown id.

    The fact a just-undoable reject removed stays in its group, so the page can show it with Undo.
    """
    canonical = store.canonical_ids([person_id]).get(person_id)
    if canonical is None:
        return None
    person = store.get_persons([canonical])[canonical]
    member = person.list_status == "in_list"
    claims = store.claims_of([canonical])
    event = latest(store, canonical)
    removed = store.get_claim(event.claim_id) if event and event.kind == "reject_claim" else None
    shown = claims + ([removed] if removed and removed.id not in {c.id for c in claims} else [])
    facts = store.get_orgs(list({c.org_id for c in shown if c.org_id}))
    sources = store.get_sources(list({c.source_id for c in shown}))
    seen_at = person.seen_at if member else None
    groups: dict[str, list[Claim]] = {}
    for claim in shown:
        if group := group_of(claim, facts):
            groups.setdefault(group, []).append(claim)
    lines = {title: fact_lines(found, facts, sources, seen_at) for title, found in groups.items()}
    removed_view = claim_view(removed, sources[removed.source_id], facts.get(removed.org_id or "")) if removed else None
    name_match = None
    if not member:
        name_match = next(iter(network.name_matches(store, [canonical])), None)
    possible = [p for p in network.possible_matches(store, canonical) if p != name_match]
    views = person_views(store, [[canonical], *([[name_match]] if name_match else []), *[[p] for p in possible]], today)
    return ProfileView(
        person=views[0], contact=[contact_of(kind, claims, sources) for kind in ("email", "phone")],
        facts=[FactGroup(title=title, facts=lines[title]) for title in GROUPS if lines.get(title)],
        found_as=found_as(store, canonical, claims, sources), possible=views[2:] if name_match else views[1:],
        name_match=views[1] if name_match else None, last=last_of(store, person, event, removed_view),
    )
