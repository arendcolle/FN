"""The Quick workflow: which steps run in which order."""
import sys

from fn import parse, rank, resolve
from fn.contracts import (
    LaneIn,
    ParseIn,
    ParseOut,
    RankIn,
    ResolveIn,
    SaveIn,
    SaveOut,
    Search,
)
from fn.lanes import LANES
from fn.llm import StructuredLLM, from_settings
from fn.steps import StepContext, run_step, skip_step


def save(ctx: StepContext, inp: SaveIn) -> SaveOut:
    return SaveOut(count=ctx.store.save_candidates(ctx.search_id, inp.candidates, inp.flags))


def run(ctx: StepContext, search: Search) -> None:
    """Run the Quick steps in order: parse, each lane, resolve, rank and save."""
    inp = ParseIn(question=search.question)
    if search.chips is not None:
        chips = skip_step(ctx, "parse", inp, ParseOut(chips=search.chips)).chips
    else:
        chips = run_step(ctx, "parse", parse.run, inp).chips
        ctx.store.set_search_chips(search.id, chips, "parsed")
    lane_in = LaneIn(search_id=search.id, chips=chips, depth=search.depth)
    outs = [run_step(ctx, f"lane:{lane.name}", lane.run, lane_in) for lane in LANES]
    resolved = run_step(ctx, "resolve", resolve.run, ResolveIn(outs=outs))
    ranked = run_step(ctx, "rank", rank.run, RankIn(entries=resolved.entries, chips=chips))
    run_step(ctx, "save", save, SaveIn(candidates=ranked.candidates, flags=resolved.flags))


def main(argv: list[str] | None = None, llm: StructuredLLM | None = None) -> int:
    """Run one search for the question in argv in the foreground and print its steps.

    Returns 0 when the search ends done, else 1.
    """
    from fn import config, net
    from fn.store import Store
    from fn.worker import Worker

    question = " ".join(sys.argv[1:] if argv is None else argv)
    settings = config.from_env()
    store = Store(settings.db_path)
    store.migrate()
    worker = Worker(store, settings, llm=llm or from_settings(settings), http=net.Client(settings))
    found = worker.execute(worker.create_search(question).id)
    print(f"search {found.id} {found.status}")
    for step in store.list_steps(found.id):
        print(f"  {step.seq} {step.step} {step.status} {step.error_type or ''}".rstrip())
    return 0 if found.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
