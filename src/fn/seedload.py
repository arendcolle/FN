"""data/seeds/*.jsonl to persons, sources and claims; fn-seed."""
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from fn import geo, orgs
from fn.config import ROOT, Settings
from fn.contracts import (
    ClaimDraft,
    DateMethod,
    DatePrecision,
    HttpClient,
    Identifier,
    Relation,
    Search,
    SeedIn,
    SeedOut,
    Source,
    normalize,
)
from fn.steps import StepContext, run_step
from fn.store import Store
from fn.worker import Worker

SEEDS = ROOT / "data" / "seeds"


class ListSpec(NamedTuple):
    """How a list's rows become claims: the list claim's relation and organization (by its name in
    data/org_aliases.csv), whether role is a job title, whether place is a current place, and that claim's relation.
    """
    claim: tuple[Relation, str] | None
    job: bool = False
    place: bool = False
    place_relation: Relation | None = None


SPECS: dict[str, ListSpec] = {
    "baef": ListSpec(("fellow_of", "Belgian American Educational Foundation")),
    "francqui": ListSpec(("fellow_of", "Francqui Foundation")),
    "kvab": ListSpec(("member_of", "KVAB")),
    "climate": ListSpec(("member_of", "Belgian Climate Centre"), job=True),
    "consuls": ListSpec(("consul_for", "Belgium"), job=True, place=True, place_relation="lives_in"),
    "fayat": ListSpec(("fellow_of", "Flemish Government")),
    "wikidata": ListSpec(None, job=True, place=True),
    "chambers": ListSpec(None, job=True),
}
# The list claims by list; the other lists' rows carry no list claim.
LISTS: dict[str, tuple[Relation, str]] = {name: spec.claim for name, spec in SPECS.items() if spec.claim}
RELATIONS: dict[str, Relation] = {
    "home": "affiliated_with", "host": "hosted_by", "employer": "works_at", "member_of": "member_of",
    "student": "studied_at",
}
DATE_METHODS: dict[str, DateMethod | None] = {
    "none": None,
    "document heading": "document_heading",
    "document note (last modified September 2025)": "document_heading",
    "sitemap_lastmod": "sitemap",
    "page text": "page_date",
    "item modified": "record_field",
}
PRECISION: dict[int, DatePrecision] = {4: "year", 7: "month", 10: "day"}
Locate = Callable[[str, list[str]], tuple[float, float] | None]


def source_of(row: dict) -> Source:
    """The seed page a row quotes, with the normalized text of its raw text layer."""
    text = normalize((ROOT / row["raw_path"]).read_text(encoding="utf-8"))
    return Source(
        id=hashlib.sha1(f"seed_page\0{row['source_url']}".encode()).hexdigest(), kind="seed_page",
        url=row["source_url"], title=row["source_title"], text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(), source_date=row["source_date"],
        date_method=DATE_METHODS[row["date_method"]], fetched_at=datetime.fromisoformat(row["fetched_at"]),
    )


