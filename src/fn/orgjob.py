"""fn-orgs: refresh the facts of every org in data/org_aliases.csv as one recorded job."""
import sys

from fn import orgs
from fn.config import Settings, from_env
from fn.contracts import HttpClient, OrgsIn, Search
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


def main() -> int:
    settings = from_env()
    store = Store(settings.db_path)
    store.migrate()
    job = refresh(store, settings, Client(settings))
    step = next(iter(store.list_steps(job.id)), None)
    if job.status == "done":
        print(f"fn-orgs job {job.id} done: {len(orgs.ids())} orgs saved into {settings.db_path}")
    else:
        print(f"fn-orgs job {job.id} {job.status}: " + (f"{step.error_type}: {step.error_message}" if step else str(job.error)))
    store.close()
    return 0 if job.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
