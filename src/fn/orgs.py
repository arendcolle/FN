"""Institution identity from data/org_aliases.csv, and institution facts from ROR, Wikidata and OpenAlex."""
import csv
from datetime import datetime
from functools import cache

from fn.config import ROOT
from fn.contracts import (
    REGISTRY_ID,
    Claim,
    HttpClient,
    Org,
    OrgFacts,
    OrgsIn,
    OrgsOut,
    Source,
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


class OrgError(RuntimeError):
    """An org record could not be fetched, or it lacks the name fn-orgs stores."""


def fold(text: str) -> str:
    return " ".join(normalize(text).casefold().split())


@cache
def _rows() -> list[tuple[str, str]]:
    """Every (alias, org id) in the file; raises ValueError for an id not in ror:/wikidata: form or an alias listed twice."""
    rows, seen = [], set()
    for row in csv.DictReader(ALIASES.read_text(encoding="utf-8").splitlines()):
        if not REGISTRY_ID.fullmatch(row["org_id"]):
            raise ValueError(f"org_aliases.csv: {row['org_id']!r} for {row['alias']!r} is not ror:<id> or wikidata:<Q>")
        if fold(row["alias"]) in seen:
            raise ValueError(f"org_aliases.csv: alias {row['alias']!r} is listed twice")
        seen.add(fold(row["alias"]))
        rows.append((row["alias"], row["org_id"]))
    return rows


@cache
def _by_alias() -> dict[str, str]:
    return {fold(alias): org for alias, org in _rows()}


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
    return [alias for alias, found in _rows() if found == org] if org else []


def ids() -> list[str]:
    """Every org id in the alias file, once each, in file order."""
    return list(dict.fromkeys(org for _, org in _rows()))


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
    """Facts from a ROR v2 record: the ror_display name and its language, the first location's country and subdivision.

    Raises OrgError for a record without a ror_display name.
    """
    i, display = next(((i, n) for i, n in enumerate(record.get("names") or []) if "ror_display" in n["types"]), (0, None))
    if display is None:
        raise OrgError("the ROR record has no ror_display name")
    where = (record.get("locations") or [{}])[0].get("geonames_details") or {}
    geo = "locations.0.geonames_details"
    fields: list[tuple[str, object]] = [
        ("id", record["id"]), (f"names.{i}.value", display["value"]), (f"names.{i}.lang", display.get("lang")),
        (f"{geo}.name", where.get("name")), (f"{geo}.country_code", where.get("country_code")),
        (f"{geo}.country_subdivision_code", where.get("country_subdivision_code")), ("status", record.get("status")),
    ]
    modified = ((record.get("admin") or {}).get("last_modified") or {}).get("date")
    source, _ = record_source(record["id"], f"ROR record {display['value']}", fields, record, fetched_at, modified)
    return OrgFacts(id=f"ror:{record['id'].rsplit('/', 1)[-1]}", name=display["value"],
                    country_code=where.get("country_code"), region=where.get("country_subdivision_code"),
                    name_lang=display.get("lang")), source


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
