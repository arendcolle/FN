"""LinkedIn lane: Apify profile search, else Google and Parallel; each profile a vendor_record source with dated claims."""
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from fn import extract, geo, orgs, parse, websearch
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
    StepCall,
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
GOOGLE_URL = "https://api.apify.com/v2/acts/scraperlink~google-search-results-serp-scraper/run-sync-get-dataset-items"
GOOGLE_PARAMS = {"maxTotalChargeUsd": "0.05", "timeout": "120"}
GOOGLE_TIMEOUT_S = 150
GOOGLE_USD = 0.001
SITE = "site:www.linkedin.com/in"
MAX_ROLES = 3
SCHOOLS_PER_QUERY = 3
MAX_PROFILES = 20
PROFILE_CHARS = 40_000
PROFILE_OBJECTIVE = "Where this person lives, their jobs and where they studied"
MAX_TITLES = 12
# Run timeout, call timeout and profiles per run; chips before version 2 keep round three's, so their recorded run replays.
SIZES = {1: (240, 290, 25), 2: (270, 295, 10)}
MAX_CHARGE_USD = 0.25
MAX_QUERY = 300
PAGE_USD = 0.10
PROFILE_USD = 0.004
NO_QUERY = "no role, topic or institution chip"
OFF = "LinkedIn lane is off and has no recorded run for this input; FN_LINKEDIN=1 runs it live for about $0.20"
REPLAYED = "FN_HTTP=replay has no recorded LinkedIn run for this input"
RESEARCHERS = "researchers only; LinkedIn not asked"
FREE_PLAN = "Apify's free plan runs this actor ten times in total; a paid plan is needed"
NO_ROOM = "the month's Apify budget has no room for a run (${used:.2f} of ${cap:.2f} used)"
NO_ACCOUNT = "could not read the Apify account; no paid run"
NO_PARALLEL = "LinkedIn lane skipped: no key for api.parallel.ai; set PARALLEL_API_KEY or store it in the Keychain"
NO_ADDRESSES = "Google found no LinkedIn profile address; Parallel not called"
NONE_PARSED = "no profile of this run could be parsed"
ASKED_AGAIN = "Google route: query {n} came back without the LinkedIn limit; asked again with the limit at the end"
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
# The same cities to the area name and the "City, State" text a profile's place line holds, for the Google route.
PLACES = {
    "New York City, US": ["New York City Metropolitan Area", "New York, New York"],
    "San Francisco, US": ["San Francisco Bay Area", "San Francisco, California"],
    "Boston, US": ["Greater Boston", "Boston, Massachusetts"],
    "Washington, US": ["Washington DC-Baltimore Area", "Washington, District of Columbia"],
    "Atlanta, US": ["Atlanta Metropolitan Area", "Atlanta, Georgia"],
    "Chicago, US": ["Greater Chicago Area", "Chicago, Illinois"],
    "Los Angeles, US": ["Los Angeles Metropolitan Area", "Los Angeles, California"],
    "Houston, US": ["Greater Houston", "Houston, Texas"],
    "Seattle, US": ["Greater Seattle Area", "Seattle, Washington"],
}
# The lines of Parallel's profile text: a block field, a header bullet, a headline bullet and its nested text.
FIELD = re.compile(r"^   - ([^:]+?):\s*(.*)$")
LABEL = re.compile(r"^\s?\*\s+([^:]+?):\s*(.*)$")
HEADLINE = re.compile(r"^\s?\*\s+headline\s*$", re.IGNORECASE)
NESTED = re.compile(r"^\s+-\s+(.*)$")
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


def mentions(address: str, who: str) -> list[Identifier]:
    """The web lane's identifiers for the owner of a profile page, without and with www, so both lanes meet in one person."""
    return [extract.identifier(url, who) for url in (address.replace("://www.", "://", 1), address)]


def people(ctx: StepContext, profiles: list[dict], considered: list[Considered],
           numbers: list[int] | None = None) -> list[LaneHit]:
    """One hit per person in the profiles, in the actor's order, with every profile's source and claims stored.

    A profile without a linkedinUrl, or whose name has fewer than two words, is skipped. One URL twice is one
    person and one hit. Each profile, and each school spelling that maps to no org id, is added to considered.
    The result number of each profile is its place in numbers, else 1 to n.
    """
    hits: dict[str, LaneHit] = {}
    unmapped: dict[str, None] = {}
    # The city list loads before the write starts; when it cannot load, the places get no point.
    try:
        geo.cities(ctx.http)
    except HttpError:
        pass
    with ctx.store.tx():
        for rank, profile in zip(numbers or range(1, len(profiles) + 1), profiles):
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
            known = [Identifier(scheme="profile_url", value=source.url), *mentions(source.url, who)]
            person = ctx.store.resolve_person(known, who)
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


