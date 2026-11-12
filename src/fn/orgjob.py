"""fn-orgs: refresh the facts of every org in data/org_aliases.csv as one recorded job."""
import argparse
import sys

from fn import extract, geo, orgs
from fn.config import Settings, from_env
from fn.contracts import HttpClient, OrgsIn, PlacesIn, PlacesOut, Search
from fn.net import Client
from fn.steps import StepContext, run_step
from fn.store import Store
from fn.worker import Worker


def job_steps(ctx: StepContext, _: Search) -> None:
    run_step(ctx, "orgs", orgs.run, OrgsIn(ids=orgs.ids()))


def refresh(store: Store, settings: Settings, http: HttpClient) -> Search:
    """Run fn-orgs as a job: one searches row of kind job with one orgs step over every alias-file id.

    Returns the ended job; a failed fetch leaves it failed, with the error on its orgs step.
    """
    worker = Worker(store, settings, llm=None, http=http)
    try:
        return worker.execute(worker.create_search("fn-orgs", kind="job").id, job_steps)
    finally:
        worker.shutdown()


def places(ctx: StepContext, _: PlacesIn) -> PlacesOut:
    """Fill org cities from stored OpenAlex records and give stored place claims the coordinates geo finds.

    Raises RuntimeError without an HTTP client, which fetches the city index.
    """
    if ctx.http is None:
        raise RuntimeError("fn-orgs --places needs an HTTP client")
    return PlacesOut(orgs=orgs.backfill_places(ctx.store), claims=extract.locate_stored(ctx.store, geo.cities(ctx.http)))


def fill_places(store: Store, settings: Settings, http: HttpClient) -> Search:
    """Run fn-orgs --places as a job: one searches row of kind job with one places step; returns the ended job."""
    worker = Worker(store, settings, llm=None, http=http)
    try:
        return worker.execute(worker.create_search("fn-orgs --places", kind="job").id,
                              lambda ctx, _: run_step(ctx, "places", places, PlacesIn()))
    finally:
        worker.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(prog="fn-orgs")
    parser.add_argument("--places", action="store_true",
                        help="fill org cities from stored OpenAlex records and locate stored place claims")
    run = fill_places if parser.parse_args().places else refresh
    settings = from_env()
    store = Store(settings.db_path)
    store.migrate()
    job = run(store, settings, Client(settings))
    step = next(iter(store.list_steps(job.id)), None)
    if job.status == "done" and job.question == "fn-orgs --places":
        out = PlacesOut.model_validate_json(store.get_payload(step.id)[1])
        print(f"fn-orgs --places job {job.id} done: {out.orgs} orgs got a city, {out.claims} place claims got "
              f"coordinates in {settings.db_path}")
    elif job.status == "done":
        print(f"fn-orgs job {job.id} done: {len(orgs.ids())} orgs saved into {settings.db_path}")
    else:
        print(f"fn-orgs job {job.id} {job.status}: " + (f"{step.error_type}: {step.error_message}" if step else str(job.error)))
    store.close()
    return 0 if job.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
