"""Institution identity from data/org_aliases.csv, and institution facts from ROR, Wikidata and OpenAlex."""
import csv
import re
import time
from datetime import datetime
from functools import cache

from fn.config import ROOT
from fn.contracts import (
    REGISTRY_ID,
    Claim,
    HttpClient,
    Org,
    OrgFacts,
    OrgMatchIn,
    OrgMatchOut,
    OrgsIn,
    OrgsOut,
    Source,
    name_key,
    normalize,
    record_source,
)
from fn.net import HttpError
from fn.steps import StepContext
from fn.store import Store

ALIASES = ROOT / "data" / "org_aliases.csv"
UNMAPPED = ROOT / "data" / "org_aliases_unmapped.txt"
ROR_API = "https://api.ror.org/v2/organizations"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
RANKS = ("preferred", "normal")
MATCH_RELATIONS = ("works_at", "worked_at", "affiliated_with", "hosted_by", "studied_at")
MIN_CHARS = 3
MAX_NAME_CHARS = 200
SEARCH_PACE_S = 0.0


class OrgError(RuntimeError):
    """An org record could not be fetched, or it lacks the name fn-orgs stores."""


def fold(text: str) -> str:
    return " ".join(normalize(text).casefold().split())


@cache
def _rows() -> list[tuple[str, str, bool]]:
    """Every (alias, org id, post) in the file; raises ValueError for an id not in ror:/wikidata: form, an alias listed
    twice or a post cell that is neither empty nor yes.
    """
    rows, seen = [], set()
    for row in csv.DictReader(ALIASES.read_text(encoding="utf-8").splitlines()):
        if not REGISTRY_ID.fullmatch(row["org_id"]):
            raise ValueError(f"org_aliases.csv: {row['org_id']!r} for {row['alias']!r} is not ror:<id> or wikidata:<Q>")
        if fold(row["alias"]) in seen:
            raise ValueError(f"org_aliases.csv: alias {row['alias']!r} is listed twice")
        mark = (row.get("post") or "").strip()
        if mark not in ("", "yes"):
            raise ValueError(f"org_aliases.csv: post {mark!r} for {row['alias']!r} is not empty or yes")
        seen.add(fold(row["alias"]))
        rows.append((row["alias"], row["org_id"], mark == "yes"))
    return rows


@cache
def _by_alias() -> dict[str, str]:
    return {fold(alias): org for alias, org, _ in _rows()}


@cache
def unmapped() -> frozenset[str]:
    """Institution strings checked and left out of the alias file on purpose, folded."""
    return frozenset(fold(line) for line in UNMAPPED.read_text(encoding="utf-8").splitlines() if line.strip())


def org_id(text: str) -> str | None:
    return _by_alias().get(fold(text))


def ref(text: str) -> str | None:
    """The chip ref for an institution name: its org id when that is a ROR id, else None."""
    found = org_id(text)
    return found if found and found.startswith("ror:") else None


def names(org: str | None) -> list[str]:
    """Every spelling the alias file gives the org, in file order; empty for an org it does not list."""
    return [alias for alias, found, _ in _rows() if found == org] if org else []


def ids() -> list[str]:
    """Every org id in the alias file, once each, in file order."""
    return list(dict.fromkeys(org for _, org, _ in _rows()))


@cache
def _posts() -> frozenset[tuple[str, str]]:
    return frozenset((fold(alias), org) for alias, org, post in _rows() if post)


def post(text: str, org: str | None) -> bool:
    """Whether the alias file marks this spelling of org as a post away from its home, such as a US arm or a consulate."""
    return (fold(text), org) in _posts()


def overruled(answers: dict[str, str | None]) -> dict[str, str]:
    """Each stored ROR answer for a name the alias file gives another org: the folded name and the answer's org."""
    return {key: org for key, org in answers.items() if org and _by_alias().get(key, org) != org}


def belgian_claims(claims: list[Claim], facts: dict[str, Org]) -> list[tuple[Claim, Org]]:
    """Each claim whose org has country code BE, with that org, in claim order; facts holds the orgs by id.

    Any kind and relation counts; a claim without an org_id never does.
    """
    return [(c, facts[c.org_id]) for c in claims if c.org_id in facts and facts[c.org_id].country_code == "BE"]


