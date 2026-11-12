"""OpenAlex lane: authors of Belgian works per topic chip and of each institution chip, every fetched author a hit."""
from dataclasses import dataclass, field
from datetime import datetime

from fn import geo, orgs
from fn.contracts import (
    Chips,
    Claim,
    ClaimDraft,
    Considered,
    GeoArea,
    Identifier,
    LaneHit,
    LaneIn,
    LaneName,
    LaneOut,
    OrgFacts,
    Person,
    Source,
    normalize,
    record_source,
)
from fn.steps import StepContext, fan_out
from fn.store import Store

name: LaneName = "openalex"
API = "https://api.openalex.org"
WORK_SELECT = "id,display_name,publication_year,authorships"
AUTHOR_SELECT = "id,display_name,orcid,affiliations,last_known_institutions,updated_date"
INSTITUTION_SELECT = "id,display_name,ror,country_code,type,geo"
WORKS_PER_PAGE = 100
AUTHORS_PER_PAGE = 200
MAX_PAGES = 4
BATCH = 100
MAX_AUTHORS = 2000
WORKS_PER_AUTHOR = 3
FETCH_WORKERS = 3
NO_QUERY = "no topic or institution chip"


@dataclass
class Seen:
    name: str
    order: int
    works: int = 0
    found_by: list[str] = field(default_factory=list)
    works_seen: list[dict] = field(default_factory=list)


def short(openalex_id: str) -> str:
    return openalex_id.rsplit("/", 1)[-1]


def note(reason: str, kept: bool = False, stage: str = "query") -> Considered:
    return Considered(person_key="-", name="", stage=stage, kept=kept, reason=reason)


def chip_ror(text: str, ref: str | None) -> str | None:
    """The ROR url of an institution chip: its ror: ref, else the ROR id data/org_aliases.csv gives its text."""
    ref = ref if ref and ref.startswith("ror:") else orgs.ref(text)
    return f"https://ror.org/{ref[4:]}" if ref else None


def org_of(inst: dict) -> str:
    """The org id of an OpenAlex institution: ror:<id> when OpenAlex gives its ROR, else openalex:<I…>."""
    return f"ror:{short(inst['ror'])}" if inst.get("ror") else f"openalex:{short(inst['id'])}"


def seen_authors(ctx: StepContext, chips: Chips, considered: list[Considered]) -> tuple[dict[str, Seen], list[str]]:
    """Every author on up to 4 pages of each institution's authors and on page 1 of each topic's Belgian works.

    Returns the authors by OpenAlex id in the order first seen, and one line per query sent.
    """
    seen: dict[str, Seen] = {}
    queries: list[str] = []

    def see(author: dict, how: str) -> Seen:
        found = seen.setdefault(short(author["id"]), Seen(author.get("display_name") or "", len(seen)))
        if how not in found.found_by:
            found.found_by.append(how)
        return found

    # Institution lists go first: they are the narrower query, so MAX_AUTHORS cuts topic authors before them.
    for chip in chips.institutions:
        ror = chip_ror(chip.text, chip.ref)
        if ror is None:
            considered.append(note(f"institution {chip.text!r} has no ROR id in data/org_aliases.csv; not queried"))
            continue
        where = f"last_known_institutions.ror:{ror},affiliations.institution.country_code:BE"
        queries.append(f"authors filter={where}")
        for page in range(1, MAX_PAGES + 1):
            body = ctx.http.get(f"{API}/authors", {"filter": where, "per_page": str(AUTHORS_PER_PAGE),
                                                   "page": str(page), "select": "id,display_name"}).json()
            for author in body["results"]:
                see(author, f"institution {chip.text!r}")
            count = body["meta"]["count"]
            if page * AUTHORS_PER_PAGE >= count or not body["results"]:
                break
        else:
            considered.append(note(f"institution {chip.text!r}: {count} authors, read the first {MAX_PAGES} pages"))
    for chip in chips.topics:
        queries.append(f"works search={chip.text!r} filter=institutions.country_code:BE")
        body = ctx.http.get(f"{API}/works", {"search": chip.text, "filter": "institutions.country_code:BE",
                                             "per_page": str(WORKS_PER_PAGE), "select": WORK_SELECT}).json()
        for work in body["results"]:
            authors = {short(a["author"]["id"]): a["author"] for a in work["authorships"] if a["author"].get("id")}
            for author in authors.values():
                found = see(author, f"works on {chip.text!r}")
                found.works += 1
                if len(found.works_seen) < WORKS_PER_AUTHOR and work["id"] not in {w["id"] for w in found.works_seen}:
                    found.works_seen.append({k: work.get(k) for k in ("id", "display_name", "publication_year")})
    return seen, queries