def drafts(row: dict, person_id: str, source: Source, locate: Locate | None = None) -> list[ClaimDraft]:
    """The list claim, one affiliation claim per institution and a topic claim, all quoting the row.

    A row of a job list with a role also gets it as a role claim without a relation; a row of a place list with a
    place gets a location claim with the coordinates locate(city, jurisdiction or the state after the comma) gives.
    A row's year dates its claims as a record field; without one they take the source's date.
    Raises KeyError for an unknown list, relation or date method, and ValueError when the quote is not in the source.
    """
    quote = normalize(row["quote"])
    start = source.text.find(quote)
    if start < 0:
        raise ValueError(f"{row['row_key']}: quote not in {row['raw_path']}")
    base = {"person_id": person_id, "quote": quote, "quote_start": start, "quote_end": start + len(quote),
            "source": source}
    if row["year"] is not None:
        base |= {"claim_date": str(row["year"]), "date_precision": "year", "date_method": "record_field"}
    else:
        base |= {"claim_date": source.source_date, "date_precision": PRECISION[len(source.source_date)],
                 "date_method": source.date_method}
    spec = SPECS[row["list"]]
    found = []
    if spec.claim:
        relation, list_org = spec.claim
        found.append(ClaimDraft(kind="role", relation=relation, org_id=orgs.org_id(list_org),
                                value=row["role"] or row["source_title"], **base))
    if spec.job and row["role"]:
        cut = max(quote.find(row["role"]), quote.find(" ") + 1)
        found.append(ClaimDraft(kind="role", value=row["role"], **base | {"quote": quote[cut:], "quote_start": start + cut}))
    if spec.place and row["place"]:
        city, *states = row["place"].split(", ") if row["jurisdiction"] is None else [row["place"], *row["jurisdiction"]]
        lat, lon = (locate and locate(city, states)) or (None, None)
        found.append(ClaimDraft(kind="location", relation=spec.place_relation, value=row["place"], lat=lat, lon=lon,
                                **base))
    for inst in row["institutions"]:
        found.append(ClaimDraft(kind="affiliation", relation=RELATIONS[inst["relation"]],
                                org_id=orgs.org_id(inst["name"]), value=inst["name"], **base))
    if row["field"]:
        found.append(ClaimDraft(kind="topic", value=row["field"], **base))
    return found


def load(store: Store, seeds: Path = SEEDS, locate: Locate | None = None) -> int:
    """Load every seed row in one transaction and return the row count; a second load writes nothing.

    locate gives the coordinates of a place list's city; without it those claims have none.
    """
    sources: dict[str, Source] = {}
    count = 0
    with store.tx():
        for path in sorted(seeds.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row["raw_path"] not in sources:
                    sources[row["raw_path"]] = source_of(row)
                source = sources[row["raw_path"]]
                person = store.resolve_person([Identifier(scheme="seed", value=row["row_key"])], row["name"])
                for draft in drafts(row, person.id, source, locate):
                    store.upsert_claim(draft)
                count += 1
    return count


def locator(http: HttpClient) -> Locate:
    """A locate function on the GeoNames cities: the city with each state of the jurisdiction in turn.

    The city alone is tried only when no state of the jurisdiction is a known state.
    """
    names = geo.cities(http)

    def locate(city: str, states: list[str]) -> tuple[float, float] | None:
        known = any(geo.name_key(s) in geo.aliases().get("state", {}) for s in states)
        for state in states if known else [None]:
            if found := geo.locate_city(city, state, None, names):
                return found.lat, found.lon
        return None

    return locate


def run(ctx: StepContext, _: SeedIn) -> SeedOut:
    """Load the seed rows with their cities located on GeoNames; raises RuntimeError without an HTTP client."""
    if ctx.http is None:
        raise RuntimeError("fn-seed needs an HTTP client")
    locate = locator(ctx.http)
    before = ctx.store.conn.total_changes
    rows = load(ctx.store, locate=locate)
    return SeedOut(rows=rows, changed=ctx.store.conn.total_changes - before)


def job_steps(ctx: StepContext, _: Search) -> None:
    run_step(ctx, "seed", run, SeedIn())


def refresh(store: Store, settings: Settings, http: HttpClient) -> Search:
    """Run fn-seed as a job: one searches row of kind job with one seed step; returns the ended job."""
    worker = Worker(store, settings, llm=None, http=http)
    try:
        return worker.execute(worker.create_search("fn-seed", kind="job").id, job_steps)
    finally:
        worker.shutdown()


def main() -> int:
    from fn import config
    from fn.net import Client

    settings = config.from_env()
    store = Store(settings.db_path)
    store.migrate()
    job = refresh(store, settings, Client(settings))
    step = next(iter(store.list_steps(job.id)), None)
    if job.status == "done":
        out = SeedOut.model_validate_json(store.get_payload(step.id)[1])
        print(f"{out.rows} seed rows loaded into {settings.db_path}; {out.changed} rows changed")
    else:
        print(f"fn-seed job {job.id} {job.status}: " + (f"{step.error_type}: {step.error_message}" if step else str(job.error)))
    store.close()
    return 0 if job.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