def missing_facts(claims: list[Claim], facts: dict[str, Org]) -> list[str]:
    """The org ids of the claims that have no stored facts, sorted and once each."""
    return sorted({c.org_id for c in claims if c.org_id and c.org_id not in facts})


def save(store: Store, facts: list[OrgFacts], source: Source, *, replace: bool) -> None:
    """Store each org's facts with the source they came from, in one transaction.

    replace=True overwrites a stored row with the same id (fn-orgs); replace=False keeps it (the OpenAlex lane).
    Raises ValueError for a source without fetched_at.
    """
    if source.fetched_at is None:
        raise ValueError(f"org facts need a dated source; {source.id} has no fetched_at")
    with store.tx():
        store.upsert_source(source)
        for fact in facts:
            store.upsert_org(Org(**fact.model_dump(), source_id=source.id, fetched_at=source.fetched_at), replace)


def ror_record(record: dict, fetched_at: datetime) -> tuple[OrgFacts, Source]:
    """Facts from a ROR v2 record: the ror_display name and its language, the first location's country, subdivision,
    city and coordinates.

    Raises OrgError for a record without a ror_display name.
    """
    i, display = next(((i, n) for i, n in enumerate(record.get("names") or []) if "ror_display" in n["types"]), (0, None))
    if display is None:
        raise OrgError("the ROR record has no ror_display name")
    where = (record.get("locations") or [{}])[0].get("geonames_details") or {}
    geo = "locations.0.geonames_details"
    fields: list[tuple[str, object]] = [
        ("id", record["id"]), (f"names.{i}.value", display["value"]), (f"names.{i}.lang", display.get("lang")),
        (f"{geo}.name", where.get("name")), (f"{geo}.lat", where.get("lat")), (f"{geo}.lng", where.get("lng")),
        (f"{geo}.country_code", where.get("country_code")),
        (f"{geo}.country_subdivision_code", where.get("country_subdivision_code")), ("status", record.get("status")),
    ]
    modified = ((record.get("admin") or {}).get("last_modified") or {}).get("date")
    source, _ = record_source(record["id"], f"ROR record {display['value']}", fields, record, fetched_at, modified)
    return OrgFacts(id=f"ror:{record['id'].rsplit('/', 1)[-1]}", name=display["value"],
                    country_code=where.get("country_code"), region=where.get("country_subdivision_code"),
                    name_lang=display.get("lang"), city=where.get("name"), lat=where.get("lat"),
                    lon=where.get("lng")), source


def backfill_places(store: Store) -> int:
    """Fill the city and coordinates of stored orgs without a city from the stored OpenAlex institution records.

    The org is the record's ROR id, else its OpenAlex id; a record whose org is not stored or has a city is
    skipped. Makes no outside call. Returns the number of org rows filled.
    """
    filled = 0
    with store.tx():
        for text in store.record_texts("OpenAlex institution "):
            lines = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)
            ror, oa, city = lines.get("ror"), lines.get("id"), lines.get("geo.city")
            org = f"ror:{ror.rsplit('/', 1)[-1]}" if ror else f"openalex:{oa.rsplit('/', 1)[-1]}" if oa else None
            lat, lon = lines.get("geo.latitude"), lines.get("geo.longitude")
            if org and city:
                filled += store.fill_org_place(org, city, float(lat) if lat else None, float(lon) if lon else None)
    return filled


def _wikidata(http: HttpClient, params: dict[str, str]) -> dict:
    body = http.get(WIKIDATA_API, params | {"format": "json"}).json()
    if "error" in body:
        raise OrgError(f"Wikidata {params['action']} answered {body['error'].get('info', body['error'])}")
    return body


def ranked_values(body: dict, prop: str) -> list:
    """The values of the item's prop statements, preferred rank first, then normal; deprecated ones and gaps are skipped."""
    found = [c for c in body.get("claims", {}).get(prop, []) if c.get("rank") in RANKS and "datavalue" in c["mainsnak"]]
    return [c["mainsnak"]["datavalue"]["value"] for c in sorted(found, key=lambda c: RANKS.index(c["rank"]))]