def fetch(ctx: StepContext, path: str, key: str, ids: list[str], select: str) -> dict[str, dict]:
    """OpenAlex records by short id, fetched in batches of 100 ids on 3 workers and merged in batch order.

    Raises the error of the first failed batch once every batch has ended.
    """
    def batch(start: int) -> dict:
        return ctx.http.get(f"{API}/{path}", {"filter": f"{key}:{'|'.join(ids[start:start + BATCH])}",
                                              "per_page": str(BATCH), "select": select}).json()

    found: dict[str, dict] = {}
    for body in fan_out(batch, range(0, len(ids), BATCH), FETCH_WORKERS):
        if isinstance(body, Exception):
            raise body
        found |= {short(r["id"]): r for r in body["results"]}
    return found


def quote(source: Source, spans: dict[str, tuple[int, int]], first: str, last: str) -> dict:
    start, end = spans[first][0], spans[last][1]
    return {"quote": source.text[start:end], "quote_start": start, "quote_end": end, "source": source}


def author_source(record: dict, fetched_at: datetime) -> tuple[Source, dict[str, tuple[int, int]]]:
    fields: list[tuple[str, object]] = [("id", record["id"]), ("display_name", record["display_name"]),
                                        ("orcid", record.get("orcid"))]
    for i, inst in enumerate(record.get("last_known_institutions") or []):
        fields += [(f"last_known_institutions.{i}.display_name", inst["display_name"]),
                   (f"last_known_institutions.{i}.country_code", inst.get("country_code"))]
    for i, aff in enumerate(record.get("affiliations") or []):
        fields += [(f"affiliations.{i}.institution.display_name", aff["institution"]["display_name"]),
                   (f"affiliations.{i}.institution.country_code", aff["institution"].get("country_code")),
                   (f"affiliations.{i}.years", ", ".join(str(y) for y in aff.get("years") or []))]
    updated = (record.get("updated_date") or "")[:10] or None
    return record_source(record["id"], f"OpenAlex author {record['display_name']}", fields, record, fetched_at, updated)


def affiliation_orgs(record: dict, institutions: dict[str, dict]) -> list[OrgFacts]:
    """The institution of each affiliation with years, with the name and country OpenAlex gives it.

    The city and coordinates come from the institution's fetched record in institutions, by short id, when it has a geo.
    """
    found = []
    for a in record.get("affiliations") or []:
        inst = a["institution"]
        if not a.get("years"):
            continue
        where = (institutions.get(short(inst["id"])) or {}).get("geo") or {}
        found.append(OrgFacts(id=org_of(inst), name=normalize(inst["display_name"]), country_code=inst.get("country_code"),
                              city=where.get("city"), lat=where.get("latitude"), lon=where.get("longitude")))
    return found


def affiliation_drafts(record: dict, person_id: str, source: Source,
                       spans: dict[str, tuple[int, int]]) -> list[ClaimDraft]:
    """One affiliated_with claim per affiliation with years, dated by them and quoting its lines of the author record.

    Each claim lists the record's years, sorted and once each, and runs from the first to the last.
    """
    drafts = []
    for i, aff in enumerate(record.get("affiliations") or []):
        inst, years = aff["institution"], sorted(set(aff.get("years") or []))
        if not years:
            continue
        drafts.append(ClaimDraft(
            person_id=person_id, kind="affiliation", relation="affiliated_with", org_id=org_of(inst),
            value=normalize(inst["display_name"]), claim_date=str(years[-1]), date_precision="year",
            date_method="record_field", valid_from=str(years[0]), valid_to=str(years[-1]), years=years,
            **quote(source, spans, f"affiliations.{i}.institution.display_name", f"affiliations.{i}.years"),
        ))
    return drafts


