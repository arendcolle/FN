"""LinkedIn lane: one Apify profile search per search, each profile a vendor_record source with dated claims."""
import json
from datetime import datetime

from fn import geo, orgs
from fn.contracts import (
    Chips,
    ClaimDraft,
    Considered,
    GeoArea,
    Identifier,
    LaneHit,
    LaneIn,
    LaneName,
    LaneOut,
    Source,
    clean_name,
    name_key,
    normalize,
    record_source,
)
from fn.contracts import profile_url as canonical
from fn.net import CacheMiss, MissingKey
from fn.steps import StepContext

name: LaneName = "linkedin"
ACTOR_URL = "https://api.apify.com/v2/actors/harvestapi~linkedin-profile-search/run-sync-get-dataset-items"
RUN_TIMEOUT_S = 240
CALL_TIMEOUT_S = 290
MAX_CHARGE_USD = 0.25
MAX_QUERY = 300
PAGE_USD = 0.10
PROFILE_USD = 0.004
NO_QUERY = "no topic or institution chip"
OFF = "LinkedIn lane is off and has no recorded run for this input; FN_LINKEDIN=1 runs it live for about $0.20"
UNITED_STATES = "United States"
# The Belgian schools the actor filters profiles on.
SCHOOLS = ["KU Leuven", "Ghent University", "University of Antwerp", "Vrije Universiteit Brussel", "Hasselt University",
           "Université libre de Bruxelles", "UCLouvain", "University of Liège", "Vlerick Business School"]
# GeoArea.city ("name, country code") to LinkedIn's location names; a city not here sends its own name.
LOCATIONS = {
    "New York City, US": ["New York City Metropolitan Area", "New Jersey"],
    "San Francisco, US": ["San Francisco Bay Area"],
    "Boston, US": ["Greater Boston"],
    "Washington, US": ["Washington DC-Baltimore Area"],
    "Atlanta, US": ["Atlanta Metropolitan Area"],
    "Chicago, US": ["Chicago Metropolitan Area"],
    "Los Angeles, US": ["Los Angeles Metropolitan Area"],
    "Houston, US": ["Houston Metropolitan Area"],
    "Seattle, US": ["Greater Seattle Area"],
}
EDUCATION = ("schoolName", "degree", "fieldOfStudy", "startDate.year", "endDate.year")
JOB = ("companyName", "position", "location", "startDate.text", "endDate.text")


def note(reason: str, kept: bool = False, stage: str = "query") -> Considered:
    return Considered(person_key="-", name="", stage=stage, kept=kept, reason=reason)


def query_terms(chips: Chips) -> tuple[list[str], list[str]]:
    """The topic chips, else the institution chips, as terms, each multi-word chip in double quotes.

    Double quotes inside a chip are dropped first, and a chip without text makes no term. Returns the leading
    whole terms whose ORed query is at most MAX_QUERY characters, the actor's limit, and the terms left out.
    """
    found = [" ".join(c.text.replace('"', "").split()) for c in chips.topics or chips.institutions]
    terms = [f'"{t}"' if " " in t else t for t in found if t]
    kept = 0
    while kept < len(terms) and len(" OR ".join(terms[:kept + 1])) <= MAX_QUERY:
        kept += 1
    return terms[:kept], terms[kept:]


def search_query(chips: Chips) -> str:
    """The terms of query_terms that fit, joined by " OR ". Empty when no chip has text or the first is too long."""
    return " OR ".join(query_terms(chips)[0])


def locations(chips: Chips, area: GeoArea | None) -> list[str]:
    """The LinkedIn locations for the place chip; area is geo.area's answer for it, None when it names no city.

    No place or anywhere_us gives United States. A place abroad, or one geo.py cannot locate, sends its own text.
    """
    place = chips.place
    if place is None or place.kind == "anywhere_us":
        return [UNITED_STATES]
    if place.kind == "abroad" or area is None:
        return [place.text]
    return list(LOCATIONS.get(area.city) or [area.city.rsplit(", ", 1)[0]])


def actor_input(chips: Chips, area: GeoArea | None) -> dict:
    """The actor's input: the chips' search query, the Belgian schools, the locations and one page of full profiles."""
    return {"searchQuery": search_query(chips), "schools": list(SCHOOLS), "locations": locations(chips, area),
            "profileScraperMode": "Full", "takePages": 1, "maxItems": 25}