def quoted(texts: list[str]) -> str:
    """The texts in double quotes, inner quotes dropped, joined by " OR "."""
    return " OR ".join('"' + t.replace('"', "") + '"' for t in texts)


def places(chips: Chips, area: GeoArea | None) -> list[str]:
    """The place phrases of a Google query: the city's PLACES, else what locations gives."""
    place = chips.place
    if place and place.kind not in ("abroad", "anywhere_us") and area and area.city in PLACES:
        return PLACES[area.city]
    return locations(chips, area)


def schools(chips: Chips) -> list[str]:
    """The SCHOOLS an institution chip names, else all of them."""
    named = {orgs.org_id(c.text) for c in chips.institutions} - {None}
    return [s for s in SCHOOLS if orgs.org_id(s) in named] or list(SCHOOLS)


def google_queries(chips: Chips, area: GeoArea | None) -> tuple[list[str], list[str]]:
    """One Google query per group of SCHOOLS_PER_QUERY schools, and the role terms past MAX_ROLES left out.

    The roles are the job titles of a version-2 question, else the terms of query_terms.
    """
    titles = job_titles(chips)[0] if chips.version >= 2 else []
    roles = [f'"{t}"' if " " in t else t for t in titles] if titles else query_terms(chips)[0]
    if not roles:
        return [], []
    where, named = quoted(places(chips, area)), schools(chips)
    groups = [named[i:i + SCHOOLS_PER_QUERY] for i in range(0, len(named), SCHOOLS_PER_QUERY)]
    return [f"{SITE} ({' OR '.join(roles[:MAX_ROLES])}) ({where}) ({quoted(group)})" for group in groups], roles[MAX_ROLES:]


def results_of(body: bytes) -> list[dict] | None:
    """The results list of the answer's first item; None when the answer has none."""
    try:
        answer = json.loads(body)
    except ValueError:
        return None
    first = answer[0] if isinstance(answer, list) and answer else None
    found = first.get("results") if isinstance(first, dict) else None
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else None


def search_google(ctx: StepContext, query: str, live: bool) -> list[dict]:
    """The results of one Google query through the scraper; an answer without a results list is not cached."""
    body = {"keyword": query, "limit": "10", "country": "US", "hl": "en"}
    response = ctx.http.post(GOOGLE_URL, body, GOOGLE_PARAMS, timeout_s=GOOGLE_TIMEOUT_S, cost=lambda _: GOOGLE_USD,
                             keep=lambda b: results_of(b) is not None, cache="refresh" if live else "only")
    return results_of(response.content) or []


def profile_address(url: str) -> str | None:
    """The canonical address of a LinkedIn profile on www.linkedin.com or linkedin.com; None for any other address."""
    parts = urlsplit(url.strip())
    segments = [s for s in parts.path.split("/") if s]
    if parts.netloc.lower() not in ("www.linkedin.com", "linkedin.com") or len(segments) < 2 or segments[0] != "in":
        return None
    return canonical(f"https://www.linkedin.com/in/{segments[1]}")


def profile_count(results: list[dict]) -> int:
    """How many of the results are profile addresses."""
    return sum(profile_address(str(r.get("url") or "")) is not None for r in results)


def addresses(answers: list[list[dict]]) -> tuple[list[str], int]:
    """The first MAX_PROFILES distinct profile addresses, the first result of each answer in turn, then the second;
    and the count of results that are no profile address.
    """
    found: dict[str, None] = {}
    others = 0
    for position in range(max(map(len, answers), default=0)):
        for answer in answers:
            if position < len(answer):
                address = profile_address(str(answer[position].get("url") or ""))
                others += address is None
                if address and len(found) < MAX_PROFILES:
                    found[address] = None
    return list(found), others