def wikidata_item(http: HttpClient, item: str, fetched_at: datetime) -> tuple[OrgFacts, Source]:
    """Facts from a Wikidata item: its English label, and the ISO code (P297) of its country (P17).

    Raises OrgError for an item Wikidata does not have, one without an English label or an error answer.
    """
    labels = _wikidata(http, {"action": "wbgetentities", "ids": item, "props": "labels", "languages": "en"})
    entity = labels["entities"].get(item, {})
    name = entity.get("labels", {}).get("en", {}).get("value")
    if "missing" in entity or not name:
        raise OrgError("no such item" if "missing" in entity else "no English label")
    countries = _wikidata(http, {"action": "wbgetclaims", "entity": item, "property": "P17"})
    country = next((v["id"] for v in ranked_values(countries, "P17")), None)
    codes = _wikidata(http, {"action": "wbgetclaims", "entity": country, "property": "P297"}) if country else {}
    code = next(iter(ranked_values(codes, "P297")), None)
    fields: list[tuple[str, object]] = [("id", item), ("labels.en", name), ("claims.P17", country),
                                        ("claims.P17.P297", code)]
    raw = {"labels": labels, "P17": countries, "P297": codes}
    source, _ = record_source(f"https://www.wikidata.org/wiki/{item}", f"Wikidata item {name}", fields, raw, fetched_at)
    return OrgFacts(id=f"wikidata:{entity['id']}", name=name, country_code=code), source


def fetch(http: HttpClient, org: str, fetched_at: datetime) -> tuple[OrgFacts, Source]:
    """The facts and record Source of one alias-file org.

    Raises OrgError naming the id for a failed call, a body that is not JSON or not the expected shape,
    and a record of another org.
    """
    scheme, key = org.split(":", 1)
    try:
        if scheme == "ror":
            facts, source = ror_record(http.get(f"{ROR_API}/{key}").json(), fetched_at)
        elif scheme == "wikidata":
            facts, source = wikidata_item(http, key, fetched_at)
        else:
            raise OrgError("fn-orgs fetches ror: and wikidata: ids only")
        if facts.id != org:
            raise OrgError(f"the record fetched is {facts.id}")
    except (HttpError, OrgError) as exc:
        raise OrgError(f"{org}: {exc}") from exc
    except (ValueError, KeyError) as exc:
        raise OrgError(f"{org}: unexpected answer, {type(exc).__name__}: {exc}") from exc
    return facts, source


def run(ctx: StepContext, inp: OrgsIn) -> OrgsOut:
    """Fetch each org's record and save its facts over any stored row, and return the stored orgs.

    Raises OrgError naming the id at the first failed fetch, with the orgs before it saved,
    and RuntimeError without an HTTP client.
    """
    if ctx.http is None:
        raise RuntimeError("fn-orgs needs an HTTP client")
    for org in inp.ids:
        facts, source = fetch(ctx.http, org, ctx.now())
        save(ctx.store, [facts], source, replace=True)
        ctx.log.info("%s: %s, %s %s, name in %s", org, facts.name, facts.country_code, facts.region, facts.name_lang)
    return OrgsOut(orgs=list(ctx.store.get_orgs(inp.ids).values()))


def askable(name: str) -> bool:
    """Whether ROR is asked about the name: at least MIN_CHARS letters or digits, at most MAX_NAME_CHARS, not unmapped."""
    return (len(name_key(name).replace(" ", "")) >= MIN_CHARS and len(name) <= MAX_NAME_CHARS
            and fold(name) not in unmapped())


def ror_names(record: dict) -> list[str]:
    """Every name of a ROR record, whatever its type, leaving out an acronym of under 3 characters."""
    return [n["value"] for n in record.get("names") or []
            if n.get("value") and not ("acronym" in n["types"] and len(n["value"]) < 3)]


def words(text: str) -> list[str]:
    """The words of the folded text, with a lone "u" read as "university"."""
    return ["university" if w == "u" else w for w in re.findall(r"\w+", fold(text))]


def _inside(inner: list[str], outer: list[str]) -> bool:
    return any(outer[i:i + len(inner)] == inner for i in range(len(outer) - len(inner) + 1))


def named(record: dict, name: str) -> bool:
    """Whether a name of the record stands as a run of whole words in the employer text, or an employer text of two
    words or more stands in a name of the record."""
    given = words(name)
    return bool(given) and any(w and (_inside(w, given) or (len(given) > 1 and _inside(given, w)))
                               for w in map(words, ror_names(record)))


