"""LinkedIn lane: one Apify profile search per search, each profile a vendor_record source with dated claims."""
import json
from datetime import datetime

from fn import geo, orgs, parse
from fn.config import Settings
from fn.contracts import (
    Chips,
    ClaimDraft,
    Considered,
    GeoArea,
    HttpClient,
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
from fn.net import CacheMiss, HttpError, MissingKey
from fn.steps import StepContext

name: LaneName = "linkedin"
ACTOR_URL = "https://api.apify.com/v2/actors/harvestapi~linkedin-profile-search/run-sync-get-dataset-items"
ACCOUNT_URL = "https://api.apify.com/v2/users/me"
LIMITS_URL = "https://api.apify.com/v2/users/me/limits"
MAX_TITLES = 12
# Run timeout, call timeout and profiles per run; chips before version 2 keep round three's, so their recorded run replays.
SIZES = {1: (240, 290, 25), 2: (270, 295, 10)}
MAX_CHARGE_USD = 0.25
MAX_QUERY = 300
PAGE_USD = 0.10
PROFILE_USD = 0.004
NO_QUERY = "no role, topic or institution chip"
OFF = "LinkedIn lane is off and has no recorded run for this input; FN_LINKEDIN=1 runs it live for about $0.20"
RESEARCHERS = "researchers only; LinkedIn not asked"
FREE_PLAN = "Apify's free plan runs this actor ten times in total; a paid plan is needed"
NO_ROOM = "the month's Apify budget has no room for a run (${used:.2f} of ${cap:.2f} used)"
NO_ACCOUNT = "could not read the Apify account; no paid run"
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
    "Chicago, US": ["Greater Chicago Area"],
    "Los Angeles, US": ["Los Angeles Metropolitan Area"],
    "Houston, US": ["Greater Houston"],
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


def title(text: str) -> str:
    """A role chip as a job title: quotes dropped, lower case, a closing "people" or "persons" dropped, the last word singular."""
    words = text.replace('"', "").lower().split()
    if words and words[-1] in ("people", "persons"):
        words.pop()
    if words and words[-1].endswith("ies"):
        words[-1] = words[-1][:-3] + "y"
    elif words and words[-1].endswith("s") and not words[-1].endswith("ss"):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def job_titles(chips: Chips) -> tuple[list[str], list[str]]:
    """The distinct non-empty titles of the role chips in chip order: the first MAX_TITLES, then the rest."""
    found = list(dict.fromkeys(t for t in map(title, (c.text for c in chips.roles)) if t))
    return found[:MAX_TITLES], found[MAX_TITLES:]


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
    """The actor's input: the job titles of a version-2 question, else the search query; the Belgian schools, the
    locations and one page of full profiles.
    """
    titles = job_titles(chips)[0] if chips.version >= 2 else []
    found = {"currentJobTitles": titles} if titles else {"searchQuery": search_query(chips)}
    return found | {"schools": list(SCHOOLS), "locations": locations(chips, area), "profileScraperMode": "Full",
                    "takePages": 1, "maxItems": SIZES[min(chips.version, 2)][2]}


def may_run_live(settings: Settings, chips: Chips) -> bool:
    """Whether a run may go out: FN_LINKEDIN=1, or the staff server with a token and chips of version 2 or later."""
    return settings.linkedin_live or (settings.linkedin_auto and settings.apify_token is not None and chips.version >= 2)


class NoPaidRun(Exception):
    """The Apify account has no plan or budget for a paid run; the message says why."""


def number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_account(http: HttpClient) -> None:
    """Raise NoPaidRun unless the Apify account is on a paid plan with MAX_CHARGE_USD left of this month's budget.

    Both answers are read with cache="none" and only the plan tier and the two dollar figures are used.
    """
    try:
        tier = dig(json.loads(http.get(ACCOUNT_URL, cache="none").content), "data.plan.tier")
        if not isinstance(tier, str) or not tier:
            raise NoPaidRun(NO_ACCOUNT)
        if "free" in tier.lower():
            raise NoPaidRun(FREE_PLAN)
        limits = json.loads(http.get(LIMITS_URL, cache="none").content)
    except (HttpError, ValueError):
        raise NoPaidRun(NO_ACCOUNT) from None
    cap, used = dig(limits, "data.limits.maxMonthlyUsageUsd"), dig(limits, "data.current.monthlyUsageUsd")
    if not (number(cap) and number(used)):
        raise NoPaidRun(NO_ACCOUNT)
    if round(cap - used, 6) < MAX_CHARGE_USD:
        raise NoPaidRun(NO_ROOM.format(used=used, cap=cap))


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

    A claim quotes its entry's lines, runs from the entry's start year to its end year (a current job to
    scrape_year) and is dated by the end year, else the start year. An entry without a school or company name,
    or without lines, makes no claim. A current job with a position adds a role claim with the same quote and dates.
    """
    found = []
    for section, keys, org_key in (("education", EDUCATION, "schoolName"), ("experience", JOB, "companyName")):
        for i, entry in enumerate(profile.get(section) or []):
            org = entry.get(org_key)
            paths = [p for p in (f"{section}.{i}.{k}" for k in keys) if p in spans]
            if not org or not paths:
                continue
            first, last = spans[paths[0]][0], spans[paths[-1]][1]
            current = section == "experience" and dig(entry, "endDate.text") == "Present"
            start = year(entry, "startDate.year")
            end = scrape_year if current else year(entry, "endDate.year")
            relation = "studied_at" if section == "education" else "works_at" if current else "worked_at"
            dated = end or start
            claim = ClaimDraft(
                person_id=person_id, kind="affiliation", relation=relation, org_id=orgs.org_id(org),
                value=normalize(org), quote=source.text[first:last], quote_start=first, quote_end=last, source=source,
                claim_date=dated, date_precision="year" if dated else None,
                date_method="record_field" if dated else None, valid_from=start, valid_to=end,
            )
            found.append(claim)
            if current and isinstance(entry.get("position"), str) and entry["position"].strip():
                found.append(claim.model_copy(update={"kind": "role", "relation": None, "org_id": None,
                                                      "value": normalize(entry["position"])}))
    return found


def place_claim(person_id: str, source: Source, spans: dict[str, tuple[int, int]], profile: dict,
                ctx: StepContext) -> ClaimDraft | None:
    """A lives_in claim of the profile's parsed location text, else its location text, quoting the location line.

    None without a location text or its line. The point is the city geo.py locates for the text, if any; the
    claim is dated by the source date to the day.
    """
    value = next((v for v in (dig(profile, "location.parsed.text"), dig(profile, "location.linkedinText"))
                  if isinstance(v, str) and v.strip()), None)
    if value is None or "location.linkedinText" not in spans:
        return None
    start, end = spans["location.linkedinText"]
    lat, lon = geo.coordinates(ctx.http, normalize(value), ctx.log) or (None, None)
    dated = {"claim_date": source.source_date, "date_precision": "day", "date_method": "record_field"} \
        if source.source_date else {}
    return ClaimDraft(person_id=person_id, kind="location", relation="lives_in", value=normalize(value), lat=lat, lon=lon,
                      quote=source.text[start:end], quote_start=start, quote_end=end, source=source, **dated)


def people(ctx: StepContext, profiles: list[dict], considered: list[Considered]) -> list[LaneHit]:
    """One hit per person in the profiles, in the actor's order, with every profile's source and claims stored.

    A profile without a linkedinUrl, or whose name has fewer than two words, is skipped. One URL twice is one
    person and one hit. Each profile, and each school spelling that maps to no org id, is added to considered.
    """
    hits: dict[str, LaneHit] = {}
    unmapped: dict[str, None] = {}
    # The city list loads before the write starts; when it cannot load, the places get no point.
    try:
        geo.cities(ctx.http)
    except HttpError:
        pass
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
            made = drafts(person.id, source, spans, profile, (day or now.date().isoformat())[:4])
            lives = place_claim(person.id, source, spans, profile, ctx)
            claims = [ctx.store.upsert_claim(d, now) for d in [*made, *([lives] if lives else [])]]
            unmapped |= dict.fromkeys(c.value for c in claims if c.relation == "studied_at" and c.org_id is None)
            where = f"result {rank}, {source.url}"
            if profile.get("headline"):
                where = f"result {rank}, {profile['headline']}, {source.url}"
            hit = hits.get(person.id) or LaneHit(person_id=person.id, name_key=person.name_key, lane=name,
                                                 rank=len(hits) + 1, score=1 / rank, matched_on=where)
            ids = list(dict.fromkeys([*hit.claim_ids, *(c.id for c in claims)]))
            hits[person.id] = hit.model_copy(update={"claim_ids": ids})
            studied = sum(c.relation == "studied_at" for c in claims)
            jobs = sum(c.relation in ("works_at", "worked_at") for c in claims)
            reason = f"result {rank}: {studied} education and {jobs} job claims"
            considered.append(Considered(person_key=source.url, name=who, stage="profile", kept=True, reason=reason))
    considered += [Considered(person_key=school, name="", stage="school", kept=False,
                              reason=f"school {school!r} maps to no org id in data/org_aliases.csv")
                   for school in unmapped]
    return list(hits.values())


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    """Search LinkedIn through Apify for the chips and make every profile the actor returns a hit.

    A version-2 question searches by the job titles of its role chips, else by topics or institutions. A run goes
    out when may_run_live says so and the Apify account has a paid plan and budget; else a recorded run is served
    or the lane notes why not. Raises RuntimeError without an HTTP client, HttpError for a refused or failed call.
    """
    chips = inp.chips
    if parse.researchers_only(chips):
        return LaneOut(lane=name, query="", total_seen=0, considered=[note(RESEARCHERS)])
    titles, extra = job_titles(chips) if chips.version >= 2 else ([], [])
    used, left = ([], []) if titles else query_terms(chips)
    considered = [note(f"more than {MAX_TITLES} job titles; left out: {', '.join(extra)}")] if extra else []
    if left:
        considered.append(note(f"query over {MAX_QUERY} characters; chips left out: {', '.join(left)}"))
    if not (titles or used):
        return LaneOut(lane=name, query="", total_seen=0, considered=considered or [note(NO_QUERY)])
    if ctx.http is None:
        raise RuntimeError("the LinkedIn lane needs an HTTP client")
    body = actor_input(chips, geo.area(ctx.http, chips.place))
    searched = f"job titles {', '.join(titles)}" if titles else body["searchQuery"]
    query = f"{searched}; locations {', '.join(body['locations'])}"
    live = may_run_live(ctx.settings, chips)
    run_s, call_s, _ = SIZES[min(chips.version, 2)]
    params = {"timeout": str(run_s), "maxTotalChargeUsd": str(MAX_CHARGE_USD)}
    try:
        response = ctx.http.post(ACTOR_URL, body, params, timeout_s=call_s, cost=estimate, keep=has_profiles,
                                 cache="prefer" if live else "only", before=lambda: check_account(ctx.http))
    except CacheMiss:
        reason = "FN_HTTP=replay has no recorded LinkedIn run for this input" if live else OFF
        return LaneOut(lane=name, query=query, total_seen=0, considered=[*considered, note(reason)])
    except NoPaidRun as exc:
        return LaneOut(lane=name, query=query, total_seen=0, considered=[*considered, note(str(exc))])
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