def profiles_of(body: bytes) -> list[dict]:
    """The objects of the actor's answer; empty when the answer is not a JSON list."""
    try:
        answer = json.loads(body)
    except ValueError:
        return []
    return [p for p in answer if isinstance(p, dict)] if isinstance(answer, list) else []


def has_profiles(body: bytes) -> bool:
    """Whether the answer holds at least one profile with a linkedinUrl; an answer without one is not worth caching."""
    return any(p.get("linkedinUrl") for p in profiles_of(body))


def estimate(body: bytes) -> float:
    """Dollars for a live run at one search page plus each profile; the actor reports no cost."""
    return PAGE_USD + PROFILE_USD * len(profiles_of(body))


def dig(data: object, path: str) -> object:
    """The value at a dotted path of nested dicts; None when any step is missing."""
    for key in path.split("."):
        data = data.get(key) if isinstance(data, dict) else None
    return data


def year(entry: dict, path: str) -> str | None:
    value = dig(entry, path)
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else None


def full_name(profile: dict) -> str:
    return clean_name(f"{profile.get('firstName') or ''} {profile.get('lastName') or ''}")


def profile_source(profile: dict, fetched_at: datetime,
                   source_date: str | None) -> tuple[Source, dict[str, tuple[int, int]]]:
    """The profile as a vendor_record Source: its name, headline, location, education and experience lines.

    Returns it with each line's offsets by path. The repeats in currentPosition and profileTopEducation are
    not read.
    """
    fields = [(k, dig(profile, k)) for k in ("firstName", "lastName", "headline", "location.linkedinText")]
    for section, keys in (("education", EDUCATION), ("experience", JOB)):
        for i, entry in enumerate(profile.get(section) or []):
            fields += [(f"{section}.{i}.{k}", dig(entry, k)) for k in keys]
    return record_source(canonical(profile["linkedinUrl"]), f"LinkedIn profile {full_name(profile)}", fields, profile,
                         fetched_at, source_date, kind="vendor_record")


def drafts(person_id: str, source: Source, spans: dict[str, tuple[int, int]], profile: dict,
           scrape_year: str) -> list[ClaimDraft]:
    """One affiliation claim per education entry (studied_at) and per job (works_at while current, else worked_at).

    A claim quotes its entry's lines and takes valid_from and valid_to from the entry's start and end years;
    a current job runs to scrape_year. claim_date is the end year, else the start year, else empty. An entry
    without a school or company name makes no claim.
    """
    found = []
    for section, keys, org_key in (("education", EDUCATION, "schoolName"), ("experience", JOB, "companyName")):
        for i, entry in enumerate(profile.get(section) or []):
            org = entry.get(org_key)
            if not org:
                continue
            paths = [p for p in (f"{section}.{i}.{k}" for k in keys) if p in spans]
            first, last = spans[paths[0]][0], spans[paths[-1]][1]
            current = section == "experience" and dig(entry, "endDate.text") == "Present"
            start = year(entry, "startDate.year")
            end = scrape_year if current else year(entry, "endDate.year")
            relation = "studied_at" if section == "education" else "works_at" if current else "worked_at"
            dated = end or start
            found.append(ClaimDraft(
                person_id=person_id, kind="affiliation", relation=relation, org_id=orgs.org_id(org),
                value=normalize(org), quote=source.text[first:last], quote_start=first, quote_end=last, source=source,
                claim_date=dated, date_precision="year" if dated else None,
                date_method="record_field" if dated else None, valid_from=start, valid_to=end,
            ))
    return found