def when(fields: dict, prefix: str, text: bool = True) -> dict:
    """The year, and the text, of a block's start or end date; empty values are left out."""
    year = fields.get(("", f"{prefix} date year"), "")
    found = {"year": int(year) if year.isdigit() else None, "text": fields.get(("", f"{prefix} date")) if text else None}
    return {k: v for k, v in found.items() if v}


def job_entry(fields: dict) -> dict:
    current = fields.get(("", "is current"), "").lower() == "true"
    entry = {"companyName": fields.get(("", "company name")), "position": fields.get(("", "title")),
             "location": fields.get(("", "locality")), "startDate": when(fields, "start"),
             "endDate": {"text": "Present"} if current else when(fields, "end")}
    return {k: v for k, v in entry.items() if v}


def education_entry(fields: dict) -> dict:
    entry = {"schoolName": fields.get(("school", "name")), "degree": fields.get(("", "degree")),
             "fieldOfStudy": fields.get(("field of study", "name")), "startDate": when(fields, "start", False),
             "endDate": when(fields, "end", False)}
    return {k: v for k, v in entry.items() if v}


def read_profile(text: str, url: str, acquired_at: str) -> dict | None:
    """Parallel's labelled text of a profile as the strict actor's profile dict.

    Only the header and the Experience and Education blocks are read. A text of PROFILE_CHARS or more was cut, so
    its last line is dropped. None without a first or last name.
    """
    lines = text.split("\n")
    head: dict[str, str] = {}
    blocks: list[tuple[str, dict]] = []
    section = sub = None
    headline = False
    for line in lines[:-1] if len(text) >= PROFILE_CHARS else lines:
        if line.startswith("# "):
            section, sub = line[2:].strip().lower(), None
            if section in ("experience", "education"):
                blocks.append((section, {}))
        elif line.startswith("## "):
            sub = line[3:].strip().lower()
        elif section is None:
            if headline and (nested := NESTED.match(line)):
                head.setdefault("headline", nested[1].strip())
            elif label := LABEL.match(line):
                head.setdefault(label[1].strip().lower(), label[2].strip())
            headline = bool(HEADLINE.match(line))
        elif section in ("experience", "education") and (field := FIELD.match(line)):
            blocks[-1][1].setdefault((sub or "", field[1].strip().lower()), field[2].strip())
    if not (head.get("first name") and head.get("last name")):
        return None
    profile = {"firstName": head["first name"], "lastName": head["last name"], "headline": head.get("headline"),
               "location": {"linkedinText": head["locality"]} if head.get("locality") else None,
               "experience": [e for kind, f in blocks if kind == "experience" if (e := job_entry(f))],
               "education": [e for kind, f in blocks if kind == "education" if (e := education_entry(f))],
               "linkedinUrl": url, "_meta": {"scrapedAt": acquired_at}}
    return {k: v for k, v in profile.items() if v is not None}


def belgian_school(school: str, facts: dict) -> bool:
    """Whether the school's folded name holds one of the SCHOOLS' names, or its org is in Belgium in facts."""
    folded = orgs.fold(school)
    if any(orgs.fold(s) in folded for s in SCHOOLS):
        return True
    found = facts.get(orgs.org_id(school) or "")
    return bool(found and found.country_code == "BE")


def expected_misses(calls: list[StepCall]) -> set[int]:
    """The seq of each call whose cache miss is off by design: every strict-route call and the first Google query."""
    first = min((c.seq for c in calls if GOOGLE_URL in c.request), default=None)
    return {c.seq for c in calls if ACTOR_URL in c.request} | ({first} if first is not None else set())