def chosen(body: dict, fetched_at: datetime, name: str) -> tuple[OrgFacts, Source] | None:
    """The facts and record Source of the one chosen item of a ROR affiliation answer, if its names stand in the name.

    None for no chosen item, several, or a chosen organization none of whose names stands in the employer name.
    Raises OrgError for a body without items and for a record ror_record refuses.
    """
    try:
        picked = [item["organization"] for item in body["items"] if item.get("chosen")]
        return ror_record(picked[0], fetched_at) if len(picked) == 1 and named(picked[0], name) else None
    except (ValueError, KeyError, TypeError) as exc:
        raise OrgError(f"unexpected answer, {type(exc).__name__}: {exc}") from exc


def unlinked(store: Store, person_ids: list[str] | None, wrong: dict[str, str]) -> list[tuple[str, str, int]]:
    """The id, value and position of every claim without an org and with a match relation, rejected ones too, and of
    every such claim at the org that wrong gives its folded name.

    With person_ids, only the claims of those persons, each at the first index of its person in the list; else all, at 0.
    """
    if person_ids is None:
        found = store.unlinked_affiliations(MATCH_RELATIONS)
        if wrong:
            found += [(i, v) for i, v, org in store.linked_affiliations(MATCH_RELATIONS, sorted(set(wrong.values())))
                      if wrong.get(fold(v)) == org]
        return [(claim_id, value, 0) for claim_id, value in found]
    canonical = store.canonical_ids(person_ids)
    places: dict[str, int] = {}
    for i, person_id in enumerate(person_ids):
        places.setdefault(canonical.get(person_id, person_id), i)
    return [(c.id, c.value, places[c.person_id]) for c in store.claims_of(list(places), include_hidden=True)
            if (c.org_id is None or c.org_id == wrong.get(fold(c.value))) and c.relation in MATCH_RELATIONS
            and c.person_id in places]


def match(ctx: StepContext, inp: OrgMatchIn) -> OrgMatchOut:
    """Ask ROR once per employer name that has claims without an org, and link the chosen org to every claim of the name.

    A name in the alias file is linked from the file, never asked or counted, and overrules a stored answer for it.
    Any other stored answer is reused without a call. With person_ids only those persons' claims are read, and names
    are asked in the order of the ids; with most, no more than that many are asked and the rest count as left.
    Raises OrgError naming the name at a 429, a 5xx or a failed call; RuntimeError without an HTTP client.
    """
    if ctx.http is None:
        raise RuntimeError("fn-orgs --match needs an HTTP client")
    groups: dict[str, tuple[str, list[str], int]] = {}
    answers = ctx.store.org_answers()
    for claim_id, value, place in unlinked(ctx.store, inp.person_ids, overruled(answers)):
        name, claim_ids, first = groups.get(fold(value), (value, [], place))
        groups[fold(value)] = (name, [*claim_ids, claim_id], min(first, place))
    aliases = _by_alias()
    asked = picked = linked = failed = left = 0
    known = answers.keys() | aliases.keys()
    for key, (name, claim_ids, _) in sorted(groups.items(), key=lambda g: (g[0] not in known, g[1][2], g[0])):
        if key in aliases:
            linked += ctx.store.relink_claims(claim_ids, aliases[key])
            continue
        if key in answers:
            linked += ctx.store.link_claims(claim_ids, answers[key]) if answers[key] else 0
            continue
        if not askable(name):
            continue
        if inp.most is not None and asked >= inp.most:
            left += 1
            continue
        if asked:
            time.sleep(inp.pace_s)
        asked += 1
        try:
            found = chosen(ctx.http.get(ROR_API, {"affiliation": name, "single_search": ""}).json(), ctx.now(), name)
        except HttpError as exc:
            if exc.status is None or exc.status == 429 or exc.status >= 500:
                raise OrgError(f"{name!r}: {exc}") from exc
            failed += 1
            continue
        except (ValueError, OrgError):
            failed += 1
            continue
        with ctx.store.tx():
            if found:
                save(ctx.store, [found[0]], found[1], replace=False)
            org = found[0].id if found else None
            ctx.store.save_org_answer(key, name, org, ctx.now())
            linked += ctx.store.link_claims(claim_ids, org) if org else 0
        picked += bool(found)
    return OrgMatchOut(asked=asked, chosen=picked, linked=linked, failed=failed, left=left)
