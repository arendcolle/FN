"""fn-index: store every OpenAlex author in the US with a Belgian affiliation, with main topics and years with works."""
import sys

import httpx

from fn.config import Settings, from_env
from fn.contracts import HttpClient, IndexIn, IndexOut, Search
from fn.lanes import openalex
from fn.net import HttpError
from fn.steps import StepContext, run_step
from fn.store import Store
from fn.worker import Worker

FILTER = "last_known_institutions.country_code:US,affiliations.institution.country_code:BE"
SELECT = "id,display_name,orcid,affiliations,last_known_institutions,updated_date,topics,works_count,counts_by_year"
PER_PAGE = 100
MAX_WORKS = 1000
MIN_BELGIAN_YEARS = 2
RESERVE = 3000


def remaining(response: httpx.Response) -> float | None:
    """The credits OpenAlex says are left today, from the x-ratelimit-remaining header; None without a number."""
    try:
        return float(response.headers["x-ratelimit-remaining"])
    except (KeyError, ValueError):
        return None


def belgian_years(record: dict) -> int:
    """How many distinct years the record's Belgian affiliations cover."""
    return len({y for a in openalex.belgian(record) for y in a["years"]})


def keeps(record: dict) -> bool:
    """Whether the author is stored: not a merged namesake (many works) and Belgian for MIN_BELGIAN_YEARS years."""
    return (record.get("works_count") or 0) <= MAX_WORKS and belgian_years(record) >= MIN_BELGIAN_YEARS


def save(ctx: StepContext, record: dict, institutions: dict[str, dict]) -> None:
    """Store one author as the OpenAlex lane does, with its topic claims, in one transaction."""
    cut = {k: record[k] for k in openalex.AUTHOR_SELECT.split(",") if k in record}
    with ctx.store.tx():
        now = ctx.now()
        person, _, _ = openalex.save_author(ctx.store, cut, institutions, now)
        for draft in openalex.author_topics(record, person.id, now):
            ctx.store.upsert_claim(draft, now)


def run(ctx: StepContext, inp: IndexIn) -> IndexOut:
    """Page through the authors matching FILTER and store each, until the end or the credit reserve.

    Leaves out a result without id or name, an id seen before in the run, and an author with over MAX_WORKS works
    or under MIN_BELGIAN_YEARS Belgian years. Stops after a page that leaves under RESERVE credits and on a 429.
    Raises RuntimeError without an HTTP client, in prefer mode, or in live mode without an OpenAlex key.
    """
    if ctx.http is None:
        raise RuntimeError("fn-index needs an HTTP client")
    if ctx.settings.http_mode == "prefer":
        raise RuntimeError("fn-index needs live HTTP mode: prefer mode would serve cached pages")
    if ctx.settings.http_mode != "replay" and not ctx.settings.openalex_api_key:
        raise RuntimeError("fn-index needs OPENALEX_API_KEY")
    out = {"pages": 0, "authors": 0, "new": 0, "skipped": 0, "malformed": 0, "stopped": ""}
    seen: set[str] = set()
    institutions: dict[str, dict] = {}
    asked: set[str] = set()
    cursor = "*"
    while cursor:
        try:
            response = ctx.http.get(f"{openalex.API}/authors", {"filter": FILTER, "select": SELECT,
                                                                "per_page": str(PER_PAGE), "cursor": cursor})
            body = response.json()
            kept = []
            for record in body["results"]:
                if not record.get("id") or not record.get("display_name"):
                    out["malformed"] += 1
                elif record["id"] in seen or not keeps(record):
                    out["skipped"] += 1
                else:
                    kept.append(record)
                seen.add(record.get("id") or "")
            last = [(r.get("last_known_institutions") or [None])[0] for r in kept]
            wanted = [i for i in dict.fromkeys(openalex.short(i["id"]) for i in last if i) if i not in asked]
            if wanted:
                institutions |= openalex.fetch(ctx, "institutions", "openalex", wanted, openalex.INSTITUTION_SELECT)
                asked.update(wanted)
        except HttpError as exc:
            if exc.status != 429:
                raise
            out["stopped"] = str(exc)
            break
        if not body["results"]:
            break
        held = ctx.store.person_ids_by_identifier("openalex", [openalex.short(r["id"]) for r in kept])
        out["new"] += sum(openalex.short(r["id"]) not in held for r in kept)
        for record in kept:
            save(ctx, record, institutions)
        out["pages"] += 1
        out["authors"] += len(kept)
        left = remaining(response)
        ctx.log.info("fn-index: page %d, %d authors stored so far, %s credits left", out["pages"], out["authors"],
                     "unknown" if left is None else f"{left:.0f}")
        if left is not None and left < RESERVE:
            out["stopped"] = f"{left:.0f} credits left, under the reserve of {RESERVE}"
            break
        cursor = body["meta"].get("next_cursor")
    return IndexOut(**out)


def refresh(store: Store, settings: Settings, http: HttpClient) -> Search:
    """Run fn-index as a job: one searches row of kind job with one index step; returns the ended job."""
    worker = Worker(store, settings, llm=None, http=http)
    try:
        return worker.execute(worker.create_search("fn-index", kind="job").id,
                              lambda ctx, _: run_step(ctx, "index", run, IndexIn()))
    finally:
        worker.shutdown()


def main() -> int:
    from fn.net import Client

    settings = from_env()
    store = Store(settings.db_path)
    store.migrate()
    job = refresh(store, settings, Client(settings))
    step = next(iter(store.list_steps(job.id)), None)
    if job.status != "done":
        print(f"fn-index job {job.id} {job.status}: " + (f"{step.error_type}: {step.error_message}" if step else str(job.error)))
        store.close()
        return 1
    out = IndexOut.model_validate_json(store.get_payload(step.id)[1])
    print(f"fn-index job {job.id} done: {out.pages} pages, {out.authors} authors stored, {out.new} new, "
          f"{out.skipped} skipped, {out.malformed} malformed" + (f"; stopped: {out.stopped}" if out.stopped else ""))
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