def location_draft(inst: dict, person_id: str, fetched_at: datetime) -> ClaimDraft | None:
    """A location claim from the institution record's geo, dated the day it was read; None without coordinates."""
    where = inst.get("geo") or {}
    if where.get("latitude") is None or where.get("longitude") is None:
        return None
    parts = ["city", "region", "country", "latitude", "longitude"]
    fields = [("id", inst["id"]), ("display_name", inst["display_name"]), ("ror", inst.get("ror")),
              ("country_code", inst.get("country_code")), *((f"geo.{p}", where.get(p)) for p in parts)]
    source, spans = record_source(inst["id"], f"OpenAlex institution {inst['display_name']}", fields, inst, fetched_at)
    first = next(f"geo.{p}" for p in parts if f"geo.{p}" in spans)
    return ClaimDraft(
        person_id=person_id, kind="location", value=", ".join(where[p] for p in parts[:3] if where.get(p)),
        claim_date=fetched_at.date().isoformat(), date_precision="day", date_method="read_date",
        lat=where["latitude"], lon=where["longitude"], **quote(source, spans, first, "geo.longitude"),
    )


def save_author(store: Store, record: dict, institutions: dict[str, dict],
                now: datetime) -> tuple[Person, list[Claim], Claim | None]:
    """Store one author record: its person by OpenAlex id and ORCID, its affiliation orgs and claims, and a location.

    The location comes from the last known institution when institutions holds its record by short id.
    Returns the person, the affiliation claims and the location claim or None.
    """
    idents = [Identifier(scheme="openalex", value=short(record["id"]))]
    idents += [Identifier(scheme="orcid", value=record["orcid"])] if record.get("orcid") else []
    person = store.resolve_person(idents, record["display_name"])
    source, spans = author_source(record, now)
    orgs.save(store, affiliation_orgs(record, institutions), source, replace=False)
    claims = [store.upsert_claim(d, now) for d in affiliation_drafts(record, person.id, source, spans)]
    last = (record.get("last_known_institutions") or [None])[0]
    inst = institutions.get(short(last["id"])) if last else None
    location = location_draft(inst, person.id, now) if inst else None
    return person, claims, store.upsert_claim(location, now) if location else None


def topic_drafts(works: list[dict], person_id: str, fetched_at: datetime) -> list[ClaimDraft]:
    """One topic claim per matching work with a title, dated by its publication year when it has one."""
    drafts = []
    for work in works:
        title, year = normalize(work["display_name"] or ""), work["publication_year"]
        if not title:
            continue
        fields = [("id", work["id"]), ("display_name", title), ("publication_year", year)]
        source, spans = record_source(work["id"], f"OpenAlex work {title}", fields, work, fetched_at)
        dated = {"claim_date": str(year), "date_precision": "year", "date_method": "record_field"} if year else {}
        drafts.append(ClaimDraft(person_id=person_id, kind="topic", value=title, **dated,
                                 **quote(source, spans, "display_name", "display_name")))
    return drafts


def place_area(ctx: StepContext, chips: Chips, considered: list[Considered]) -> GeoArea | None:
    place = chips.place
    if place is None:
        return None
    if place.kind not in geo.METRO_KINDS:
        considered.append(note(f"place {place.text!r} is {place.kind}; distance does not rank", True, "place"))
        return None
    area = geo.area(ctx.http, place)
    considered.append(note(
        f"place {place.text!r} is {area.city} ({area.lat:.2f}, {area.lon:.2f}), radius {area.radius_km:g} km" if area
        else f"place {place.text!r} names no city in GeoNames cities15000; distance does not rank", True, "place"))
    return area


def placed(area: GeoArea | None, inst: dict | None) -> tuple[int, str]:
    """The place group (0 inside or no place chip, 1 place unknown, 2 outside) and its reason."""
    where = (inst or {}).get("geo") or {}
    if where.get("latitude") is None or where.get("longitude") is None:
        return (1 if area else 0), "place unknown: no last known institution with coordinates"
    at = f"last known {inst['display_name']}, {where.get('city')}"
    if area is None:
        return 0, at
    km = geo.distance_km(area.lat, area.lon, where["latitude"], where["longitude"])
    inside = km <= area.radius_km
    return (0 if inside else 2), f"{at}, {km:,.0f} km from {area.city} ({'inside' if inside else 'outside'} the radius)"