def people(ctx: StepContext, profiles: list[dict], considered: list[Considered]) -> list[LaneHit]:
    """One hit per person in the profiles, in the actor's order, with every profile's source and claims stored.

    A profile without a linkedinUrl, or whose name has fewer than two words, is skipped. One URL twice is one
    person and one hit. Each profile, and each school spelling that maps to no org id, is added to considered.
    """
    hits: dict[str, LaneHit] = {}
    unmapped: dict[str, None] = {}
    with ctx.store.tx():
        for rank, profile in enumerate(profiles, 1):
            who = full_name(profile)
            if not profile.get("linkedinUrl"):
                considered.append(Considered(person_key=f"result {rank}", name=who, stage="profile", kept=False,
                                             reason=f"result {rank}: no linkedinUrl; skipped"))
                continue
            if len(name_key(who).split()) < 2:
                considered.append(Considered(person_key=canonical(profile["linkedinUrl"]), name=who, stage="profile",
                                             kept=False, reason=f"name has fewer than two words: {who!r}"))
                continue
            now, day = ctx.now(), str(dig(profile, "_meta.scrapedAt") or "")[:10] or None
            source, spans = profile_source(profile, now, day)
            person = ctx.store.resolve_person([Identifier(scheme="profile_url", value=source.url)], who)
            claims = [ctx.store.upsert_claim(d, now)
                      for d in drafts(person.id, source, spans, profile, (day or now.date().isoformat())[:4])]
            unmapped |= dict.fromkeys(c.value for c in claims if c.relation == "studied_at" and c.org_id is None)
            where = f"result {rank}, {source.url}"
            if profile.get("headline"):
                where = f"result {rank}, {profile['headline']}, {source.url}"
            hit = hits.get(person.id) or LaneHit(person_id=person.id, name_key=person.name_key, lane=name,
                                                 rank=len(hits) + 1, score=1 / rank, matched_on=where)
            ids = list(dict.fromkeys([*hit.claim_ids, *(c.id for c in claims)]))
            hits[person.id] = hit.model_copy(update={"claim_ids": ids})
            studied = sum(c.relation == "studied_at" for c in claims)
            reason = f"result {rank}: {studied} education and {len(claims) - studied} job claims"
            considered.append(Considered(person_key=source.url, name=who, stage="profile", kept=True, reason=reason))
    considered += [Considered(person_key=school, name="", stage="school", kept=False,
                              reason=f"school {school!r} maps to no org id in data/org_aliases.csv")
                   for school in unmapped]
    return list(hits.values())


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    """Search LinkedIn through Apify for the chips and make every profile the actor returns a hit.

    With FN_LINKEDIN=1 a recorded input is served from the cache, else the call runs live; without it only a
    recorded run is served, else the lane notes it is off. Without an Apify token it notes that. Raises
    RuntimeError without an HTTP client, and HttpError for a refused or failed call.
    """
    chips = inp.chips
    used, left = query_terms(chips)
    considered = [note(f"query over {MAX_QUERY} characters; chips left out: {', '.join(left)}")] if left else []
    if not used:
        return LaneOut(lane=name, query="", total_seen=0, considered=considered or [note(NO_QUERY)])
    if ctx.http is None:
        raise RuntimeError("the LinkedIn lane needs an HTTP client")
    body = actor_input(chips, geo.area(ctx.http, chips.place))
    query = f"{body['searchQuery']}; locations {', '.join(body['locations'])}"
    live = ctx.settings.linkedin_live
    params = {"timeout": str(RUN_TIMEOUT_S), "maxTotalChargeUsd": str(MAX_CHARGE_USD)}
    try:
        response = ctx.http.post(ACTOR_URL, body, params, timeout_s=CALL_TIMEOUT_S, cost=estimate, keep=has_profiles,
                                 cache="prefer" if live else "only")
    except CacheMiss:
        reason = "FN_HTTP=replay has no recorded LinkedIn run for this input" if live else OFF
        return LaneOut(lane=name, query=query, total_seen=0, considered=[*considered, note(reason)])
    except MissingKey as exc:
        ctx.log.warning("LinkedIn lane skipped: %s", exc)
        return LaneOut(lane=name, query=query, total_seen=0,
                       considered=[*considered, note(f"LinkedIn lane skipped: {exc}")])
    profiles = profiles_of(response.content)
    if not has_profiles(response.content):
        considered.append(note("Apify returned no profiles; not cached"))
    total = next((dig(p, "_meta.pagination.totalElements") for p in profiles if dig(p, "_meta.pagination")), None)
    considered.append(note(f"read {len(profiles)} of {total} profiles" if total is not None
                           else f"read {len(profiles)} profiles", True, "read"))
    hits = people(ctx, profiles, considered)
    ctx.log.info("linkedin lane: %d of %s profiles, %d people; a live run costs about $%.2f (estimate)", len(profiles),
                 total, len(hits), estimate(response.content))
    return LaneOut(lane=name, query=query, total_seen=len(profiles), hits=hits, considered=considered)