def google_route(ctx: StepContext, chips: Chips, area: GeoArea | None, live: bool, off: str,
                 considered: list[Considered]) -> LaneOut:
    """The second route: Google finds profile addresses, Parallel reads them, a Belgian school keeps a person.

    A cache miss on the first query notes off; on a later query or the read it raises CacheMiss. The scraper
    sometimes drops the site limit: an answer where under half the results are profile addresses is asked once
    more with the limit at the end, and the answer with more profile addresses is used.
    """
    queries, left = google_queries(chips, area)
    query = " | ".join(queries)
    if left:
        considered.append(note(f"Google route: more than {MAX_ROLES} role terms; left out: {', '.join(left)}"))
    if live and ctx.settings.http_mode != "replay" and ctx.settings.parallel_api_key is None:
        ctx.log.warning(NO_PARALLEL)
        return LaneOut(lane=name, query=query, total_seen=0, considered=[*considered, note(NO_PARALLEL)])
    answers = []
    for i, text in enumerate(queries):
        try:
            found = search_google(ctx, text, live)
        except CacheMiss:
            if i:
                raise
            return LaneOut(lane=name, query=query, total_seen=0, considered=[*considered, note(off)])
        if 2 * profile_count(found) < len(found):
            considered.append(note(ASKED_AGAIN.format(n=i + 1)))
            found = max(found, search_google(ctx, f"{text.removeprefix(SITE).strip()} {SITE}", live), key=profile_count)
        answers.append(found)
    urls, others = addresses(answers)
    if not urls:
        return LaneOut(lane=name, query=query, total_seen=0, considered=[*considered, note(NO_ADDRESSES)])
    answer = websearch.extract_pages(ctx, urls, PROFILE_OBJECTIVE, PROFILE_CHARS, "refresh" if live else "only")
    read = {canonical(r["url"]): r for r in answer.get("results") or [] if r.get("url")}
    failed = {canonical(e["url"]): e for e in answer.get("errors") or [] if e.get("url")}
    parsed, rows = [], {}
    for n, url in enumerate(urls, 1):
        page = read.get(url, {})
        if not page.get("full_content"):
            reason = f"result {n}: not read ({failed.get(url, {}).get('error_type') or 'missing'})"
        elif profile := read_profile(page["full_content"], url, page.get("acquired_at") or ""):
            parsed.append((n, profile))
            continue
        else:
            reason = f"result {n}: no first and last name; not read"
        rows[n] = Considered(person_key=f"result {n}", name="", stage="profile", kept=False, reason=reason)
    named = [[e["schoolName"] for e in p.get("education", []) if e.get("schoolName")] for _, p in parsed]
    found = [i for group in named for s in group if (i := orgs.org_id(s))]
    facts = ctx.store.get_orgs(list(dict.fromkeys(found)))
    kept = []
    for (n, profile), group in zip(parsed, named):
        if any(belgian_school(s, facts) for s in group):
            kept.append((n, profile))
        else:
            rows[n] = Considered(person_key=f"result {n}", name="", stage="profile", kept=False,
                                 reason=f"result {n}: no Belgian school among {len(group)} schools; not kept")
    considered += [rows[n] for n in sorted(rows)]
    if not parsed:
        considered.append(note(NONE_PARSED))
    hits = people(ctx, [p for _, p in kept], considered, [n for n, _ in kept])
    total = sum(map(len, answers))
    considered.append(note(f"Google route: {len(queries)} queries, {total} results, {total - others} profile addresses, "
                           f"{sum(bool(read.get(u, {}).get('full_content')) for u in urls)} read", True, "read"))
    ctx.log.info("linkedin lane, Google route: %d addresses, %d parsed, %d people", len(urls), len(parsed), len(hits))
    return LaneOut(lane=name, query=query, total_seen=len(urls), hits=hits, considered=considered)


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    """Search LinkedIn through Apify for the chips and make every profile the actor returns a hit.

    A version-2 question searches by the job titles of its role chips, else by topics or institutions. A run goes
    out when may_run_live says so and the Apify account has a paid plan and budget; else a recorded run is served,
    or the Google route finds the people. Raises RuntimeError without an HTTP client, HttpError for a refused or failed call.
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
    area = geo.area(ctx.http, chips.place)
    body = actor_input(chips, area)
    searched = f"job titles {', '.join(titles)}" if titles else body["searchQuery"]
    query = f"{searched}; locations {', '.join(body['locations'])}"
    live = may_run_live(ctx.settings, chips)
    run_s, call_s, _ = SIZES[min(chips.version, 2)]
    params = {"timeout": str(run_s), "maxTotalChargeUsd": str(MAX_CHARGE_USD)}
    try:
        response = ctx.http.post(ACTOR_URL, body, params, timeout_s=call_s, cost=estimate, keep=has_profiles,
                                 cache="prefer" if live else "only", before=lambda: check_account(ctx.http))
    except CacheMiss:
        return google_route(ctx, chips, area, live, REPLAYED if live else OFF, considered)
    except NoPaidRun as exc:
        return google_route(ctx, chips, area, live, REPLAYED, [*considered, note(str(exc))])
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