def belgian(record: dict) -> list[dict]:
    """The record's Belgian affiliations that have years."""
    return [a for a in record.get("affiliations") or [] if a["institution"].get("country_code") == "BE" and a.get("years")]


def found_on(seen: Seen) -> int:
    """The works and institution lists the author was found on; the hit's score, which orders nothing."""
    return seen.works + sum(how.startswith("institution") for how in seen.found_by)


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    """Find authors, order every one with a record by place group, then the order seen, and store every one.

    Each of the first 2,000 authors seen that OpenAlex returns a record for is a hit, Belgian or not. Each gets a
    person, an affiliation claim per affiliation with years, a location claim from the last known institution
    and a topic claim per matching work, up to 3. Every author seen is in considered with its verdict. Raises RuntimeError without an HTTP client.
    """
    if not inp.chips.topics and not inp.chips.institutions:
        return LaneOut(lane=name, query="", total_seen=0, considered=[note(NO_QUERY)])
    if ctx.http is None:
        raise RuntimeError("the OpenAlex lane needs an HTTP client")
    considered: list[Considered] = []
    seen, queries = seen_authors(ctx, inp.chips, considered)
    area = place_area(ctx, inp.chips, considered)
    ids = list(seen)
    records = fetch(ctx, "authors", "ids.openalex", ids[:MAX_AUTHORS], AUTHOR_SELECT)
    kept = [a for a in ids if a in records]
    last_known = {a: (records[a].get("last_known_institutions") or [None])[0] for a in kept}
    inst_ids = list(dict.fromkeys(short(i["id"]) for i in last_known.values() if i))
    institutions = fetch(ctx, "institutions", "openalex", inst_ids, INSTITUTION_SELECT)
    where = {a: placed(area, institutions.get(short(i["id"])) if i else None) for a, i in last_known.items()}
    ordered = sorted(kept, key=lambda a: (where[a][0], seen[a].order))
    hits = []
    with ctx.store.tx():
        for rank, author in enumerate(ordered, 1):
            record, now = records[author], ctx.now()
            person, claims, location = save_author(ctx.store, record, institutions, now)
            be_names = {normalize(a["institution"]["display_name"]) for a in belgian(record)}
            reasons = [c.id for c in claims if c.value in be_names]
            if location:
                reasons.append(location.id)
            reasons += [ctx.store.upsert_claim(d, now).id for d in topic_drafts(seen[author].works_seen, person.id, now)]
            hits.append(LaneHit(person_id=person.id, name_key=person.name_key, lane=name, rank=rank,
                                score=found_on(seen[author]), matched_on="; ".join([*seen[author].found_by, where[author][1]]), claim_ids=reasons))
    rank_of = {a: r for r, a in enumerate(ordered, 1)}
    for author, found in seen.items():
        record = records.get(author)
        if author not in rank_of:
            reason = (f"not fetched: beyond the first {MAX_AUTHORS} authors seen" if found.order >= MAX_AUTHORS
                      else "no author record returned")
            considered.append(Considered(person_key=author, name=found.name, stage="record", kept=False, reason=reason))
            continue
        affs = ", ".join(f"{a['institution']['display_name']} {min(a['years'])}-{max(a['years'])}" for a in belgian(record)) or "none"
        considered.append(Considered(
            person_key=author, name=found.name, stage="rank", kept=True,
            reason=f"rank {rank_of[author]}, seen #{found.order + 1}; found by {'; '.join(found.found_by)}; "
                   f"Belgian affiliations {affs}; {where[author][1]}",
        ))
    with_be = sum(bool(belgian(records[a])) for a in kept)
    ctx.log.info("openalex lane: %d authors seen, %d hits, %d with a Belgian affiliation", len(seen), len(hits), with_be)
    return LaneOut(lane=name, query="; ".join(queries), total_seen=len(seen), hits=hits, considered=considered)
